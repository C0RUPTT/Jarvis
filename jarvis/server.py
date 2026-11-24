"""Phone server: the iPhone web app and iOS Shortcuts talk to Jarvis on the laptop through this.

Run with `python -m jarvis serve`, then expose it privately to your phone with Tailscale
(see docs/PHONE_SETUP.md). Every API call needs the secret token.
"""

from __future__ import annotations

import base64
import hmac
import tempfile
from pathlib import Path

from .announcer import Announcer
from .brain import make_brain
from .config import Config
from .tools import Context
from .voice.tts import clean_for_speech, synthesize_mp3

WEB_DIR = Path(__file__).parent / "web"


def create_app(config: Config, speak_on_laptop: bool = False):
    from fastapi import Body, FastAPI, File, Header, HTTPException, Query, UploadFile
    from fastapi.responses import FileResponse, PlainTextResponse

    speaker = None
    if speak_on_laptop:
        from .voice.tts import Speaker

        speaker = Speaker(voice=config.tts_voice, rate=config.tts_rate)

    announcer = Announcer(config.ntfy_topic, speak=(lambda t: speaker.say(t, wait=False)) if speaker else None)
    ctx = Context(
        config=config,
        # Nobody is at the laptop to answer, so risky tools of the API brain are refused unless
        # JARVIS_UNSAFE_NO_CONFIRM=1. (The Claude Code brain uses Claude Code's own permission mode.)
        confirm=lambda question: False,
        announce=announcer.announce,
        extras={"announcer": announcer},
    )
    brain = make_brain(ctx, on_interim=lambda text: print(f"JARVIS (interim): {text}"))

    whisper: list = []  # loaded on first voice request

    def transcribe(path: str) -> str:
        if not whisper:
            from .voice.listener import Transcriber

            whisper.append(Transcriber(config.whisper_model))
        return whisper[0].transcribe(path)

    app = FastAPI(title="Jarvis", docs_url=None, redoc_url=None)

    def check(token: str | None) -> None:
        if not token or not hmac.compare_digest(token, config.token):
            raise HTTPException(status_code=401, detail="Bad or missing token")

    def respond(text: str, heard: str = "", with_audio: bool = True) -> dict:
        print(f"JARVIS: {text}")
        audio = synthesize_mp3(text, config.online_voice) if with_audio else None
        return {
            "heard": heard,
            "reply": text,
            "speech": clean_for_speech(text),
            "audio": base64.b64encode(audio).decode() if audio else None,
        }

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/status")
    def status(x_jarvis_token: str | None = Header(None)):
        check(x_jarvis_token)
        return {"ok": True, "user_name": config.user_name, "brain": config.brain}

    @app.post("/api/talk")
    def talk(audio: UploadFile = File(...), x_jarvis_token: str | None = Header(None)):
        """Voice in, voice out: the phone web app sends a recording, gets back text + speech."""
        check(x_jarvis_token)
        suffix = ".mp4" if "mp4" in (audio.content_type or "") else ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio.file.read())
            path = f.name
        try:
            heard = transcribe(path)
        finally:
            Path(path).unlink(missing_ok=True)
        print(f"\nYou (phone): {heard!r}")
        if len(heard.strip(" .!?,")) < 2:
            return {"heard": "", "reply": "", "speech": "", "audio": None}
        return respond(brain.ask(heard), heard=heard)

    @app.post("/api/ask")
    def ask(
        payload: dict = Body(...),
        x_jarvis_token: str | None = Header(None),
        format: str = Query("json"),
    ):
        """Text in, text out. Used by the web app's keyboard and by iOS Shortcuts / Siri."""
        check(x_jarvis_token or payload.get("token"))
        text = str(payload.get("text", "")).strip()
        if not text:
            raise HTTPException(status_code=400, detail="No text")
        print(f"\nYou: {text}")
        reply = brain.ask(text)
        if format == "text":  # simplest for Shortcuts: the reply as plain text
            print(f"JARVIS: {reply}")
            return PlainTextResponse(clean_for_speech(reply))
        return respond(reply, heard=text, with_audio=bool(payload.get("audio", True)))

    @app.post("/api/reset")
    def reset(x_jarvis_token: str | None = Header(None)):
        check(x_jarvis_token)
        brain.reset()
        return {"ok": True}

    @app.get("/api/events")
    def events(after: int = 0, x_jarvis_token: str | None = Header(None)):
        """Things Jarvis says unprompted (timers, reminders) and phone actions to perform."""
        check(x_jarvis_token)
        return {"events": announcer.events_since(after)}

    @app.on_event("shutdown")
    def shutdown():
        brain.close()

    return app


def serve(config: Config, speak_on_laptop: bool = False) -> None:
    import uvicorn

    app = create_app(config, speak_on_laptop)
    print("\n" + "=" * 64)
    print(f" Jarvis is listening on http://{config.host}:{config.port}")
    print(" On your phone, open your Tailscale address with this token:")
    print(f"   https://<your-laptop>.<your-tailnet>.ts.net/?token={config.token}")
    print(" (see docs/PHONE_SETUP.md)")
    print("=" * 64 + "\n")
    uvicorn.run(app, host=config.host, port=config.port, log_level="warning")
