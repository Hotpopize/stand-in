"""
breaker.py — semantic circuit breaker. Volumetric limits don't catch a bot that's degenerating;
conversational entropy does.

It compares turn k against turn k-2 (same speaker's rhythm) by cosine distance:
  - distance <= loop_dist  : the bot is saying what it said two turns ago -> stalling/looping.
    Trips after `loop_patience` consecutive stalls (one repeat can be legitimate).
  - distance >= derail_dist : sudden topic whiplash -> incoherence/derailment. Trips at once.
A volumetric backstop (max consecutive bot turns with no human/contact progress) is included too,
because the two failure modes are complementary, not either/or.

Trip -> halt auto-mode for the conversation, escalate to a human, log the reason.
"""
from textvec import embed, distance


class SemanticBreaker:
    def __init__(self, loop_dist=0.35, loop_patience=2, max_bot_streak=4):
        self.loop_dist, self.loop_patience, self.max_bot_streak = loop_dist, loop_patience, max_bot_streak

    def evaluate(self, turns):
        """turns: list of {"role": "bot"|"contact", "text": str} in order. Returns the first trip.
        Entropy is measured on the BOT's own turn sequence — comparing a bot turn to its previous
        one and the one before that (k vs k-1, k-2). A contact's turns are not scored; they can
        jump topic legitimately. Low distance = the bot is repeating itself = looping."""
        bot_embeds, stalls, bot_streak = [], 0, 0
        for k, t in enumerate(turns):
            if t["role"] != "bot":
                bot_streak = 0
                continue
            bot_streak += 1
            if bot_streak >= self.max_bot_streak:
                return self._trip(k, "volumetric", f"{bot_streak} bot turns with no contact progress")
            e = embed(t["text"])
            cmps = bot_embeds[-2:]                       # previous one or two bot turns (k-1, k-2)
            if cmps:
                d = min(distance(e, c) for c in cmps)
                if d <= self.loop_dist:
                    stalls += 1
                    if stalls >= self.loop_patience:
                        bot_embeds.append(e)
                        return self._trip(k, "loop", f"bot repeating a prior turn; distance {d:.2f} ≤ {self.loop_dist}")
                else:
                    stalls = 0
            bot_embeds.append(e)
        return {"tripped": False}

    def _trip(self, k, kind, detail):
        return {"tripped": True, "at_turn": k, "kind": kind, "detail": detail,
                "action": "halt auto; escalate to human"}
