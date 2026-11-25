"""Watchers: "tell me when X happens" (a price drops, an item is back in stock, a flight is delayed,
news on a topic). Each one is checked every few hours by a small, cheap Claude session with web
search (Haiku, minimal prompt), and Jarvis announces it the moment the condition is met.

Limits keep usage low: at most 8 active watchers, checked no more often than every 2 hours."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import tool

MAX_WATCHERS = 8
MIN_HOURS = 2
_lock = threading.Lock()
_started = False

CHECK_PROMPT = """You check one condition for a personal assistant. Use web search to find the \
current facts, then answer with ONLY a JSON object, no other text:
{{"met": true or false, "summary": "one or two plain sentences with the key facts (prices, times, links)"}}

Watching for: {what}
Previous check said: {last}"""


def _file(ctx) -> Path:
    return ctx.config.data_dir / "watchers.json"


def _load(ctx) -> list[dict]:
    path = _file(ctx)
    try:
        return json.loads(path.read_text()) if path.exists() else []
    except json.JSONDecodeError:
        return []


def _save(ctx, items: list[dict]) -> None:
    _file(ctx).write_text(json.dumps(items, indent=1))


def check_once(what: str, last: str) -> dict:
    """Ask a lean, cheap Claude Code session whether the condition is met."""
    claude = shutil.which("claude")
    if not claude:
        return {"met": False, "summary": "Claude Code isn't available."}
    out = subprocess.run(
        [claude, "-p", CHECK_PROMPT.format(what=what, last=last or "nothing yet"),
         "--output-format", "json", "--model", "haiku", "--system-prompt", "You are a careful fact checker.",
         "--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch", "WebFetch",
         "--strict-mcp-config", "--no-session-persistence"],
        capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL,
    )
    try:
        result = json.loads(out.stdout.strip().splitlines()[-1]).get("result", "")
        start, end = result.find("{"), result.rfind("}")
        data = json.loads(result[start:end + 1])
        return {"met": bool(data.get("met")), "summary": str(data.get("summary", ""))[:500]}
    except (ValueError, IndexError):
        return {"met": False, "summary": ""}


def start(ctx) -> None:
    global _started
    if _started:
        return
    _started = True

    def loop():
        time.sleep(60)
        while True:
            with _lock:
                due = [w for w in _load(ctx) if w["active"] and time.time() - w.get("checked", 0) >= w["every_hours"] * 3600]
            for w in due[:2]:   # at most two checks per round, to spread usage out
                try:
                    res = check_once(w["what"], w.get("last", ""))
                except Exception as e:  # noqa: BLE001
                    res = {"met": False, "summary": f"(check failed: {e})"}
                with _lock:
                    items = _load(ctx)
                    for item in items:
                        if item["id"] == w["id"]:
                            item["checked"], item["last"] = time.time(), res["summary"] or item.get("last", "")
                            if res["met"]:
                                item["active"] = bool(item.get("repeat"))
                    _save(ctx, items)
                if res["met"]:
                    ctx.announce(f"Heads up: {w['what']}. {res['summary']}", urgent=bool(w.get("urgent")))
            time.sleep(300)

    threading.Thread(target=loop, daemon=True, name="jarvis-watchers").start()


@tool(
    "add_watcher",
    "Watch for something and tell the user when it happens: 'tell me when the PS5 drops below $400', "
    "'let me know if my AA100 flight tomorrow is delayed', 'when the new Dune trailer is out'. "
    "Checked every few hours with web search. Write 'what' as a precise, checkable condition "
    "including names, numbers, dates and the site if the user gave one.",
    {
        "what": {"type": "string"},
        "every_hours": {"type": "number", "description": f"How often to check (minimum {MIN_HOURS}, default 6)"},
        "repeat": {"type": "boolean", "description": "Keep watching after it triggers (default: stop)"},
        "urgent": {"type": "boolean", "description": "Break through quiet/hold/night mode"},
    },
    ["what"],
)
def add_watcher(ctx, what: str, every_hours: float = 6, repeat: bool = False, urgent: bool = False):
    with _lock:
        items = _load(ctx)
        active = [w for w in items if w["active"]]
        if len(active) >= MAX_WATCHERS:
            return f"There are already {MAX_WATCHERS} active watchers; remove one first (list_watchers)."
        item = {"id": max((w["id"] for w in items), default=0) + 1, "what": what, "active": True,
                "every_hours": max(MIN_HOURS, float(every_hours or 6)), "repeat": repeat, "urgent": urgent,
                "created": time.time(), "checked": 0, "last": ""}
        _save(ctx, items + [item])
    return f"Watcher #{item['id']} set; I'll check every {item['every_hours']:g} hours."


@tool("list_watchers", "List what Jarvis is watching for, with the latest finding.")
def list_watchers(ctx):
    active = [w for w in _load(ctx) if w["active"]]
    if not active:
        return "Not watching anything."
    return "\n".join(f"#{w['id']}: {w['what']} (every {w['every_hours']:g}h)"
                     + (f"\n   last check: {w['last']}" if w.get("last") else "") for w in active)


@tool("remove_watcher", "Stop a watcher by its number.", {"watcher_id": {"type": "integer"}}, ["watcher_id"])
def remove_watcher(ctx, watcher_id: int):
    with _lock:
        items = _load(ctx)
        hit = next((w for w in items if w["id"] == watcher_id and w["active"]), None)
        if not hit:
            return f"No active watcher #{watcher_id}."
        hit["active"] = False
        _save(ctx, items)
    return f"Stopped watching: {hit['what']}"
