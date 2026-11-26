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
