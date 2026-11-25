"""Run an interactive login command (Claude Code, Tailscale) and also send any login link it
prints to your Telegram, so you can tap it on your phone instead of copying it out of a
browser terminal. Everything you type still goes to the command as normal.

With --reply, anything you then send to your bot in Telegram is typed into the command (for
login codes), so nothing has to be pasted into a phone's browser terminal.

Usage: python scripts/relay_links.py [--reply] <command> [args...]
Reads the Telegram token and user id from the .env file in the current folder.
"""

from __future__ import annotations

import os
import pty
import re
import json
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

URL = re.compile(rb"https://[^\s\x1b\x07'\"<>]+")
ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
sent: set[str] = set()
buffer = b""
master_fd: int | None = None
REPLY = False


def _env() -> dict:
    path = Path(__file__).resolve().parent.parent / ".env"
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.split(" #")[0].strip()
    return values


def telegram(text: str) -> None:
    env = _env()
    token, user = env.get("JARVIS_TELEGRAM_TOKEN"), env.get("JARVIS_TELEGRAM_USER_ID")
    if not (token and user):
        return
    data = urllib.parse.urlencode({"chat_id": user, "text": text}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data, timeout=10).close()
    except OSError:
        pass


def _telegram_api(method: str, params: dict, timeout: int = 40):
    env = _env()
    token = env.get("JARVIS_TELEGRAM_TOKEN")
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data, timeout=timeout) as r:
        return json.load(r).get("result", [])


def relay_replies() -> None:
    """Type the owner's Telegram messages into the command (e.g. a login code)."""
    user = str(_env().get("JARVIS_TELEGRAM_USER_ID", ""))
    try:
        pending = _telegram_api("getUpdates", {"timeout": 0})
        offset = (pending[-1]["update_id"] + 1) if pending else 0   # ignore older messages
    except OSError:
        return
    while True:
        try:
            updates = _telegram_api("getUpdates", {"offset": offset, "timeout": 30})
        except OSError:
            time.sleep(3)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            text = (msg.get("text") or "").strip()
            if str((msg.get("from") or {}).get("id")) != user or not text or text.startswith("/"):
                continue
            if master_fd is not None:
                os.write(master_fd, text.encode() + b"\r")
                telegram("Got it, entered that into the setup.")


def on_output(fd: int) -> bytes:
    global buffer, master_fd
    if master_fd is None:
        master_fd = fd
        if REPLY:
            threading.Thread(target=relay_replies, daemon=True).start()
    data = os.read(fd, 4096)
    buffer = (buffer + ANSI.sub(b"", data))[-8000:]
    for match in URL.finditer(buffer):
        if match.end() >= len(buffer):
            continue  # the link may still be arriving; wait for the rest
        url = match.group(0).decode(errors="ignore").rstrip(".,)")
        interesting = any(k in url for k in ("login", "oauth", "authorize", "claude.ai", "anthropic.com"))
        if interesting and len(url) > 30 and url not in sent and not any(url in s for s in sent):
            sent.add(url)
            extra = "\nIf it shows a code afterwards, send the code to me here." if REPLY else ""
            telegram(f"Jarvis setup: tap to sign in ({CMD[0]}):\n{url}{extra}")
    return data


CMD = sys.argv[1:]

if __name__ == "__main__":
    if CMD[:1] == ["--reply"]:
        REPLY, CMD = True, CMD[1:]
    if not CMD:
        sys.exit(__doc__)
    status = pty.spawn(CMD, master_read=on_output)
    sys.exit(os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else 0)
