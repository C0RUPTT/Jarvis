"""Delivers things Jarvis says on its own (job results, timers, reminders, phone actions) to
wherever you are: Telegram (main), the phone web app if it's open, ntfy (fallback), and/or the
laptop speakers. Quiet mode sends silently; hold mode keeps everything for later."""

from __future__ import annotations

import itertools
import threading
import time
import urllib.request
from typing import Callable

MODES = ("normal", "quiet", "hold")


class Announcer:
    def __init__(self, ntfy_topic: str = "", speak: Callable[[str], None] | None = None):
        self.ntfy_topic = ntfy_topic
        self.speak = speak
        self.telegram = None             # set by the runtime when Telegram is configured
        self.mode = "normal"
        self._ids = itertools.count(1)
        self._events: list[dict] = []
        self._held: list[str] = []
        self._lock = threading.Lock()

    # -- what tools and jobs call ------------------------------------------------

    def announce(self, text: str, urgent: bool = False, quiet: bool = False) -> None:
        """Say something unprompted, e.g. a timer going off or a job finishing."""
        if self.mode == "hold" and not urgent:
            with self._lock:
                self._held.append(text)
            return
        silent = (quiet or self.mode == "quiet") and not urgent
        self._add({"type": "say", "text": text, "silent": silent})
        self.push(text, silent=silent)
        if self.speak and not silent:
            self.speak(text)

    def open_on_phone(self, url: str, label: str) -> None:
        """Ask the phone to open a link or app (maps, music, phone call, a Shortcut...)."""
        self._add({"type": "open", "url": url, "text": label})
        self.push(f"{label}\n{url}")

    def push(self, text: str, silent: bool = False, title: str = "Jarvis") -> bool:
        """Send a notification to the phone. Returns False if no channel is set up."""
        if self.telegram is not None:
            return self.telegram.send(text, silent=silent)
        if self.ntfy_topic:
            headers = {"Title": title, **({"Priority": "low"} if silent else {})}
            req = urllib.request.Request(f"https://ntfy.sh/{self.ntfy_topic}", data=text.encode(),
                                         method="POST", headers=headers)
            try:
                urllib.request.urlopen(req, timeout=10).close()
                return True
            except OSError as e:
                print(f"[ntfy] push failed: {e}")
        return False

    # -- delivery modes -------------------------------------------------------------

    def set_mode(self, mode: str) -> str:
        if mode not in MODES:
            return f"Unknown mode {mode}; use one of {', '.join(MODES)}."
        self.mode = mode
        return f"Delivery mode is now {mode}."

    def take_held(self) -> list[str]:
        """Everything kept while in hold mode (or that the user hasn't heard yet), then cleared."""
        with self._lock:
            held, self._held = self._held, []
        return held

    # -- for the web app -------------------------------------------------------------

    def events_since(self, last_id: int) -> list[dict]:
        with self._lock:
            return [e for e in self._events if e["id"] > last_id]

    def _add(self, event: dict) -> None:
        with self._lock:
            event = {"id": next(self._ids), "time": time.time(), **event}
            self._events = (self._events + [event])[-50:]
