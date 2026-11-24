"""Builds a running Jarvis: brain, background jobs, notifications and Telegram, wired together.
Shared by every mode (phone server, terminal, laptop voice)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
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
        """Called by the phone's wake-up automation (alarm stopped / Sleep Focus off)."""
        self.announcer.wake()
        held = self.announcer.take_held()
        greeting = f"Good morning, {self.config.user_name}."
        if not held:
            return greeting + " Nothing came in overnight."
        return f"{greeting} Overnight: " + " ".join(held)

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
        bot.commands = {
            "jobs": lambda: jobs.summary() if jobs else "No background jobs in this mode.",
            "stats": lambda: metrics.report(config.data_dir),
            "reset": lambda: (brain.reset(), "New conversation started.")[1],
            "quiet": lambda: announcer.set_mode("quiet"),
            "hold": lambda: announcer.set_mode("hold"),
            "normal": lambda: announcer.set_mode("normal"),
        }
        try:
            print(f"[telegram] connected as @{bot.check()}")
            announcer.telegram = bot
            bot.start()
            rt.telegram = bot
        except RuntimeError as e:
            print(f"[telegram] not started: {e}")
    return rt
