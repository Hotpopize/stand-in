"""
gateway.py — Threema Gateway transport for the dual engine, using the official SDK.

    python gateway.py keygen        # print a private/public key pair; register the PUBLIC one in the Gateway console
    python gateway.py               # serve the callback locally and expose it via ngrok

Env (.env): GATEWAY_ID (*XXXXXXX), GATEWAY_SECRET, GATEWAY_PRIVATE_KEY (private:<hex>),
            NGROK_AUTHTOKEN, PORT (default 8080), LLM_BASE_URL (optional).

Incoming E2E message -> intent engine -> persona engine -> reply sent as an E2E TextMessage.
Escalations send nothing and are logged. The SDK does HMAC verification and decryption.
"""
import asyncio, os
from aiohttp import web
from threema.gateway import Connection, e2e
from threema.gateway.key import Key

from intent import IntentEngine
from persona import PersonaEngine

intent, persona = IntentEngine(), PersonaEngine()


async def on_message(msg):
    if not isinstance(msg, e2e.TextMessage):
        return
    spec = intent.build({"id": msg.message_id.hex(), "text": msg.text})
    out = persona.render(spec)
    print(f"[{msg.from_id}] {spec.category}/{spec.action}: {out['customer_text'] or out['internal_note']}")
    if out["customer_text"]:
        await e2e.TextMessage(conn, text=out["customer_text"], to_id=msg.from_id).send()


def keygen():
    priv, pub = Key.generate_pair()
    print("GATEWAY_PRIVATE_KEY=" + Key.encode(priv))
    print("public key (register this in the Gateway console):", Key.encode(pub))


async def serve():
    global conn
    port = int(os.getenv("PORT", "8080"))
    conn = Connection(os.environ["GATEWAY_ID"], os.environ["GATEWAY_SECRET"], key=os.environ["GATEWAY_PRIVATE_KEY"])
    app = e2e.create_application(conn)
    e2e.add_callback_route(conn, app, on_message, path="/gateway_callback")
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    import ngrok
    listener = await ngrok.forward(port, authtoken_from_env=True)
    print(f"callback URL -> {listener.url()}/gateway_callback   (paste into the Gateway console)")
    await asyncio.Event().wait()


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv; load_dotenv()
    keygen() if len(sys.argv) > 1 and sys.argv[1] == "keygen" else asyncio.run(serve())
