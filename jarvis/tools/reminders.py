"""Reminders that survive restarts: at a time ("at 5pm", "tomorrow at 9") or on an event from the
phone ("when I get home", "when I leave home", "when I get in the car"). Event reminders fire when
the iPhone's automation calls /api/event (see docs/AUTOMATIONS.md)."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

from . import tool

EVENTS = {
    "arrive_home": "when you get home",
    "leave_home": "when you leave home",
    "arrive_work": "when you get to work",
    "leave_work": "when you leave work",
    "car": "when you get in the car",
}
_lock = threading.Lock()
_started = False


def _file(ctx) -> Path:
    return ctx.config.data_dir / "reminders.json"


def _load(ctx) -> list[dict]:
    path = _file(ctx)
    try:
        return json.loads(path.read_text()) if path.exists() else []
    except json.JSONDecodeError:
        return []


def _save(ctx, items: list[dict]) -> None:
    _file(ctx).write_text(json.dumps(items, indent=1))


def start(ctx) -> None:
    """Background checker for timed reminders (called once at startup)."""
    global _started
    if _started:
        return
    _started = True

    def loop():
        while True:
            now = datetime.now().astimezone()
            with _lock:
                items = _load(ctx)
                due = [r for r in items if r.get("at") and datetime.fromisoformat(r["at"]) <= now]
                if due:
                    _save(ctx, [r for r in items if r not in due])
            for r in due:
                ctx.announce(f"Reminder: {r['text']}", urgent=bool(r.get("urgent")))
            time.sleep(15)

    threading.Thread(target=loop, daemon=True, name="jarvis-reminders").start()


def fire_event(ctx, event: str) -> list[str]:
    """The phone reported an event (e.g. arrive_home): deliver and remove matching reminders."""
    with _lock:
        items = _load(ctx)
        hits = [r for r in items if r.get("event") == event]
        if hits:
            _save(ctx, [r for r in items if r not in hits])
    return [r["text"] for r in hits]


@tool(
    "set_reminder",
    "Set a reminder. Either at a time (when = local ISO datetime, e.g. 2026-11-26T17:00) or on an "
    "event from the user's phone (event = arrive_home, leave_home, arrive_work, leave_work, car), "
    "for things like 'remind me to take out the trash when I get home'. Survives restarts.",
    {
        "text": {"type": "string", "description": "What to remind them of, phrased to be read aloud"},
        "when": {"type": "string", "description": "Local ISO datetime, for time-based reminders"},
        "event": {"type": "string", "enum": list(EVENTS)},
        "urgent": {"type": "boolean", "description": "Break through quiet/hold/night mode"},
    },
    ["text"],
)
def set_reminder(ctx, text: str, when: str = "", event: str = "", urgent: bool = False):
    if not when and not event:
        return "Give either a time (when) or an event."
    item = {"text": text, "urgent": urgent}
    if when:
        at = datetime.fromisoformat(when)
        at = at if at.tzinfo else at.astimezone()
        if at <= datetime.now().astimezone():
            return "That time has already passed."
        item["at"] = at.isoformat()
        spoken = f"{at:%A %b %d at %I:%M %p}".replace(" 0", " ")
    else:
        if event not in EVENTS:
            return f"Unknown event; use one of {', '.join(EVENTS)}."
        item["event"] = event
        spoken = EVENTS[event]
    with _lock:
        items = _load(ctx)
        item["id"] = max((r["id"] for r in items), default=0) + 1
        _save(ctx, items + [item])
    note = ""
    if event:
        note = " (This needs the phone automation for that event; see docs/AUTOMATIONS.md.)"
    return f"Reminder #{item['id']} set for {spoken}.{note}"


@tool("list_reminders", "List upcoming reminders (timed and event-based).")
def list_reminders(ctx):
    items = _load(ctx)
    if not items:
        return "No reminders."
    lines = []
    for r in sorted(items, key=lambda r: r.get("at") or "9999"):
        when = (datetime.fromisoformat(r["at"]).strftime("%a %b %d %I:%M %p").replace(" 0", " ") if r.get("at")
                else EVENTS.get(r.get("event"), r.get("event")))
        lines.append(f"#{r['id']}: {when} - {r['text']}")
    return "\n".join(lines)


@tool("cancel_reminder", "Cancel a reminder by its number.", {"reminder_id": {"type": "integer"}}, ["reminder_id"])
def cancel_reminder(ctx, reminder_id: int):
    with _lock:
        items = _load(ctx)
        kept = [r for r in items if r["id"] != reminder_id]
        if len(kept) == len(items):
            return f"No reminder #{reminder_id}."
        _save(ctx, kept)
    return f"Cancelled reminder #{reminder_id}."
