"""`python -m jarvis doctor`: checks everything Jarvis needs and says exactly what to fix."""

from __future__ import annotations

import importlib.util
import json
import platform
import shutil
import socket
import subprocess
import sys
import time

from .config import Config

OK, WARN, FAIL = "✅", "⚠️ ", "❌"


def run_doctor(config: Config) -> int:
    problems = 0

    def report(status: str, what: str, fix: str = "") -> None:
        nonlocal problems
        problems += status == FAIL
        print(f"{status} {what}" + (f"\n     → {fix}" if fix else ""))

    print(f"Jarvis doctor ({platform.system()}, Python {platform.python_version()})\n")

    if sys.version_info < (3, 10):
        report(FAIL, "Python 3.10 or newer is needed", "Install a newer Python")
    else:
        report(OK, "Python version")

    missing = [m for m in ("fastapi", "uvicorn", "mcp", "faster_whisper", "edge_tts", "dotenv")
               if importlib.util.find_spec(m) is None]
    if missing:
        report(FAIL, f"Missing packages: {', '.join(missing)}", "pip install -r requirements.txt")
    else:
        report(OK, "Python packages")

    claude = shutil.which("claude")
    if not claude:
        report(FAIL, "Claude Code not found", "Install it (see docs/TONIGHT.md), then run `claude` once to log in")
    else:
        started = time.monotonic()
        try:
            out = subprocess.run(
                [claude, "-p", "Reply with exactly: ready", "--output-format", "json", "--model", "haiku",
                 "--system-prompt", "You are a test.", "--tools", "", "--no-session-persistence",
                 "--strict-mcp-config"],
                capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL,
            )
            result = json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else {}
            if result.get("is_error") or "ready" not in str(result.get("result", "")).lower():
                report(FAIL, "Claude Code is installed but couldn't answer",
                       "Run `claude` in a terminal and log in with your Claude account. "
                       f"Details: {(result.get('result') or out.stderr)[:200]}")
            else:
                report(OK, f"Claude Code is logged in and answering ({time.monotonic() - started:.1f}s)")
        except (subprocess.TimeoutExpired, json.JSONDecodeError, IndexError) as e:
            report(FAIL, "Claude Code didn't respond properly", f"Run `claude` to check it works ({e})")

    if config.telegram_token and config.telegram_user_id:
        from .telegram import TelegramBot

        try:
            name = TelegramBot(config.telegram_token, int(config.telegram_user_id)).check()
            report(OK, f"Telegram bot @{name} (answers only user {config.telegram_user_id})")
        except (RuntimeError, ValueError) as e:
            report(FAIL, f"Telegram: {e}", "Check JARVIS_TELEGRAM_TOKEN and JARVIS_TELEGRAM_USER_ID in .env")
    elif config.telegram_token or config.telegram_user_id:
        report(FAIL, "Telegram is half set up", "Set both JARVIS_TELEGRAM_TOKEN and JARVIS_TELEGRAM_USER_ID")
    else:
        report(WARN, "Telegram not set up (no notifications)", "See docs/TONIGHT.md, step 3")

    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", config.port)) == 0:
            report(WARN, f"Port {config.port} is in use (Jarvis already running?)")
        else:
            report(OK, f"Port {config.port} is free")

    tailscale = shutil.which("tailscale")
    if not tailscale:
        report(WARN, "Tailscale not found (needed for Siri and the web app)", "Install it: docs/TONIGHT.md, step 4")
    else:
        status = subprocess.run([tailscale, "status", "--json"], capture_output=True, text=True)
        try:
            dns = json.loads(status.stdout)["Self"]["DNSName"].rstrip(".")
            report(OK, f"Tailscale is connected: https://{dns}")
            print(f"     Siri URL:    https://{dns}/api/ask?format=text")
            print(f"     Web app URL: https://{dns}/?token={config.token}")
        except (json.JSONDecodeError, KeyError):
            report(WARN, "Tailscale is installed but not connected", "Run: sudo tailscale up")

    print(f"\nYour Jarvis token (for the Siri Shortcut): {config.token}")
    print("All good!" if not problems else f"\n{problems} problem(s) to fix.")
    return 1 if problems else 0
