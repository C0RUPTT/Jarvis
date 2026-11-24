"""Text-to-speech. Uses the macOS `say` command on Macs and pyttsx3 elsewhere (offline)."""

from __future__ import annotations

import platform
import queue
import re
import shutil
import subprocess
import threading


def clean_for_speech(text: str) -> str:
    """Strip markdown and other things that sound bad when read aloud."""
    text = re.sub(r"```.*?```", " (code omitted) ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)      # [label](url) -> label
    text = re.sub(r"https?://\S+", "the link", text)
    text = re.sub(r"[*_#>|]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


class Speaker:
    """Speaks text on a background thread so timers can talk at any moment."""

    def __init__(self, voice: str = "", rate: int = 185, enabled: bool = True):
        self.voice = voice
        self.rate = rate
        self.enabled = enabled
        self._queue: queue.Queue = queue.Queue()
        self._use_say = platform.system() == "Darwin" and shutil.which("say") is not None
        threading.Thread(target=self._worker, daemon=True).start()

    def say(self, text: str, wait: bool = True) -> None:
        text = clean_for_speech(text)
        print(f"JARVIS: {text}")
        if not self.enabled or not text:
            return
        done = threading.Event()
        self._queue.put((text, done))
        if wait:
            done.wait()

    # -- internals ---------------------------------------------------------

    def _worker(self) -> None:
        engine = None
        if not self._use_say:
            engine = self._init_pyttsx3()
        while True:
            text, done = self._queue.get()
            try:
                if self._use_say:
                    cmd = ["say", "-r", str(self.rate)]
                    cmd += ["-v", self.voice or "Daniel"]  # Daniel = British English
                    subprocess.run(cmd + [text], check=False)
                elif engine is not None:
                    engine.say(text)
                    engine.runAndWait()
            except Exception as e:  # noqa: BLE001
                print(f"[tts error] {e}")
            finally:
                done.set()

    def _init_pyttsx3(self):
        try:
            if platform.system() == "Windows":
                try:
                    import comtypes  # COM must be initialised on this thread for SAPI voices

                    comtypes.CoInitialize()
                except Exception:  # noqa: BLE001
                    pass
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
            voices = engine.getProperty("voices") or []
            chosen = None
            if self.voice:
                chosen = next((v for v in voices if self.voice.lower() in v.name.lower()), None)
            if chosen is None:  # prefer a British English voice, Jarvis-style
                chosen = next(
                    (v for v in voices
                     if any(k in (v.name + str(v.id)).lower()
                            for k in ("en-gb", "en_gb", "united kingdom", "george", "hazel", "daniel"))),
                    None,
                )
            if chosen is not None:
                engine.setProperty("voice", chosen.id)
            return engine
        except Exception as e:  # noqa: BLE001
            print(f"[tts] Speech output unavailable ({e}); replies will be printed only.")
            self.enabled = False
            return None
