"""Long text, spoken: say a short version, send the full text to the phone.

Listening is not reading: a list of five things is easy to scan and hard to hold in your head. So
anything long (a Claude Code session's reply, a long answer) is spoken as the answer plus at most a
few points, and the complete text goes to Telegram, never cut off.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

SPOKEN_LIMIT = 420    # characters: about 25 seconds of speech
FULL_ON_PHONE = "The full version is on your phone."

_LIST_LINE = re.compile(r"^\s*(?:[-*•]|\d+[.)]|[a-z][.)])\s+", re.M)


def list_items(text: str) -> int:
    return len(_LIST_LINE.findall(text or ""))


def is_long(text: str) -> bool:
    return len(text or "") > SPOKEN_LIMIT or list_items(text) > 3


def plain(text: str) -> str:
    """Markdown to plain speakable text."""
    text = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_#>|]+", "", text)
    text = _LIST_LINE.sub("", text)
    return " ".join(text.split())


def _first_sentences(text: str, limit: int = 260) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", plain(text))
    out = ""
    for s in sentences:
        if out and len(out) + len(s) > limit:
            break
        out = (out + " " + s).strip()
    return out[:limit].rsplit(" ", 1)[0] + "…" if len(out) > limit else out


SUMMARY_PROMPT = """Rewrite this for Jarvis to SAY ALOUD to the user, who is listening, not reading.
Rules: lead with the answer or outcome in one sentence. Then at most three key points, grouping
related items ("three fixes are live; two need your test"). No lists, markdown, URLs or code.
Under 70 words. Plain spoken English, British butler tone, call the user "sir" at most once.
Do not mention that you are summarising. Reply with only the words to speak.

{context}Text:
{text}"""


def summary(text: str, context: str = "") -> str:
    """Short spoken version (cheap Haiku call; falls back to the first sentences)."""
    claude = shutil.which("claude")
    if claude:
        try:
            out = subprocess.run(
                [claude, "-p", SUMMARY_PROMPT.format(text=text[:6000], context=context + "\n" if context else ""),
                 "--output-format", "json", "--model", "haiku", "--tools", "",
                 "--strict-mcp-config", "--no-session-persistence"],
                capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
            result = json.loads(out.stdout.strip().splitlines()[-1]).get("result", "").strip()
            if 20 < len(result) < 900:
                return plain(result)
        except (ValueError, IndexError, OSError, subprocess.SubprocessError):
            pass
    return _first_sentences(text)


def for_voice(text: str, context: str = "", smart: bool = True) -> tuple[str, str | None]:
    """(what to say, full text to send to the phone or None). smart=False skips the model call
    (instant; for answers someone is waiting on)."""
    if not is_long(text):
        return plain(text), None
    short = summary(text, context) if smart else _first_sentences(text)
    return f"{short} {FULL_ON_PHONE}", text
