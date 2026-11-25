#!/usr/bin/env python3
"""Claude Code "Stop" hook: tells Jarvis that Claude finished a turn, so Jarvis can announce it and
knows which session is which (so you can say "pick up on my Jarvis session").

Posts {label, summary, seconds, session} to JARVIS_NOTIFY_URL (the private ntfy topic shown by the
bot's /notifysetup). Does nothing if it's unset, and never blocks or slows Claude down."""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

url = os.environ.get("JARVIS_NOTIFY_URL")
if not url:
    sys.exit(0)
try:
    event = json.load(sys.stdin)
except Exception:
    event = {}
if event.get("stop_hook_active"):
    sys.exit(0)
# A helper `claude` run started inside a session (e.g. a test in a temp folder) inherits the
# session's id; its "done" is not the session's reply, so don't report it.
project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
if project_dir.startswith(("/tmp/", "/var/tmp/")):
    sys.exit(0)


def worked_seconds(transcript: str) -> int:
    """How long since the user's last message: roughly how long Claude worked on it."""
    try:
        last = None
        with open(transcript) as f:
            for line in f:
                entry = json.loads(line)
                if entry.get("type") != "user" or not entry.get("timestamp"):
                    continue
                content = (entry.get("message") or {}).get("content")
                is_tool_result = isinstance(content, list) and any(
                    isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
                if not is_tool_result:
                    last = entry["timestamp"]
        if last:
            started = datetime.fromisoformat(last.replace("Z", "+00:00")).timestamp()
            return max(0, int(time.time() - started))
    except Exception:
        pass
    return -1   # unknown


body = json.dumps({
    "label": os.path.basename(project_dir),
    "summary": (event.get("last_assistant_message") or "")[:1500],
    "seconds": worked_seconds(event.get("transcript_path") or ""),
    "session": os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID") or "",   # cloud sessions only
}).encode()
try:
    urllib.request.urlopen(urllib.request.Request(url, data=body, method="POST"), timeout=5).close()
except Exception:
    pass
