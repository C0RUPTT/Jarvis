"""Background jobs: heavy work (building apps, coding, long research) runs in a full Claude Code
session while the conversation stays quick. One job runs at a time to protect your usage limits;
others wait in a queue. When a job finishes, Jarvis tells you (see announcer.py)."""

from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import metrics

WORKER_INSTRUCTIONS = """You are the background worker for Jarvis, a voice assistant. The user asked \
for this by voice and is not watching you work, so work autonomously and make sensible decisions \
yourself. Unless told otherwise, put each new project in its own folder inside the current \
directory, use git, and commit your work as you go. Test what you build before finishing.

Existing GitHub projects: if the brief names a GitHub repository (owner/name), work in a folder \
of that name inside the current directory: clone it with git if it isn't there yet, otherwise pull \
the latest. GitHub access is already configured for git (and the gh CLI if installed). Commit your \
changes and push them to a new branch named jarvis/<short-topic>, unless the brief says to push to \
the main branch. Say which branch you pushed in your summary.

When you are done, end with a short summary written to be read aloud: two or three plain \
sentences, no markdown, saying what you did, where it is, and how to try it."""


@dataclass
class Job:
    id: int
    task: str
    status: str = "queued"          # queued | running | done | failed | cancelled
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    result: str = ""
    session_id: str | None = None
    continues: int | None = None    # id of the job this one follows up on
    quiet: bool = False             # deliver silently
    activity: list = field(default_factory=list)   # live log of what the worker is doing (dashboard)
    preview: str = ""                               # path of a web page it built, under /preview/
    repo: str = ""                                  # GitHub "owner/name" this job works on
    cloud_url: str = ""                             # Claude Code cloud session, if it runs there
    branch: str = ""                                # branch the cloud session finished on
    path: str = ""                                  # local folder of the repo, if any
    workspace: bool = False                         # runs in the private jarvis-workspace repo (no project)

    def describe(self) -> str:
        age = int(time.time() - (self.started or self.created))
        line = f"#{self.id} [{self.status}] {self.task[:120]}"
        if self.status == "running":
            line += f" (running {age // 60}m {age % 60}s)"
        if self.result and self.status in {"done", "failed"}:
            more = " [preview: read_job_result gives the full result]" if len(self.result) > 400 else ""
            line += f"\n   result: {self.result[:400]}{more}"
        return line


class JobRunner:
    def __init__(self, data_dir: Path, workdir: Path, model: str, permission_mode: str,
                 on_finished: Callable[[Job], None]):
        self.claude = shutil.which("claude")
        self.workdir = workdir
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.permission_mode = permission_mode
        self.on_finished = on_finished
        self.on_started_cloud: Callable[[Job], None] = lambda job: None
        self.state_file = data_dir / "jobs.json"
        self.jobs: dict[int, Job] = self._load()
        self._ids = itertools.count(max(self.jobs, default=0) + 1)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._current: subprocess.Popen | None = None
        resume_watching = []
        for job in self.jobs.values():
            if job.status != "running":
                continue
            if job.cloud_url:
                # A cloud session keeps working while Jarvis restarts (every update): just resume
                # watching for its finish signal, so you're still told when it's done. (Re-queueing
                # it used to start a second cloud session.)
                resume_watching.append(job)
            else:
                job.status = "queued"            # a job on this server died with the restart: run again
                job.activity = (job.activity + [f"{time.strftime('%H:%M:%S')}  Jarvis restarted; running it again."])[-40:]
        threading.Thread(target=self._loop, daemon=True, name="jarvis-jobs").start()
        for job in resume_watching:
            threading.Thread(target=self._watch_cloud, args=(job, job.path), daemon=True).start()

    # -- public API (used by tools) -------------------------------------------

    def submit(self, task: str, continues: int | None = None, quiet: bool = False, repo: str = "") -> Job:
        with self._lock:
            previous = self.jobs.get(continues) if continues else None
            repo = repo or (previous.repo if previous else "")
            job = Job(id=next(self._ids), task=task, continues=continues, quiet=quiet, repo=repo)
            self.jobs[job.id] = job
            self._save()
        self._wake.set()
        return job

    def cancel(self, job_id: int) -> str:
        with self._lock:
            job = self.jobs.get(job_id)
            if not job or job.status not in {"queued", "running"}:
                return f"No active job #{job_id}."
            if job.status == "running" and self._current:
                self._current.kill()
            job.status = "cancelled"
            self._save()
        return f"Cancelled job #{job_id}."

    def summary(self, limit: int = 8) -> str:
        jobs = sorted(self.jobs.values(), key=lambda j: j.id, reverse=True)[:limit]
        return "\n".join(j.describe() for j in jobs) or "No jobs yet."

    # -- internals -------------------------------------------------------------

    def _loop(self) -> None:
        while True:
            job = self._next_queued()
            if job is None:
                self._wake.wait(timeout=30)
                self._wake.clear()
                continue
            self._run(job)

    def _next_queued(self) -> Job | None:
        with self._lock:
            queued = [j for j in self.jobs.values() if j.status == "queued"]
            return min(queued, key=lambda j: j.id) if queued else None

    def _run(self, job: Job) -> None:
        with self._lock:
            job.status, job.started = "running", time.time()
            self._save()
        from . import cloud

        if not job.repo and cloud.enabled() and os.getenv("JARVIS_JOBS_IN_CLOUD", "1") != "0":
            # Not about a project: still run it in Claude Code's cloud (Anthropic's machines), in a
            # private scratch repository, so this small server stays quick for your conversations.
            ws, error = cloud.ensure_workspace()
            if ws:
                job.repo, job.workspace = ws, True
            else:
                self._note(job, f"No cloud workspace ({error}); running on this server.")
        if job.repo:
            if cloud.enabled() and self._run_cloud(job):
                return          # running in the cloud; a watcher thread finishes the job
            if not job.path:    # cloud disabled: still work inside a local clone of the repo
                job.path = cloud.prepare_repo(job.repo, self.workdir)[0]
            self._note(job, f"Working on {job.repo} on this server" + (f" in {job.path}." if job.path else "."))
            job.task += (f"\n\n(The project is the GitHub repository {job.repo}"
                         + (", already cloned in the current directory" if job.path else "") + ".)")

        cmd = [
            self.claude or "claude", "-p", job.task,
            "--output-format", "stream-json", "--verbose",   # stream so the dashboard can show progress
            "--model", self.model,
            "--permission-mode", self.permission_mode,
            "--append-system-prompt", WORKER_INSTRUCTIONS,
        ]
        previous = self.jobs.get(job.continues) if job.continues else None
        if previous and previous.session_id:
            cmd += ["--resume", previous.session_id]   # follow-up: same conversation, same project

        output, result_event = "", None
        try:
            # Background work runs at the lowest CPU and disk priority, so your conversations with
            # Jarvis stay quick while a job is busy on this small server.
            nice = ["nice", "-n", "19"] + (["ionice", "-c", "3"] if shutil.which("ionice") else []) \
                if shutil.which("nice") else []
            self._current = subprocess.Popen(
                nice + cmd, cwd=job.path or self.workdir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            )
            killer = threading.Timer(3 * 3600, self._current.kill)
            killer.start()
            try:
                for line in self._current.stdout:
                    event = _json_or_none(line)
                    if event is None:
                        output = (output + line)[-4000:]
                        continue
                    if event.get("type") == "result":
                        result_event = event
                    elif event.get("type") == "assistant":
                        self._note_activity(job, event)
                self._current.wait()
            finally:
                timed_out = not killer.is_alive() and self._current.returncode not in (0, None)
                killer.cancel()
            if timed_out and result_event is None:
                output = '{"is_error": true, "result": "The job ran over three hours, so I stopped it."}'
        except FileNotFoundError:
            output = '{"is_error": true, "result": "Claude Code is not installed on the server."}'
        finally:
            self._current = None

        result = result_event or _parse_result(output)
        job.preview = find_preview(self.workdir, since=job.started or 0)
        with self._lock:
            if job.status == "cancelled":
                return
            job.finished = time.time()
            job.session_id = result.get("session_id") or job.session_id
            job.result = (result.get("result") or "").strip() or output[-500:]
            job.status = "failed" if result.get("is_error") else "done"
            self._save()
        metrics.record("job", seconds=job.finished - job.started, usage=result.get("usage"),
                       ok=job.status == "done", job_id=job.id)
        self.on_finished(job)

    def _note(self, job: Job, line: str) -> None:
        with self._lock:
            job.activity = (job.activity + [f"{time.strftime('%H:%M:%S')}  {line}"])[-40:]
            self._save()

    def _run_cloud(self, job: Job) -> bool:
        """Start (or continue) the job as a Claude Code cloud session. False = use the local fallback."""
        from . import cloud

        path, error = cloud.prepare_repo(job.repo, self.workdir)
        job.path = path
        if error:
            self._note(job, f"Couldn't download {job.repo} ({error}); running locally.")
            return False
        previous = self.jobs.get(job.continues) if job.continues else None
        if previous and previous.cloud_url:
            error = cloud.follow_up(previous.cloud_url, job.task, job.id, path)
            job.cloud_url = previous.cloud_url
        else:
            self._note(job, "Starting a Claude Code cloud session...")
            task = job.task + (cloud.WORKSPACE_INSTRUCTIONS.format(job_id=job.id) if job.workspace else "")
            job.cloud_url, error = cloud.launch(task, job.id, path)
        if error or not job.cloud_url:
            self._note(job, f"Cloud session unavailable ({error or 'no session link'}); running on this server instead.")
            job.cloud_url = ""
            return False
        self._note(job, f"Running in the cloud: {job.cloud_url}")
        try:   # so "tell my <project> session ..." and list_claude_sessions know it right away
            from . import claude_sessions

            if not claude_sessions.name_of(self.state_file.parent, job.cloud_url):
                claude_sessions.seen(self.state_file.parent, job.repo.split("/")[-1], job.cloud_url,
                                     f"(Jarvis job #{job.id} started) {job.task[:200]}")
        except Exception:  # noqa: BLE001
            pass
        self._save()
        self.on_started_cloud(job)
        threading.Thread(target=self._watch_cloud, args=(job, path), daemon=True).start()
        return True

    def _watch_cloud(self, job: Job, path: str) -> None:
        """Poll GitHub for the session's 'jarvis-done' commit, then finish the job."""
        from . import cloud

        deadline, nudged = time.time() + 6 * 3600, False
        while time.time() < deadline and job.status == "running":
            time.sleep(60)
            try:
                found = cloud.find_done(job.repo, job.id)
            except Exception as e:  # noqa: BLE001 - GitHub hiccup; keep watching
                self._note(job, f"(couldn't check GitHub: {e})")
                continue
            if found:
                job.branch, summary = found
                cloud.checkout_branch(path, job.branch)
                with self._lock:
                    job.status, job.finished = "done", time.time()
                    job.result = f"{summary} (Branch: {job.branch})"
                    if job.workspace:   # the full answer, written by the session into the workspace
                        full = cloud.read_file(job.repo, job.branch, f"job-{job.id}/RESULT.md")
                        if full:
                            job.result = full.strip()
                    job.preview = find_preview(self.workdir, since=job.started or 0)
                    self._save()
                self.on_finished(job)
                return
            if not nudged and time.time() - (job.started or time.time()) > 45 * 60:
                nudged = True
                self._note(job, "No finish signal after 45 minutes; check the session in the Claude app.")
        if job.status == "running":
            with self._lock:
                job.status, job.finished = "failed", time.time()
                job.result = f"The cloud session didn't report back. See it in the Claude app: {job.cloud_url}"
                self._save()
            self.on_finished(job)

    def _note_activity(self, job: Job, event: dict) -> None:
        """Turn a worker message into short human-readable activity lines for the dashboard."""
        for block in (event.get("message") or {}).get("content") or []:
            if block.get("type") == "tool_use":
                args = block.get("input") or {}
                detail = (args.get("command") or args.get("file_path") or args.get("path") or args.get("query")
                          or args.get("url") or args.get("pattern") or args.get("description") or "")
                first_line = str(detail).strip().splitlines()[0] if str(detail).strip() else ""
                line = f"{block.get('name')}: {first_line[:120]}"
            elif block.get("type") == "text" and block.get("text", "").strip():
                line = "💬 " + block["text"].strip().replace("\n", " ")[:200]
            else:
                continue
            with self._lock:
                job.activity = (job.activity + [f"{time.strftime('%H:%M:%S')}  {line}"])[-40:]
                self._save()

    def _load(self) -> dict[int, Job]:
        if not self.state_file.exists():
            return {}
        try:
            return {d["id"]: Job(**d) for d in json.loads(self.state_file.read_text())}
        except (json.JSONDecodeError, TypeError):
            return {}

    def _save(self) -> None:
        recent = sorted(self.jobs.values(), key=lambda j: j.id)[-200:]
        self.state_file.write_text(json.dumps([asdict(j) for j in recent], indent=1))


PREVIEW_DIRS = ("", "dist", "build", "public", "out", "site", "docs")


def find_preview(projects: Path, since: float) -> str:
    """The most recently changed project with a web page to open, as a path like 'coinflip/' or
    'flight-tracker/dist/'. Empty if the job didn't build a viewable page."""
    best, best_time = "", since - 5
    if not projects.exists():
        return ""
    for project in projects.iterdir():
        if not project.is_dir() or project.name.startswith("."):
            continue
        for sub in PREVIEW_DIRS:
            page = project / sub / "index.html"
            if page.exists():
                changed = max((f.stat().st_mtime for f in (project / sub).rglob("*")
                               if f.is_file() and "node_modules" not in f.parts and ".git" not in f.parts),
                              default=0)
                if changed > best_time:
                    best, best_time = f"{project.name}/{sub + '/' if sub else ''}", changed
                break
    return best


def _json_or_none(line: str):
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _parse_result(output: str) -> dict:
    """The JSON result is the last JSON object Claude Code prints."""
    for line in reversed(output.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {"is_error": True, "result": output.strip()[-500:] or "The job produced no output."}
