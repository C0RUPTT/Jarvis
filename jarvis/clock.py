"""Exact clock times: the user wants "4:45", never "quarter to five". The model is told so, but
tool output (e.g. a connected app's schedule) sometimes slips through, so replies are fixed here."""

from __future__ import annotations

import re

_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}
_HOUR = r"(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|1[0-2]|[1-9])"
_PATTERN = re.compile(
    rf"\b(?:a\s+)?(quarter|half)\s+(to|till|til|of|past|after)\s+{_HOUR}(?:\s+o'?clock)?\b", re.I)


def _hour(token: str) -> int:
    return int(token) if token.isdigit() else _WORDS[token.lower()]


# "three minutes to two", "eight minutes past two", "twenty past nine"
_NUM = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                    "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
_NUM.update({"twenty-five": 25, "twenty five": 25})
_MINUTES = re.compile(
    r"\b(twenty[- ]five|" + "|".join(sorted(_NUM, key=len, reverse=True)) + r"|\d{1,2})( minutes?)? "
    rf"(to|till|til|past|after) {_HOUR}\b"
    r"(?:\s+o'?clock)?", re.I)


def _minutes(m: re.Match) -> str:
    word = m.group(1).lower()
    n = int(word) if word.isdigit() else _NUM.get(word)
    if n is None or not 0 < n < 60 or (not m.group(2) and n not in (5, 10, 20, 25)):
        return m.group(0)
    hour = _hour(m.group(4))
    if m.group(3).lower() in ("past", "after"):
        return f"{hour}:{n:02d}"
    return f"{12 if hour == 1 else hour - 1}:{60 - n:02d}"


def exact_times(text: str) -> str:
    text = _MINUTES.sub(_minutes, text)
    def fix(m: re.Match) -> str:
        part, direction, hour = m.group(1).lower(), m.group(2).lower(), _hour(m.group(3))
        if part == "half":
            if direction not in ("past", "after"):
                return m.group(0)
            return f"{hour}:30"
        if direction in ("past", "after"):
            return f"{hour}:15"
        return f"{12 if hour == 1 else hour - 1}:45"
    return _PATTERN.sub(fix, text)
