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


def exact_times(text: str) -> str:
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
