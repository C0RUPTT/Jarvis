"""Talking to the user's Claude Code sessions: list them and send them messages by voice."""

from __future__ import annotations

import time

from . import tool


@tool(
    "list_claude_sessions",
    "List the user's recent Claude Code sessions (project name, how long ago, what it last said). "
    "Use when they ask about their sessions or before sending a message to one.",
)
def list_claude_sessions(ctx):
    from .. import claude_sessions

    items = claude_sessions.load(ctx.config.data_dir)
    if not items:
        return ("No sessions known yet. Sessions appear here after they finish a task (via the done "
                "hook); the user can also give a claude.ai/code session link.")
    lines = []
    for s in items[:10]:
        mins = int((time.time() - s["last_seen"]) // 60)
        ago = f"{mins} min ago" if mins < 120 else f"{mins // 60} h ago"
        lines.append(f"- {s['project'] or '?'} ({ago}), id {s['id']}: {s['last_summary'][:120]}")
    return "\n".join(lines)


@tool(
    "send_to_claude_session",
    "Send a message into one of the user's existing Claude Code sessions, as if they typed it there, "
    "to continue that work with its full history ('pick up on my Jarvis session: ...', 'tell the "
    "flight tracker session to ...'). 'session' is a project name from list_claude_sessions, a "
    "session id, or a claude.ai/code link. The user hears the result when the session finishes.",
    {
        "session": {"type": "string"},
        "message": {"type": "string", "description": "The instruction, written as the user would type it"},
    },
    ["session", "message"],
)
def send_to_claude_session(ctx, session: str, message: str):
    from .. import claude_sessions

    target = session.strip()
    if not (target.startswith(("session_", "cse_")) or "claude.ai/code" in target):
        match = claude_sessions.find(ctx.config.data_dir, target)
        if not match:
            return f"I don't know a session for '{session}' yet. Ask the user for its link, or list_claude_sessions."
        target = match["id"]
    error = claude_sessions.send(target, message)
    if error:
        return f"Couldn't send it: {error}"
    rt = ctx.extras.get("runtime")
    if rt is not None:
        rt.await_reply(claude_sessions.normalize(target))   # its next reply is read out, however quick
    return (f"Sent to {target}. Its reply will be read to the user when it arrives (they can ask "
            "'is it ready?'). Say so in a few words.")


@tool(
    "register_claude_session",
    "Remember a Claude Code session the user gives you by link (claude.ai/code/session_...) so you can "
    "send messages into it later. 'project' is what the user calls it, e.g. Jarvis or flight tracker.",
    {"link": {"type": "string"}, "project": {"type": "string"}},
    ["link", "project"],
)
def register_claude_session(ctx, link: str, project: str):
    from .. import claude_sessions

    sid = claude_sessions.normalize(link)
    if not sid.startswith("session_"):
        return "That doesn't look like a Claude Code session link (claude.ai/code/session_...)."
    claude_sessions.seen(ctx.config.data_dir, project, sid, "(registered by link)")
    return f"Saved: '{project}' is {sid}."
