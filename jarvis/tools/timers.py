"""Short countdown timers that Jarvis announces when they go off (reminders live in reminders.py)."""

from __future__ import annotations

import itertools
import threading
from datetime import datetime, timedelta

from . import tool

_ids = itertools.count(1)
_active: dict[int, tuple[threading.Timer, str, datetime]] = {}


def _schedule(ctx, when: datetime, message: str) -> int:
    timer_id = next(_ids)

    def fire():
        _active.pop(timer_id, None)
        ctx.announce(message)

    delay = max(0.0, (when - datetime.now()).total_seconds())
    t = threading.Timer(delay, fire)
    t.daemon = True
    t.start()
    _active[timer_id] = (t, message, when)
    return timer_id


@tool(
    "set_timer",
    "Start a countdown timer. When it ends Jarvis says the message out loud.",
    {
        "seconds": {"type": "integer", "description": "Total duration in seconds"},
        "message": {"type": "string", "description": "What to say when it ends, e.g. 'Your tea is ready, sir.'"},
    },
    ["seconds", "message"],
)
def set_timer(ctx, seconds: int, message: str):
    when = datetime.now() + timedelta(seconds=seconds)
    timer_id = _schedule(ctx, when, message)
    return f"Timer #{timer_id} set: it goes off in {seconds} seconds (at {when:%H:%M:%S})."


@tool("list_timers", "List active countdown timers (for reminders, use list_reminders).")
def list_timers(ctx):
    if not _active:
        return "No active timers or reminders."
    return "\n".join(
        f"#{i}: {when:%a %H:%M:%S} - {msg}" for i, (_, msg, when) in sorted(_active.items())
    )


@tool(
    "cancel_timer",
    "Cancel a timer or reminder by its number.",
    {"timer_id": {"type": "integer"}},
    ["timer_id"],
)
def cancel_timer(ctx, timer_id: int):
    entry = _active.pop(timer_id, None)
    if not entry:
        return f"No timer #{timer_id}."
    entry[0].cancel()
    return f"Cancelled #{timer_id}."
