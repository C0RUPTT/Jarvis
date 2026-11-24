"""Timers and reminders that Jarvis announces out loud when they go off."""

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


@tool(
    "set_reminder",
    "Set a reminder for a specific local date/time. Jarvis says the message out loud then. "
    "Only works while Jarvis is running.",
    {
        "when": {"type": "string", "description": "ISO local datetime, e.g. 2026-11-24T17:30:00"},
        "message": {"type": "string"},
    },
    ["when", "message"],
)
def set_reminder(ctx, when: str, message: str):
    at = datetime.fromisoformat(when)
    if at < datetime.now():
        return "That time is in the past."
    timer_id = _schedule(ctx, at, message)
    return f"Reminder #{timer_id} set for {at:%A %H:%M}."


@tool("list_timers", "List active timers and reminders.")
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
