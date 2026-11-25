"""Run an interactive login command (Claude Code, Tailscale) and also send any login link it
prints to your Telegram, so you can tap it on your phone instead of copying it out of a
browser terminal. Everything you type still goes to the command as normal.

Usage: python scripts/relay_links.py <command> [args...]
Reads the Telegram token and user id from the .env file in the current folder.
"""

from __future__ import annotations

import os
import pty
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

URL = re.compile(rb"https://[^\s\x1b\x07'\"<>]+")
ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
sent: set[str] = set()
buffer = b""


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


def on_output(fd: int) -> bytes:
    global buffer
    data = os.read(fd, 4096)
    buffer = (buffer + ANSI.sub(b"", data))[-8000:]
    for match in URL.finditer(buffer):
        if match.end() >= len(buffer):
            continue  # the link may still be arriving; wait for the rest
        url = match.group(0).decode(errors="ignore").rstrip(".,)")
        interesting = any(k in url for k in ("login", "oauth", "authorize", "claude.ai", "anthropic.com"))
        if interesting and len(url) > 30 and url not in sent and not any(url in s for s in sent):
            sent.add(url)
            telegram(f"Jarvis setup: tap to sign in ({sys.argv[1]}):\n{url}")
    return data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    status = pty.spawn(sys.argv[1:], master_read=on_output)
    sys.exit(os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else 0)
