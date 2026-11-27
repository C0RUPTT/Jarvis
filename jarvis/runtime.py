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


def _remember_once(data_dir: Path, key: str, fact: str) -> None:
    """Add a fact the user told us outside Jarvis (e.g. in the dev session) to Jarvis's memory once."""
    import json
    from datetime import date

    from .tools.memory import load_facts

    facts = load_facts(data_dir)
    if any(key in f.get("fact", "").lower() for f in facts):
        return
    facts.append({"id": max((f["id"] for f in facts), default=0) + 1, "fact": fact, "added": date.today().isoformat()})
    try:
        (data_dir / "memory.json").write_text(json.dumps(facts, indent=2))
    except OSError:
        pass


@dataclass
class Runtime:
    config: Config
    announcer: Announcer
    ctx: Context
    brain: object
    jobs: object | None
    telegram: object | None
    _whisper: object | None = None
    claude_watch: str = "always"   # "off" | "once" | "always": announce when Claude Code finishes
    dictation: list | None = None  # long-message mode: pieces collected until the user says "done"
    awaiting: set = None           # Claude Code sessions we sent a message to and await a reply from
    siri_inbox: list = None        # things to speak in the ongoing Siri conversation
    last_siri: float = 0.0         # when the Siri Shortcut last talked to us
    recent: list = None            # the last few exchanges, so the web app can pick up a Siri chat

    def __post_init__(self):
        self.awaiting = set()
        self.siri_inbox = []
        self.recent = []
        self._awaiting_since: dict = {}

    # Sessions we sent a message to. Kept on disk, so a restart (every update restarts Jarvis) doesn't
    # forget them, and kept for hours: a session busy with a long task replies only when it's done.
    AWAIT_HOURS = 6

    def _awaiting_file(self) -> Path:
        return self.config.data_dir / "awaiting.json"

    def _load_awaiting(self) -> None:
        import json

        try:
            saved = json.loads(self._awaiting_file().read_text())
        except (OSError, ValueError):
            saved = {}
        cutoff = time.time() - self.AWAIT_HOURS * 3600
        self._awaiting_since = {k: v for k, v in saved.items() if v > cutoff}
        self.awaiting = set(self._awaiting_since)

    def _save_awaiting(self) -> None:
        import json

        try:
            self._awaiting_file().write_text(json.dumps(self._awaiting_since))
        except OSError:
            pass

    def await_reply(self, session_id: str) -> None:
        self.awaiting.add(session_id)
        self._awaiting_since[session_id] = time.time()
        self._save_awaiting()

    def active_awaiting(self) -> set:
        """Sessions sent a message in the last 10 minutes: Siri keeps waiting for these. (Replies
        that come later are still delivered; see claude_code_finished.)"""
        return {sid for sid in self.awaiting if time.time() - self._awaiting_since.get(sid, 0) <= 600}

    def deliver(self, text: str, urgent: bool = True, full: str | None = None) -> None:
        """Tell the user something now. If a Siri conversation is going on, it's spoken there on the
        next turn (an open Siri conversation blocks spoken notifications); otherwise, or if no Siri
        turn picks it up within 25 seconds, it's announced as usual."""
        if time.time() - self.last_siri > 90:
            self.announcer.announce(text, urgent=urgent, full=full)
            return
        if full:
            self.announcer.push_full(full)
        item = [text]
        self.siri_inbox.append(item)

        def fallback():
            if item in self.siri_inbox:
                self.siri_inbox.remove(item)
                self.announcer.announce(text, urgent=urgent)
        import threading

        threading.Timer(25, fallback).start()

    def take_siri_inbox(self) -> list[str]:
        items, self.siri_inbox[:] = list(self.siri_inbox), []
        return [i[0] for i in items]

    def claude_code_finished(self, label: str = "", summary: str = "", seconds: int = -1,
                             session: str = "") -> str:
        """Called (via the Claude Code Stop hook) when a Claude Code session finishes a turn."""
        from . import claude_sessions

        claude_sessions.seen(self.config.data_dir, label, session, summary)
        sid = claude_sessions.normalize(session) if session else ""
        if sid and claude_sessions.is_side_run(label):
            return "ignored (a helper run inside that session, not its reply)"
        if sid and sid in self.awaiting and \
                time.time() - self._awaiting_since.get(sid, 0) < self.AWAIT_HOURS * 3600:
            # A reply to something the user sent through Jarvis: always read it out, however quick.
            self.awaiting.discard(sid)
            self._awaiting_since.pop(sid, None)
            self._save_awaiting()
            name = claude_sessions.name_of(self.config.data_dir, sid) or label or "Claude Code"
            self._deliver_long(f"Your {name} session says:", summary or "done.", context=f"From the user's {name} session.")
            return "delivered reply"
        if self.claude_watch == "off":
            return "ignored (announcements off)"
        min_seconds = int(os.getenv("JARVIS_CLAUDE_MIN_SECONDS", "30"))
        if self.claude_watch == "always" and 0 <= seconds < min_seconds:
            return "ignored (quick reply)"
        where = f" on {label}" if label else ""
        # Announcements you asked for always get through, with sound.
        self._deliver_long(f"Claude Code is done{where}.", summary, context=f"A Claude Code session{where} finished.")
        if self.claude_watch == "once":
            self.set_claude_watch(self._watch_default())
        return "announced"

    def _deliver_long(self, intro: str, body: str, context: str = "") -> None:
        """Speak a short version of a long reply and send the whole thing to the phone, never cut
        off. Summarising takes a few seconds, so it runs in the background."""
        from . import spoken

        def run():
            say, full = spoken.for_voice(body, context=context) if body else ("", None)
            self.deliver(f"{intro} {say}".strip(), urgent=True, full=f"{intro}\n\n{full}" if full else None)
        import threading

        threading.Thread(target=run, daemon=True).start()

    def _watch_default(self) -> str:
        path = self.config.data_dir / "claude-watch"
        return path.read_text().strip() if path.exists() else os.getenv("JARVIS_CLAUDE_WATCH", "always")

    def set_claude_watch(self, mode: str, remember: bool = False) -> None:
        """'once' is temporary; 'always' and 'off' are remembered across restarts."""
        self.claude_watch = mode
        if remember or mode in ("always", "off"):
            (self.config.data_dir / "claude-watch").write_text(mode)

    def transcribe(self, audio) -> str:
        from . import stt_cloud

        if stt_cloud.enabled() and isinstance(audio, (str, Path)):
            try:
                return stt_cloud.transcribe(str(audio))
            except Exception as e:  # noqa: BLE001 - any problem: use the server's own Whisper
                print(f"[voice] fast recognition unavailable ({e}); using the server's own")
        if self._whisper is None:
            from .voice.listener import Transcriber

            self._whisper = Transcriber(self.config.whisper_model)
        return self._whisper.transcribe(audio)

    def ask(self, text: str, on_sentence=None) -> str:
        """Everything the user says goes through here: fast path first, then Claude.
        on_sentence: optional, gets each sentence of Claude's answer as soon as it's written."""
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
            import inspect

            streams = on_sentence is not None and "on_sentence" in inspect.signature(self.brain.ask).parameters
            reply = self.brain.ask(text, on_sentence=on_sentence) if streams else self.brain.ask(text)
        held = self.announcer.peek_held()
        if woke and held:
            reply += f" Also, good morning: {held} thing{'s' if held != 1 else ''} came in overnight. Ask me what you missed."
        from .clock import exact_times

        reply = exact_times(reply)
        self.recent = (self.recent + [{"you": text, "jarvis": reply, "time": time.time()}])[-8:]
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
            body = job.result or ""
            if job.preview:
                from . import admin

                host = admin.public_host()
                if host:
                    body += f"\nTry it: https://{host}/preview/{job.preview}"
            if job.quiet:
                announcer.announce(f"Job {job.id} {verb}. {body}", quiet=True)
                return
            # Like a session reply: spoken where you are (Siri, the web app), short when it's long,
            # with the full text on the phone; never held back by a missed moment.
            rt._deliver_long(f"Job {job.id} {verb}.", body, context=f"A background coding job ({job.task[:100]}) finished.")

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
    rt._load_awaiting()
    from . import sms

    # Spoken Mail alerts wait while Jarvis is talking to you (a Siri turn in the last 45 s, or the web
    # app in a conversation), so they never talk over it.
    sms.busy = lambda: time.time() - rt.last_siri < 45 or time.time() < announcer.web_talking_until
    _remember_once(config.data_dir, "yattee",
                   "Uses the YouTube app for videos and the Yattee app for music (never YouTube for music).")
    if os.getenv("JARVIS_NOTIFY_LISTENER", "1") != "0":
        from . import notify_listener

        notify_listener.start(config.notify_topic, rt.claude_code_finished, config.data_dir)
    rt.claude_watch = rt._watch_default()
    ctx.extras["runtime"] = rt
    brain._runtime = rt   # lets /notifycheck show the announcement mode

    if telegram and config.telegram_token and config.telegram_user_id:
        from .telegram import TelegramBot
        from .voice.tts import synthesize_mp3

        bot = TelegramBot(config.telegram_token, int(config.telegram_user_id))
        bot.offset_file = config.data_dir / "telegram-offset"
        bot.on_text = rt.ask
        bot.transcribe = rt.transcribe
        bot.synthesize = lambda text: synthesize_mp3(text, config.online_voice)
        from . import admin

        bot.commands = {
            **admin.commands(config, jobs, brain),
            "jobs": lambda: jobs.summary() if jobs else "No background jobs in this mode.",
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
            brain._telegram = bot   # lets /voicechime send the clip
            admin.report_update(lambda text: announcer.announce(text, reply=True))
        except RuntimeError as e:
            print(f"[telegram] not started: {e}")
    return rt
