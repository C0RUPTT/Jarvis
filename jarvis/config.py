"""Settings, read from environment variables (and a .env file if present)."""

from __future__ import annotations

import os
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
    model: str
    effort: str
    data_dir: Path
    whisper_model: str
    wake_threshold: float
    tts_voice: str
    tts_rate: int
    unsafe_no_confirm: bool

    @classmethod
    def load(cls) -> "Config":
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

        data_dir = Path(os.getenv("JARVIS_DATA_DIR", Path.home() / ".jarvis")).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            user_name=os.getenv("JARVIS_USER_NAME", "sir"),
            model=os.getenv("JARVIS_MODEL", "claude-opus-5-5"),
            effort=os.getenv("JARVIS_EFFORT", "low"),
            data_dir=data_dir,
            whisper_model=os.getenv("JARVIS_WHISPER_MODEL", "base.en"),
            wake_threshold=float(os.getenv("JARVIS_WAKE_THRESHOLD", "0.5")),
            tts_voice=os.getenv("JARVIS_TTS_VOICE", ""),
            tts_rate=int(os.getenv("JARVIS_TTS_RATE", "185")),
            unsafe_no_confirm=_env_bool("JARVIS_UNSAFE_NO_CONFIRM"),
        )
