"""GitHub access, so Jarvis can open, work on and save your existing projects.

The key (a fine-grained personal access token) is stored in .env as JARVIS_GITHUB_TOKEN. Set it
by sending `/github <token>` to your bot; the message is deleted straight away.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path

API = "https://api.github.com"


def token() -> str:
    return os.getenv("JARVIS_GITHUB_TOKEN", "").strip()


def _api(path: str, tok: str):
    req = urllib.request.Request(f"{API}{path}", headers={
        "Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "jarvis-assistant",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def whoami(tok: str) -> str:
    return _api("/user", tok)["login"]


def list_repos(tok: str | None = None) -> list[dict]:
    tok = tok or token()
    if not tok:
        return []
    repos = _api("/user/repos?per_page=100&sort=pushed&affiliation=owner,collaborator", tok)
    return [{"name": r["full_name"], "private": r["private"], "pushed": r.get("pushed_at", "")[:10],
             "description": r.get("description") or ""} for r in repos]


def configure_git(tok: str | None = None) -> None:
    """Let git (and the coding worker) use the token for github.com, and the gh CLI if installed."""
    tok = tok or token()
    if not tok:
        return
    os.environ["GH_TOKEN"] = tok              # inherited by Claude Code jobs (gh CLI, API calls)
    os.environ["GITHUB_TOKEN"] = tok
    creds = Path.home() / ".git-credentials"
    line = f"https://x-access-token:{tok}@github.com"
    lines = [l for l in (creds.read_text().splitlines() if creds.exists() else []) if "@github.com" not in l]
    creds.write_text("\n".join(lines + [line]) + "\n")
    creds.chmod(0o600)
    run = lambda *a: subprocess.run(["git", "config", "--global", *a], capture_output=True)  # noqa: E731
    run("credential.helper", "store")
    if subprocess.run(["git", "config", "--global", "user.name"], capture_output=True).returncode != 0:
        run("user.name", "Jarvis")
        run("user.email", "jarvis@users.noreply.github.com")


def save_token(tok: str, env_file: Path) -> str:
    """Validate and store the token. Returns a message for the user."""
    tok = tok.strip()
    try:
        login = whoami(tok)
        count = len(list_repos(tok))
    except Exception as e:  # noqa: BLE001
        return f"That GitHub key didn't work ({e}). Check it was copied completely."
    lines = [l for l in (env_file.read_text().splitlines() if env_file.exists() else [])
             if not l.startswith("JARVIS_GITHUB_TOKEN=")]
    env_file.write_text("\n".join(lines + [f"JARVIS_GITHUB_TOKEN={tok}"]) + "\n")
    os.environ["JARVIS_GITHUB_TOKEN"] = tok
    configure_git(tok)
    # Optional: the GitHub CLI makes pull requests easier for the worker.
    subprocess.Popen(["sudo", "-n", "apt-get", "install", "-y", "-qq", "gh"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return (f"Connected to GitHub as {login}; I can see {count} repositories. I deleted your message "
            f"so the key isn't left in this chat. Try: 'open my flight tracker project'.")
