"""Builds a running Jarvis: brain, background jobs, notifications and Telegram, wired together.
Shared by every mode (phone server, terminal, laptop voice)."""

from __future__ import annotations

import os
import re
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
    claude_watch: str = "off"      # "off" | "once" | "always": announce when Claude Code finishes
    dictation: list | None = None  # long-message mode: pieces collected until the user says "done"

    def claude_code_finished(self, label: str = "", summary: str = "") -> str:
        """Called by the Claude Code hook (POST /api/notify) when a Claude Code session finishes a task."""
        if self.claude_watch == "off":
            return "ignored (not watching)"
        where = f" on {label}" if label else ""
        text = f"Claude Code is done{where}."
        if summary:
            text += f" {summary[:300]}"
        # The user explicitly asked for this, so it always gets through, with sound.
        self.announcer.announce(text, urgent=True)
        if self.claude_watch == "once":
            self.claude_watch = "off"
        return "announced"

    def transcribe(self, audio) -> str:
        if self._whisper is None:
            from .voice.listener import Transcriber

            self._whisper = Transcriber(self.config.whisper_model)
        return self._whisper.transcribe(audio)

    def ask(self, text: str) -> str:
        """Everything the user says goes through here: fast path first, then Claude."""
        from . import fastpath

        long_reply = self._long_message(text)
        if long_reply is not None:
            if not long_reply.startswith("\x00"):
                return long_reply
            text = long_reply[1:]   # the finished long message, handled as one request below

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

    _LONG_START = re.compile(r"^(ok(ay)?,? |hey jarvis,? )?(i have a long (one|message|request|question)|"
                             r"long (message|one|request)|let me explain( something)?|start dictation|"
                             r"dictation mode|this is going to be a long one)\W*$", re.I)
    _LONG_END = re.compile(r"^(ok(ay)?,? )?(done|i'?m done|that'?s it|that is (it|all)|finished|over|send it|"
                           r"go( ahead)?|end message)\W*$", re.I)
    _LONG_CANCEL = re.compile(r"^(cancel|never ?mind|forget it|scratch that)\W*$", re.I)
    _ACKS = ["Mm-hm.", "Go on.", "Got it, keep going.", "Okay.", "I'm with you.", "Carry on."]

    def _long_message(self, text: str) -> str | None:
        """Long-message mode, for Siri cutting you off at every pause. Returns a reply, None (not in
        this mode), or "\x00" + the full message once the user says "done"."""
        cleaned = text.strip()
        if self.dictation is None:
            if self._LONG_START.match(cleaned):
                self.dictation = []
                return "Go ahead. Take your time, and say done when you're finished."
            return None
        if self._LONG_CANCEL.match(cleaned):
            self.dictation = None
            return "Scrapped. What would you like instead?"
        end = self._LONG_END.match(cleaned)
        if not end:
            self.dictation.append(cleaned)
            return self._ACKS[len(self.dictation) % len(self._ACKS)]
        full, self.dictation = " ".join(self.dictation).strip(), None
        if not full:
            return "I didn't catch anything. What did you want to say?"
        return "\x00" + full

    def morning(self) -> str:
        """'Good morning, Jarvis' (or the wake-up automation): ends night mode and gives the rundown:
        what came in overnight, background jobs, and today's calendar."""
        self.announcer.wake()
        parts = [f"Good morning, {self.config.user_name}."]
        held = self.announcer.take_held()
        weather = self._weather_line()
        if weather:
            parts.append(weather)
        parts.append(("Overnight: " + " ".join(held)) if held else "Nothing came in overnight.")
        parts.append(self._today_calendar())
        parts.append(self._today_reminders())
        parts.append(self._watchers_line())
        from . import fastpath

        running = fastpath._running_jobs(self)
        if running:
            parts.append(running)
        return " ".join(p for p in parts if p)

    def _weather_line(self) -> str:
        city = os.getenv("JARVIS_CITY", "")
        if not city:
            return ""
        try:
            from .tools.weather import get_weather

            report = get_weather(self.ctx, city, fahrenheit=os.getenv("JARVIS_UNITS", "imperial") != "metric")
            today = report.splitlines()[0]
            first = report.splitlines()[1] if len(report.splitlines()) > 1 else ""
            # "Dallas, United States: partly cloudy, 61°F (feels like 59°F)..." -> spoken summary
            now = today.split(": ", 1)[-1].split(", humidity")[0]
            hi_lo = first.split(": ", 1)[-1] if first else ""
            return f"Weather: {now}. Today: {hi_lo}."
        except Exception:  # noqa: BLE001
            return ""

    def _today_reminders(self) -> str:
        try:
            from .tools.reminders import _load

            today = datetime.now().astimezone().date()
            items = [r for r in _load(self.ctx) if r.get("at") and datetime.fromisoformat(r["at"]).date() == today]
        except Exception:  # noqa: BLE001
            return ""
        if not items:
            return ""
        spoken = "; ".join(f"{datetime.fromisoformat(r['at']):%I:%M %p}".lstrip("0") + f" {r['text']}" for r in items)
        return f"Reminders today: {spoken}."

    def _watchers_line(self) -> str:
        try:
            from .tools.watchers import _load

            active = [w for w in _load(self.ctx) if w["active"]]
        except Exception:  # noqa: BLE001
            return ""
        return f"I'm still watching {len(active)} thing{'s' if len(active) != 1 else ''} for you." if active else ""

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
    from . import github

    github.configure_git()   # no-op unless JARVIS_GITHUB_TOKEN is set
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
            text = f"Job {job.id} {verb}. {job.result}"
            if job.preview:
                from . import admin

                host = admin.public_host()
                if host:
                    text += f"\nTry it: https://{host}/preview/{job.preview}"
            announcer.announce(text, quiet=job.quiet)

        jobs = JobRunner(config.data_dir, config.projects_dir, config.worker_model,
                         config.cc_permission_mode, on_finished=job_finished)
        jobs.on_started_cloud = lambda job: announcer.announce(
            f"Job {job.id} is running as a Claude Code cloud session. Watch or steer it in the Claude "
            f"app: {job.cloud_url}", quiet=True)
        ctx.extras["jobs"] = jobs

    from .tools import reminders, watchers

    reminders.start(ctx)
    watchers.start(ctx)
    from . import backup

    backup.start_nightly(config, announcer.announce)
    brain = make_brain(ctx, on_interim)
    rt = Runtime(config=config, announcer=announcer, ctx=ctx, brain=brain, jobs=jobs, telegram=None)
    if os.getenv("JARVIS_NOTIFY_LISTENER", "1") != "0":
        from . import notify_listener

        notify_listener.start(config.notify_topic, lambda label, summary: rt.claude_code_finished(label, summary))

    if telegram and config.telegram_token and config.telegram_user_id:
        from .telegram import TelegramBot
        from .voice.tts import synthesize_mp3

        bot = TelegramBot(config.telegram_token, int(config.telegram_user_id))
        bot.on_text = rt.ask
        bot.transcribe = rt.transcribe
        bot.synthesize = lambda text: synthesize_mp3(text, config.online_voice)
        from . import admin

        bot.commands = {
            **admin.commands(config, jobs, brain),
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
            admin.report_update(lambda text: announcer.announce(text, reply=True))
        except RuntimeError as e:
            print(f"[telegram] not started: {e}")
    return rt
