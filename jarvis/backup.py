"""Nightly backup of Jarvis's memory, reminders, watchers, jobs and the projects it built, to a
private GitHub repository (default: <you>/jarvis-backup). Keys and passwords are never backed up.

/backup runs it now; /restore copies it back onto a fresh server (after the installer)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from . import github

DATA_FILES = ("memory.json", "reminders.json", "watchers.json", "delivery.json", "jobs.json",
              "metrics.jsonl")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", ".cache", "target"}
SKIP_NAMES = {".env", ".env.local", ".git-credentials"}
MAX_FILE = 20 * 1024 * 1024


def _repo_name() -> str:
    explicit = os.getenv("JARVIS_BACKUP_REPO", "")
    if explicit:
        return explicit
    return f"{github.whoami(github.token())}/jarvis-backup"


def _git(*args, cwd: Path) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=600)
    return p.returncode, (p.stdout + p.stderr).strip()


def _ensure_repo(name: str) -> str:
    """Create the private backup repo if possible. Returns "" if it exists or was created."""
    tok = github.token()
    req = urllib.request.Request(f"https://api.github.com/repos/{name}", headers={
        "Authorization": f"Bearer {tok}", "User-Agent": "jarvis-assistant"})
    try:
        urllib.request.urlopen(req, timeout=20).close()
        return ""
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return f"couldn't check the backup repository ({e.code})"
    data = json.dumps({"name": name.split("/")[1], "private": True, "auto_init": True,
                       "description": "Jarvis backups (private)"}).encode()
    req = urllib.request.Request("https://api.github.com/user/repos", data=data, method="POST", headers={
        "Authorization": f"Bearer {tok}", "User-Agent": "jarvis-assistant", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=20).close()
        time.sleep(3)
        return ""
    except urllib.error.HTTPError:
        return (f"the repository {name} doesn't exist and my GitHub key can't create it. Create it "
                "yourself on github.com/new (name: jarvis-backup, Private), then send /backup again")


def _copy_tree(src: Path, dst: Path) -> None:
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        if any(part in SKIP_DIRS for part in rel.parts) or path.name in SKIP_NAMES:
            continue
        if path.is_file() and path.stat().st_size <= MAX_FILE:
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def backup_now(config) -> str:
    if not github.token():
        return "Backups need GitHub connected (/github)."
    try:
        name = _repo_name()
    except Exception as e:  # noqa: BLE001
        return f"Backup failed: couldn't reach GitHub ({e})."
    problem = _ensure_repo(name)
    if problem:
        return f"Backup skipped: {problem}."
    work = config.data_dir / "backup-repo"
    if (work / ".git").exists():
        _git("pull", "-q", "--ff-only", cwd=work)
    else:
        if work.exists():
            shutil.rmtree(work)
        code, out = _git("clone", "-q", f"https://github.com/{name}.git", str(work), cwd=config.data_dir)
        if code != 0:
            return f"Backup failed while cloning {name}: {out[-300:]}"
    for folder in ("data", "projects"):
        shutil.rmtree(work / folder, ignore_errors=True)
    (work / "data").mkdir()
    for fname in DATA_FILES:
        if (config.data_dir / fname).exists():
            shutil.copy2(config.data_dir / fname, work / "data" / fname)
    if config.projects_dir.exists():
        _copy_tree(config.projects_dir, work / "projects")
    (work / "README.md").write_text(
        "# Jarvis backup\n\nWritten automatically every night. Restore on a new server with /restore "
        "in Telegram after running the installer. Keys and passwords are not included.\n")
    _git("add", "-A", cwd=work)
    code, out = _git("commit", "-q", "-m", f"Backup {datetime.now():%Y-%m-%d %H:%M}", cwd=work)
    if code != 0 and "nothing to commit" in out:
        return "Backup is up to date; nothing changed since the last one."
    code, out = _git("push", "-q", cwd=work)
    if code != 0:
        return f"Backup failed while pushing: {out[-300:]}"
    return f"Backed up to {name} (private)."


def restore(config) -> str:
    work = config.data_dir / "backup-repo"
    if not github.token():
        return "Connect GitHub first (/github), then /restore."
    try:
        name = _repo_name()
    except Exception as e:  # noqa: BLE001
        return f"Couldn't reach GitHub ({e})."
    if work.exists():
        shutil.rmtree(work)
    code, out = _git("clone", "-q", f"https://github.com/{name}.git", str(work), cwd=config.data_dir)
    if code != 0:
        return f"Couldn't download the backup from {name}: {out[-300:]}"
    restored = 0
    for f in (work / "data").glob("*"):
        shutil.copy2(f, config.data_dir / f.name)
        restored += 1
    if (work / "projects").exists():
        _copy_tree(work / "projects", config.projects_dir)
    from . import admin

    admin._restart_soon()
    return f"Restored {restored} data files and your projects from {name}. Restarting to load them."


def start_nightly(config, announce) -> None:
    """Back up once a night (around 4:30 local time) when GitHub is connected."""
    def loop():
        last_day = None
        while True:
            now = datetime.now()
            if now.hour == 4 and now.minute >= 30 and last_day != now.date() and github.token():
                last_day = now.date()
                result = backup_now(config)
                if not (result.startswith("Backed up") or result.startswith("Backup is up to date")):
                    announce(f"Nightly backup problem: {result}")
            time.sleep(120)

    threading.Thread(target=loop, daemon=True, name="jarvis-backup").start()
