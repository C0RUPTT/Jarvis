"""Named places for navigation ("take me to Sam")."""

from __future__ import annotations

from . import tool


@tool(
    "save_place",
    "Remember a named place for navigation, e.g. name 'Sam' with Sam's address, or 'the gym'. Use when "
    "the user tells you an address to keep, or after asking for one when 'take me to <name>' didn't match.",
    {"name": {"type": "string"}, "address": {"type": "string", "description": "Full street address or place"}},
    ["name", "address"],
)
def save_place(ctx, name: str, address: str):
    from .. import places

    places.save(ctx.config.data_dir, name, address)
    return f"Saved: '{name}' is {address}. 'Take me to {name}' now opens Waze straight there."


@tool("list_places", "List the user's saved named places (Home and Work come from Waze itself).")
def list_places(ctx):
    from .. import places

    items = places.load(ctx.config.data_dir)
    if not items:
        return "No saved places yet (Home and Work use Waze's own favorites)."
    return "\n".join(f"- {p['name']}: {p['address']}" for p in items.values())


@tool("forget_place", "Forget a saved named place.", {"name": {"type": "string"}}, ["name"])
def forget_place(ctx, name: str):
    from .. import places

    return "Forgotten." if places.forget(ctx.config.data_dir, name) else f"I had no place called {name}."
