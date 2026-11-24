"""File system access."""

from __future__ import annotations

from pathlib import Path

from . import tool

MAX_READ_CHARS = 50_000


def _path(p: str) -> Path:
    return Path(p).expanduser()


@tool(
    "list_directory",
    "List files and folders in a directory. '~' is the user's home folder.",
    {"path": {"type": "string", "description": "Directory path, default '~'"}},
)
def list_directory(ctx, path: str = "~"):
    d = _path(path)
    entries = sorted(d.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    lines = [f"{'[dir] ' if e.is_dir() else ''}{e.name}" for e in entries[:300]]
    if len(entries) > 300:
        lines.append(f"... and {len(entries) - 300} more")
    return f"{d.resolve()}:\n" + ("\n".join(lines) or "(empty)")


@tool(
    "find_files",
    "Search for files by name pattern (glob, e.g. '*.pdf' or '*resume*') under a folder.",
    {
        "pattern": {"type": "string"},
        "folder": {"type": "string", "description": "Where to search, default '~'"},
    },
    ["pattern"],
)
def find_files(ctx, pattern: str, folder: str = "~"):
    results = []
    for p in _path(folder).rglob(pattern):
        if any(part.startswith(".") for part in p.parts[-4:]):
            continue  # skip hidden folders like .git, .cache
        results.append(str(p))
        if len(results) >= 50:
            break
    return "\n".join(results) or "No matches."


@tool(
    "read_file",
    "Read a text file and return its contents.",
    {"path": {"type": "string"}},
    ["path"],
)
def read_file(ctx, path: str):
    text = _path(path).read_text(errors="replace")
    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + "\n...[truncated]"
    return text


@tool(
    "write_file",
    "Create or overwrite a text file (notes, scripts, documents). The user confirms first.",
    {
        "path": {"type": "string"},
        "content": {"type": "string"},
        "append": {"type": "boolean", "description": "Append instead of overwrite"},
    },
    ["path", "content"],
    dangerous=True,
)
def write_file(ctx, path: str, content: str, append: bool = False):
    p = _path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a" if append else "w") as f:
        f.write(content)
    return f"Wrote {len(content)} characters to {p}."
