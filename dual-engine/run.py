"""
run.py — glue the two engines and show the boundary.

  python run.py            run the built-in sample tickets through both engines
  python run.py gen 12     write 12 synthetic tickets to data/tickets.jsonl, then run

The audit records BOTH sides of the contract per ticket: the ResponseSpec the Intent Engine
produced, and what the Persona Engine rendered from it. That's how you verify the boundary held.
"""
import json, os, sys, random
from datetime import datetime, timezone
from pathlib import Path

from contract import ResponseSpec
from intent import IntentEngine
from persona import PersonaEngine

AUDIT = Path("data/audit.jsonl"); AUDIT.parent.mkdir(parents=True, exist_ok=True)
intent, persona = IntentEngine(), PersonaEngine()

TEMPLATES = [
    "Where can I download a receipt with VAT for my Team subscription?",
    "I'm locked out and the password reset email never arrives.",
    "How do I set up a second workspace for my team?",
    "How do I export my data to CSV?",
    "The dashboard is blank with a 502 error since this morning.",
    "This didn't work for us — I want to cancel and get a refund for the year.",
    "Honestly the worst support ever. Third time asking. Unacceptable.",
    "What's your enterprise pricing, and can we book a demo?",
    "Wie kann ich mein Passwort zurücksetzen?",            # German -> persona renders in de
    "I was charged twice on my last invoice, can you check?",
    "hey",
    "is the thing fixed yet??",
]

def gen(n):
    rows = [{"id": f"T{i:03d}", "text": t} for i, t in enumerate(random.sample(TEMPLATES, min(n, len(TEMPLATES))), 1)]
    Path("data/tickets.jsonl").write_text("\n".join(json.dumps(r) for r in rows)); return rows

def run(rows):
    print(f"{'id':<5} {'category':<15} {'action':<9} {'lang':<4} reply / note")
    print("-" * 92)
    for t in rows:
        spec = intent.build(t)                      # ENGINE 1: what to say
        out  = persona.render(spec)                 # ENGINE 2: how it sounds
        shown = out["customer_text"] or f"(no customer reply) {out['internal_note']}"
        print(f"{spec.ticket_id:<5} {spec.category:<15} {spec.action:<9} {spec.constraints.language:<4} {shown[:60]}")
        AUDIT.open("a").write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "spec": spec.to_dict(), "rendered": out}, ensure_ascii=False) + "\n")
    print("-" * 92)
    print("spec + rendered for every ticket in", AUDIT)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "gen":
        run(gen(int(sys.argv[2]) if len(sys.argv) > 2 else 12))
    else:
        run([{"id": f"T{i:03d}", "text": t} for i, t in enumerate(TEMPLATES, 1)])
