"""Hears "Claude Code is done" pings via ntfy.sh, a free relay, with nothing public on the server.

Claude Code sessions (cloud or on a computer) run a Stop hook that POSTs a small JSON message to
https://ntfy.sh/<secret topic>. This listener keeps an outgoing connection to that topic and
calls Runtime.claude_code_finished for each message. The topic name is the only secret, and all
it allows is sending "done" pings.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request


STATUS: dict = {"topic": "", "connected_since": 0.0, "last_message": 0.0, "messages": 0, "last_error": ""}


def start(topic: str, on_done, data_dir=None) -> None:
    STATUS["topic"] = topic
    # Remember the last ping we handled, so pings sent while Jarvis was restarting (every update
    # restarts it) are picked up afterwards instead of lost. ntfy keeps them for 12 hours.
    mark = (data_dir / "notify-last-id") if data_dir else None

    def remember(event_id: str) -> None:
        if mark:
            try:
                mark.write_text(event_id)
            except OSError:
                pass

    def loop():
        since = str(int(time.time()))
        if mark and mark.exists():
            saved = mark.read_text().strip()
            age = time.time() - mark.stat().st_mtime
            if saved and age < 6 * 3600:
                since = saved
        while True:
            try:
                req = urllib.request.Request(f"https://ntfy.sh/{topic}/json?since={since}",
                                             headers={"User-Agent": "jarvis-assistant"})
                with urllib.request.urlopen(req, timeout=90) as resp:
                    STATUS["connected_since"], STATUS["last_error"] = time.time(), ""
                    for raw in resp:
                        event = json.loads(raw)
                        if event.get("event") != "message":
                            continue
                        since = event.get("id", since)
                        remember(since)
                        STATUS["last_message"], STATUS["messages"] = time.time(), STATUS["messages"] + 1
                        try:
                            data = json.loads(event.get("message") or "{}")
                        except json.JSONDecodeError:
                            data = {"summary": event.get("message", "")}
                        if not data.get("stop_hook_active"):
                            on_done(str(data.get("label", ""))[:60], str(data.get("summary", ""))[:1500],
                                    int(data.get("seconds", -1) or -1), str(data.get("session", ""))[:80])
            except Exception as e:  # noqa: BLE001 - network blips: reconnect quietly
                STATUS["connected_since"] = 0.0
                if "timed out" not in str(e):
                    STATUS["last_error"] = f"{time.strftime('%H:%M:%S')} {e}"
                    print(f"[notify] reconnecting after: {e}")
                time.sleep(5)

    threading.Thread(target=loop, daemon=True, name="jarvis-notify").start()
