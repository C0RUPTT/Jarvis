"""Obsidian notes by voice ("add this to App Ideas"). See jarvis/notes.py for the safety rules."""

from __future__ import annotations

import time

from . import tool

NOT_SET_UP = ("Obsidian isn't connected to Jarvis yet. Tell the user it needs a one-time setup on the "
              "server: send /obsidian in Telegram for the steps. Don't open an obsidian:// link instead.")


def _pick(name: str):
    from .. import notes

    hits = notes.find(name)
    if not hits:
        return None, (f"No note called '{name}' in the vault. Ask whether to create it (create_note) or "
                      "which existing note they meant. Don't create it without a yes.")
    if len(hits) > 1:
        names = ", ".join(str(h.relative_to(notes.vault()))[:-3] for h in hits[:6])
        return None, f"Several notes match '{name}': {names}. Ask which one; don't guess."
    return hits[0], ""


@tool(
    "add_to_note",
    "Add a line to an existing Obsidian note, e.g. 'add better Jarvis voice to App Ideas'. Appends only "
    "(never changes what's there), skips it if the same line is already in the note, and confirms once "
    "Obsidian Sync has it. For new notes use create_note, only when asked.",
    {"note": {"type": "string", "description": "Note name as the user said it, e.g. 'app ideas'"},
     "text": {"type": "string", "description": "What to add, as one short line or sentence"}},
    ["note", "text"],
)
def add_to_note(ctx, note: str, text: str):
    from .. import notes

    if notes.vault() is None:
        return NOT_SET_UP
    path, problem = _pick(note)
    if problem:
        return problem
    if notes.already_there(path, text):
        return f"'{text}' is already in {path.stem}; nothing added. Say so."
    started = time.time()
    notes.append(path, text)
    if not notes.sync_running():
        return (f"Added to {path.stem} on the server, but the Obsidian sync service isn't running, so it "
                "won't reach their devices yet. Say so; /obsidian has the fix.")
    if notes.wait_synced(path, started):
        return f"Added to {path.stem}, and Obsidian Sync has sent it. Confirm in a few words."
    return (f"Added to {path.stem}; the sync service is running but hadn't reported sending it after 20 "
            "seconds. Say it's added and should appear in Obsidian shortly.")


@tool(
    "read_note",
    "Read an Obsidian note (e.g. 'what's in my app ideas?'). Summarise for voice; send long ones to the "
    "phone if asked.",
    {"note": {"type": "string"}},
    ["note"],
)
def read_note(ctx, note: str):
    from .. import notes

    if notes.vault() is None:
        return NOT_SET_UP
    path, problem = _pick(note)
    if problem:
        return problem
    return f"{path.stem}:\n" + path.read_text(encoding="utf-8", errors="replace")[:8000]


@tool(
    "find_notes",
    "Find Obsidian notes by name (e.g. 'which notes do I have about projects?').",
    {"name": {"type": "string"}},
    ["name"],
)
def find_notes(ctx, name: str):
    from .. import notes

    root = notes.vault()
    if root is None:
        return NOT_SET_UP
    hits = notes.find(name)
    return "\n".join(str(h.relative_to(root))[:-3] for h in hits[:15]) or f"No notes matching '{name}'."


@tool(
    "create_note",
    "Create a NEW Obsidian note. Only when the user asked for a new note (never as a fallback without "
    "asking). Fails rather than overwrite if one with that name exists.",
    {"name": {"type": "string"}, "text": {"type": "string"},
     "folder": {"type": "string", "description": "Optional folder inside the vault"}},
    ["name", "text"],
)
def create_note(ctx, name: str, text: str, folder: str = ""):
    from .. import notes

    if notes.vault() is None:
        return NOT_SET_UP
    if notes.find(name) and any(n.stem.lower() == name.strip().lower() for n in notes.find(name)):
        return f"A note called '{name}' already exists; add to it with add_to_note instead."
    started = time.time()
    try:
        path = notes.create(name, text, folder)
    except FileExistsError:
        return f"A note called '{name}' already exists there; nothing was changed."
    synced = notes.sync_running() and notes.wait_synced(path, started)
    return f"Created note '{path.stem}'" + (", and Obsidian Sync has sent it." if synced else " on the server; it should sync shortly.")
