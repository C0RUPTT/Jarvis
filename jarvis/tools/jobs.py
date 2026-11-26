"""Tools for handing heavy work to the background worker (see jarvis/jobs.py)."""

from __future__ import annotations

from . import tool


def _runner(ctx):
    runner = ctx.extras.get("jobs")
    if runner is None:
        raise RuntimeError("Background jobs aren't available in this mode.")
    return runner


@tool(
    "start_job",
    "Start a background job in a full Claude Code session with a shell, files, git and the web. "
    "Use it for anything that takes more than a few seconds or needs a computer: building apps, "
    "writing or fixing code, multi-step research, file work, installing things. Write the task as "
    "a complete brief (what to build, for whom, key features, anything the user said). Don't invent "
    "file paths: the worker builds in the user's projects folder unless the user named a location. "
    "The user is told when it finishes.",
    {
        "task": {"type": "string", "description": "Complete instructions for the worker"},
        "follow_up_of": {"type": "integer", "description": "Job number this continues, e.g. changes to an app it built"},
        "repo": {"type": "string", "description": "GitHub repository 'owner/name' when working on an existing project (from list_projects). These run as Claude Code cloud sessions the user can watch in the Claude app"},
        "quiet": {"type": "boolean", "description": "Deliver the result silently (user asked not to be disturbed)"},
    },
    ["task"],
)
def start_job(ctx, task: str, follow_up_of: int | None = None, quiet: bool = False, repo: str = ""):
    job = _runner(ctx).submit(task, continues=follow_up_of, quiet=quiet, repo=repo.strip())
    ahead = sum(1 for j in _runner(ctx).jobs.values() if j.status in {"queued", "running"} and j.id != job.id)
    return f"Job #{job.id} started" + (f" ({ahead} job(s) ahead of it in the queue)." if ahead else ".")


@tool("job_status", "List recent background jobs and how they're going, with results of finished ones.")
def job_status(ctx):
    return _runner(ctx).summary()


@tool(
    "cancel_job",
    "Cancel a queued or running background job.",
    {"job_id": {"type": "integer"}},
    ["job_id"],
)
def cancel_job(ctx, job_id: int):
    return _runner(ctx).cancel(job_id)


@tool(
    "read_job_result",
    "Read the FULL result of a background job (job_status only shows a short preview). Speak the part "
    "the user asked about or two or three key points; set send_to_phone to also send the complete "
    "text to their phone (do that when it's long or they ask for it).",
    {"job_id": {"type": "integer"}, "send_to_phone": {"type": "boolean"}},
    ["job_id"],
)
def read_job_result(ctx, job_id: int, send_to_phone: bool = False):
    job = _runner(ctx).jobs.get(job_id)
    if job is None:
        return f"There's no job {job_id}."
    if not job.result:
        return f"Job {job_id} is {job.status} and has no result yet."
    if send_to_phone:
        rt = ctx.extras.get("runtime")
        if rt is not None:
            rt.announcer.push_full(f"Job {job_id} ({job.status}):\n\n{job.result}")
    return f"Full result of job {job_id} ({job.status}){' (also sent to the phone)' if send_to_phone else ''}:\n\n{job.result}"
