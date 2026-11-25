"""The fast path: simple, frequent commands handled by plain code instead of Claude.
Instant (no model call), free (no usage) and reliable (the model can't forget to do it).

Only short utterances are matched, so "how do I make my fan quiet?" still goes to Claude.
"""

from __future__ import annotations

import re

MAX_WORDS = 12

_PATTERNS = [
    ("read_unread", r"^(can you |please )?(read|tell) me (my |the )?(notifications|messages|alerts|texts)|"
                    r"^(read|play) (my |the )?(notifications|messages|alerts)|^what did you (send|tell) me|"
                    r"^(any|do i have any) (new )?(messages|notifications|alerts)"),
    ("claude_always", r"^(always|every time)?\s*(tell|let) me (know )?(every time|whenever|each time) claude( code)? (is done|finishes|is finished)|^always (tell|let) me (know )?when claude( code)? (is done|finishes|is finished)"),
    ("claude_once", r"^(please )?(tell|let) me (know )?when claude( code)?('s| is)? (done|finished|finishes)|^(ping|notify) me when claude( code)? (is done|finishes)"),
    ("claude_off", r"^(stop|don'?t) (telling|tell|notifying|notify) me (about|when) claude"),
    ("claude_every", r"^(tell me about|announce) every (reply|response|turn|time)"),
    ("claude_long", r"^only (tell me about |announce )?(long|big|longer) (tasks|jobs|ones|work)"),
    ("update", r"^(please |go |can you |could you )?(update yourself|update jarvis|update|check for updates|install (the )?updates?|get the latest( version)?|upgrade yourself)( now| please)?$"),
    ("morning", r"^(hey |hi |ok(ay)? )?(good )?morning( jarvis)?$|^i'?m (up|awake)( now)?$|^(start|begin) my day$"),
    ("hold", r"^(please )?(hold (everything|it all|all|my (messages|notifications|stuff))|"
             r"don'?t (bother|disturb|interrupt) me|do not disturb|hold (on to )?everything)"),
    ("quiet", r"^(please )?(tell me quietly|quiet mode|go quiet|(be )?silent( mode)?|"
              r"i'?m in a meeting|notify me silently|silent notifications)"),
    ("normal", r"^(ok(ay)?,? )?(back to normal|normal mode|you can (talk|notify me|interrupt me) again|"
               r"i'?m (back|free)( now)?|unmute)"),
    ("missed", r"^(so,? |ok(ay)?,? )?(what did i miss|catch me up|anything new|what'?s new|"
               r"any updates|what happened while i was (away|gone|out))"),
    ("jobs", r"^(how'?s|how is|how are|what'?s the status of|status of) (the |my )?(job|jobs|build|app|project)s?"),
]
_COMPILED = [(name, re.compile(p, re.I)) for name, p in _PATTERNS]


# "Switch to the app": hand a Siri conversation over to the web app (same conversation, no time limits).
# "Switch to the app": hand a Siri conversation over to the web app (same conversation, no time limits).
# Dictation words it many ways ("switch to the Jarvis web app", "open Jarvis app", "go to the app"),
# so: a short request with a switch/open-type verb whose only target is "the app" / "Jarvis app" /
# "web app" / "your app" (never another app's name, so "open the YouTube app" still opens YouTube).
_HANDOFF_VERB = re.compile(r"\b(switch|swap|change|move|go|open|launch|use|continue|carry on|talk|keep talking|"
                           r"take (this|it)|hand (it|this|me)|bring up|pull up|pick (this|it) up|finish (this|it))\b", re.I)
_HANDOFF_TARGET = re.compile(
    r"\b(?:to |in |on |over |into |up |off |the |your |my |jarvis'?s? |jarvis |web |own )*app(?:s| mode)?\b", re.I)
_HANDOFF_ONLY = re.compile(
    r"^(?:ok(?:ay)?|hey|so|um|uh|please|let'?s|can we|could we|can you|could you|i want to|i'?d like to|"
    r"jarvis|switch|swap|change|move|go|open|launch|use|continue|carry|on|talk|keep|talking|take|this|it|hand|"
    r"me|off|over|bring|pull|up|pick|finish|to|in|into|the|your|my|jarvis'?s?|web|own|app|apps|mode|now|"
    r"instead|please|then|yourself)(?:[\s,.!?']+|$)", re.I)


def is_handoff(text: str) -> bool:
    t = text.strip().strip(".!?").lower()
    if not t or len(t.split()) > 10:
        return False
    if re.fullmatch(r"(?:open |switch to |go to )?(?:yourself|jarvis)", t) or re.fullmatch(r"(?:web |jarvis )?app mode", t):
        return True
    if re.fullmatch(r"hand (?:it|this|me) (?:off|over)(?: to the app)?", t):
        return True
    if not (_HANDOFF_VERB.search(t) and _HANDOFF_TARGET.search(t)):
        return False
    rest = t
    while rest:   # every word must be one of the handoff words: any other word names something else
        m = _HANDOFF_ONLY.match(rest)
        if not m:
            return False
        rest = rest[m.end():]
    return True


class _Handoff:   # keeps HANDOFF.match(text) working for older callers
    @staticmethod
    def match(text: str):
        return is_handoff(text) or None


HANDOFF = _Handoff()


def app_link(rt) -> str:
    from .admin import public_host

    host = public_host() or f"localhost:{rt.config.port}"
    from urllib.parse import quote

    # The token rides along so Safari works even if only the home-screen app was set up.
    return f"https://{host}/?talk=1&token={quote(rt.config.token or '')}"


RELAY = re.compile(
    r"^(?:please |can you |could you )?(?:pick up on|pick up|continue|go back to|tell|ask|message|send to)\s+"
    r"(?:on\s+)?(?:my\s+|the\s+)?(?P<project>[\w .'-]{2,40}?)\s+(?:code\s+|claude\s+code\s+)?session"
    r"(?:\s*[:,-]\s*|\s+(?:to|and|that)\s+|\s+)(?P<message>.{2,})$", re.I)


def _relay(text: str, rt) -> str | None:
    """'Pick up on my Jarvis session: <message>' -> send straight into that Claude Code session
    (instant: no Claude call; the session's reply is read out when it arrives)."""
    m = RELAY.match(text)
    if not m or rt is None or getattr(rt, "ctx", None) is None:
        return None
    from . import claude_sessions

    match = claude_sessions.find(rt.config.data_dir, m.group("project"))
    if not match:   # name unclear (dictation slip): use the most recently active session, and say its name
        import time as _time

        recent = [s for s in claude_sessions.load(rt.config.data_dir) if _time.time() - s["last_seen"] < 6 * 3600]
        match = recent[0] if recent else None
    if not match:
        return None   # unknown session: let Claude handle it (it can ask for the link)
    error = claude_sessions.send(match["id"], m.group("message").strip())
    if error:
        return f"I couldn't reach your {match['project']} session: {error}"
    rt.await_reply(match["id"])
    return f"Sent to your {match['project']} session. I'll read you its reply when it comes."


def handle(text: str, rt) -> str | None:
    """Return a reply if this is a fast-path command, otherwise None (send it to Claude)."""
    cleaned = re.sub(r"^(hey |ok |okay )?jarvis[,.!]?\s*", "", text.strip(), flags=re.I).strip(" .!?")
    if HANDOFF.match(text.strip()) and rt is not None:
        rt.announcer.open_on_phone(app_link(rt), "Jarvis")
        return "Over to the app, sir. Tap the screen once and carry on; I remember where we were."
    relayed = _relay(cleaned, rt)
    if relayed is not None:
        return relayed
    if not cleaned or len(cleaned.split()) > MAX_WORDS:
        return None
    for name, pattern in _COMPILED:
        if pattern.search(cleaned):
            return _ACTIONS[name](rt)
    return None


def _hold(rt) -> str:
    rt.announcer.set_mode("hold")
    return f"Holding everything, {rt.config.user_name}. Ask me what you missed when you're ready."


def _quiet(rt) -> str:
    rt.announcer.set_mode("quiet")
    return "Quiet mode. I'll send things silently."


def _normal(rt) -> str:
    rt.announcer.set_mode("normal")
    held = rt.announcer.take_held()
    if not held:
        return "Back to normal. Nothing came in while you were away."
    return f"Back to normal. While you were away: " + " ".join(held)


def _read_unread(rt) -> str:
    items = rt.announcer.take_unread()
    if not items:
        return "Nothing new from me since you last checked, sir."
    head = "One since you last checked. " if len(items) == 1 else f"{len(items)} since you last checked. "
    return head + " ".join(items)


def _missed(rt) -> str:
    held = rt.announcer.take_held()
    parts = []
    unread = rt.announcer.take_unread()
    if unread:
        parts.append(f"Sent to your phone: " + " ".join(unread))
    if held:
        parts.append(f"{len(held)} thing{'s' if len(held) != 1 else ''} while you were away: " + " ".join(held))
    running = _running_jobs(rt)
    if running:
        parts.append(running)
    if not parts:
        parts.append("Nothing new.")
    if rt.announcer.night:
        parts.append("Night mode is on until you wake up.")
    elif rt.announcer.mode != "normal":
        parts.append(f"I'm still in {rt.announcer.mode} mode; say 'back to normal' to change that.")
    return " ".join(parts)


def _jobs(rt) -> str:
    if rt.jobs is None:
        return "There are no background jobs in this mode."
    active = [j for j in rt.jobs.jobs.values() if j.status in {"running", "queued"}]
    if not active:
        last = max(rt.jobs.jobs.values(), key=lambda j: j.id, default=None)
        if last is None:
            return "No jobs yet."
        return f"Nothing running. The last job, number {last.id}, {last.status}: {last.result[:300]}"
    return _running_jobs(rt)


def _running_jobs(rt) -> str:
    if rt.jobs is None:
        return ""
    import time

    lines = []
    for j in sorted(rt.jobs.jobs.values(), key=lambda j: j.id):
        if j.status == "running":
            mins = int((time.time() - (j.started or time.time())) // 60)
            lines.append(f"Job {j.id} is still working, {mins} minute{'s' if mins != 1 else ''} in.")
        elif j.status == "queued":
            lines.append(f"Job {j.id} is waiting its turn.")
    return " ".join(lines)


def _morning(rt) -> str:
    return rt.morning()


def _update(rt) -> str:
    """Answer straight away (Siri only waits ~10s); update in the background; the restarted Jarvis
    reports what's new (see runtime.build -> report_update)."""
    import threading

    from . import admin

    if not admin.update_available():
        return "I'm already on the latest version, sir."

    def run():
        result = admin.update()
        if result.startswith("Updated"):
            admin.UPDATE_NOTE.parent.mkdir(parents=True, exist_ok=True)
            admin.UPDATE_NOTE.write_text(result.split("What's new:", 1)[-1].strip())
        else:
            rt.announcer.announce(result, reply=True)   # e.g. rolled back after failed checks

    threading.Thread(target=run, daemon=True).start()
    return "Updating now, sir. I'll be back in about a minute and I'll message you what's new."


def _claude_once(rt) -> str:
    rt.claude_watch = "once"   # temporary: back to the remembered setting afterwards
    return "Will do. I'll tell you the moment Claude Code finishes."


def _claude_always(rt) -> str:
    rt.set_claude_watch("always")
    return "Understood. I'll tell you every time Claude Code finishes, until you say stop."


def _claude_off(rt) -> str:
    rt.set_claude_watch("off")
    return "Righto, no more Claude Code updates."


def _claude_every(rt) -> str:
    import os

    os.environ["JARVIS_CLAUDE_MIN_SECONDS"] = "0"
    rt.set_claude_watch("always")
    return "Every Claude Code reply, then. Do say if it gets chatty."


def _claude_long(rt) -> str:
    import os

    os.environ["JARVIS_CLAUDE_MIN_SECONDS"] = "120"
    rt.set_claude_watch("always")
    return "Only work that takes two minutes or more, sir."


_ACTIONS = {"claude_every": _claude_every, "claude_long": _claude_long, "read_unread": _read_unread, "claude_once": _claude_once, "claude_always": _claude_always, "claude_off": _claude_off,
            "update": _update, "morning": _morning, "hold": _hold, "quiet": _quiet, "normal": _normal, "missed": _missed, "jobs": _jobs}
