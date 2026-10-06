"""
Threema AI offline responder — rough MVP.

One process, no database. Pipeline:
  Gateway callback -> HMAC check -> decrypt -> operator command? -> presence check
  -> grace window -> LLM (or static OOO) -> send reply -> notify operator -> audit log

Run:   uvicorn app:app --host 0.0.0.0 --port 8080
Test:  python app.py simulate "hey, are you around?"     (no Gateway needed)
"""
import asyncio, hashlib, hmac, json, os, secrets, sys, time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Response
from nacl.public import Box, PrivateKey, PublicKey

load_dotenv()

# ---------------------------------------------------------------- config
GATEWAY_ID     = os.getenv("GATEWAY_ID", "*XXXXXXX")
GATEWAY_SECRET = os.getenv("GATEWAY_SECRET", "")
PRIVATE_KEY    = os.getenv("PRIVATE_KEY_HEX", "")          # 32-byte hex, generated once
OPERATOR_ID    = os.getenv("OPERATOR_ID", "ABCDEFGH")      # the client's personal Threema ID
GRACE_SECONDS  = int(os.getenv("GRACE_SECONDS", "45"))     # window to !hold before the bot replies
HOLD_MINUTES   = int(os.getenv("HOLD_MINUTES", "60"))
QUIET_HOURS    = os.getenv("QUIET_HOURS", "")              # e.g. "22-08" -> bot ON between 22:00 and 08:00
LLM_BASE_URL   = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL      = os.getenv("LLM_MODEL", "llama3.1")
LLM_API_KEY    = os.getenv("LLM_API_KEY", "ollama")
HISTORY_TURNS  = int(os.getenv("HISTORY_TURNS", "6"))
AUDIT_PATH     = Path(os.getenv("AUDIT_PATH", "audit.jsonl"))
PRESENCE_TOKEN = os.getenv("PRESENCE_TOKEN", "")          # shared secret for the phone Focus webhook
BUCKETS        = json.loads(Path("buckets.json").read_text()) if Path("buckets.json").exists() else {}
PERSONA        = Path("persona.md").read_text() if Path("persona.md").exists() else "You are a brief, polite assistant."
STATIC_OOO     = os.getenv("STATIC_OOO", "Hi — this is an automated assistant. The person you're messaging is offline; they'll see your message when they're back.")

API = "https://msgapi.threema.ch"

# ---------------------------------------------------------------- state (in-memory)
state = {
    "mode": "auto",            # auto | on | off   (manual override beats schedule)
    "phone_focus": None,       # None | "on" | "off"  set by /presence webhook
    "holds": {},               # contact_id -> unix ts until which bot stays silent
    "pending": {},             # contact_id -> asyncio.Task in grace window
    "history": {},             # contact_id -> [{"role","content"}]
    "pubkeys": {},             # contact_id -> PublicKey
}

def now() -> float: return time.time()
def iso() -> str: return datetime.now(timezone.utc).isoformat()

def bot_should_answer() -> bool:
    if state["mode"] == "on":  return True
    if state["mode"] == "off": return False
    if state["phone_focus"] is not None: return state["phone_focus"] == "on"
    if not QUIET_HOURS:        return True
    start, end = (int(x) for x in QUIET_HOURS.split("-"))
    h = datetime.now().hour
    return (start <= h or h < end) if start > end else (start <= h < end)

def audit(**rec):
    rec.setdefault("ts", iso())
    with AUDIT_PATH.open("a") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")

# ---------------------------------------------------------------- threema gateway crypto
_sk = PrivateKey(bytes.fromhex(PRIVATE_KEY)) if PRIVATE_KEY else None

async def pubkey(tid: str) -> PublicKey:
    if tid not in state["pubkeys"]:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{API}/pubkeys/{tid}", params={"from": GATEWAY_ID, "secret": GATEWAY_SECRET})
            r.raise_for_status()
        state["pubkeys"][tid] = PublicKey(bytes.fromhex(r.text.strip()))
    return state["pubkeys"][tid]

def verify_mac(fields: dict, mac: str) -> bool:
    msg = "".join(fields[k] for k in ("from", "to", "messageId", "date", "nonce", "box")).encode()
    calc = hmac.new(GATEWAY_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, mac)

async def decrypt(sender: str, nonce_hex: str, box_hex: str) -> tuple[int, bytes]:
    box = Box(_sk, await pubkey(sender))
    plain = box.decrypt(bytes.fromhex(box_hex), bytes.fromhex(nonce_hex))
    plain = plain[: -plain[-1]]                    # strip PKCS#7-style padding
    return plain[0], plain[1:]                     # (type byte, payload)

async def send_text(to: str, text: str) -> str:
    """Encrypt + POST /send_e2e. Returns Threema message id."""
    payload = b"\x01" + text.encode()
    pad = secrets.randbelow(255) + 1
    payload += bytes([pad]) * pad
    nonce = secrets.token_bytes(24)
    ct = Box(_sk, await pubkey(to)).encrypt(payload, nonce).ciphertext
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{API}/send_e2e", data={
            "from": GATEWAY_ID, "to": to, "secret": GATEWAY_SECRET,
            "nonce": nonce.hex(), "box": ct.hex()})
    if r.status_code == 402: raise RuntimeError("Gateway credits exhausted")
    r.raise_for_status()
    return r.text.strip()

# ---------------------------------------------------------------- LLM
async def llm_reply(contact: str, text: str) -> tuple[str, str]:
    hist = state["history"].setdefault(contact, [])
    hist.append({"role": "user", "content": text})
    bucket_list = "\n".join(f"- {k}: {v['when']}" for k, v in BUCKETS.items()) or "- other: anything"
    system = (PERSONA + "\n\nClassify the message into exactly one bucket:\n" + bucket_list +
              "\n\nRespond ONLY with JSON: {\"bucket\": \"<name>\", \"reply\": \"<text or FALLBACK>\"}")
    msgs = [{"role": "system", "content": system}] + hist[-HISTORY_TURNS:]
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json={"model": LLM_MODEL, "messages": msgs, "temperature": 0.4, "max_tokens": 200})
            r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip().strip("`")
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        data = json.loads(raw)
        bucket, out = data.get("bucket", "other"), (data.get("reply") or "").strip()
        policy = BUCKETS.get(bucket, {}).get("action", "reply")   # reply | ooo | silent
        audit(event="bucket", contact=contact, bucket=bucket, action=policy)
        if policy == "silent": return "", f"{LLM_MODEL}/{bucket}"
        if policy == "ooo" or not out or out.upper().startswith("FALLBACK"):
            out = BUCKETS.get(bucket, {}).get("template") or STATIC_OOO
        hist.append({"role": "assistant", "content": out})
        return out, f"{LLM_MODEL}/{bucket}"
    except Exception as e:
        audit(event="llm_fallback", contact=contact, error=str(e))
        return STATIC_OOO, "static_ooo"

# ---------------------------------------------------------------- operator commands
async def handle_command(text: str) -> str:
    parts = text.strip().split(maxsplit=2)
    cmd = parts[0].lower()
    if cmd == "!on":        state["mode"] = "on";   return "Bot ON (manual)."
    if cmd == "!off":       state["mode"] = "off";  return "Bot OFF (manual)."
    if cmd == "!auto":      state["mode"] = "auto"; return "Bot on schedule/auto."
    if cmd == "!standdown":
        state["mode"] = "off"
        for t in state["pending"].values(): t.cancel()
        state["pending"].clear()
        return "STANDDOWN: all replies cancelled, bot OFF."
    if cmd == "!hold" and len(parts) > 1:
        cid = parts[1].upper()
        state["holds"][cid] = now() + HOLD_MINUTES * 60
        if t := state["pending"].pop(cid, None): t.cancel()
        return f"Holding {cid} for {HOLD_MINUTES} min — you handle it."
    if cmd == "!release" and len(parts) > 1:
        state["holds"].pop(parts[1].upper(), None); return f"Released {parts[1].upper()}."
    if cmd == "!correct" and len(parts) > 2:
        mid = await send_text(parts[1].upper(), f"Correction: the previous automated message contained an error. {parts[2]}")
        audit(event="correction", contact=parts[1].upper(), text=parts[2], msg_id=mid)
        return "Correction sent."
    if cmd == "!status":
        return f"mode={state['mode']} answering={bot_should_answer()} holds={list(state['holds'])} pending={list(state['pending'])}"
    return "Commands: !on !off !auto !standdown !hold ID !release ID !correct ID text !status"

# ---------------------------------------------------------------- core pipeline
async def notify_operator(text: str):
    if OPERATOR_ID and _sk: await send_text(OPERATOR_ID, text)
    else: print("[NOTIFY]", text)

async def answer_after_grace(contact: str, nick: str, text: str, dry: bool):
    try:
        await asyncio.sleep(GRACE_SECONDS)
        if now() < state["holds"].get(contact, 0) or not bot_should_answer():
            audit(event="suppressed", contact=contact); return
        reply, model = await llm_reply(contact, text)
        if not reply:
            audit(event="silent", contact=contact, model=model)
            await notify_operator(f"🔕 {nick} ({contact}): {text[:200]}\n(bucket says: don't reply — yours to handle)"); return
        mid = "dry-run" if dry else await send_text(contact, reply)
        audit(event="outbound", contact=contact, nick=nick, inbound=text, outbound=reply, model=model, msg_id=mid)
        await notify_operator(f"✅ Replied to {nick} ({contact})\nThey said: {text[:200]}\nI said: {reply}\n\n!hold {contact} to take over · !correct {contact} <text>")
    except asyncio.CancelledError:
        audit(event="cancelled_by_operator", contact=contact)
    finally:
        state["pending"].pop(contact, None)

async def process_inbound(contact: str, nick: str, text: str, dry: bool = False):
    audit(event="inbound", contact=contact, nick=nick, text=text)
    if contact == OPERATOR_ID and text.startswith("!"):
        ack = await handle_command(text); await notify_operator(ack); return
    if contact == OPERATOR_ID:
        return                                           # operator chatting, not a command
    if now() < state["holds"].get(contact, 0):
        audit(event="suppressed_hold", contact=contact); return
    if not bot_should_answer():
        await notify_operator(f"📩 {nick} ({contact}): {text[:300]}\n(bot is OFF — not replying)"); return
    if t := state["pending"].pop(contact, None): t.cancel()  # new message resets grace window
    await notify_operator(f"⏳ {nick} ({contact}): {text[:300]}\nReplying in {GRACE_SECONDS}s — !hold {contact} to stop me.")
    state["pending"][contact] = asyncio.create_task(answer_after_grace(contact, nick, text, dry))

# ---------------------------------------------------------------- HTTP
app = FastAPI()

@app.post("/callback")
async def callback(from_: str = Form(alias="from"), to: str = Form(...), messageId: str = Form(...),
                   date: str = Form(...), nonce: str = Form(...), box: str = Form(...),
                   mac: str = Form(...), nickname: str = Form("")):
    fields = {"from": from_, "to": to, "messageId": messageId, "date": date, "nonce": nonce, "box": box}
    if not verify_mac(fields, mac):
        audit(event="bad_mac", contact=from_); return Response(status_code=401)
    try:
        mtype, payload = await decrypt(from_, nonce, box)
    except Exception as e:
        audit(event="decrypt_error", contact=from_, error=str(e)); return Response(status_code=200)
    if mtype == 0x01:                                    # text message
        await process_inbound(from_, nickname or from_, payload.decode("utf-8", "replace"))
    else:
        audit(event="ignored_type", contact=from_, type=mtype)   # receipts, media, groups: ignored in MVP
    return Response(status_code=200)                     # always 200, or Gateway retries 3x

@app.post("/presence")
async def presence(token: str = Form(...), focus: str = Form(...)):
    """iOS Shortcut / Tasker: POST token=<PRESENCE_TOKEN>&focus=on|off|clear. 'on' = he is unreachable."""
    if not PRESENCE_TOKEN or not hmac.compare_digest(token, PRESENCE_TOKEN): return Response(status_code=401)
    state["phone_focus"] = None if focus == "clear" else ("on" if focus == "on" else "off")
    audit(event="presence_webhook", focus=focus)
    if state["phone_focus"] == "off":                      # he's back: cancel anything about to send
        for t in state["pending"].values(): t.cancel()
        state["pending"].clear()
    return {"phone_focus": state["phone_focus"], "answering": bot_should_answer()}

@app.get("/health")
async def health(): return {"ok": True, "mode": state["mode"], "answering": bot_should_answer()}

# ---------------------------------------------------------------- local simulation
async def _simulate(text: str, contact: str = "TESTUSER"):
    global GRACE_SECONDS; GRACE_SECONDS = 2
    print(f"> {contact}: {text}")
    await process_inbound(contact, "Test", text, dry=True)
    while state["pending"]: await asyncio.sleep(0.2)
    print(open(AUDIT_PATH).read().splitlines()[-1])

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "keygen":
        k = PrivateKey.generate()
        print("PRIVATE_KEY_HEX=" + k.encode().hex()); print("PUBLIC_KEY_HEX=" + k.public_key.encode().hex())
        print("Register the PUBLIC key in the Gateway console.")
    elif len(sys.argv) > 2 and sys.argv[1] == "simulate":
        asyncio.run(_simulate(" ".join(sys.argv[2:])))
    else:
        print(__doc__)
