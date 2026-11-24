"""Telegram channel: chat with Jarvis, send voice notes and get spoken replies, and receive
notifications (job done, timers, reminders). Free, works with the phone locked.

Setup: create a bot with @BotFather, put its token in JARVIS_TELEGRAM_TOKEN and your numeric user
id (from @userinfobot) in JARVIS_TELEGRAM_USER_ID. The bot ignores everyone else.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Callable

from . import metrics

API = "https://api.telegram.org"


class TelegramBot:
    def __init__(self, token: str, user_id: int):
        self.token = token
        self.user_id = int(user_id)
        self.offset = 0
        self.on_text: Callable[[str], str] | None = None       # text in -> reply text
        self.transcribe: Callable[[str], str] | None = None    # audio file path -> text
        self.synthesize: Callable[[str], bytes | None] | None = None  # text -> mp3 bytes
        self.commands: dict[str, Callable[[], str]] = {}

    # -- sending ---------------------------------------------------------------

    def send(self, text: str, silent: bool = False) -> bool:
        """Send a message to the owner. silent=True: no sound or vibration."""
        ok = True
        for chunk in _chunks(text, 4000):
            ok &= self._call("sendMessage", {"chat_id": self.user_id, "text": chunk,
                                              "disable_notification": silent}) is not None
        return ok

    def send_voice(self, mp3: bytes, silent: bool = False) -> None:
        self._upload("sendVoice", {"chat_id": str(self.user_id),
                                   "disable_notification": str(silent).lower()},
                     "voice", "jarvis.mp3", mp3, "audio/mpeg")

    def typing(self) -> None:
        self._call("sendChatAction", {"chat_id": self.user_id, "action": "typing"})

    def check(self) -> str:
        """Verify the token. Returns the bot's @username."""
        me = self._call("getMe", {})
        if not me:
            raise RuntimeError("Telegram token is invalid or Telegram is unreachable.")
        return me["username"]

    # -- receiving ---------------------------------------------------------------

    def start(self) -> None:
        threading.Thread(target=self._poll_loop, daemon=True, name="jarvis-telegram").start()

    def _poll_loop(self) -> None:
        while True:
            updates = self._call("getUpdates", {"offset": self.offset, "timeout": 50}, timeout=60)
            if updates is None:
                time.sleep(5)
                continue
            for update in updates:
                self.offset = update["update_id"] + 1
                try:
                    self._handle(update)
                except Exception as e:  # noqa: BLE001
                    print(f"[telegram] error handling message: {e}")
                    self.send(f"Sorry, something went wrong: {e}")

    def _handle(self, update: dict) -> None:
        msg = update.get("message") or {}
        sender = (msg.get("from") or {}).get("id")
        if sender != self.user_id:
            if sender:
                print(f"[telegram] ignored a message from someone else (id {sender})")
            return

        started = time.monotonic()
        voice = msg.get("voice") or msg.get("audio")
        if voice:
            self.typing()
            text = self._transcribe_file(voice["file_id"])
            if not text:
                self.send("I couldn't make out that voice note.")
                return
            self.send(f"🎙 {text}", silent=True)
        else:
            text = (msg.get("text") or "").strip()
        if not text:
            return

        command = text.split()[0].lower().lstrip("/") if text.startswith("/") else ""
        if command in self.commands:
            self.send(self.commands[command]())
            return
        if command == "start":
            self.send("Jarvis online. Text me, or hold the mic button to talk.")
            return

        self.typing()
        reply = self.on_text(text) if self.on_text else "I'm not fully started yet."
        self.send(reply)
        if voice and self.synthesize:        # answer a voice note with a voice note
            audio = self.synthesize(reply)
            if audio:
                self.send_voice(audio, silent=True)
        metrics.record("telegram", time.monotonic() - started, voice=bool(voice))

    def _transcribe_file(self, file_id: str) -> str:
        info = self._call("getFile", {"file_id": file_id})
        if not info or not self.transcribe:
            return ""
        url = f"{API}/file/bot{self.token}/{info['file_path']}"
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
        with tempfile.NamedTemporaryFile(suffix=Path(info["file_path"]).suffix or ".ogg", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            return self.transcribe(path)
        finally:
            Path(path).unlink(missing_ok=True)

    # -- HTTP --------------------------------------------------------------------

    def _call(self, method: str, params: dict, timeout: int = 20):
        req = urllib.request.Request(
            f"{API}/bot{self.token}/{method}", data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.load(resp)
            return body.get("result") if body.get("ok") else None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            if method != "getUpdates":
                print(f"[telegram] {method} failed: {e}")
            return None

    def _upload(self, method: str, fields: dict, name: str, filename: str, data: bytes, mime: str):
        boundary = uuid.uuid4().hex
        parts = []
        for key, value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                     f"Content-Type: {mime}\r\n\r\n".encode() + data + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(
            f"{API}/bot{self.token}/{method}", data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            urllib.request.urlopen(req, timeout=60).close()
        except OSError as e:
            print(f"[telegram] {method} failed: {e}")


def _chunks(text: str, size: int):
    text = text or "(empty)"
    for i in range(0, len(text), size):
        yield text[i:i + size]
