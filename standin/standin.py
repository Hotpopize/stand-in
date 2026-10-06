"""
standin.py — answer for the person when they're away. Labelled, by default.

Rules (the whole thing):
  1. A contact writes in a room.
  2. The owner wrote anywhere in the last AWAY_AFTER min  -> present      -> do nothing.
  3. The owner wrote in THIS room in the last ROOM_QUIET min -> handling it -> do nothing.
  4. Otherwise answer (persona.md), in the room.
  5. The owner's own messages are the only control signal. No commands, no pings.

HONESTY:
  LABELLED mode (default) — the bot is a SEPARATE account with a display name that
  says "(bot)". The contact sees a distinct, named sender. No deception: whoever
  they're talking to is openly not the owner. This is the only mode meant for real
  contacts. On Threema the equivalent is the Gateway ID's "*" prefix, enforced by
  the platform.

  UNLABELLED mode (BOT_USER == OWNER_USER) exists only for the closed-loop
  detection experiment where YOU are on both ends. It replies from the owner's own
  identity. Do not point it at people who haven't been told.

Transport is `Channel`; subclass it for Threema/whatever. Matrix included.
Run:  python standin.py            Needs .env (testenv.py writes a working one).
"""
import asyncio, json, os, time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv; load_dotenv()

AWAY_AFTER = int(os.getenv("AWAY_AFTER_MIN", "15")) * 60
ROOM_QUIET = int(os.getenv("ROOM_QUIET_MIN", "60")) * 60
HISTORY    = int(os.getenv("HISTORY_TURNS", "8"))
PERSONA    = Path("persona.md").read_text() if Path("persona.md").exists() else "Reply briefly."
AUDIT      = Path(os.getenv("AUDIT_PATH", "data/audit.jsonl")); AUDIT.parent.mkdir(parents=True, exist_ok=True)
LLM        = dict(url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"), model=os.getenv("LLM_MODEL", "llama3.1"),
                  key=os.getenv("LLM_API_KEY", "ollama"))
FALLBACK   = os.getenv("FALLBACK", "")

OWNER_USER = os.getenv("OWNER_USER") or os.getenv("USER_ID")        # the person; their messages = control signal
BOT_USER   = os.getenv("BOT_USER") or OWNER_USER                    # who the bot logs in as
BOT_PW     = os.getenv("BOT_PASSWORD") or os.getenv("PASSWORD", "")
DISPLAY    = os.getenv("DISPLAY_NAME", "")                          # set on the bot account (label lives here)
PREFIX     = os.getenv("MESSAGE_PREFIX", "")                        # optional per-message tag, e.g. "[auto] "
LABELLED   = BOT_USER != OWNER_USER


class StandIn:
    def __init__(self, channel):
        self.ch = channel
        self.last_seen_anywhere = 0.0
        self.last_seen_in: dict[str, float] = {}
        self.history: dict[str, list] = {}

    def away(self, room):
        t = time.time()
        return t - self.last_seen_anywhere > AWAY_AFTER and t - self.last_seen_in.get(room, 0) > ROOM_QUIET

    async def person_said(self, room, text):
        self.last_seen_anywhere = self.last_seen_in[room] = time.time()
        self.history.setdefault(room, []).append({"role": "assistant", "content": text})

    async def contact_said(self, room, who, text):
        h = self.history.setdefault(room, []); h.append({"role": "user", "content": text})
        if not self.away(room):
            self._log(event="skip_present", room=room); return
        reply = await self._llm(h[-HISTORY:])
        if not reply: self._log(event="skip_no_model", room=room); return
        await self.ch.send(room, reply)
        h.append({"role": "assistant", "content": reply})
        self._log(event="replied", room=room, who=who, inbound=text, outbound=reply)

    async def _llm(self, msgs):
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{LLM['url']}/chat/completions", headers={"Authorization": f"Bearer {LLM['key']}"},
                    json={"model": LLM["model"], "temperature": 0.5, "max_tokens": 160,
                          "messages": [{"role": "system", "content": PERSONA}] + msgs})
                r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            self._log(event="llm_error", error=str(e)); return FALLBACK

    def _log(self, **rec):
        rec["ts"] = datetime.now(timezone.utc).isoformat()
        with AUDIT.open("a") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")


class Channel:
    async def send(self, room, text): ...
    async def run(self, s: StandIn): ...


class Matrix(Channel):
    def __init__(self):
        from nio import AsyncClient
        self.hs = os.getenv("HOMESERVER")
        self.session = Path(os.getenv("SESSION_FILE", "data/session.json"))
        self.c = AsyncClient(self.hs, BOT_USER); self.own: set[str] = set(); self.t0 = int(time.time() * 1000)

    async def send(self, room, text):
        r = await self.c.room_send(room, "m.room.message", {"msgtype": "m.text", "body": PREFIX + text},
                                   ignore_unverified_devices=True)
        if eid := getattr(r, "event_id", None): self.own.add(eid)

    async def login(self):
        from nio import LoginResponse
        if self.session.exists():
            s = json.loads(self.session.read_text())
            self.c.restore_login(s["user_id"], s["device_id"], s["access_token"])
            if getattr(await self.c.whoami(), "user_id", None) == BOT_USER: return True
        r = await self.c.login(BOT_PW, device_name="stand-in")
        if not isinstance(r, LoginResponse): print("login failed:", r); return False
        self.session.write_text(json.dumps({"user_id": r.user_id, "device_id": r.device_id, "access_token": r.access_token}))
        self.session.chmod(0o600); return True

    async def run(self, s: StandIn):
        from nio import RoomMessageText, InviteMemberEvent
        if not await self.login(): return
        if LABELLED and DISPLAY:                                   # the label: visible to every contact
            await self.c.set_displayname(DISPLAY)
        async def on_msg(room, ev):
            if ev.server_timestamp < self.t0 or ev.event_id in self.own:
                self.own.discard(ev.event_id); return
            if LABELLED and ev.sender == BOT_USER: return         # our own account on another device
            if ev.sender == OWNER_USER: await s.person_said(room.room_id, ev.body)
            else: await s.contact_said(room.room_id, room.user_name(ev.sender) or ev.sender, ev.body)
        async def on_invite(room, ev):
            if ev.state_key == BOT_USER: await self.c.join(room.room_id)
        self.c.add_event_callback(on_msg, RoomMessageText)
        self.c.add_event_callback(on_invite, InviteMemberEvent)
        await self.c.sync(timeout=5000, full_state=True)
        mode = f"LABELLED as {BOT_USER} (display: {DISPLAY or '—'})" if LABELLED else f"UNLABELLED as {OWNER_USER}"
        print(f"stand-in live — {mode}, device={self.c.device_id}")
        await self.c.sync_forever(timeout=30000)


async def _main():
    if not LABELLED and os.getenv("I_UNDERSTAND_UNLABELLED") != "yes":
        print("UNLABELLED mode (BOT_USER == OWNER_USER) replies from the owner's own identity.\n"
              "It is for the closed-loop detection test only. Set I_UNDERSTAND_UNLABELLED=yes to run it.")
        return
    ch = Matrix()
    await ch.run(StandIn(ch))


if __name__ == "__main__":
    asyncio.run(_main())
