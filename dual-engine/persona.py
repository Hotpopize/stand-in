"""
persona.py — Engine 2: decides HOW it sounds. Consumes a ResponseSpec, emits text.

Responsibilities (and nothing else):
  - render the spec's claims in a voice (tone card), language, and length
  - prepend a disclosure label when the spec requires it
  - on an escalate spec, produce NO customer text — only an internal note

It MUST NOT: change the action, add a fact not in `claims`, invent prices/promises/dates, or
re-decide the route. It never sees the KB or the policy — only the spec. Swapping the voice
(support brand -> an individual agent's voice in phase 2) is a change to THIS file alone.
"""
import os
from pathlib import Path
from contract import ResponseSpec

VOICE = Path("brand.md").read_text() if Path("brand.md").exists() else "Warm, brief, plain."
LLM = dict(url=os.getenv("LLM_BASE_URL", ""), model=os.getenv("LLM_MODEL", "llama3.1"),
           key=os.getenv("LLM_API_KEY", "ollama"))
GREET = {"en": "Thanks for reaching out!", "de": "Danke für deine Nachricht!"}
CLOSE = {"en": "If that doesn't sort it, just reply here.", "de": "Falls das nicht hilft, antworte einfach hier."}
LABEL = {"en": "[Automated reply] ", "de": "[Automatische Antwort] "}


class PersonaEngine:
    def __init__(self, voice: str = VOICE):
        self.voice = voice

    def render(self, spec: ResponseSpec) -> dict:
        if spec.action == "escalate":
            return {"customer_text": None,
                    "internal_note": f"Escalate to human — {spec.escalation_reason}. "
                                     f"Category {spec.category}, score {spec.confidence}.",
                    "auto_ready": False}

        lang = spec.constraints.language if spec.constraints.language in GREET else "en"
        text = self._llm(spec, lang) or self._template(spec, lang)
        if spec.constraints.disclosure_required:
            text = LABEL[lang] + text
        return {"customer_text": text, "internal_note": None, "auto_ready": spec.action == "auto"}

    # --- fact-safe rendering: claims are the only material allowed in --------
    def _template(self, spec, lang):
        body = " ".join(c.text for c in spec.claims)      # claims only — nothing else can enter
        return f"{GREET[lang]} {body} {CLOSE[lang]}"

    def _llm(self, spec, lang):
        if not LLM["url"]:
            return None
        try:
            import httpx
            claims = "\n".join(f"- ({c.source}) {c.text}" for c in spec.claims)
            system = (self.voice + f"\n\nRender a reply in {lang}, at most {spec.constraints.max_words} words. "
                      "Use ONLY the facts below — do not add any fact, price, date, or promise that isn't here. "
                      f"Avoid: {', '.join(spec.constraints.must_not)}.\n\nFACTS:\n" + claims)
            with httpx.Client(timeout=30) as c:
                r = c.post(f"{LLM['url']}/chat/completions",
                           headers={"Authorization": f"Bearer {LLM['key']}"},
                           json={"model": LLM["model"], "temperature": 0.3, "max_tokens": 220,
                                 "messages": [{"role": "system", "content": system},
                                              {"role": "user", "content": "Write the reply."}]})
                r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            return None
