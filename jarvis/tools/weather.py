"""Weather from Open-Meteo (free, no API key needed)."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from . import tool

WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "heavy freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "rain showers", 81: "heavy rain showers", 82: "violent rain showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm with hail",
}


def _get(url: str, params: dict) -> dict:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(full, timeout=10) as resp:
        return json.load(resp)


@tool(
    "get_weather",
    "Get current weather and a 3-day forecast for a city.",
    {
        "city": {"type": "string", "description": "City name, e.g. 'London' or 'Austin'"},
        "fahrenheit": {"type": "boolean", "description": "Use Fahrenheit/mph instead of Celsius/kmh"},
    },
    ["city"],
)
def get_weather(ctx, city: str, fahrenheit: bool = False):
    geo = _get("https://geocoding-api.open-meteo.com/v1/search", {"name": city, "count": 1})
    if not geo.get("results"):
        return f"Couldn't find a place called {city}."
    place = geo["results"][0]

    params = {
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto",
        "forecast_days": 3,
    }
    if fahrenheit:
        params |= {"temperature_unit": "fahrenheit", "wind_speed_unit": "mph"}
    data = _get("https://api.open-meteo.com/v1/forecast", params)

    unit = "°F" if fahrenheit else "°C"
    c = data["current"]
    lines = [
        f"{place['name']}, {place.get('country', '')}: {WEATHER_CODES.get(c['weather_code'], 'unknown')}, "
        f"{c['temperature_2m']}{unit} (feels like {c['apparent_temperature']}{unit}), "
        f"humidity {c['relative_humidity_2m']}%, wind {c['wind_speed_10m']} {'mph' if fahrenheit else 'km/h'}."
    ]
    d = data["daily"]
    for i, day in enumerate(d["time"]):
        lines.append(
            f"{day}: {WEATHER_CODES.get(d['weather_code'][i], 'unknown')}, "
            f"{d['temperature_2m_min'][i]}-{d['temperature_2m_max'][i]}{unit}, "
            f"{d['precipitation_probability_max'][i]}% chance of rain"
        )
    return "\n".join(lines)
