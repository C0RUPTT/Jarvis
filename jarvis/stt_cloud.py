"""Optional fast speech-to-text: Groq's hosted Whisper (free tier; about half a second instead of
~3 seconds on this small server). Only used when GROQ_API_KEY is set (Telegram: /groq <key>), and
any failure falls straight back to the server's own Whisper, so it can't make things less reliable."""

from __future__ import annotations

import json
import os
import urllib.request
import uuid
from pathlib import Path

URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = os.getenv("JARVIS_GROQ_MODEL", "whisper-large-v3-turbo")


def enabled() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def transcribe(path: str, timeout: float | None = None) -> str:
    """Raises on any problem (the caller falls back to local Whisper)."""
    data = Path(path).read_bytes()
    if timeout is None:   # long recordings take longer to upload and transcribe
        timeout = 6 + len(data) / 100_000
    boundary = uuid.uuid4().hex
    name = Path(path).name
    if name.endswith(".oga"):          # Telegram voice notes: same format, the name Groq accepts
        name = name[:-4] + ".ogg"

    def field(key: str, value: str) -> bytes:
        return f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()

    body = (field("model", MODEL) + field("language", "en") + field("response_format", "verbose_json")
            + f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
              f"Content-Type: application/octet-stream\r\n\r\n".encode() + data + b"\r\n"
            + f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
        "Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "jarvis-assistant"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    return real_speech(data)


def real_speech(data: dict) -> str:
    """Speech models invent words for background noise ("Thank you.", "I'm a man."). Each piece of
    text comes with how likely it was really silence and how sure the model was; keep only the
    pieces that were really spoken."""
    segments = data.get("segments")
    if not segments:
        return str(data.get("text", "")).strip()
    kept = [seg.get("text", "") for seg in segments
            if not (seg.get("no_speech_prob", 0) > 0.5 and seg.get("avg_logprob", 0) < -0.6)
            and seg.get("avg_logprob", 0) > -1.2]
    text = " ".join(t.strip() for t in kept).strip()
    if not text and data.get("text", "").strip():
        print(f"[voice] ignored background noise heard as {data.get('text', '').strip()!r}")
    return text


def save_key(key: str) -> str:
    key = key.strip()
    if not key.startswith("gsk_"):
        return "That doesn't look like a Groq key (they start with gsk_). Get one free at console.groq.com > API Keys."
    from .admin import set_env_value

    set_env_value("GROQ_API_KEY", key)
    os.environ["GROQ_API_KEY"] = key
    return ("Saved. Voice notes and the web app now use fast speech recognition, falling back to the "
            "server's own if it ever fails. (I deleted your message so the key isn't left in the chat.)")
