"""Delivers things Jarvis says on its own (job results, timers, reminders, phone actions) to
wherever you are: Telegram (main), the phone web app if it's open, ntfy (fallback), and/or the
laptop speakers. Quiet mode sends silently; hold mode keeps everything for later."""

from __future__ import annotations

import itertools
import json
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable

MODES = ("normal", "quiet", "hold")


class Announcer:
    def __init__(self, ntfy_topic: str = "", speak: Callable[[str], None] | None = None,
                 state_file: Path | None = None, quiet_start: str = ""):
        self.ntfy_topic = ntfy_topic
        self.speak = speak
        self.telegram = None             # set by the runtime when Telegram is configured
        self.mode = "normal"
        self.night = False               # in night mode: hold everything until the user wakes up
        self.quiet_start = quiet_start   # "HH:MM" when night mode starts, "" = never
        self._ids = itertools.count(1)
        self._events: list[dict] = []
        self._held: list[str] = []
        self._lock = threading.Lock()
        self._state_file = state_file
        self._load()
        if quiet_start:
            threading.Thread(target=self._night_watch, daemon=True, name="jarvis-night").start()

    # -- what tools and jobs call ------------------------------------------------

    def announce(self, text: str, urgent: bool = False, quiet: bool = False, reply: bool = False) -> None:
        """Say something unprompted, e.g. a timer going off or a job finishing.
        reply=True: the answer to something the user just asked, so it's never held (only made
        silent at night or in quiet/hold mode)."""
        if reply and not urgent:
            silent = quiet or self.night or self.mode != "normal"
            self._add({"type": "say", "text": text, "silent": silent})
            self.push(text, silent=silent)
            return
        if (self.mode == "hold" or self.night) and not urgent:
            with self._lock:
                self._held.append(f"[{datetime.now():%H:%M}] {text}")
            self._save()
            return
        silent = (quiet or self.mode == "quiet") and not urgent
        self._add({"type": "say", "text": text, "silent": silent})
        self.push(text, silent=silent)
        if self.speak and not silent:
            self.speak(text)

    # -- phone actions ------------------------------------------------------------
    # While a Siri request is being answered, actions are captured and returned to the Shortcut,
    # which performs them on the phone itself. Otherwise they go out as Telegram links/messages.
    _capture: list | None = None

    def begin_capture(self) -> None:
        self._capture = []

    def end_capture(self) -> list[dict]:
        captured, self._capture = self._capture or [], None
        return captured

    def open_on_phone(self, url: str, label: str) -> None:
        """Ask the phone to open a link or app (maps, music, phone call, a Shortcut...)."""
        if self._capture is not None:
            self._capture.append({"type": "open", "url": url, "text": label})
            return
        self._add({"type": "open", "url": url, "text": label})
        self.push(f"{label}\n{url}")

    def phone_action(self, kind: str, fallback: str, **data) -> bool:
        """A native phone action (timer, alarm). Returns False if no Siri request can take it,
        in which case the caller should use its fallback."""
        if self._capture is not None:
            self._capture.append({"type": kind, **data})
            return True
        return False

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
        self._save()
        return f"Delivery mode is now {mode}."

    def take_held(self) -> list[str]:
        """Everything kept while in hold mode (or that the user hasn't heard yet), then cleared."""
        with self._lock:
            held, self._held = self._held, []
        self._save()
        return held

    def peek_held(self) -> int:
        return len(self._held)

    # -- night mode (quiet hours) -------------------------------------------------

    def start_night(self) -> None:
        self.night = True
        self._save()

    def wake(self) -> bool:
        """The user is up (alarm stopped, Sleep Focus off, or they talked to Jarvis).
        Returns True if night mode was on."""
        was_night, self.night = self.night, False
        if was_night:
            self._save()
        return was_night

    def _night_watch(self) -> None:
        last_day = None
        while True:
            now = datetime.now()
            if now.strftime("%H:%M") == self.quiet_start and last_day != now.date():
                last_day = now.date()
                self.start_night()
            time.sleep(20)

    # -- persistence (so held items survive a restart) -------------------------------

    def _save(self) -> None:
        if self._state_file is None:
            return
        with self._lock:
            state = {"mode": self.mode, "night": self.night, "held": self._held}
        self._state_file.write_text(json.dumps(state, indent=1))

    def _load(self) -> None:
        if self._state_file is None or not self._state_file.exists():
            return
        try:
            state = json.loads(self._state_file.read_text())
            self.mode = state.get("mode", "normal")
            self.night = bool(state.get("night", False))
            self._held = list(state.get("held", []))
        except (json.JSONDecodeError, TypeError):
            pass

    # -- for the web app -------------------------------------------------------------

    def events_since(self, last_id: int) -> list[dict]:
        with self._lock:
            return [e for e in self._events if e["id"] > last_id]

    def _add(self, event: dict) -> None:
        with self._lock:
            event = {"id": next(self._ids), "time": time.time(), **event}
            self._events = (self._events + [event])[-50:]
