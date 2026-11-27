"""The phone's location, only when Jarvis asks for it (a route or travel-time question).

Nothing tracks you: when a question needs it, Jarvis asks the phone once:
- the web app answers straight away (the browser asks permission the first time);
- the Siri Shortcut sends it with its next waiting step (the server says "location": "yes");
- in Telegram you can share your location (paperclip > Location).
A location is used for 10 minutes, then forgotten as stale."""

from __future__ import annotations

import threading
import time

FRESH_SECONDS = 600

_lock = threading.Condition()
_latest: dict = {}           # {"lat", "lon", "time", "source"}
_wanted_until = 0.0          # a question is waiting for the phone's location until then


def set_location(lat: float, lon: float, source: str) -> None:
    global _wanted_until
    lat, lon = float(lat), float(lon)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return
    with _lock:
        _latest.update(lat=lat, lon=lon, time=time.time(), source=source)
        _wanted_until = 0.0
        _lock.notify_all()
    print(f"[location] received from {source}")


def wanted() -> bool:
    """True while a question is waiting for the phone's location (the Siri reply then asks for it)."""
    return time.time() < _wanted_until


def fresh() -> dict | None:
    with _lock:
        if _latest and time.time() - _latest["time"] < FRESH_SECONDS:
            return dict(_latest)
    return None


def request(timeout: float = 25, announcer=None) -> dict | None:
    """Ask the phone for its location now and wait for it. None if it doesn't arrive in time."""
    global _wanted_until
    now = time.time()
    with _lock:
        _wanted_until = now + timeout
    if announcer is not None:
        announcer._add({"type": "location_request"})   # the web app answers this right away
    with _lock:
        _lock.wait_for(lambda: bool(_latest) and _latest["time"] >= now, timeout=timeout)
        _wanted_until = 0.0
        if _latest and _latest["time"] >= now:
            return dict(_latest)
    return None


last_denied = 0.0   # when the web app last reported that location permission was refused


def missing_help(siri_recent: bool) -> str:
    """Why no location arrived, as plainly as we can tell, with the fix."""
    import time as _t

    if _t.time() - last_denied < 300:
        return ("The web app isn't allowed to use the location. Fix: Settings > Apps > Safari > Location > "
                "Ask Next Time or Allow (or Settings > Privacy & Security > Location Services > Safari Websites).")
    if siri_recent:
        return ("Siri's Shortcut doesn't send the location yet: it needs the one-time location step. "
                "Send /locationsetup in Telegram for the steps.")
    return ("The phone didn't send its location. In the web app: allow location when asked. With Siri: "
            "send /locationsetup in Telegram for the one-time Shortcut step. Or share it in Telegram "
            "(paperclip > Location).")


# -- a traffic-aware ETA computed on the phone (Apple Maps "Get Travel Time" in the Siri Shortcut) --
_eta: dict = {}                 # {"text", "time", "dest"}
_eta_wanted: dict = {"dest": "", "until": 0.0}


def eta_wanted() -> str:
    """The destination a question is waiting on an ETA for ("" if none)."""
    return _eta_wanted["dest"] if time.time() < _eta_wanted["until"] else ""


def set_eta(text: str) -> None:
    with _lock:
        _eta.update(text=str(text)[:80], time=time.time(), dest=_eta_wanted["dest"])
        _eta_wanted.update(dest="", until=0.0)
        _lock.notify_all()
    print(f"[location] phone sent a travel time: {text!r}")


def request_eta(destination: str, timeout: float = 25) -> str | None:
    """Ask the Siri Shortcut to run Apple Maps' Get Travel Time to `destination`; returns its text
    (e.g. "23 min", "1 hr 5 min") or None if it didn't come back in time."""
    now = time.time()
    with _lock:
        _eta_wanted.update(dest=destination, until=now + timeout)
        _lock.wait_for(lambda: _eta.get("time", 0) >= now, timeout=timeout)
        _eta_wanted.update(dest="", until=0.0)
        if _eta.get("time", 0) >= now:
            return _eta["text"]
    return None


def parse_minutes(text: str) -> int | None:
    """'23 min', '1 hr 5 min', '1 hour, 5 minutes', '45m', '1:05' -> minutes."""
    import re

    t = text.lower()
    if m := re.fullmatch(r"\s*(\d+):(\d{2})\s*", t):
        return int(m.group(1)) * 60 + int(m.group(2))
    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b", t)
    mins = re.search(r"(\d+)\s*(?:m|min|mins|minute|minutes)\b", t)
    if not hours and not mins:
        only = re.fullmatch(r"\s*(\d+)\s*", t)
        return int(only.group(1)) if only else None
    return round(float(hours.group(1)) * 60 if hours else 0) + (int(mins.group(1)) if mins else 0)
