# Shadow Execution + Semantic Circuit Breaker

Two safety layers around the dual engine. One decides *when the bot is allowed to graduate from
assist to auto*; the other *catches a live conversation going wrong in real time*.

    python shadow_demo.py     # runs both over synthetic data

## 1. Shadow Execution — earning the assist → auto flip

The proxy runs **passive**: it ingests the production stream read-only, generates its intent +
persona draft, and **never sends**. When the human operator's real reply lands later (hours on),
`shadow.py` joins the two and scores the delta:

| Axis | Meaning | Want | How |
|---|---|---|---|
| `factual_alignment` | did the draft say what the human said? | high | coverage of the human's content tokens by the draft (swap for embedding cosine in prod) |
| `tone_divergence` | how far is the register? | low | distance over a small style-feature vector (length, punctuation, greeting/sign-off, politeness) |
| `unauthorized_commitments` | promises/money/deadlines the draft made that the human did **not** | **zero** | a speech-act lexicon — "I've refunded you", "free month", "guaranteed", "by Friday" — never the bare noun |

**One unauthorized commitment is an automatic BLOCK**, regardless of the other two — that's the
irreversible-harm axis. `aggregate()` rolls records up per category into PROMOTE / HOLD. A
category graduates only on enough clean samples with zero commitments and all-PASS.

What the demo shows: the grounded drafts PASS; an injected draft that promises a refund + free
month + "100% guaranteed" is BLOCKed with every phrase named; `how_to` reaches PROMOTE on two
clean samples while `billing` is held back by that single bad draft. That's shadow mode doing its
job — you get the evidence to flip a category to auto, per category, without a customer ever
seeing a shadow draft.

## 2. Semantic Circuit Breaker — catching a live run going wrong

Volumetric limits (N/min) don't catch a bot that's *degenerating*. `breaker.py` measures
conversational entropy on the **bot's own turn sequence**, comparing turn *k* to *k-1* and *k-2*
by cosine distance:

- **loop / stall** — distance ≤ `loop_dist`: the bot is repeating what it said a turn or two ago.
  Trips after `loop_patience` consecutive stalls (one repeat can be legitimate).
- **volumetric backstop** — `max_bot_streak` bot turns with no contact progress.

The contact's turns are **not** scored — a person can change topic legitimately; the thing being
guarded is the bot. On a trip: halt auto for that conversation, escalate to a human, log the
reason. The demo trips the looping thread (bot re-sending "reset your password" three ways) and
the 4-in-a-row streak, and leaves the healthy thread alone.

> Note on embeddings: `textvec.py` is a dependency-free hashing stand-in so this runs with no
> model. Both layers only call `embed()`/`cosine()`, so production is a one-file swap to
> sentence-transformers or an embeddings endpoint — at which point `factual_alignment` and the
> k-vs-k-2 topic-drift signal get much sharper.

## Files

- `shadow.py` — scorer (`score`, `aggregate`) + the commitment lexicon.
- `breaker.py` — `SemanticBreaker` (loop + volumetric).
- `textvec.py` — the embedding stand-in.
- `shadow_demo.py` — runs both over synthetic cases, including adversarial drafts.
