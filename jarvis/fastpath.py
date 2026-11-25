"""The fast path: simple, frequent commands handled by plain code instead of Claude.
Instant (no model call), free (no usage) and reliable (the model can't forget to do it).

Only short utterances are matched, so "how do I make my fan quiet?" still goes to Claude.
"""

from __future__ import annotations

import re

MAX_WORDS = 12

_PATTERNS = [
    ("claude_always", r"^(always|every time)?\s*(tell|let) me (know )?(every time|whenever|each time) claude( code)? (is done|finishes|is finished)|^always (tell|let) me (know )?when claude( code)? (is done|finishes|is finished)"),
    ("claude_once", r"^(please )?(tell|let) me (know )?when claude( code)?('s| is)? (done|finished|finishes)|^(ping|notify) me when claude( code)? (is done|finishes)"),
    ("claude_off", r"^(stop|don'?t) (telling|tell|notifying|notify) me (about|when) claude"),
    ("update", r"^(please )?(update yourself|update jarvis|check for updates|install (the )?updates|get the latest( version)?)$"),
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


def handle(text: str, rt) -> str | None:
    """Return a reply if this is a fast-path command, otherwise None (send it to Claude)."""
    cleaned = re.sub(r"^(hey |ok |okay )?jarvis[,.!]?\s*", "", text.strip(), flags=re.I).strip(" .!?")
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


def _missed(rt) -> str:
    held = rt.announcer.take_held()
    parts = []
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
    from . import admin

    if not admin.update_available():
        return "I'm already on the latest version."
    result = admin.update()
    return result.split("\n")[0] if result.startswith("Updated") else result


def _claude_once(rt) -> str:
    rt.claude_watch = "once"
    return "Will do. I'll tell you the moment Claude Code finishes."


def _claude_always(rt) -> str:
    rt.claude_watch = "always"
    return "Understood. I'll tell you every time Claude Code finishes, until you say stop."


def _claude_off(rt) -> str:
    rt.claude_watch = "off"
    return "Righto, no more Claude Code updates."


_ACTIONS = {"claude_once": _claude_once, "claude_always": _claude_always, "claude_off": _claude_off,
            "update": _update, "morning": _morning, "hold": _hold, "quiet": _quiet, "normal": _normal, "missed": _missed, "jobs": _jobs}
