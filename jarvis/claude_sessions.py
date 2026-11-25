"""Which Claude Code sessions you've been working in, learned from their "done" pings, so Jarvis can
send messages into them ("pick up on my Jarvis session: ...")."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path


def _file(data_dir: Path) -> Path:
    return data_dir / "claude-sessions.json"


def load(data_dir: Path) -> list[dict]:
    try:
        return json.loads(_file(data_dir).read_text())
    except (OSError, json.JSONDecodeError):
        return []


def normalize(session: str) -> str:
    """'cse_01ABC' (inside the session) or a claude.ai link -> 'session_01ABC'."""
    session = session.strip().rstrip("/").split("?")[0].rsplit("/", 1)[-1]
    if session.startswith("cse_"):
        session = "session_" + session[4:]
    return session


def seen(data_dir: Path, label: str, session: str, summary: str) -> None:
    if not session:
        return
    sid = normalize(session)
    items = [s for s in load(data_dir) if s["id"] != sid]
    items.insert(0, {"id": sid, "project": label, "last_seen": time.time(), "last_summary": summary[:300]})
    _file(data_dir).write_text(json.dumps(items[:30], indent=1))


def send(session: str, message: str) -> str:
    """Send a message into a Claude Code cloud session, as if typed there. Returns "" or an error."""
    claude = shutil.which("claude")
    if not claude:
        return "Claude Code isn't installed on the server."
    p = subprocess.run([claude, "-p", message, "--cloud", normalize(session), "--output-format", "json"],
                       capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    try:
        result = json.loads(p.stdout.strip().splitlines()[-1])
        return "" if result.get("ok") else str(result.get("error") or "unknown error")
    except (ValueError, IndexError):
        return (p.stderr or p.stdout).strip()[-300:] or "no response"


def find(data_dir: Path, name: str) -> dict | None:
    """The session whose project best matches a spoken name, allowing for dictation slips
    ("drivers" for "Jarvis"). Most recently active first."""
    import difflib

    key = name.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    sessions = load(data_dir)
    norm = [(s["project"] or "").lower().replace("-", "").replace("_", "").replace(" ", "") for s in sessions]
    for s, n in zip(sessions, norm):
        if key and n and (key in n or n in key):
            return s
    close = difflib.get_close_matches(key, norm, n=1, cutoff=0.6)
    return sessions[norm.index(close[0])] if close else None
