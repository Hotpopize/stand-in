"""
step1.py — the whole step-1 build, nothing else:

  1. receive a message      (Threema Gateway SDK callback, hosted locally, exposed via ngrok)
  2. draft a reply          (any OpenAI-compatible LLM API — Ollama, OpenAI, etc.)
  3. send it from your ID   (SDK, end-to-end encrypted TextMessage from your Gateway *ID)
  4. log the action         (one JSON line per message in log.jsonl)

  python step1.py keygen    # once: register the printed PUBLIC key in the Gateway console
  python step1.py           # run; paste the printed URL + /gateway_callback into the console

.env:
  GATEWAY_ID=*XXXXXXX  GATEWAY_SECRET=...  GATEWAY_PRIVATE_KEY=private:...  NGROK_AUTHTOKEN=...
  LLM_BASE_URL=http://127.0.0.1:11434/v1  LLM_MODEL=llama3.1  LLM_API_KEY=ollama
  SYSTEM_PROMPT="Reply briefly and helpfully."   PORT=8080
"""
import asyncio, json, os, time
import httpx
from aiohttp import web
from threema.gateway import Connection, e2e
from threema.gateway.key import Key
from dotenv import load_dotenv; load_dotenv()

LLM = dict(url=os.getenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1"), model=os.getenv("LLM_MODEL", "llama3.1"),
           key=os.getenv("LLM_API_KEY", "ollama"), system=os.getenv("SYSTEM_PROMPT", "Reply briefly and helpfully."))


async def draft(text):                                                    # 2
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{LLM['url']}/chat/completions", headers={"Authorization": f"Bearer {LLM['key']}"},
                         json={"model": LLM["model"], "messages": [{"role": "system", "content": LLM["system"]},
                                                                    {"role": "user", "content": text}]})
        r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def log(**rec):                                                           # 4
    rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open("log.jsonl", "a") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")


async def on_message(msg):                                                # 1 -> 2 -> 3 -> 4
    text = getattr(msg, "text", None)                                     # receipts/media carry no text
    if not text: return
    reply = await draft(text)
    await e2e.TextMessage(conn, text=reply, to_id=msg.from_id).send()     # 3
    log(from_id=msg.from_id, inbound=text, outbound=reply, model=LLM["model"])
    print(f"{msg.from_id}: {text!r} -> {reply!r}")


async def serve():
    global conn
    port = int(os.getenv("PORT", "8080"))
    conn = Connection(os.environ["GATEWAY_ID"], os.environ["GATEWAY_SECRET"], key=os.environ["GATEWAY_PRIVATE_KEY"])
    app = e2e.create_application(conn)
    e2e.add_callback_route(conn, app, on_message, path="/gateway_callback")   # SDK does HMAC + decryption
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    import ngrok
    listener = await ngrok.forward(port, authtoken_from_env=True)
    print(f"callback: {listener.url()}/gateway_callback")
    await asyncio.Event().wait()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "keygen":
        priv, pub = Key.generate_pair()
        print("GATEWAY_PRIVATE_KEY=" + Key.encode(priv)); print("register in console:", Key.encode(pub))
    else:
        asyncio.run(serve())
