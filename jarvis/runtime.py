"""Builds a running Jarvis: brain, background jobs, notifications and Telegram, wired together.
Shared by every mode (phone server, terminal, laptop voice)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import metrics
from .announcer import Announcer
from .brain import make_brain
from .config import Config
from .tools import Context


@dataclass
class Runtime:
    config: Config
    announcer: Announcer
    ctx: Context
    brain: object
    jobs: object | None
    telegram: object | None
    _whisper: object | None = None

    def transcribe(self, audio) -> str:
        if self._whisper is None:
            from .voice.listener import Transcriber

            self._whisper = Transcriber(self.config.whisper_model)
        return self._whisper.transcribe(audio)

    def ask(self, text: str) -> str:
        """Everything the user says goes through here: fast path first, then Claude."""
        from . import fastpath

        started = time.monotonic()
        # Talking to Jarvis after 4am ends night mode; mention anything that came in overnight.
        woke = datetime.now().hour >= 4 and self.announcer.wake()
        reply = fastpath.handle(text, self)
        if reply is not None:
            metrics.record("fast", time.monotonic() - started)
        else:
            reply = self.brain.ask(text)
        held = self.announcer.peek_held()
        if woke and held:
            reply += f" Also, good morning: {held} thing{'s' if held != 1 else ''} came in overnight. Ask me what you missed."
        return reply

    def morning(self) -> str:
        """'Good morning, Jarvis' (or the wake-up automation): ends night mode and gives the rundown:
        what came in overnight, background jobs, and today's calendar."""
        self.announcer.wake()
        parts = [f"Good morning, {self.config.user_name}."]
        held = self.announcer.take_held()
        parts.append(("Overnight: " + " ".join(held)) if held else "Nothing came in overnight.")
        parts.append(self._today_calendar())
        from . import fastpath

        running = fastpath._running_jobs(self)
        if running:
            parts.append(running)
        return " ".join(p for p in parts if p)

    def _today_calendar(self) -> str:
        import os

        if not os.getenv("JARVIS_ICLOUD_USER"):
            return ""
        try:
            from .tools.calendar import calendar_events

            events = calendar_events(self.ctx)
        except Exception as e:  # noqa: BLE001 - the rundown should never fail because of the calendar
            return f"I couldn't reach your calendar ({e})."
        if events.startswith("Nothing"):
            return "Your calendar is clear today."
        lines = events.splitlines()[1:]
        items = "; ".join(line.split(": ", 1)[-1].split(" [")[0] if ": " in line else line for line in lines[:5])
        times = [line.split(": ", 1)[0].split(" ")[-1] for line in lines[:5]]
        def say_time(t: str) -> str:
            start = t.split("-")[0]                 # "14:30-15:00" -> "2:30 PM"
            try:
                hour, minute = (int(x) for x in start.split(":"))
            except ValueError:
                return start
            suffix = "AM" if hour < 12 else "PM"
            hour = hour % 12 or 12
            return f"{hour} {suffix}" if minute == 0 else f"{hour}:{minute:02d} {suffix}"

        spoken = "; ".join(
            (f"{say_time(t)} {i}" if t[:1].isdigit() else i).replace(" @ ", " at ")
            for t, i in zip(times, items.split("; "))
        )
        more = f", and {len(lines) - 5} more" if len(lines) > 5 else ""
        return f"Today you have {len(lines)} thing{'s' if len(lines) != 1 else ''}: {spoken}{more}."

    def close(self) -> None:
        self.brain.close()


def build(config: Config, speak: Callable[[str], None] | None = None,
          on_interim: Callable[[str], None] | None = None,
          confirm: Callable[[str], bool] | None = None,
          telegram: bool = True) -> Runtime:
    metrics.init(config.data_dir)
    announcer = Announcer(config.ntfy_topic, speak=speak, state_file=config.data_dir / "delivery.json",
                          quiet_start=config.quiet_start)
    ctx = Context(
        config=config,
        # Unattended by default: risky actions in the API brain are refused unless a confirm
        # callback is given. The Claude Code brain uses Claude Code's own permission mode.
        confirm=confirm or (lambda question: False),
        announce=announcer.announce,
        extras={"announcer": announcer},
    )

    jobs = None
    if config.brain == "claude-code":
        from .jobs import JobRunner

        def job_finished(job):
            verb = {"done": "is done", "failed": "hit a problem"}.get(job.status, job.status)
            announcer.announce(f"Job {job.id} {verb}. {job.result}", quiet=job.quiet)

        jobs = JobRunner(config.data_dir, config.projects_dir, config.worker_model,
                         config.cc_permission_mode, on_finished=job_finished)
        ctx.extras["jobs"] = jobs

    brain = make_brain(ctx, on_interim)
    rt = Runtime(config=config, announcer=announcer, ctx=ctx, brain=brain, jobs=jobs, telegram=None)

    if telegram and config.telegram_token and config.telegram_user_id:
        from .telegram import TelegramBot
        from .voice.tts import synthesize_mp3

        bot = TelegramBot(config.telegram_token, int(config.telegram_user_id))
        bot.on_text = rt.ask
        bot.transcribe = rt.transcribe
        bot.synthesize = lambda text: synthesize_mp3(text, config.online_voice)
        from . import admin

        bot.commands = {
            **admin.commands(config, jobs),
            "jobs": lambda: jobs.summary() if jobs else "No background jobs in this mode.",
            "stats": lambda: metrics.report(config.data_dir),
            "reset": lambda: (brain.reset(), "New conversation started.")[1],
            "quiet": lambda: announcer.set_mode("quiet"),
            "hold": lambda: announcer.set_mode("hold"),
            "normal": lambda: announcer.set_mode("normal"),
        }
        if os.getenv("JARVIS_AUTO_UPDATE", "1") != "0" and (Path(__file__).parent.parent / ".git").exists():
            admin.auto_update_loop(rt)
        try:
            print(f"[telegram] connected as @{bot.check()}")
            announcer.telegram = bot
            bot.start()
            rt.telegram = bot
        except RuntimeError as e:
            print(f"[telegram] not started: {e}")
    return rt
