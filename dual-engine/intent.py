"""
intent.py — Engine 1: decides WHAT to do. Emits a ResponseSpec. Writes no prose.

Responsibilities (and nothing else):
  - classify the ticket into a category + confidence
  - retrieve supporting facts from the KB
  - apply policy: sensitive categories escalate; confidence sets the route
  - package the allowed facts + constraints into a ResponseSpec

It MUST NOT: phrase a reply, pick a greeting, choose a language's wording. It may be fully
deterministic (it is here) — no model required — which is exactly why it's testable and auditable.
"""
import json, os, re
from pathlib import Path
from contract import ResponseSpec, Claim, Constraints

KB   = json.loads(Path("kb.json").read_text()) if Path("kb.json").exists() else []
HIGH = float(os.getenv("CONF_HIGH", "0.75"))
MED  = float(os.getenv("CONF_MED",  "0.45"))

POLICY = {
    "how_to":         {"sensitive": False, "auto_ok": True},
    "account_access": {"sensitive": False, "auto_ok": True},
    "billing":        {"sensitive": False, "auto_ok": True},
    "bug":            {"sensitive": False, "auto_ok": False},
    "sales":          {"sensitive": False, "auto_ok": False},
    "refund":         {"sensitive": True,  "auto_ok": False},
    "complaint":      {"sensitive": True,  "auto_ok": False},
    "other":          {"sensitive": False, "auto_ok": False},
}
CUES = {
    "billing":        ["invoice", "charge", "charged", "receipt", "vat", "payment", "card", "subscription", "price", "plan"],
    "refund":         ["refund", "money back", "chargeback", "reimburse", "cancel and"],
    "account_access": ["login", "log in", "password", "reset", "locked out", "2fa", "can't access", "sign in"],
    "how_to":         ["how do i", "how to", "where do i", "steps", "set up", "configure", "enable", "export"],
    "bug":            ["error", "broken", "crash", "not working", "bug", "fails", "stuck", "blank", "502", "500"],
    "complaint":      ["terrible", "worst", "angry", "unacceptable", "disappointed", "complaint", "ridiculous", "scam"],
    "sales":          ["pricing for", "enterprise", "demo", "quote", "upgrade to", "how much", "discount"],
}
TOK = re.compile(r"[a-z0-9']+")
_toks = lambda s: set(TOK.findall(s.lower()))


def _classify(text):
    t = text.lower()
    scores = {c: sum(1 for cue in cues if cue in t) for c, cues in CUES.items()}
    scores = {c: n for c, n in scores.items() if n}
    if not scores:
        return "other", 0.30
    cat = max(scores, key=scores.get)
    vals = sorted(scores.values(), reverse=True)
    margin = vals[0] - (vals[1] if len(vals) > 1 else 0)
    return cat, round(min(0.95, 0.45 + 0.15 * vals[0] + 0.1 * margin), 2)


def _retrieve(text, k=2):
    q = _toks(text)
    scored = []
    for e in KB:
        doc = _toks(e["title"] + " " + e["body"] + " " + " ".join(e.get("tags", [])))
        if doc:
            scored.append((len(q & doc) / (len(q | doc) ** 0.5 + 1e-9), e))
    scored.sort(key=lambda x: x[0], reverse=True)
    hits = [e for s, e in scored[:k] if s > 0.12]        # threshold: drop weak matches
    return hits, round(min(1.0, scored[0][0]) if scored else 0.0, 2)


def _language(text):
    de = {"ich", "wie", "kann", "nicht", "mein", "rechnung", "passwort", "bitte", "danke"}
    return "de" if len(_toks(text) & de) >= 2 else "en"


class IntentEngine:
    def build(self, ticket: dict) -> ResponseSpec:
        text = ticket.get("text", "")
        cat, conf = _classify(text)
        hits, retr = _retrieve(text)
        # on-topic guard: a claim may only stand if it shares vocabulary with the category.
        # stops a weak/wrong retrieval from feeding the persona an off-topic fact (the T008 failure).
        cat_tokens = _toks(" ".join(CUES.get(cat, [])) + " " + cat)
        hits = [h for h in hits if _toks(h["title"] + " " + " ".join(h.get("tags", []))) & cat_tokens]
        pol = POLICY.get(cat, POLICY["other"])
        score = round(0.6 * conf + 0.4 * retr, 2)

        if pol["sensitive"]:
            action, reason = "escalate", f"{cat} is a human-only category"
        elif not hits:
            action, reason = "escalate", "no supporting knowledge found"
        elif score >= HIGH and pol["auto_ok"]:
            action, reason = "auto", None
        elif score >= MED:
            action, reason = "assist", None
        else:
            action, reason = "escalate", "confidence below threshold"

        claims = [Claim(source=h["id"], text=h["body"]) for h in hits] if action != "escalate" else []
        cons = Constraints(
            language=_language(text),
            max_words=120,
            must_not=["prices, dates, or promises not present in the claims"],
            next_step="invite a reply if it doesn't resolve",
            disclosure_required=os.getenv("DISCLOSE", "false").lower() == "true",
        )
        return ResponseSpec(ticket_id=ticket.get("id", "?"), action=action, category=cat,
                            confidence=score, claims=claims, constraints=cons, escalation_reason=reason)
