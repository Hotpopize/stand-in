"""
testenv.py — throwaway test environment for standin.py. One command, no Docker.

  python testenv.py up        local Synapse in ./env; users me + alex + assistant; a room; writes .env (LABELLED)
  python testenv.py scenario  alex writes -> labelled bot replies; me replies -> bot goes quiet; prints transcript
  python testenv.py down       stop the homeserver (data stays in ./env; delete ./env to reset)

Requires: pip install matrix-synapse matrix-nio httpx python-dotenv
"""
import asyncio, json, os, signal, subprocess, sys, time
from pathlib import Path

ENV = Path("env"); ENV.mkdir(exist_ok=True)
HS, NAME = "http://127.0.0.1:8008", "lab"
OWNER, CONTACT, BOT = f"@me:{NAME}", f"@alex:{NAME}", f"@assistant:{NAME}"
DISPLAY = "Me — assistant (bot)"
PW = "test-pw"


def sh(*a): return subprocess.run(a, check=True, capture_output=True, text=True)


def up():
    cfg = ENV / "homeserver.yaml"
    if not cfg.exists():
        sh(sys.executable, "-m", "synapse.app.homeserver", "--server-name", NAME, "--config-path", str(cfg),
           "--generate-config", "--report-stats=no")
        y = cfg.read_text().replace("    - ::1\n", "")
        y += ("\nrc_message: {per_second: 100, burst_count: 100}\n"
              "rc_login: {address: {per_second: 100, burst_count: 100}, account: {per_second: 100, burst_count: 100}, failed_attempts: {per_second: 100, burst_count: 100}}\n")
        cfg.write_text(y)
    p = subprocess.Popen([sys.executable, "-m", "synapse.app.homeserver", "--config-path", str(cfg)],
                         stdout=(ENV / "synapse.log").open("w"), stderr=subprocess.STDOUT)
    (ENV / "synapse.pid").write_text(str(p.pid))
    import httpx
    for _ in range(40):
        try: httpx.get(f"{HS}/_matrix/client/versions", timeout=1); break
        except Exception: time.sleep(0.5)
    else: sys.exit("homeserver did not come up — see env/synapse.log")
    for u in ("me", "alex", "assistant"):
        subprocess.run(["register_new_matrix_user", "-c", str(cfg), "-u", u, "-p", PW, "--no-admin", HS],
                       capture_output=True)
    asyncio.run(_rooms())
    Path(".env").write_text(
        f"HOMESERVER={HS}\nOWNER_USER={OWNER}\nBOT_USER={BOT}\nBOT_PASSWORD={PW}\nDISPLAY_NAME={DISPLAY}\n"
        f"AWAY_AFTER_MIN=0\nROOM_QUIET_MIN=1\n"
        f"LLM_BASE_URL={os.getenv('LLM_BASE_URL', 'http://127.0.0.1:11434/v1')}\n"
        f"FALLBACK=I'm away right now — this is {DISPLAY}. I'll pass your message on.\n")
    print(f"up. me={OWNER} contact={CONTACT} bot={BOT} display={DISPLAY!r}")
    print(f"   room={json.loads((ENV/'rooms.json').read_text())['dm']}")
    print("now:  python standin.py   (second shell)   then:  python testenv.py scenario")


async def _rooms():
    from nio import AsyncClient
    if (ENV / "rooms.json").exists(): return
    me = AsyncClient(HS, OWNER); await me.login(PW, device_name="phone")
    room = await me.room_create(name="chat", invite=[CONTACT, BOT]); await me.close()
    for u in (CONTACT, BOT):                                     # settle membership before the bot runs
        c = AsyncClient(HS, u); await c.login(PW, device_name="phone"); await c.join(room.room_id); await c.close()
    (ENV / "rooms.json").write_text(json.dumps({"dm": room.room_id}))


async def _scenario():
    from nio import AsyncClient, RoomMessageText
    dm = json.loads((ENV / "rooms.json").read_text())["dm"]
    al = AsyncClient(HS, CONTACT); await al.login(PW, device_name="phone"); await al.sync(timeout=1000)
    me = AsyncClient(HS, OWNER);   await me.login(PW, device_name="phone"); await me.sync(timeout=1000)
    async def say(c, t): await c.room_send(dm, "m.room.message", {"msgtype": "m.text", "body": t}); await asyncio.sleep(4)
    print("1. me is away. alex writes:");                                   await say(al, "hey, you around tonight?")
    print("2. me replies from phone -> bot should go quiet here:");          await say(me, "yep, 8 works")
    print("3. alex again -> expect NO bot reply (me is present):");          await say(al, "cool, see you then")

    # what the CONTACT sees as the bot's name — this is the honesty check
    label = await al.get_displayname(BOT)
    r = await al.room_messages(dm, start="", limit=8)
    print("\n--- what alex sees (oldest first) ---")
    names = {OWNER: "me", CONTACT: "alex", BOT: getattr(label, "displayname", "?")}
    for e in reversed(r.chunk):
        if isinstance(e, RoomMessageText):
            print(f"  {names.get(e.sender, e.sender):>22} | {e.sender:<14} | {e.body}")
    print(f"\n bot's display name to alex: {getattr(label, 'displayname', '?')!r}")
    print(f" bot sender id is {BOT} — a different account from {OWNER}, so alex cannot mistake one for the other.")
    await al.close(); await me.close()


def down():
    pid = ENV / "synapse.pid"
    if pid.exists():
        try: os.kill(int(pid.read_text()), signal.SIGTERM)
        except ProcessLookupError: pass
        pid.unlink()
    print("down.")


if __name__ == "__main__":
    {"up": up, "scenario": lambda: asyncio.run(_scenario()), "down": down}.get(
        sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
