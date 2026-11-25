#!/usr/bin/env python3
"""Claude Code "Stop" hook: tells Jarvis that Claude finished a task, so Jarvis can announce it
("let me know when Claude Code is done"). Posts a small message to JARVIS_NOTIFY_URL (the private
ntfy topic shown by the bot's /notifysetup). Does nothing if it's unset; never blocks Claude."""
import json
import os
import sys
import urllib.request

url = os.environ.get("JARVIS_NOTIFY_URL")
if not url:
    sys.exit(0)
try:
    event = json.load(sys.stdin)
except Exception:
    event = {}
if event.get("stop_hook_active"):
    sys.exit(0)
label = os.path.basename(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
body = json.dumps({"label": label, "summary": (event.get("last_assistant_message") or "")[:500]}).encode()
try:
    urllib.request.urlopen(urllib.request.Request(url, data=body, method="POST"), timeout=5).close()
except Exception:
    pass
