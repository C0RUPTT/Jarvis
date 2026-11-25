"""Reaching the user's phone: notifications and opening phone apps via links."""

from __future__ import annotations

from urllib.parse import quote

from . import tool


@tool(
    "notify_phone",
    "Send a push notification to the user's phone (e.g. a list, an address, a recipe, "
    "something to read later). Requires ntfy to be set up.",
    {
        "message": {"type": "string"},
        "title": {"type": "string", "description": "Short title, default 'Jarvis'"},
    },
    ["message"],
)
def notify_phone(ctx, message: str, title: str = "Jarvis"):
    announcer = ctx.extras.get("announcer")
    if announcer and announcer.push(message, title=title):
        return "Sent to the phone."
    return "Phone notifications aren't set up (JARVIS_NTFY_TOPIC is empty)."


@tool(
    "phone_timer",
    "Start a timer in the iPhone's Clock app (rings on the phone even offline). Use for any "
    "timer request. If the phone can't take it right now, a server timer is used instead.",
    {
        "minutes": {"type": "number", "description": "Length in minutes (decimals allowed, e.g. 0.5)"},
        "label": {"type": "string", "description": "What it's for, e.g. pasta"},
    },
    ["minutes"],
)
def phone_timer(ctx, minutes: float, label: str = "Timer"):
    announcer = ctx.extras.get("announcer")
    if announcer and announcer.phone_action("timer", "", minutes=minutes, label=label):
        return f"Timer for {minutes:g} minutes will start on the phone."
    from .timers import set_timer

    return set_timer(ctx, int(minutes * 60), f"Your {label} timer is done.") + " (server timer; Telegram will ping you)"


@tool(
    "open_on_phone",
    "Open an app or link on the user's iPhone. Works with any URL, including app links: "
    "'maps://?daddr=<address>&dirflg=d' (start driving directions), 'tel:<number>' (call), 'sms:<number>&body=<text>' (text), "
    "'music://', 'spotify:search:<query>', 'youtube://results?search_query=<q>' or a YouTube video URL, "
    "'shortcuts://run-shortcut?name=<name>&input=text&text=<text>' "
    "(run any iPhone Shortcut, which can set alarms, add calendar events, control the home, etc.), "
    "'mailto:', 'https://...'. For Shortcuts, prefer run_phone_shortcut.",
    {
        "url": {"type": "string"},
        "label": {"type": "string", "description": "What this does, shown to the user"},
    },
    ["url", "label"],
)
def open_on_phone(ctx, url: str, label: str):
    from urllib.parse import quote

    announcer = ctx.extras.get("announcer")
    if not announcer:
        return "No phone is connected in this mode."
    url = quote(url.strip(), safe=":/?&=#%+@,;!$'()*~")   # e.g. spaces in addresses -> %20
    live = announcer._capture is not None
    announcer.open_on_phone(url, label)
    if live:
        return "It opens on the phone right now (the user may need to unlock it). Just confirm briefly."
    return "Sent to the phone as a tappable Telegram link."


@tool(
    "run_phone_shortcut",
    "Run one of the user's iPhone Shortcuts by name, optionally passing text to it. Use for "
    "things only the phone can do: alarms, calendar, reminders, messages, smart home, Focus modes.",
    {
        "name": {"type": "string", "description": "Exact Shortcut name"},
        "text": {"type": "string", "description": "Optional input text for the Shortcut"},
    },
    ["name"],
)
def run_phone_shortcut(ctx, name: str, text: str = ""):
    url = f"shortcuts://run-shortcut?name={quote(name)}"
    if text:
        url += f"&input=text&text={quote(text)}"
    return open_on_phone(ctx, url, f"Run Shortcut: {name}")
