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
    "open_on_phone",
    "Open an app or link on the user's iPhone. Works with any URL, including app links: "
    "'maps://?daddr=<address>' (directions), 'tel:<number>' (call), 'sms:<number>&body=<text>' (text), "
    "'music://', 'spotify:', 'shortcuts://run-shortcut?name=<name>&input=text&text=<text>' "
    "(run any iPhone Shortcut, which can set alarms, add calendar events, control the home, etc.), "
    "'mailto:', 'https://...'. For Shortcuts, prefer run_phone_shortcut.",
    {
        "url": {"type": "string"},
        "label": {"type": "string", "description": "What this does, shown to the user"},
    },
    ["url", "label"],
)
def open_on_phone(ctx, url: str, label: str):
    announcer = ctx.extras.get("announcer")
    if not announcer:
        return "No phone is connected in this mode."
    announcer.open_on_phone(url, label)
    return "Sent to the phone (it opens automatically if the Jarvis app is open, otherwise via notification)."


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
