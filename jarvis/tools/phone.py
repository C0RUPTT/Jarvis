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
    "Open an app or link on the user's iPhone. Use the right link format, or it only opens the app:\n"
    "- Navigation, Apple Maps: maps://?daddr=<address>&dirflg=d\n"
    "- Navigation, Waze (if the user mentions Waze or prefers it): https://waze.com/ul?q=<address>&navigate=yes\n"
    "- Navigation, Google Maps: comgooglemaps://?daddr=<address>&directionsmode=driving\n"
    "- PLAY a YouTube video: first find a specific video with web search, then open its "
    "https://www.youtube.com/watch?v=<id> link (that plays it). Only fall back to "
    "vnd.youtube://results?search_query=<q> if you truly can't find one. Videos open in the YouTube "
    "app; the user listens to music in the Yattee app instead (see memory).\n"
    "- Music: spotify:search:<query>, or a specific open.spotify.com track/playlist link (found via "
    "web search) to play it; Apple Music: a music.apple.com link.\n"
    "- Settings pages: App-prefs:WIFI, App-prefs:Bluetooth, App-prefs:BATTERY_USAGE, "
    "App-prefs:NOTIFICATIONS_ID, App-prefs:General, App-prefs:Privacy (NOT app-settings:, which "
    "opens an app's own settings).\n"
    "- Calls / texts / email: tel:<number>, sms:<number>&body=<text>, mailto:<address>\n"
    "- Any app: its URL scheme (e.g. spotify://, instagram://, whatsapp://) or its https:// link.\n"
    "- The user's own Shortcuts: prefer run_phone_shortcut.\n"
    "Addresses and queries are URL-encoded automatically.",
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


@tool(
    "open_jarvis_app",
    "Open the Jarvis web app on the user's phone (the voice app with the orb): use when they say "
    "'switch to the app', 'open the Jarvis app', 'the web app', 'let's continue in the app', or any "
    "wording that means moving this conversation to Jarvis's own app. Never ask 'which app?' for these.",
)
def open_jarvis_app(ctx):
    from ..fastpath import app_link

    rt = ctx.extras.get("runtime")
    if rt is None:
        return "The phone link isn't available in this mode."
    rt.announcer.open_on_phone(app_link(rt), "Jarvis")
    return "Opening the Jarvis app on the phone. Tell the user to tap the screen once to keep talking."


CALL_SHORTCUT = "Jarvis Call"


@tool(
    "call_contact",
    "Call someone from the user's iPhone Contacts by name ('call Khloee', 'ring mum'). The phone looks "
    "the name up itself (contacts stay on the phone), asks which one on screen if there are several "
    "matches or numbers, says so if there's no match, then starts the call. Confirm in a few words "
    "('Calling Khloee.'). For a number the user says aloud, use open_on_phone with tel: instead.",
    {"name": {"type": "string", "description": "The person's name as the user said it"}},
    ["name"],
)
def call_contact(ctx, name: str):
    name = name.strip()
    if not name:
        return "Ask who to call."
    url = f"shortcuts://run-shortcut?name={quote(CALL_SHORTCUT)}&input=text&text={quote(name)}"
    open_on_phone(ctx, url, f"Call {name}")
    return (f"The phone is running the '{CALL_SHORTCUT}' Shortcut for '{name}'. Say e.g. 'Calling {name}.' "
            f"If they say nothing happened, the Shortcut isn't set up yet: tell them to send /callsetup "
            f"in Telegram for the steps (about two minutes).")
