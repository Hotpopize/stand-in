# stand-in

A support assistant that **drafts** replies and **routes** tickets, built as two engines — one decides *what* to say, one decides *how* it sounds — wrapped in guardrails that decide *when it's allowed to act on its own*. a messaging stand-in on a server you control.

**Status: prototype.** Everything here runs end-to-end on synthetic data. Nothing has been measured against real tickets or real human replies yet, and no language model has written a draft in any verified run. Treat every "it works" as "the plumbing runs."

## Step 1 — the minimal build

`step1.py` is the whole thing in one file: receive via the Threema Gateway SDK → draft with any OpenAI-compatible LLM → send from your `*ID` via the SDK → log. Hosted on your PC, exposed with ngrok.

```bash
pip install -r requirements.txt
python step1.py keygen      # register the PUBLIC key in the Gateway console
# .env: GATEWAY_ID GATEWAY_SECRET GATEWAY_PRIVATE_KEY NGROK_AUTHTOKEN LLM_BASE_URL LLM_MODEL
python step1.py             # paste the printed .../gateway_callback URL into the console
```
Chain verified locally with a stub LLM and intercepted send; not yet against a live Gateway.

## Repo map

| Folder | What it is | State |
|---|---|---|
| `dual-engine/` | **The main build.** Intent engine → typed contract → persona engine, plus shadow execution and a semantic circuit breaker. | Runs; invariants tested |
| `standin/` | The Matrix lab: a stand-in that replies when you're away, labelled by default, with a one-command throwaway homeserver. | Transport verified once, scripted |
| `dual-engine/gateway.py` | Threema Gateway transport via the **official SDK** (`threema.gateway`). Labelled `*ID`, hosted on your PC, exposed with ngrok. | Callback route + HMAC rejection verified locally; no live message yet |
| `demo/` | Published interactive demo of labelled vs. undisclosed replies. | Simulation, scripted replies |
| `tests/` | Regression suite for the engine invariants. | 11 tests, `pytest -q` |

Deliberately **not** included: the earlier `impersonation-lab` (superseded by `standin/`), the second demo variant, VPS/Caddy files, and the hand-rolled Threema crypto (replaced by the official SDK).

## Walkthrough

### 0. Prerequisites
Python 3.11+. Nothing else is required to run the engine or the tests. A local model (Ollama) is optional and only affects draft *wording*.

```bash
git clone https://github.com/Hotpopize/stand-in.git && cd stand-in
pip install -r dual-engine/requirements.txt pytest
```

### 1. Prove the invariants hold (10 seconds)
```bash
pytest -q
```
Eleven tests lock the rules that must never regress: refunds and complaints always escalate; no supporting knowledge → escalate; the on-topic guard keeps a sales ticket from receiving a password fact; the persona renders *only* the claims it's handed and nothing on an escalation; the commitment detector fires on "I've refunded you" and not on "a teammate can refund"; the breaker trips on a loop and a bot streak, not on a healthy thread.

These test **rules, not quality**. Quality is the next step.

### 2. Run the engine over synthetic tickets
```bash
cd dual-engine
python run.py              # 12 sample tickets → category, route, rendered reply
python shadow_demo.py      # shadow scoring + readiness verdicts + breaker trips
```
`run.py` shows each ticket's route (`auto` / `assist` / `escalate`) and what the persona rendered. `data/audit.jsonl` stores the **spec and the rendered text side by side** per ticket — that's how you verify the boundary held.

`shadow_demo.py` compares drafts against "what the human actually sent" on three axes — factual alignment, tone divergence, unauthorized commitments — and rolls them into a per-category **PROMOTE / HOLD** verdict. Read `dual-engine/SHADOW.md` for what each number means.

### 3. Plug in a model (optional)
```bash
LLM_BASE_URL=http://127.0.0.1:11434/v1 LLM_MODEL=llama3.1 python run.py
```
Without it, the persona engine uses a template path and every reply is the KB text wrapped in a greeting. With it, drafts are model-written — and this is the **first unverified path**: it has never been exercised in a recorded run.

### 4. Threema Gateway on your PC (needs a Gateway ID + ngrok token)
```bash
cd dual-engine
python gateway.py keygen           # register the printed PUBLIC key in the Gateway console
# .env: GATEWAY_ID=*XXXXXXX  GATEWAY_SECRET=...  GATEWAY_PRIVATE_KEY=private:...  NGROK_AUTHTOKEN=...
python gateway.py                  # prints https://<ngrok>/gateway_callback — paste into the console
```
Incoming message → intent → persona → reply sent as an E2E `TextMessage` from your `*ID`. Escalations send nothing. HMAC and decryption are the SDK's, not ours.

### 5. Run the lab (optional, needs `matrix-synapse`)
```bash
cd ../standin && pip install -r requirements.txt
python testenv.py up        # throwaway Synapse + 3 users + a room, writes .env
python standin.py           # second shell — logs in as a separate labelled bot account
python testenv.py scenario  # contact writes → bot replies → you reply → bot goes quiet
python testenv.py down
```
Default is **labelled**: a separate `@assistant` account with "(bot)" in its display name. Undisclosed mode (replying from the owner's own identity) exists for closed-loop self-tests only and is fenced behind `I_UNDERSTAND_UNLABELLED=yes`. Do not point it at people who haven't been told.

## Architecture in one picture

```
ticket ──▶ INTENT ENGINE ──▶ ResponseSpec ──▶ PERSONA ENGINE ──▶ reply + route
           classify           { action,          render claims
           retrieve             claims[src,txt],  in a voice,
           gate + policy        constraints }     language, label
           WHAT to say          the contract      HOW it sounds
                                     │
              shadow execution ◀─────┘─────▶ circuit breaker
              (earns assist→auto)           (halts a live run)
```

The contract is the whole design: the persona engine is handed **only** `spec.claims`, so it cannot assert a fact the intent engine didn't vet. What it *can* do is faithfully render a wrong fact if the intent engine hands it one — fact correctness is an intent-side job. That exact failure was found and fixed during the build (see `dual-engine/README.md`).

## Verification status — read this before trusting anything

| Component | Verified? | How |
|---|---|---|
| Routing invariants (sensitive→escalate, on-topic guard, no-KB→escalate) | ✅ | `pytest`, deterministic |
| Persona renders only claims; nothing on escalate | ✅ | `pytest` |
| Commitment detector, breaker loop/streak | ✅ on my own cases | `pytest` + `shadow_demo.py` |
| Matrix transport (login, session restore, send/receive, own-echo, quiet-after-human) | ✅ once | one scripted scenario on a real Synapse; presence timing was forced (`AWAY_AFTER_MIN=0`) |
| LLM draft path | ❌ | never run with a model present |
| Shadow metrics on **held-out** human replies | ❌ | all test cases were authored by the same hand that tuned the rules — see below |
| Threema Gateway transport (official SDK) | ✅ locally | callback route rejects forged/empty requests (400); keygen works. ❌ no live Gateway message yet |

**The overfitting problem, stated plainly.** The knowledge base, the tickets, the "human" replies, and the adversarial drafts were all written by the same author who then tuned thresholds, the lexicon and the alignment metric until they passed. The results show the code behaves as designed; they do not show it works. The fix is held-out data nobody here wrote — real tickets with the replies people actually sent. Until that exists, every readiness verdict is theatre.

## Boundaries

- It never sends on its own. A human approves every reply until a category is promoted by shadow evidence.
- Refunds, complaints, and anything without KB support go to a human, enforced in code.
- The persona engine cannot add a fact, price, date or promise not in the spec.
- The undisclosed stand-in mode is for closed-loop research on yourself only.

## Next

1. **Real data.** Get tickets + actual human replies from a real operation. Freeze the rules, run shadow, report with sample sizes.
2. **Real embeddings.** `textvec.py` is a hashing stand-in; swap for sentence-transformers and alignment/drift get sharp.
3. **Run a model.** Close the one unverified path that matters most.

Project notes: this repo is the code; the Claude project holds the status report and architecture decisions.
