"""Self-improvement: "let's fix that gap" sends a precise change request to the Jarvis development
session (the Claude Code session that builds Jarvis), or starts a coding job on the Jarvis repo.
The finished change is pushed to the branch this server runs, and Jarvis's auto-updater installs it
(after its startup self-test, with automatic rollback if anything breaks)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import tool

ROOT = Path(__file__).resolve().parent.parent.parent


def _branch() -> str:
    explicit = os.getenv("JARVIS_SELF_BRANCH")
    if explicit:
        return explicit
    p = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return p.stdout.strip() or "main"


def _repo() -> str:
    explicit = os.getenv("JARVIS_REPO")
    if explicit:
        return explicit
    p = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True)
    url = p.stdout.strip().removesuffix(".git")
    return "/".join(url.split("/")[-2:]) if "github.com" in url else "C0RUPTT/Jarvis"


@tool(
    "improve_jarvis",
    "Improve Jarvis itself: use when the user says 'let's fix that', 'fix that gap', 'improve yourself "
    "so...', or agrees when you offer to fix something you handled badly. Describe concretely what "
    "went wrong (quote what happened in this conversation) and exactly what should happen instead. "
    "Before calling it, read the plan back in one sentence and get a yes.",
    {
        "problem": {"type": "string", "description": "What went wrong or is missing, with specifics"},
        "desired": {"type": "string", "description": "What Jarvis should do instead"},
    },
    ["problem", "desired"],
)
def improve_jarvis(ctx, problem: str, desired: str):
    from .. import claude_sessions

    branch, repo = _branch(), _repo()
    request = (
        "Jarvis improvement request from the user, sent by voice through Jarvis.\n\n"
        f"What went wrong: {problem}\n\nWhat should happen instead: {desired}\n\n"
        f"Please implement this in the Jarvis repo ({repo}), run `python -m jarvis.selftest` plus a "
        f"focused test of the change, then commit and push to the branch the server runs: {branch}. "
        "The server installs it automatically within about 15 minutes (it rolls back if the self-test "
        "fails). If the user needs to do anything on their phone, say so. Finish with a two-sentence "
        "summary written to be read aloud."
    )
    dev = claude_sessions.find(ctx.config.data_dir, "Jarvis")
    if dev:
        error = claude_sessions.send(dev["id"], request)
        if not error:
            rt = ctx.extras.get("runtime")
            if rt is not None:
                rt.await_reply(dev["id"])
            return "Sent to the Jarvis development session; its reply will be read out when it's done."
    jobs = ctx.extras.get("jobs")
    if jobs is None:
        return "I couldn't reach the Jarvis session, and background jobs aren't available here."
    job = jobs.submit(request, repo=repo)
    return f"Started job {job.id} on {repo} to make the change; you'll hear when it's done."
