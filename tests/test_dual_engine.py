"""
Regression tests for the dual-engine invariants. No model, no network.

    pytest -q

These lock the rules that must never regress, not quality. Quality is measured by shadow
execution against held-out human replies (see dual-engine/SHADOW.md) — not here.
"""
import os, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "dual-engine"


@pytest.fixture(autouse=True)
def _in_dual_engine(monkeypatch):
    monkeypatch.chdir(ROOT)                     # kb.json / brand.md are loaded relative to cwd
    monkeypatch.syspath_prepend(str(ROOT))
    for m in ("intent", "persona", "shadow", "breaker", "textvec", "contract"):
        sys.modules.pop(m, None)                # fresh import under the right cwd
    yield


def spec_for(text, tid="T1"):
    from intent import IntentEngine
    return IntentEngine().build({"id": tid, "text": text})


# ---- intent engine: routing invariants -------------------------------------
@pytest.mark.parametrize("text", [
    "I want to cancel and get a refund for the year.",
    "This is the worst support I've ever had. Unacceptable.",
])
def test_sensitive_categories_always_escalate(text):
    s = spec_for(text)
    assert s.action == "escalate"
    assert s.claims == []                       # nothing for the persona to say


def test_no_supporting_knowledge_escalates():
    s = spec_for("hey")
    assert s.action == "escalate"


def test_on_topic_guard_blocks_off_topic_claims():
    # the historical T008 failure: a sales ticket must not receive a password-reset fact
    s = spec_for("What's your enterprise pricing, and can we book a demo?")
    assert s.action == "escalate"
    assert all("password" not in c.text.lower() for c in s.claims)


def test_clear_howto_is_auto_with_sourced_claim():
    s = spec_for("How do I set up a second workspace for my team?")
    assert s.action == "auto"
    assert s.claims and all(c.source.startswith("KB") for c in s.claims)


def test_german_ticket_carries_language():
    s = spec_for("Wie kann ich mein Passwort zurücksetzen? Danke!")
    assert s.constraints.language == "de"


# ---- persona engine: the contract holds ------------------------------------
def test_persona_renders_only_claims_and_nothing_on_escalate():
    from persona import PersonaEngine
    pe = PersonaEngine()
    esc = pe.render(spec_for("Refund me now."))
    assert esc["customer_text"] is None and esc["internal_note"]

    ok = spec_for("Where can I download a VAT receipt?")
    out = pe.render(ok)
    assert out["customer_text"]
    for c in ok.claims:
        assert c.text in out["customer_text"]  # template path: every claim is present verbatim


def test_disclosure_label_when_required(monkeypatch):
    monkeypatch.setenv("DISCLOSE", "true")
    from persona import PersonaEngine
    out = PersonaEngine().render(spec_for("How do I export my data to CSV?"))
    assert out["customer_text"].startswith("[Automated reply]")


# ---- shadow scorer: commitment detection is a speech act, not a keyword -----
def test_unauthorized_commitment_fires_on_promise_not_on_process_description():
    from shadow import unauthorized_commitments
    human = "A duplicate from a card retry; it auto-reverses in 5-7 business days."
    assert unauthorized_commitments("I've gone ahead and refunded you in full today.", human)
    assert not unauthorized_commitments("If it hasn't cleared, a teammate can refund the duplicate.", human)


def test_block_verdict_on_any_commitment():
    from shadow import score
    r = score({"category": "billing", "bot_draft": "100% guaranteed, free month added.", "human_actual": "It reverses itself."})
    assert r["verdict"] == "BLOCK"


# ---- circuit breaker --------------------------------------------------------
def test_breaker_trips_on_loop_and_streak_but_not_healthy():
    from breaker import SemanticBreaker
    sb = SemanticBreaker()
    healthy = [{"role": "contact", "text": "invoice question"},
               {"role": "bot", "text": "Invoices are under Settings → Billing."},
               {"role": "contact", "text": "and the VAT number?"},
               {"role": "bot", "text": "It's printed on each invoice PDF, top right."}]
    looping = [{"role": "contact", "text": "login broken"},
               {"role": "bot", "text": "Try resetting your password from the sign-in page."},
               {"role": "contact", "text": "still nothing"},
               {"role": "bot", "text": "Please reset your password from the sign-in page."},
               {"role": "contact", "text": "I did"},
               {"role": "bot", "text": "You can reset your password on the sign-in page."}]
    streak = [{"role": "contact", "text": "hi"}] + [{"role": "bot", "text": f"note {i}"} for i in range(4)]
    assert not sb.evaluate(healthy)["tripped"]
    assert sb.evaluate(looping)["kind"] == "loop"
    assert sb.evaluate(streak)["kind"] == "volumetric"
