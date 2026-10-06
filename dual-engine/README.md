# dual-engine

Two engines, one contract. The split is **what to say** vs **how it sounds**.

```
                          ┌──────────────────────────────┐
   ticket  ──────────────▶│  INTENT ENGINE   (intent.py)  │   decides WHAT
                          │  classify · retrieve · gate   │
                          │  apply policy · pick facts    │
                          └───────────────┬──────────────┘
                                          │  ResponseSpec   ← the only interface (contract.py)
                                          │  { action, category, confidence,
                                          │    claims[ {source,text} ],       ← the ONLY facts allowed out
                                          │    constraints{ language, max_words,
                                          │                 must_not, disclosure } }
                                          ▼
                          ┌──────────────────────────────┐
                          │  PERSONA ENGINE  (persona.py) │   decides HOW
                          │  render claims in a voice ·   │
                          │  language · length · label    │
                          └───────────────┬──────────────┘
                                          ▼
                       customer_text  +  internal_note  +  auto_ready
```

## Why split it

- **Voice is swappable without touching logic.** Support brand today; in phase 2 each real-estate agent gets their own voice — that's a change to `persona.py` / the voice card alone, with the routing and safety untouched.
- **Logic is testable without a model.** `intent.py` is deterministic. You can unit-test routing and fact-selection with zero LLM calls; the model only ever enters the persona step.
- **One-way fact flow is a type-level safety property.** The persona engine is handed *only* `spec.claims`. A fact the intent engine didn't vet literally isn't in scope, so the renderer can't assert it. The gate already happened upstream.

## The invariants (what each engine may NOT do)

**Intent engine** never phrases a reply, picks a greeting, or chooses wording. It only decides and packages facts.
**Persona engine** never changes the action, re-decides the route, or adds a fact/price/date/promise not in `claims`. It never sees the KB or the policy — only the spec.

## What the test run proved

12 tickets, both engines, verified end-to-end (no model — fallback renderer):

- Grounded auto-drafts for invoice, password reset, workspace, export, duplicate charge — each traceable to one KB id in its spec.
- Refund and complaint → `escalate`, no customer text, by rule.
- German ticket → language `de` detected, carried in the spec, rendered in German.
- **The bug this caught:** a sales ticket with no KB support first rendered a wrong (password) fact. The fix went in the *intent* engine — an on-topic guard that drops claims not sharing the category's vocabulary — so now it escalates instead. That's the key lesson: the contract stops the persona from *inventing* facts, but only the intent engine can stop a *wrong* fact being handed over. Retrieval precision is an intent-side responsibility.

## Run

    python run.py            # built-in sample tickets through both engines
    python run.py gen 12     # synthetic tickets, then run
    LLM_BASE_URL=http://127.0.0.1:11434/v1 python run.py   # real drafts via a local model
    DISCLOSE=true python run.py                            # prepend an "automated reply" label (phase-2 default)

`data/audit.jsonl` stores the **spec and the rendered output per ticket** — read them side by side to confirm the boundary held.

## Files

- `contract.py` — `ResponseSpec` / `Claim` / `Constraints`. The entire interface. Neither engine imports the other.
- `intent.py` — Engine 1. Deterministic. Owns classification, retrieval, policy, fact selection.
- `persona.py` — Engine 2. Owns voice, language, length, disclosure. Swap this to change how it sounds.
- `run.py` — glue + synthetic tickets + audit.
- `kb.json`, `brand.md` — sample knowledge and voice card; replace both for a real deployment.

## Honest limits (unchanged from the prototype)

Retrieval is keyword-overlap with an on-topic guard — good enough to route correctly here, but embeddings are the real upgrade as the KB grows. Confidence is a routing heuristic, not a calibrated probability. The LLM render path hasn't been run against a real model yet; the deterministic fallback is what's verified.
