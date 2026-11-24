"""Apple Calendar (iCloud) through CalDAV. Free: needs your Apple ID email and an
app-specific password (appleid.apple.com › Sign-In and Security › App-Specific Passwords)
in JARVIS_ICLOUD_USER and JARVIS_ICLOUD_APP_PASSWORD."""

from __future__ import annotations

import os
import threading
from datetime import date, datetime, time, timedelta

from . import tool

ICLOUD_CALDAV = "https://caldav.icloud.com"
_cache: dict = {}
_lock = threading.Lock()


def _calendars():
    user = os.getenv("JARVIS_ICLOUD_USER")
    password = os.getenv("JARVIS_ICLOUD_APP_PASSWORD")
    if not user or not password:
        raise RuntimeError("Apple Calendar isn't connected. Set JARVIS_ICLOUD_USER and "
                           "JARVIS_ICLOUD_APP_PASSWORD in .env (see docs/TONIGHT.md).")
    with _lock:
        if "calendars" not in _cache:
            import caldav

            client = caldav.DAVClient(url=ICLOUD_CALDAV, username=user, password=password)
            cals = client.principal().calendars()
            # Only calendars that hold events (iCloud also exposes Reminders lists here).
            _cache["calendars"] = [c for c in cals if "VEVENT" in _components(c)] or cals
        return _cache["calendars"]


def _components(cal) -> str:
    try:
        return " ".join(cal.get_supported_components())
    except Exception:  # noqa: BLE001 - not every server reports this; assume events
        return "VEVENT"


def _local(dt):
    """Calendar values can be dates (all-day) or datetimes in any zone; show in local time."""
    if isinstance(dt, datetime):
        return dt.astimezone() if dt.tzinfo else dt
    return dt


def _describe(component, cal_name: str) -> tuple:
    start = _local(component.decoded("dtstart"))
    end = _local(component.decoded("dtend")) if component.get("dtend") else None
    all_day = not isinstance(start, datetime)
    title = str(component.get("summary", "(no title)"))
    where = str(component.get("location", "") or "")
    if all_day:
        when = f"{start:%a %d %b}, all day"
        sort_key = datetime.combine(start, time.min).astimezone()
    else:
        when = f"{start:%a %d %b %H:%M}" + (f"-{end:%H:%M}" if isinstance(end, datetime) else "")
        sort_key = start if start.tzinfo else start.astimezone()
    line = f"{when}: {title}" + (f" @ {where}" if where else "") + f" [{cal_name}]"
    return sort_key, line


@tool(
    "calendar_events",
    "List events from the user's Apple Calendar. Use for 'what's my day', 'am I free Friday', "
    "'when is my next meeting'.",
    {
        "start_date": {"type": "string", "description": "YYYY-MM-DD, default today"},
        "days": {"type": "integer", "description": "How many days to cover, default 1"},
    },
)
def calendar_events(ctx, start_date: str = "", days: int = 1):
    first = date.fromisoformat(start_date) if start_date else date.today()
    start = datetime.combine(first, time.min).astimezone()
    end = start + timedelta(days=max(1, min(days, 62)))
    rows = []
    for cal in _calendars():
        for event in cal.search(start=start, end=end, event=True, expand=True):
            try:
                rows.append(_describe(event.component, cal.name or "Calendar"))
            except Exception:  # noqa: BLE001 - skip one odd event rather than fail the list
                continue
    rows.sort(key=lambda r: r[0])
    span = f"{first:%a %d %b}" + (f" to {(end - timedelta(days=1)):%a %d %b}" if days > 1 else "")
    return f"Events {span}:\n" + "\n".join(r[1] for r in rows) if rows else f"Nothing on the calendar for {span}."


@tool(
    "add_calendar_event",
    "Add an event to the user's Apple Calendar. Confirm the details back to the user after adding.",
    {
        "title": {"type": "string"},
        "start": {"type": "string", "description": "Local ISO datetime, e.g. 2026-11-26T15:00, or YYYY-MM-DD for all day"},
        "duration_minutes": {"type": "integer", "description": "Default 60; ignored for all-day events"},
        "location": {"type": "string"},
        "notes": {"type": "string"},
        "calendar": {"type": "string", "description": "Calendar name; default is the first one"},
    },
    ["title", "start"],
)
def add_calendar_event(ctx, title: str, start: str, duration_minutes: int = 60, location: str = "",
                       notes: str = "", calendar: str = ""):
    cals = _calendars()
    target = next((c for c in cals if calendar and (c.name or "").lower() == calendar.lower()), cals[0])
    if len(start) == 10:  # all day
        dtstart = date.fromisoformat(start)
        dtend = dtstart + timedelta(days=1)
    else:
        dtstart = datetime.fromisoformat(start)
        if dtstart.tzinfo is None:
            dtstart = dtstart.astimezone()
        dtend = dtstart + timedelta(minutes=duration_minutes or 60)
    fields = {"dtstart": dtstart, "dtend": dtend, "summary": title}
    if location:
        fields["location"] = location
    if notes:
        fields["description"] = notes
    target.add_event(**fields)
    when = f"{dtstart:%a %d %b %H:%M}" if isinstance(dtstart, datetime) else f"{dtstart:%a %d %b} (all day)"
    return f"Added '{title}' on {when} to {target.name}."
