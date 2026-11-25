"""Phone server: the Siri Shortcut, the iPhone web app and the Telegram bot all talk to Jarvis
through this. Run with `python -m jarvis serve` (see docs/PHONE_SETUP.md). Every web request
needs the secret token; the Telegram bot only answers your user id.
"""

from __future__ import annotations

import base64
import concurrent.futures
import hmac
import re
import threading
import tempfile
import time
from pathlib import Path

from . import metrics, runtime
from .config import Config
from .voice.tts import clean_for_speech, synthesize_mp3

WEB_DIR = Path(__file__).parent / "web"
STILL_WORKING = "Still working on that. Ask me \"is it ready?\" in a moment, or I'll message you the answer."
HANDOFF_GRACE = 20  # seconds a finished late answer waits for your next Siri turn before it's sent to Telegram
READY_CHECK = re.compile(r"^(is it |are you )?(ready|done|finished)( yet)?\??$|^(go on|and\??|well\??|still there\??|"
                         r"what did you find\??|any luck\??)$", re.I)


def create_app(config: Config, speak_on_laptop: bool = False):
    from fastapi import Body, FastAPI, File, Header, HTTPException, Query, UploadFile
    from fastapi.responses import FileResponse, PlainTextResponse

    speak = None
    if speak_on_laptop:
        from .voice.tts import Speaker

        speaker = Speaker(voice=config.tts_voice, rate=config.tts_rate)
        speak = lambda text: speaker.say(text, wait=False)  # noqa: E731

    rt = runtime.build(config, speak=speak, on_interim=lambda t: print(f"JARVIS (interim): {t}"))
    brain, announcer = rt.brain, rt.announcer
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
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

    pending: list[dict] = []          # late Siri answers: {"q", "future", "done_at", "delivered"}
    pending_lock = threading.Lock()

    def _late_text(item: dict) -> str:
        try:
            return f"About your earlier question, \"{item['q'][:60]}\": {item['future'].result()}"
        except Exception as e:  # noqa: BLE001
            return f"Sorry, your earlier question \"{item['q'][:60]}\" failed: {e}"

    def _take_finished() -> list[str]:
        """Late answers that are ready and not yet delivered, so they can be spoken in this turn."""
        with pending_lock:
            ready = [p for p in pending if p["future"].done() and not p["delivered"]]
            for p in ready:
                p["delivered"] = True
            pending[:] = [p for p in pending if not p["delivered"]]
        return [_late_text(p) for p in ready]

    def _notify_if_unclaimed(item: dict) -> None:
        """The conversation may have ended: if nobody picked the answer up in time, send it to Telegram."""
        def later():
            with pending_lock:
                if item["delivered"]:
                    return
                item["delivered"] = True
                pending[:] = [p for p in pending if p is not item]
            announcer.announce(_late_text(item), reply=True)
        threading.Timer(HANDOFF_GRACE, later).start()

    def ask_within_budget(text: str) -> str:
        """Siri gives up on slow requests, so always answer within the budget. A late answer is spoken
        at the start of your next Siri turn, or sent to Telegram if the conversation has ended."""
        earlier = _take_finished()
        if READY_CHECK.match(text.strip(" .!")):
            with pending_lock:
                waiting = [p for p in pending if not p["delivered"]]
            if waiting and not earlier:   # wait (within budget) for the oldest unfinished answer
                concurrent.futures.wait([waiting[0]["future"]], timeout=config.siri_budget)
                earlier = _take_finished()
            if earlier:
                return " ".join(earlier)
            return "Still on it. Give me another moment." if waiting else "Nothing pending; ask away."

        future = pool.submit(rt.ask, text)
        try:
            reply = future.result(timeout=config.siri_budget)
        except concurrent.futures.TimeoutError:
            item = {"q": text, "future": future, "delivered": False}
            with pending_lock:
                pending.append(item)
            future.add_done_callback(lambda f: _notify_if_unclaimed(item))
            reply = STILL_WORKING
        return " ".join(earlier + [reply])

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/status")
    def status(x_jarvis_token: str | None = Header(None)):
        check(x_jarvis_token)
        return {"ok": True, "user_name": config.user_name, "brain": config.brain,
                "telegram": rt.telegram is not None, "mode": announcer.mode}

    @app.post("/api/talk")
    def talk(audio: UploadFile = File(...), x_jarvis_token: str | None = Header(None)):
        """Voice in, voice out: the phone web app sends a recording, gets back text + speech."""
        check(x_jarvis_token)
        suffix = ".mp4" if "mp4" in (audio.content_type or "") else ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio.file.read())
            path = f.name
        try:
            heard = rt.transcribe(path)
        finally:
            Path(path).unlink(missing_ok=True)
        print(f"\nYou (phone): {heard!r}")
        if len(heard.strip(" .!?,")) < 2:
            return {"heard": "", "reply": "", "speech": "", "audio": None}
        return respond(rt.ask(heard), heard=heard)

    @app.post("/api/ask")
    def ask(
        payload: dict = Body(...),
        x_jarvis_token: str | None = Header(None),
        format: str = Query("json"),
        token: str | None = Query(None),
    ):
        """Text in, text out. format=text is for the Siri Shortcut: plain text, always fast.
        The token can be a header, a JSON field, or ?token= in the URL (simplest in Shortcuts)."""
        check(x_jarvis_token or token or payload.get("token"))
        text = str(payload.get("text", "")).strip()
        if not text:
            raise HTTPException(status_code=400, detail="No text")
        print(f"\nYou: {text}")
        if format == "siri":
            # For the Siri Shortcut: what to say, plus phone actions for the Shortcut to perform.
            started = time.monotonic()
            announcer.begin_capture()
            try:
                reply = clean_for_speech(ask_within_budget(text))
            finally:
                actions = announcer.end_capture()
            metrics.record("siri", time.monotonic() - started, late=reply == STILL_WORKING)
            opens = [a for a in actions if a["type"] == "open"]
            timers = [a for a in actions if a["type"] == "timer"]
            result = {
                "say": reply,
                "open": opens[-1]["url"] if opens else "",
                "timer_minutes": timers[-1]["minutes"] if timers else 0,
            }
            for extra in opens[:-1]:   # only one link can open at a time; send the rest to Telegram
                announcer.push(f"{extra['text']}\n{extra['url']}")
            print(f"JARVIS: {result}")
            return result
        if format == "text":
            started = time.monotonic()
            reply = clean_for_speech(ask_within_budget(text))
            metrics.record("siri", time.monotonic() - started, late=reply == STILL_WORKING)
            print(f"JARVIS: {reply}")
            return PlainTextResponse(reply)
        return respond(rt.ask(text), heard=text, with_audio=bool(payload.get("audio", True)))

    @app.post("/api/wake")
    def wake(payload: dict = Body(default={}), x_jarvis_token: str | None = Header(None),
             token: str | None = Query(None)):
        """Called by the iPhone wake-up automation: ends night mode and returns the overnight summary
        as plain text, ready for the Shortcut to speak."""
        check(x_jarvis_token or token or payload.get("token"))
        return PlainTextResponse(clean_for_speech(rt.morning()))

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
        rt.close()

    return app


def serve(config: Config, speak_on_laptop: bool = False) -> None:
    import uvicorn

    app = create_app(config, speak_on_laptop)
    print("\n" + "=" * 64)
    print(f" Jarvis is listening on http://{config.host}:{config.port}")
    print(" Web app on your phone (through Tailscale):")
    print(f"   https://<your-computer>.<your-tailnet>.ts.net/?token={config.token}")
    print(" Siri Shortcut: see docs/TONIGHT.md")
    print("=" * 64 + "\n")
    uvicorn.run(app, host=config.host, port=config.port, log_level="warning")
