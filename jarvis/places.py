"""Your named places ("Sam", "the gym", "Mom's"), so "take me to Sam" just works.

Home and Work come from Waze's own saved favorites (Waze links support those two). Waze doesn't share
your other saved places, so you tell Jarvis each one once ("remember Sam's address is 12 Oak St",
or /place Sam = 12 Oak St in Telegram); they're kept on your Jarvis server."""

from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path

WAZE_FAVORITES = {"home": "home", "my house": "home", "my place": "home", "work": "work", "the office": "work",
                  "my work": "work", "my job": "work", "the job": "work"}


def _file(data_dir: Path) -> Path:
    return data_dir / "places.json"


def _key(name: str) -> str:
    name = name.lower().strip(" .!?")
    name = re.sub(r"^(the|my)\s+", "", name)
    name = re.sub(r"\s+(house|place|home|apartment|apt)$", "", name)   # "Sam's house" -> "sam's"
    name = re.sub(r"'s$|s'$", "", name)          # "Sam's" -> "sam"
    return name.strip()


def load(data_dir: Path) -> dict:
    try:
        return json.loads(_file(data_dir).read_text())
    except (OSError, ValueError):
        return {}


def save(data_dir: Path, name: str, address: str) -> str:
    places = load(data_dir)
    places[_key(name)] = {"name": name.strip(), "address": address.strip()}
    _file(data_dir).write_text(json.dumps(places, indent=1))
    return _key(name)


def forget(data_dir: Path, name: str) -> bool:
    places = load(data_dir)
    if places.pop(_key(name), None) is None:
        return False
    _file(data_dir).write_text(json.dumps(places, indent=1))
    return True


def waze_link(data_dir: Path, spoken: str) -> tuple[str, str] | None:
    """(link, label) for a spoken place name, or None if it isn't Home/Work or a saved place."""
    raw = spoken.lower().strip(" .!?")
    if raw in WAZE_FAVORITES:
        fav = WAZE_FAVORITES[raw]
        return f"https://waze.com/ul?favorite={fav}&navigate=yes", fav.title()
    place = load(data_dir).get(_key(spoken))
    if place:
        return ("https://waze.com/ul?" + urllib.parse.urlencode({"q": place["address"], "navigate": "yes"}),
                place["name"])
    return None
