"""Long-term memory: facts about the user that persist between sessions."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import tool


def _file(ctx) -> Path:
    return ctx.config.data_dir / "memory.json"


def load_facts(data_dir: Path) -> list[dict]:
    path = data_dir / "memory.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return []


def _save(ctx, facts: list[dict]) -> None:
    _file(ctx).write_text(json.dumps(facts, indent=2))


@tool(
    "remember",
    "Save a fact about the user to long-term memory (preferences, people, projects, "
    "routines). Use whenever the user tells you something worth knowing next time.",
    {"fact": {"type": "string"}},
    ["fact"],
)
def remember(ctx, fact: str):
    facts = load_facts(ctx.config.data_dir)
    new_id = max((f["id"] for f in facts), default=0) + 1
    facts.append({"id": new_id, "fact": fact, "added": date.today().isoformat()})
    _save(ctx, facts)
    return f"Remembered (#{new_id})."


@tool(
    "recall",
    "Search long-term memory. Leave query empty to list everything.",
    {"query": {"type": "string"}},
)
def recall(ctx, query: str = ""):
    facts = load_facts(ctx.config.data_dir)
    words = query.lower().split()
    hits = [f for f in facts if all(w in f["fact"].lower() for w in words)]
    return "\n".join(f"#{f['id']}: {f['fact']}" for f in hits) or "Nothing found."


@tool(
    "forget",
    "Delete a fact from long-term memory by its number.",
    {"fact_id": {"type": "integer"}},
    ["fact_id"],
)
def forget(ctx, fact_id: int):
    facts = load_facts(ctx.config.data_dir)
    kept = [f for f in facts if f["id"] != fact_id]
    if len(kept) == len(facts):
        return f"No memory #{fact_id}."
    _save(ctx, kept)
    return f"Forgot #{fact_id}."
