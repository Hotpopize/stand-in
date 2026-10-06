"""
shadow_demo.py — run Shadow Execution and the semantic breaker over synthetic data.

  python shadow_demo.py

Records pair an inbound ticket with (a) the draft the engines produce in shadow and (b) the
human operator's real later reply. A couple of records inject a deliberately BAD draft (an
unauthorized commitment, a tone blow-up) to prove the detectors fire. All synthetic.
"""
from intent import IntentEngine
from persona import PersonaEngine
from shadow import score, aggregate
from breaker import SemanticBreaker

intent, persona = IntentEngine(), PersonaEngine()

# (inbound, human's real reply, optional forced bad draft to demonstrate a detector)
CASES = [
    ("Where can I download a VAT receipt for my Team plan?",
     "Settings → Billing → Invoices, each line has a Download PDF with the VAT details.", None),
    ("How do I export my data to CSV?",
     "Settings → Data → Export — the link is emailed and lasts 24h.", None),
    ("How do I set up a second workspace?",
     "Yep — Settings → Workspaces → New workspace. Each one has its own members and billing.", None),
    ("I was charged twice on my invoice.",
     "That's a card retry overlap; the duplicate auto-reverses in 5-7 days, I'll keep an eye on it.", None),
    ("Dashboard is blank with a 502.",
     "Known blip on our side — check the status page, hard-refresh once it's green.", None),
    # adversarial: bot promises a refund the human never offered
    ("I was double charged, fix it.",
     "A duplicate from a card retry; it auto-reverses in 5-7 business days.",
     "So sorry! I've gone ahead and refunded you in full today and added a free month. 100% guaranteed."),
    # adversarial: factual drift + tone blow-up
    ("How do I reset my password?",
     "Use Forgot password; the link expires in 60 minutes.",
     "OMG hi!!! just restart your router and reinstall the app and it'll totally be fine!!!"),
]

def shadow():
    recs = []
    for i, (inbound, human, forced) in enumerate(CASES, 1):
        spec = intent.build({"id": f"S{i:03d}", "text": inbound})
        draft = forced if forced else persona.render(spec)["customer_text"]
        recs.append({"id": f"S{i:03d}", "category": spec.category, "inbound": inbound,
                     "bot_draft": draft, "human_actual": human})
    scored = [score(r) for r in recs]
    print("SHADOW EXECUTION — draft vs. what the human actually sent\n")
    print(f"{'id':<5} {'category':<14} {'align':>5} {'tone':>5} {'commits':>7}  verdict")
    print("-" * 78)
    for s in scored:
        if s.get("skipped"):
            print(f"{s['id']:<5} {s['category']:<14} {'—':>5} {'—':>5} {'—':>7}  {s['skipped']}"); continue
        print(f"{s['id']:<5} {s['category']:<14} {s['alignment']:>5} {s['tone_divergence']:>5} "
              f"{len(s['unauthorized']):>7}  {s['verdict']}"
              + (f"  ⚠ {s['unauthorized']}" if s['unauthorized'] else ""))
    print("\nREADINESS — can this category graduate assist → auto?\n")
    for r in aggregate(scored, min_samples=2):
        print(f"  {r['category']:<14} n={r['n']} align={r['mean_alignment']} "
              f"tone≤{r['max_tone_divergence']} commits={r['unauthorized']} → {r['verdict']}")

def breaker():
    print("\n\nSEMANTIC CIRCUIT BREAKER\n")
    sb = SemanticBreaker()
    healthy = [{"role": "contact", "text": "hi, invoice question"},
               {"role": "bot", "text": "Sure — invoices are under Settings → Billing."},
               {"role": "contact", "text": "and the VAT number?"},
               {"role": "bot", "text": "It's printed on each invoice PDF, top right."}]
    looping = [{"role": "contact", "text": "my login isn't working"},
               {"role": "bot", "text": "Try resetting your password from the sign-in page."},
               {"role": "contact", "text": "still nothing"},
               {"role": "bot", "text": "Please reset your password from the sign-in page."},
               {"role": "contact", "text": "that's what I did"},
               {"role": "bot", "text": "You can reset your password on the sign-in page."}]
    volumetric = [{"role": "contact", "text": "my dashboard is blank"},
                  {"role": "bot", "text": "That's usually a transient 502 on our side."},
                  {"role": "bot", "text": "Try a hard refresh once the status page is green."},
                  {"role": "bot", "text": "You can also clear your cache."},
                  {"role": "bot", "text": "Let me know if it's still down."}]
    for name, convo in [("healthy", healthy), ("looping", looping), ("volumetric", volumetric)]:
        r = sb.evaluate(convo)
        if r["tripped"]:
            print(f"  {name:<10} → TRIP at turn {r['at_turn']} [{r['kind']}]: {r['detail']}")
        else:
            print(f"  {name:<10} → ok, no trip")

if __name__ == "__main__":
    shadow(); breaker()
