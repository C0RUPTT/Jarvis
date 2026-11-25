"""A timeline of recent Siri conversations, to see exactly where one went wrong (/siri in Telegram).

Each Shortcut request and Jarvis's reply is recorded with times. If the Shortcut goes quiet when it
should have called back (after "One moment" it must call the waiting step), that's recorded too:
it means Siri ended the Shortcut, or the Shortcut's waiting part isn't set up."""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime

_events: deque = deque(maxlen=60)
_lock = threading.Lock()
_expect: dict = {"until": 0.0, "what": ""}   # a call the Shortcut should make soon


def record(kind: str, detail: str, seconds: float | None = None, expect: str = "", within: float = 0) -> None:
    with _lock:
        _events.append((time.time(), kind, detail[:160], seconds))
        _expect.update(until=time.time() + within if expect else 0.0, what=expect)
    print(f"[siri] {kind}: {detail[:120]}" + (f" ({seconds:.1f}s)" if seconds is not None else ""))


def _watch() -> None:
    while True:
        time.sleep(1)
        with _lock:
            due = _expect["until"] and time.time() > _expect["until"]
            what = _expect["what"]
            if due:
                _expect.update(until=0.0, what="")
        if due:
            record("STOPPED", what)


threading.Thread(target=_watch, daemon=True, name="jarvis-siri-trace").start()


def report() -> str:
    with _lock:
        events = list(_events)[-25:]
    if not events:
        return "No Siri conversations since Jarvis last started."
    lines, last = ["Recent Siri timeline (newest last):"], None
    for t, kind, detail, seconds in events:
        if last and t - last > 300:
            lines.append("  ---")
        took = f" [{seconds:.1f}s]" if seconds is not None else ""
        lines.append(f"  {datetime.fromtimestamp(t):%H:%M:%S} {kind}{took}: {detail}")
        last = t
    return "\n".join(lines)
