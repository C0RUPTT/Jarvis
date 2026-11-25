"""Cloud coding handoff: run coding jobs for GitHub projects as Claude Code cloud sessions
(Anthropic's machines; visible in the Claude app's Code tab) instead of on this small server.

- launch(): `claude --cloud "<task>"` from a clone of the repo. It needs a terminal, so it runs in
  a pseudo-terminal and answers Claude Code's one-time first-run screens. Returns the session URL.
- follow_up(): `claude -p "<message>" --cloud <session id>` (documented, non-interactive).
- find_done(): the session marks its last commit "jarvis-done: [job N] <summary>"; we watch
  GitHub's branches for it, since there is no CLI command for a cloud session's status.
"""

from __future__ import annotations

import json
import os
import pty
import re
import select
import shutil
import subprocess
import time
import urllib.request

from . import github

SESSION_URL = re.compile(rb"https://claude\.ai/code/(session_[A-Za-z0-9]+)")
ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]|\x1b[=>]")

DONE_INSTRUCTIONS = """

---
Instructions from Jarvis (the user's voice assistant, which started this session):
- Work autonomously; the user is not watching. Commit as you go and push your work.
- When you are completely finished, make one final commit whose message starts exactly with
  "jarvis-done: [job {job_id}]" followed by two or three plain sentences saying what you did and
  how to try it, and push it. Jarvis watches for that commit to tell the user you're done."""


def enabled() -> bool:
    return os.getenv("JARVIS_CLOUD_JOBS", "1") != "0" and bool(shutil.which("claude")) and bool(github.token())


def prepare_repo(repo: str, projects_dir) -> tuple[str, str]:
    """Clone or update a GitHub repo locally. Returns (path, error)."""
    path = projects_dir / repo.split("/")[-1]
    if (path / ".git").exists():
        subprocess.run(["git", "pull", "-q", "--ff-only"], cwd=path, capture_output=True, timeout=300)
        return str(path), ""
    projects_dir.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(["git", "clone", "-q", f"https://github.com/{repo}.git", str(path)],
                       capture_output=True, text=True, timeout=600)
    return (str(path), "") if p.returncode == 0 else ("", p.stderr.strip()[-300:])


def launch(task: str, job_id: int, cwd: str, timeout: float = 150) -> tuple[str, str]:
    """Start a cloud session. Returns (session_url, error)."""
    claude = shutil.which("claude")
    prompt = task + DONE_INSTRUCTIONS.format(job_id=job_id)
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(cwd)
        os.environ.update(COLUMNS="120", LINES="40")
        os.execvp(claude, [claude, "--cloud", prompt])
    out, started, last_key = b"", time.time(), 0.0
    try:
        while time.time() - started < timeout:
            ready, _, _ = select.select([fd], [], [], 1)
            if ready:
                try:
                    chunk = os.read(fd, 8192)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
            match = SESSION_URL.search(out)
            if match:
                return match.group(0).decode(), ""
            text = ANSI.sub(b"", out[-4000:]).decode(errors="ignore")
            flat = text.replace(" ", "")
            if re.search(r"failed|error|403|notlogged|requires", flat, re.I) and "Cloud session" in text:
                return "", text.strip().splitlines()[-1][:300]
            # One-time first-run screens: theme, security notes, trust this folder.
            if not ready and time.time() - last_key > 3 and any(
                    k in flat for k in ("Entertoconfirm", "PressEnter", "Choosethetext", "Syntaxtheme")):
                if "trustthisfolder" in flat:
                    os.write(fd, b"\x1b[B")       # move to "Yes, I trust this folder"
                    time.sleep(0.4)
                os.write(fd, b"\r")
                last_key = time.time()
        tail = ANSI.sub(b"", out[-1500:]).decode(errors="ignore").strip().splitlines()
        return "", (tail[-1] if tail else "no output")[:300]
    finally:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def follow_up(session_url: str, message: str, job_id: int, cwd: str) -> str:
    """Send a follow-up into an existing cloud session. Returns an error or ""."""
    session = session_url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    p = subprocess.run([shutil.which("claude") or "claude", "-p", message + DONE_INSTRUCTIONS.format(job_id=job_id),
                        "--cloud", session, "--output-format", "json"],
                       cwd=cwd, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    try:
        result = json.loads(p.stdout.strip().splitlines()[-1])
        return "" if result.get("ok") else str(result.get("error") or "unknown error")
    except (ValueError, IndexError):
        return (p.stderr or p.stdout).strip()[-300:] or "no response"


def find_done(repo: str, job_id: int) -> tuple[str, str] | None:
    """Look for the 'jarvis-done: [job N]' commit on any branch. Returns (branch, summary)."""
    tok = github.token()
    headers = {"Authorization": f"Bearer {tok}", "User-Agent": "jarvis-assistant",
               "Accept": "application/vnd.github+json"}
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/branches?per_page=100", headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        branches = json.load(resp)
    marker = f"jarvis-done: [job {job_id}]"
    for b in branches:
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/commits/{b['commit']['sha']}",
                                     headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            message = json.load(resp)["commit"]["message"]
        if message.startswith(marker):
            return b["name"], message[len(marker):].strip()
    return None


def checkout_branch(path: str, branch: str) -> None:
    subprocess.run(["git", "fetch", "-q", "origin", branch], cwd=path, capture_output=True, timeout=300)
    subprocess.run(["git", "checkout", "-q", "-B", branch, f"origin/{branch}"], cwd=path,
                   capture_output=True, timeout=120)
