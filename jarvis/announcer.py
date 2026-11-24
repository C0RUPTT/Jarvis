"""Delivers things Jarvis says on its own (timers, reminders, phone actions) to wherever you are:
the phone web app (if open), a push notification (ntfy), and/or the laptop speakers."""

from __future__ import annotations

import itertools
import threading
import time
import urllib.request
from typing import Callable


class Announcer:
    def __init__(self, ntfy_topic: str = "", speak: Callable[[str], None] | None = None):
        self.ntfy_topic = ntfy_topic
        self.speak = speak
        self._ids = itertools.count(1)
        self._events: list[dict] = []
        self._lock = threading.Lock()

    def announce(self, text: str) -> None:
        """Say something unprompted, e.g. a timer going off."""
        self._add({"type": "say", "text": text})
        self.push(text, title="Jarvis")
        if self.speak:
            self.speak(text)

    def open_on_phone(self, url: str, label: str) -> None:
        """Ask the phone to open a link or app (maps, music, phone call, a Shortcut...)."""
        self._add({"type": "open", "url": url, "text": label})
        self.push(label, title="Jarvis", click=url)

    def push(self, text: str, title: str = "Jarvis", click: str = "") -> bool:
        """Send a push notification through ntfy (free). Returns False if not set up."""
        if not self.ntfy_topic:
            return False
        req = urllib.request.Request(
            f"https://ntfy.sh/{self.ntfy_topic}", data=text.encode(), method="POST",
            headers={"Title": title, **({"Click": click} if click else {})},
        )
        try:
            urllib.request.urlopen(req, timeout=10).close()
            return True
        except OSError as e:
            print(f"[ntfy] push failed: {e}")
            return False

    def events_since(self, last_id: int) -> list[dict]:
        with self._lock:
            return [e for e in self._events if e["id"] > last_id]

    def _add(self, event: dict) -> None:
        with self._lock:
            event = {"id": next(self._ids), "time": time.time(), **event}
            self._events = (self._events + [event])[-50:]
