# Threema AI offline responder — rough MVP

Single Python process. Gateway E2E webhook in, LLM reply out, operator gets a Threema notification, everything logged to `audit.jsonl`.

## Run locally without a Gateway
```
pip install -r requirements.txt
python app.py simulate "hey, are you around tomorrow?"
```
Uses a 2s grace window, dry-run send, prints the notification and audit line. Needs Ollama (or any OpenAI-compatible endpoint) at LLM_BASE_URL; without it you get the static OOO fallback.

## Go live
1. `python app.py keygen` → put PRIVATE_KEY_HEX in `.env`, register the public key on your Gateway ID (E2E mode).
2. Fill `.env` from `config.example.env`. OPERATOR_ID = the client's personal Threema ID.
3. Expose `/callback` over HTTPS with a CA-signed cert (Gateway rejects self-signed). Set it as the callback URL in the Gateway console.
4. `uvicorn app:app --host 0.0.0.0 --port 8080`
5. The client adds `*XXXXXXX` as a contact and sends `!status`.

## Operator commands (sent from OPERATOR_ID to the bot)
`!on` `!off` `!auto` `!standdown` `!hold ID` `!release ID` `!correct ID text` `!status`

## Presence logic (v0)
manual `!on/!off` > QUIET_HOURS schedule > per-contact hold. Every inbound waits GRACE_SECONDS before the bot replies, so the operator can `!hold`.

## Not in v0
Groups, media, delivery receipts, phone-Focus webhook, persistence across restarts, multi-operator.

## Docker (same command locally and on the VPS)
```
mkdir -p data && cp config.example.env .env   # fill it in
docker compose up -d --build
```
Local: Ollama runs on the host, container reaches it via host.docker.internal.
VPS: set LLM_BASE_URL to whatever endpoint you choose, uncomment the caddy service, put your domain in `Caddyfile` — Caddy gets the CA-signed cert automatically, which is what the Gateway callback requires.
Only three files carry the client: `.env`, `persona.md`, `buckets.json`. Copy those and `data/` and the deployment moves.
