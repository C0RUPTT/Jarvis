"""Where the user is, and how long it takes to get somewhere (OpenStreetMap: free, no key)."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from . import tool

UA = {"User-Agent": "jarvis-personal-assistant/1.0"}


def _get(url: str, timeout: float = 10):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as resp:
        return json.load(resp)


def _here(ctx) -> dict | None:
    from .. import location

    rt = ctx.extras.get("runtime")
    return location.fresh() or location.request(timeout=25, announcer=rt.announcer if rt else None)


def _no_location(ctx) -> str:
    import time as _t

    from .. import location

    rt = ctx.extras.get("runtime")
    siri = rt is not None and _t.time() - getattr(rt, "last_siri", 0) < 60
    return ("No location from the phone. Tell the user why in one short sentence, ask where they're "
            "starting from, and mention the fix: " + location.missing_help(siri))


def geocode(place: str, near: dict | None = None) -> dict | None:
    params = {"q": place, "format": "json", "limit": 1}
    if near:   # prefer the match nearest to the user ("Homewood" near you, not across the country)
        d = 1.5
        params.update(viewbox=f"{near['lon'] - d},{near['lat'] + d},{near['lon'] + d},{near['lat'] - d}")
    found = _get("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params))
    if not found and near:
        found = _get("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": place, "format": "json", "limit": 1}))
    if not found:
        return None
    return {"lat": float(found[0]["lat"]), "lon": float(found[0]["lon"]), "name": found[0].get("display_name", place)}


def drive_with_traffic(a: dict, b: dict) -> dict | None:
    """TomTom (free tier, no card): live-traffic drive time, if a key is set (/tomtom in Telegram)."""
    import os

    key = os.getenv("TOMTOM_API_KEY")
    if not key:
        return None
    url = (f"https://api.tomtom.com/routing/1/calculateRoute/{a['lat']},{a['lon']}:{b['lat']},{b['lon']}/json?"
           + urllib.parse.urlencode({"key": key, "traffic": "true", "travelMode": "car"}))
    summary = _get(url)["routes"][0]["summary"]
    return {"minutes": round(summary["travelTimeInSeconds"] / 60), "miles": round(summary["lengthInMeters"] / 1609.34, 1),
            "delay": round(summary.get("trafficDelayInSeconds", 0) / 60)}


def drive(a: dict, b: dict) -> dict | None:
    url = (f"https://router.project-osrm.org/route/v1/driving/{a['lon']},{a['lat']};{b['lon']},{b['lat']}"
           "?overview=false")
    data = _get(url)
    if data.get("code") != "Ok" or not data.get("routes"):
        return None
    r = data["routes"][0]
    return {"minutes": round(r["duration"] / 60), "miles": round(r["distance"] / 1609.34, 1)}


@tool(
    "get_my_location",
    "Get the user's current location from their phone, right now (only when a question needs it: "
    "where am I, what's near me). Waits up to 25 seconds for the phone to send it.",
)
def get_my_location(ctx):
    here = _here(ctx)
    if not here:
        return _no_location(ctx)
    try:
        place = _get("https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
            {"lat": here["lat"], "lon": here["lon"], "format": "json", "zoom": 16})).get("display_name", "")
    except Exception:  # noqa: BLE001
        place = ""
    return f"Lat {here['lat']:.5f}, lon {here['lon']:.5f} (from the {here['source']}). {place}"


@tool(
    "travel_time",
    "How long it takes to drive somewhere and how far it is, from the user's current location (fetched "
    "from their phone now) or from a starting point they name. Use for 'how long to get to X', "
    "'how far is X', 'when will I get to X'. The estimate doesn't include live traffic: say so. Then "
    "offer to start Waze, or open it if they asked for directions (open_on_phone with the waze_link).",
    {
        "destination": {"type": "string", "description": "Where they want to go (address, place or business)"},
        "origin": {"type": "string", "description": "Only if they named a starting point; otherwise their current location is used"},
    },
    ["destination"],
)
def travel_time(ctx, destination: str, origin: str = ""):
    import time as _t

    from .. import location

    waze_q = "https://waze.com/ul?" + urllib.parse.urlencode({"q": destination, "navigate": "yes"})
    rt = ctx.extras.get("runtime")
    if not origin and rt is not None and _t.time() - getattr(rt, "last_siri", 0) < 60:
        # Asked through Siri: the phone works it out with Apple Maps, which includes live traffic.
        text = location.request_eta(destination, timeout=25)
        minutes = location.parse_minutes(text) if text else None
        if minutes is not None:
            h, m = divmod(minutes, 60)
            took = f"{h} h {m} min" if h else f"{m} min"
            return (f"About {took} by car to {destination} from their current location, with current traffic "
                    f"(Apple Maps on their phone). Say it in one short sentence, e.g. 'About {took} with current "
                    f"traffic, sir.' Offer Waze; open it only if they asked for directions. waze_link: {waze_q}")
    try:
        start = geocode(origin) if origin else _here(ctx)
        if not start:
            return _no_location(ctx)
        end = geocode(destination, near=start)
        if not end:
            return f"Couldn't find '{destination}' on the map. Ask them to say it differently or give the address."
        route, traffic = None, False
        try:
            route = drive_with_traffic(start, end)
            traffic = route is not None
        except Exception as e:  # noqa: BLE001 - TomTom unreachable or over its free limit
            print(f"[travel] TomTom failed ({e}); using routing without traffic")
        route = route or drive(start, end)
    except Exception as e:  # noqa: BLE001 - map services unreachable
        return f"The map service didn't answer ({e}). Offer to open Waze instead."
    waze = "https://waze.com/ul?" + urllib.parse.urlencode({"ll": f"{end['lat']},{end['lon']}", "navigate": "yes"})
    if not route:
        return f"No driving route found to {end['name']}. Waze link: {waze}"
    h, m = divmod(route["minutes"], 60)
    took = f"{h} h {m} min" if h else f"{m} min"
    if traffic:
        delay = f", including about {route['delay']} min of traffic delay" if route.get("delay") else ""
        how = f"with current traffic (TomTom){delay}"
    else:
        how = ("WITHOUT live traffic (OpenStreetMap): say so. Through Siri the Shortcut's travel-time step "
               "gives a live-traffic ETA (/locationsetup); a free TomTom key adds traffic here too (/tomtom)")
    return (f"About {took} by car, {route['miles']} miles, to {end['name']}, {how}. From: "
            f"{'their current location' if not origin else origin}. waze_link: {waze}")
