"""Background jobs: heavy work (building apps, coding, long research) runs in a full Claude Code
session while the conversation stays quick. One job runs at a time to protect your usage limits;
others wait in a queue. When a job finishes, Jarvis tells you (see announcer.py)."""

from __future__ import annotations

import itertools
import json
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

    def describe(self) -> str:
        age = int(time.time() - (self.started or self.created))
        line = f"#{self.id} [{self.status}] {self.task[:120]}"
        if self.status == "running":
            line += f" (running {age // 60}m {age % 60}s)"
        if self.result and self.status in {"done", "failed"}:
            line += f"\n   result: {self.result[:400]}"
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
        self.state_file = data_dir / "jobs.json"
        self.jobs: dict[int, Job] = self._load()
        self._ids = itertools.count(max(self.jobs, default=0) + 1)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._current: subprocess.Popen | None = None
        for job in self.jobs.values():           # jobs interrupted by a restart go back in the queue
            if job.status == "running":
                job.status = "queued"
        threading.Thread(target=self._loop, daemon=True, name="jarvis-jobs").start()

    # -- public API (used by tools) -------------------------------------------

    def submit(self, task: str, continues: int | None = None, quiet: bool = False) -> Job:
        with self._lock:
            job = Job(id=next(self._ids), task=task, continues=continues, quiet=quiet)
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

        cmd = [
            self.claude or "claude", "-p", job.task,
            "--output-format", "json",
            "--model", self.model,
            "--permission-mode", self.permission_mode,
            "--append-system-prompt", WORKER_INSTRUCTIONS,
        ]
        previous = self.jobs.get(job.continues) if job.continues else None
        if previous and previous.session_id:
            cmd += ["--resume", previous.session_id]   # follow-up: same conversation, same project

        output = ""
        try:
            self._current = subprocess.Popen(
                cmd, cwd=self.workdir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            )
            output, _ = self._current.communicate(timeout=3 * 3600)
        except subprocess.TimeoutExpired:
            self._current.kill()
            output = '{"is_error": true, "result": "The job ran over three hours, so I stopped it."}'
        except FileNotFoundError:
            output = '{"is_error": true, "result": "Claude Code is not installed on the server."}'
        finally:
            self._current = None

        result = _parse_result(output)
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
