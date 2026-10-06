"""
contract.py — the boundary between the two engines.

The Intent Engine PRODUCES a ResponseSpec. The Persona Engine CONSUMES it and may only
reword what's inside it. This dataclass is the entire interface; neither engine imports the
other. The safety property falls out of the type: a fact the Intent Engine didn't put in
`claims` cannot legally appear in the reply, because `claims` is all the Persona Engine is given.
"""
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Claim:
    """A vetted statement the reply MAY use. Sourced, so every sentence is traceable."""
    source: str      # KB id, fact id, or "policy"
    text: str


@dataclass
class Constraints:
    language: str = "en"                 # persona renders in this language
    max_words: int = 120
    must_not: list = field(default_factory=list)   # e.g. ["prices", "promises", "dates not in claims"]
    next_step: Optional[str] = None      # the CTA the reply should end on
    disclosure_required: bool = False    # prepend an "automated" label (phase-2 real-estate: often True)


@dataclass
class ResponseSpec:
    """What to say — never how to say it. The Intent Engine owns every field here."""
    ticket_id: str
    action: str                          # "auto" | "assist" | "escalate"
    category: str
    confidence: float
    claims: list                         # list[Claim] — the ONLY facts the persona may assert
    constraints: Constraints
    escalation_reason: Optional[str] = None

    def to_dict(self):
        d = asdict(self)
        return d
