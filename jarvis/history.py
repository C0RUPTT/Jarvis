"""Every exchange with Jarvis, kept on your server (one file per day), so Jarvis can look back:
"what did we say about the e-bike yesterday?". Nothing leaves the server."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path


def _dir(data_dir: Path) -> Path:
    d = data_dir / "conversations"
    d.mkdir(parents=True, exist_ok=True)
    return d


def add(data_dir: Path, you: str, jarvis: str) -> None:
    try:
        line = json.dumps({"t": time.time(), "you": you, "jarvis": jarvis})
        with (_dir(data_dir) / f"{datetime.now():%Y-%m-%d}.jsonl").open("a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def since(data_dir: Path, t0: float) -> list[dict]:
    """Exchanges since a moment (today and yesterday's files)."""
    out = []
    for day in (datetime.now() - timedelta(days=1), datetime.now()):
        path = _dir(data_dir) / f"{day:%Y-%m-%d}.jsonl"
        if path.exists():
            for line in path.read_text().splitlines():
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if item["t"] >= t0:
                    out.append(item)
    return out


_STOP = set("a an the and or but to of in on at for with about is are was were be it this that what "
            "did do does we you i me my your our us he she they them how why when where which who".split())


def search(data_dir: Path, query: str, day: str = "", days_back: int = 60, limit: int = 8) -> list[dict]:
    """Best-matching past exchanges: every word of the query that matters is looked for."""
    words = [w for w in re.findall(r"[a-z0-9']+", query.lower()) if w not in _STOP and len(w) > 1]
    files = sorted(_dir(data_dir).glob("*.jsonl"), reverse=True)
    if day:
        files = [f for f in files if f.stem == day]
    else:
        cutoff = f"{datetime.now() - timedelta(days=days_back):%Y-%m-%d}"
        files = [f for f in files if f.stem >= cutoff]
    scored = []
    for path in files:
        for line in path.read_text().splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            text = f"{item['you']} {item['jarvis']}".lower()
            score = sum(1 for w in words if w in text) if words else 1
            if score:
                scored.append((score, item["t"], item))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [x[2] for x in scored[:limit]]


SUMMARY_PROMPT = """Below is a conversation between the user and Jarvis, their voice assistant. Jarvis is about to
start a fresh conversation (to stay quick) and needs to carry on seamlessly. Write a compact summary
for Jarvis (not for the user): the topics covered, decisions made, plans and times agreed, facts the
user shared, things Jarvis promised to do or follow up on, and anything left open. Plain text, at most
200 words, most recent and most important first. No preamble.

{text}"""


def summarize(exchanges: list[dict]) -> str:
    """A short summary of a conversation (cheap Haiku call). "" if it can't be made."""
    import shutil
    import subprocess

    claude = shutil.which("claude")
    if not claude or not exchanges:
        return ""
    text = "\n".join(f"User: {e['you'][:600]}\nJarvis: {e['jarvis'][:800]}" for e in exchanges)[-30000:]
    try:
        out = subprocess.run(
            [claude, "-p", SUMMARY_PROMPT.format(text=text), "--output-format", "json", "--model", "haiku",
             "--tools", "", "--strict-mcp-config", "--no-session-persistence"],
            capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
        return json.loads(out.stdout.strip().splitlines()[-1]).get("result", "").strip()[:2000]
    except (ValueError, IndexError, OSError, subprocess.SubprocessError):
        return ""
