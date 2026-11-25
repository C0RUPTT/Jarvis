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


def is_side_run(label: str) -> bool:
    """A helper Claude run inside a session (started from a temp or scratch folder, e.g. a test), not
    the session's own reply: it carries the session's id but must not count as its answer."""
    low = (label or "").lower()
    return low.startswith(("tmp", "scratchpad")) or low in {"tmp", "temp", "scratch"}


def trim(text: str, limit: int) -> str:
    """Shorten at a sentence end where possible, never mid-word."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind(".\n"))
    if end >= limit // 3:
        return cut[:end + 1]
    return cut.rsplit(" ", 1)[0] + "…"


def name_of(data_dir: Path, sid: str) -> str:
    return next((s["project"] for s in load(data_dir) if s["id"] == normalize(sid)), "")


def seen(data_dir: Path, label: str, session: str, summary: str) -> None:
    if not session:
        return
    sid = normalize(session)
    old = next((s for s in load(data_dir) if s["id"] == sid), None)
    if is_side_run(label):
        if old is None:
            return
        label, summary = old["project"], old.get("last_summary", "")   # keep its real name and reply
    elif old and old.get("named"):
        label = old["project"]          # a name the user gave it ("Jarvis") wins over the folder name
    items = [s for s in load(data_dir) if s["id"] != sid]
    entry = {"id": sid, "project": label, "last_seen": time.time(), "last_summary": summary[:4000]}
    if old and old.get("named"):
        entry["named"] = True
    items.insert(0, entry)
    _file(data_dir).write_text(json.dumps(items[:30], indent=1))


def register(data_dir: Path, project: str, session: str) -> str:
    """Remember a session under the name the user calls it. Returns its id."""
    sid = normalize(session)
    old = next((s for s in load(data_dir) if s["id"] == sid), {})
    items = [s for s in load(data_dir) if s["id"] != sid]
    items.insert(0, {"id": sid, "project": project.strip(), "named": True, "last_seen": time.time(),
                     "last_summary": old.get("last_summary", "")})
    data_dir.mkdir(parents=True, exist_ok=True)
    _file(data_dir).write_text(json.dumps(items[:30], indent=1))
    return sid


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
