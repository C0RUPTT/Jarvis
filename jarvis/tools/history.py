"""Looking back through past conversations with Jarvis."""

from __future__ import annotations

from datetime import datetime

from . import tool


@tool(
    "search_past_conversations",
    "Search everything the user has said to you before, across days (saved on the server). Use when "
    "they refer to an earlier conversation you don't see here ('what did we say about the e-bike?', "
    "'the plan from this morning', 'remind me what I told you yesterday'), before saying you don't know.",
    {
        "query": {"type": "string", "description": "Key words, e.g. 'e-bike budget'"},
        "date": {"type": "string", "description": "Optional: only this day, YYYY-MM-DD (e.g. yesterday's date)"},
    },
    ["query"],
)
def search_past_conversations(ctx, query: str, date: str = ""):
    from .. import history

    found = history.search(ctx.config.data_dir, query, day=date.strip())
    if not found:
        return "Nothing found in past conversations for that. Say so plainly."
    lines = []
    for item in sorted(found, key=lambda x: x["t"]):
        when = datetime.fromtimestamp(item["t"]).strftime("%a %b %d, %I:%M %p").replace(" 0", " ")
        lines.append(f"[{when}] You: {item['you'][:300]}\n  Jarvis: {item['jarvis'][:500]}")
    return "\n".join(lines)
