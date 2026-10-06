# stand-in

Answers for you when you're away — **as a clearly labelled bot**, not as you.

    pip install -r requirements.txt
    python testenv.py up          # throwaway Synapse + users me/alex/assistant + a room, writes .env
    python standin.py             # second shell: logs in as the SEPARATE bot account, sets its "(bot)" name
    python testenv.py scenario    # alex writes -> labelled bot replies; you reply -> it goes quiet
    python testenv.py down

Windows: `.\run.ps1 -Setup` once (venv + deps), then `.\run.ps1`.

## The honesty model
The bot is its **own account** with a display name that says `(bot)`. A contact sees a distinct,
named sender — never the owner's identity. Verified: in the test scenario the contact sees the reply
from `@assistant:lab` as "Me — assistant (bot)", while the owner's own messages come from `@me:lab`.
Two accounts, no way to mistake one for the other.

On Threema the same honesty is built in: a Gateway ID shows to contacts with a leading `*`, platform-enforced.
That's the route to use there — the label isn't optional, so it can't be quietly dropped.

A display-name suffix on the owner's *own* account is **not** this: it relabels the person, is easy to miss,
and the thread still reads as them. A separate identity is what makes "(bot)" real.

## Rules (all of them)
1. Contact writes.
2. Owner wrote anywhere in the last `AWAY_AFTER_MIN` -> present -> nothing.
3. Owner wrote in this room in the last `ROOM_QUIET_MIN` -> handling it -> nothing.
4. Otherwise answer (`persona.md`), from the labelled account.
5. The owner's own messages are the only control. No commands, no control room, no pings.

`data/audit.jsonl` is the machine log; the room itself is the human-readable record.

## Two modes
- **LABELLED** (`BOT_USER` != `OWNER_USER`) — the default and the only one for real contacts.
- **UNLABELLED** (`BOT_USER` == `OWNER_USER`) — replies from the owner's identity. For the closed-loop
  detection experiment where you're on both ends only; the script refuses it unless `I_UNDERSTAND_UNLABELLED=yes`.

## Other channels
`standin.py` -> `class Channel`. Implement `run()` (call `person_said` / `contact_said`) and `send()`.
The stand-in logic doesn't change. A Threema Gateway transport (the `*`-prefixed ID) drops in here.

## Verified
Synapse 1.162, 2026-10-03: labelled separate-account reply, display name visible to the contact,
owner's messages distinct, bot quiet once the owner is present, session persisted across restart.
