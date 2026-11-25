"""Settings, read from environment variables (and a .env file if present)."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    user_name: str
    data_dir: Path

    # Brain
    brain: str                 # "claude-code" (uses your Claude Pro/Max plan) or "api" (API key, pay per use)
    model: str                 # model for the "api" brain
    effort: str
    cc_model: str              # model alias for the "claude-code" brain: sonnet / opus / haiku
    cc_permission_mode: str    # Claude Code permission mode: auto / acceptEdits / default / bypassPermissions
    workdir: Path              # folder the talker session starts in
    projects_dir: Path         # where background jobs build things
    worker_model: str          # model for background jobs (coding, building apps)

    # Voice
    whisper_model: str
    wake_threshold: float
    tts_voice: str             # local voice name (laptop speakers)
    tts_rate: int
    online_voice: str          # free neural voice for the phone (edge-tts); empty = phone's own voice

    # Phone server
    host: str
    port: int
    token: str
    notify_token: str          # low-privilege key: can only send "Claude Code finished" pings
    ntfy_topic: str            # fallback push notifications via the ntfy app
    telegram_token: str        # from @BotFather
    telegram_user_id: str      # your numeric id (from @userinfobot); the bot ignores everyone else
    siri_budget: float         # seconds before a Siri request says "still working" and finishes later
    quiet_start: str           # "HH:MM": night mode starts (holds everything until you wake up)

    unsafe_no_confirm: bool

    @classmethod
    def load(cls) -> "Config":
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

        apply_timezone(os.getenv("JARVIS_TIMEZONE", ""))
        data_dir = Path(os.getenv("JARVIS_DATA_DIR", Path.home() / ".jarvis")).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            user_name=os.getenv("JARVIS_USER_NAME", "sir"),
            data_dir=data_dir,
            brain=os.getenv("JARVIS_BRAIN", "claude-code"),
            model=os.getenv("JARVIS_MODEL", "claude-opus-5-5"),
            effort=os.getenv("JARVIS_EFFORT", "low"),
            cc_model=os.getenv("JARVIS_CC_MODEL", "sonnet"),
            cc_permission_mode=os.getenv("JARVIS_CC_PERMISSION_MODE", "auto"),
            workdir=Path(os.getenv("JARVIS_WORKDIR", Path.home())).expanduser(),
            projects_dir=Path(os.getenv("JARVIS_PROJECTS_DIR", Path.home() / "jarvis-projects")).expanduser(),
            worker_model=os.getenv("JARVIS_WORKER_MODEL", "sonnet"),
            whisper_model=os.getenv("JARVIS_WHISPER_MODEL", "base.en"),
            wake_threshold=float(os.getenv("JARVIS_WAKE_THRESHOLD", "0.5")),
            tts_voice=os.getenv("JARVIS_TTS_VOICE", ""),
            tts_rate=int(os.getenv("JARVIS_TTS_RATE", "185")),
            online_voice=os.getenv("JARVIS_ONLINE_VOICE", "en-GB-RyanNeural"),
            host=os.getenv("JARVIS_HOST", "127.0.0.1"),
            port=int(os.getenv("JARVIS_PORT", "8765")),
            token=os.getenv("JARVIS_TOKEN") or _stored_token(data_dir),
            notify_token=os.getenv("JARVIS_NOTIFY_TOKEN") or _stored_token(data_dir, "notify-token"),
            ntfy_topic=os.getenv("JARVIS_NTFY_TOPIC", ""),
            telegram_token=os.getenv("JARVIS_TELEGRAM_TOKEN", ""),
            telegram_user_id=os.getenv("JARVIS_TELEGRAM_USER_ID", ""),
            siri_budget=float(os.getenv("JARVIS_SIRI_BUDGET", "8")),  # Siri gives up at ~10s
            quiet_start=os.getenv("JARVIS_QUIET_START", "23:00"),
            unsafe_no_confirm=_env_bool("JARVIS_UNSAFE_NO_CONFIRM"),
        )


def apply_timezone(name: str) -> bool:
    """Run Jarvis on the user's local time (servers default to UTC). name: e.g. America/New_York."""
    if not name:
        return False
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(name)  # validate
    except Exception:  # noqa: BLE001
        print(f"[config] Unknown time zone {name!r}; staying on the server's time zone.")
        return False
    os.environ["TZ"] = name
    try:
        import time

        time.tzset()
    except AttributeError:  # Windows has no tzset; TZ is still honoured by new processes
        pass
    return True


def _stored_token(data_dir: Path, name: str = "token") -> str:
    """A random secret the phone must present. Generated once and kept in the data folder."""
    path = data_dir / name
    if not path.exists():
        path.write_text(secrets.token_urlsafe(24))
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return path.read_text().strip()
