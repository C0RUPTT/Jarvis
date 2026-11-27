"""Your Obsidian vault, synced to this server by Obsidian's official headless client
(scripts/setup-obsidian.sh, service "obsidian-sync"), so Jarvis can add to notes by voice.

Safety rules: notes are only ever appended to (never rewritten or deleted), names match case-
insensitively, an ambiguous name is never guessed, a line that's already there isn't added again,
and new notes are only created when asked."""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path


def vault() -> Path | None:
    path = Path(os.getenv("JARVIS_VAULT", str(Path.home() / "vault"))).expanduser()
    return path if path.is_dir() and any(path.iterdir()) else None


def _notes(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.md") if not any(part.startswith(".") for part in p.relative_to(root).parts)]


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def find(name: str) -> list[Path]:
    """Notes whose name matches: exact (any case) first, then 'starts with', then 'contains'."""
    root = vault()
    if root is None:
        return []
    want = _norm(re.sub(r"\.md$", "", name.strip(), flags=re.I))
    want = re.sub(r"^(my|the)\s+", "", want)
    notes = _notes(root)
    for test in (lambda n: n == want, lambda n: n.startswith(want), lambda n: want in n):
        hits = [p for p in notes if test(_norm(p.stem))]
        if hits:
            return hits
    return []


def already_there(note: Path, text: str) -> bool:
    want = _norm(text)
    return bool(want) and any(_norm(re.sub(r"^\s*([-*+]|\d+[.)])\s+(\[.\]\s+)?", "", line)) == want
                              for line in note.read_text(encoding="utf-8", errors="replace").splitlines())


def append(note: Path, text: str) -> None:
    """Add text at the end, as a list item if the note is a list. Never rewrites what's there."""
    body = note.read_text(encoding="utf-8", errors="replace")
    lines = [l for l in body.splitlines() if l.strip()]
    is_list = bool(lines) and re.match(r"^\s*([-*+]|\d+[.)])\s", lines[-1])
    entry = f"- {text.strip()}" if is_list or not lines else text.strip()
    sep = "" if body.endswith("\n") or not body else "\n"
    with note.open("a", encoding="utf-8") as f:   # append-only: existing content is never touched
        f.write(f"{sep}{entry}\n")


def create(name: str, text: str, folder: str = "") -> Path:
    root = vault()
    clean = re.sub(r'[\\/:*?"<>|]', "", name).strip()
    where = (root / folder.strip("/")) if folder else root
    where.mkdir(parents=True, exist_ok=True)
    path = where / f"{clean}.md"
    with path.open("x", encoding="utf-8") as f:   # "x": fails if it exists, so nothing is overwritten
        f.write(text.strip() + "\n")
    return path


def sync_running() -> bool:
    p = subprocess.run(["systemctl", "is-active", "obsidian-sync"], capture_output=True, text=True)
    return p.stdout.strip() == "active"


def wait_synced(note: Path, since: float, timeout: float = 20) -> bool:
    """True once the sync client has picked the change up (its log mentions the file after `since`)."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(since - 1))
    deadline = time.time() + timeout
    while time.time() < deadline:
        for cmd in (["journalctl", "-u", "obsidian-sync", "--since", stamp, "--no-pager", "-o", "cat"],
                    ["sudo", "-n", "journalctl", "-u", "obsidian-sync", "--since", stamp, "--no-pager", "-o", "cat"]):
            p = subprocess.run(cmd, capture_output=True, text=True)
            if p.returncode == 0:
                if note.name in p.stdout or note.stem in p.stdout:
                    return True
                break
        time.sleep(2)
    return False
