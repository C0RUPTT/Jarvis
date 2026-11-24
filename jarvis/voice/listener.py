"""Microphone input: wake word detection ("Hey Jarvis") and speech-to-text (Whisper, local)."""

from __future__ import annotations

import time

import numpy as np

SAMPLE_RATE = 16_000
FRAME = 1280  # 80 ms at 16 kHz - the frame size openWakeWord expects


class Transcriber:
    """Speech-to-text with Whisper, running locally (free, private, works offline)."""

    def __init__(self, whisper_model: str = "base.en"):
        from faster_whisper import WhisperModel

        print(f"[voice] Loading speech recognition model '{whisper_model}'...")
        self.whisper = WhisperModel(whisper_model, device="auto", compute_type="int8")

    def transcribe(self, audio) -> str:
        """audio: a numpy int16 array at 16 kHz, or a path / file object (any format ffmpeg reads)."""
        if isinstance(audio, np.ndarray):
            audio = audio.astype(np.float32) / 32768.0
        segments, _ = self.whisper.transcribe(audio, language="en", beam_size=1, vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()


class Listener:
    def __init__(self, whisper_model: str = "base.en", wake_threshold: float = 0.5,
                 use_wake_word: bool = True):
        import sounddevice  # noqa: F401 - fail early with a clear error if missing

        self.transcriber = Transcriber(whisper_model)
        self.wake_threshold = wake_threshold
        self.wake_model = None
        if use_wake_word:
            self.wake_model = self._load_wake_model()
        self.noise_floor = self._calibrate()

    # -- wake word ---------------------------------------------------------

    @staticmethod
    def _load_wake_model():
        try:
            from openwakeword.model import Model
            from openwakeword.utils import download_models

            download_models(model_names=["hey_jarvis"])  # one-time download, cached afterwards
            return Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        except Exception as e:  # noqa: BLE001
            print(f"[voice] Wake word unavailable ({e}). Falling back to push-to-talk.")
            return None

    @property
    def has_wake_word(self) -> bool:
        return self.wake_model is not None

    def wait_for_wake_word(self) -> None:
        """Block until someone says 'Hey Jarvis'."""
        import sounddevice as sd

        self.wake_model.reset()
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME) as stream:
            while True:
                frame, _ = stream.read(FRAME)
                scores = self.wake_model.predict(frame[:, 0])
                if max(scores.values(), default=0) >= self.wake_threshold:
                    self.wake_model.reset()
                    return

    # -- recording + transcription -----------------------------------------

    def _calibrate(self) -> float:
        """Measure background noise so we know what 'silence' sounds like."""
        import sounddevice as sd

        audio = sd.rec(int(0.6 * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
        sd.wait()
        return max(_rms(audio[:, 0]), 50.0)

    def record_utterance(self, start_timeout: float = 8.0, max_seconds: float = 30.0,
                         silence_seconds: float = 0.9) -> np.ndarray | None:
        """Record until the speaker pauses. Returns None if nobody starts talking in time."""
        import sounddevice as sd

        threshold = self.noise_floor * 2.5 + 150
        frames: list[np.ndarray] = []
        pre_roll: list[np.ndarray] = []     # keep a little audio from just before speech starts
        started = False
        silent_for = 0.0
        frame_secs = FRAME / SAMPLE_RATE
        t0 = time.monotonic()

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME) as stream:
            while True:
                frame, _ = stream.read(FRAME)
                chunk = frame[:, 0].copy()
                loud = _rms(chunk) > threshold
                if not started:
                    pre_roll = (pre_roll + [chunk])[-4:]
                    if loud:
                        started = True
                        frames.extend(pre_roll)
                    elif time.monotonic() - t0 > start_timeout:
                        return None
                    continue
                frames.append(chunk)
                silent_for = 0.0 if loud else silent_for + frame_secs
                if silent_for >= silence_seconds or len(frames) * frame_secs >= max_seconds:
                    break

        return np.concatenate(frames)

    def transcribe(self, audio: np.ndarray) -> str:
        return self.transcriber.transcribe(audio)

    def listen(self, start_timeout: float = 8.0) -> str:
        audio = self.record_utterance(start_timeout=start_timeout)
        if audio is None:
            return ""
        return self.transcribe(audio)


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if len(x) else 0.0
