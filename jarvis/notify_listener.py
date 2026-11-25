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


def start(topic: str, on_done) -> None:
    def loop():
        since = str(int(time.time()))
        while True:
            try:
                req = urllib.request.Request(f"https://ntfy.sh/{topic}/json?since={since}",
                                             headers={"User-Agent": "jarvis-assistant"})
                with urllib.request.urlopen(req, timeout=90) as resp:
                    for raw in resp:
                        event = json.loads(raw)
                        if event.get("event") != "message":
                            continue
                        since = event.get("id", since)
                        try:
                            data = json.loads(event.get("message") or "{}")
                        except json.JSONDecodeError:
                            data = {"summary": event.get("message", "")}
                        if not data.get("stop_hook_active"):
                            on_done(str(data.get("label", ""))[:60], str(data.get("summary", ""))[:500],
                                    int(data.get("seconds", -1) or -1), str(data.get("session", ""))[:80])
            except Exception as e:  # noqa: BLE001 - network blips: reconnect quietly
                if "timed out" not in str(e):
                    print(f"[notify] reconnecting after: {e}")
                time.sleep(5)

    threading.Thread(target=loop, daemon=True, name="jarvis-notify").start()
