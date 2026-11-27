"""Phone server: the Siri Shortcut, the iPhone web app and the Telegram bot all talk to Jarvis
through this. Run with `python -m jarvis serve` (see docs/PHONE_SETUP.md). Every web request
needs the secret token; the Telegram bot only answers your user id.
"""

from __future__ import annotations

import base64
import concurrent.futures
import hmac
import json
import os
import re
import threading
import tempfile
import time
from pathlib import Path

# FastAPI must be imported at module level: with `from __future__ import annotations` the endpoint
# annotations (e.g. UploadFile) are resolved from this module's globals.
from fastapi import Body, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from . import fastpath, metrics, runtime, siritrace, spoken
from .config import Config
from .voice.tts import clean_for_speech, synthesize_mp3

WEB_DIR = Path(__file__).parent / "web"
STILL_WORKING = "One moment, sir."   # the Shortcut then waits for the answer via /api/wait
HANDOFF_GRACE = 20  # seconds a finished late answer waits for your next Siri turn before it's sent to Telegram
# Ways people end a Siri conversation, including how dictation mishears "bye" ("by", "buy").
GOODBYE = re.compile(
    r"^(ok(ay)?|alright|all right|thanks?( you)?|cool|great|perfect|no)?[,.! ]*"
    r"(bye|bye[- ]bye|by|buy|good ?-?bye|see (ya|you)( later)?|later|that'?s (all|it)|that will be all|"
    r"i'?m (good|all set|set)|nothing( else)?|no thanks?|nope|stop|end|exit|quit|cancel|dismissed|over and out)"
    r"( for now| jarvis| thanks?| thank you)*[.!?]*$", re.I)
# The web app's "I'm finished talking": only as the whole utterance, never a "bye" inside a sentence.
STANDBY = re.compile(r"^(ok(ay)?|alright|all right|thanks?( you)?|thank you|cool|great|perfect|no|so)?([,.! ]*jarvis)?[,.! ]*"
                     r"(bye|bye[- ]bye|by|buy|good ?-?bye|good ?night|see (ya|you)( later)?|talk (to you )?later|that'?s (all|it)|that will be all|i'?m (done|good|all set|finished)|i am (done|finished)|we'?re (done|good)|done (talking|for now)|nothing( else)?|no thanks?|stop listening|go to sleep|(go (to |on )?)?standby|sleep|dismissed|over and out)"
                     r"( for now| jarvis| thanks?| thank you| sir| then)*[.!?]*$", re.I)
def is_standby(text: str) -> bool:
    """'I'm done' / 'goodbye' / 'stop listening' as the whole thing, or as the last sentence after a
    short acknowledgement ("Sounds good. I'm done.", "Thanks, goodbye"); never inside a longer
    thought ("I'm done with my laundry")."""
    text = text.strip()
    if STANDBY.match(text):
        return True
    parts = [p.strip() for p in re.split(r"[.!?,;]+\s*", text) if p.strip()]
    if len(parts) < 2 or not STANDBY.match(parts[-1]):
        return False
    return len(" ".join(parts[:-1]).split()) <= 6   # "sounds good", "okay thanks Jarvis", "perfect"


FAREWELLS = ["Goodbye, sir.", "Very good, sir.", "I'll be here.", "Until next time, sir.", "Right you are, sir."]
READY_CHECK = re.compile(r"^(ok(ay)?,? |yes,? |yeah,? )?((is it |are you )?(ready|done|finished)( yet)?|go on|go ahead|"
                         r"continue|carry on|and|well|still there|what did you find|any luck|tell me|let'?s hear it)"
                         r"( then| please| jarvis)?[.?!]*$", re.I)


def create_app(config: Config, speak_on_laptop: bool = False):

    speak = None
    if speak_on_laptop:
        from .voice.tts import Speaker

        speaker = Speaker(voice=config.tts_voice, rate=config.tts_rate)
        speak = lambda text: speaker.say(text, wait=False)  # noqa: E731

    rt = runtime.build(config, speak=speak, on_interim=lambda t: print(f"JARVIS (interim): {t}"))

    def warm_speech_model():   # load speech recognition ahead of time, so the first voice note isn't slow
        time.sleep(60)
        try:
            from .voice.listener import Transcriber

            if rt._whisper is None:
                rt._whisper = Transcriber(config.whisper_model)
        except Exception as e:  # noqa: BLE001
            print(f"[voice] couldn't preload speech recognition: {e}")

    from . import stt_cloud

    # The server's own speech recognition takes ~200 MB of this small server's 1 GB. With fast cloud
    # recognition (Groq) it's only a fallback, so it's loaded only if it's ever needed.
    if os.getenv("JARVIS_PRELOAD_WHISPER", "1") != "0" and not stt_cloud.enabled():
        threading.Thread(target=warm_speech_model, daemon=True).start()
    brain, announcer = rt.brain, rt.announcer
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    app = FastAPI(title="Jarvis", docs_url=None, redoc_url=None)

    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(Exception)
    async def show_errors(request: Request, exc: Exception):
        """Say what actually broke (and log it) instead of a bare "Internal Server Error"."""
        import traceback

        traceback.print_exc()
        return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"[:300]})

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

    def _late_text(item: dict, for_reading: bool = False) -> str:
        """A late answer: spoken straight away, with no 'about your earlier question' preamble.
        Only the Telegram copy (for reading later) notes what it was about, at the end."""
        try:
            answer = item["future"].result()
        except Exception as e:  # noqa: BLE001
            answer = f"Sorry, sir, that one failed: {e}"
        return f"{answer}\n\n(You asked: {item['q'][:80]})" if for_reading else answer

    recently_answered: list[tuple[float, str]] = []   # (time, question) of late answers just spoken

    def _take_finished() -> list[str]:
        """Late answers that are ready and not yet delivered, so they can be spoken in this turn."""
        with pending_lock:
            ready = [p for p in pending if p["future"].done() and not p["delivered"]]
            for p in ready:
                p["delivered"] = True
            pending[:] = [p for p in pending if not p["delivered"]]
        recently_answered[:] = [r for r in recently_answered if time.time() - r[0] < 120] + \
            [(time.time(), p["q"]) for p in ready]
        return [_late_text(p) for p in ready]

    wait_state = {"last": 0.0}   # when Siri's waiting step last asked for an answer

    def _notify_if_unclaimed(item: dict) -> None:
        """The conversation may have ended: if nobody picked the answer up in time, send it to Telegram."""
        def later():
            # Siri's waiting step is still collecting answers: give it longer before Telegram.
            if time.time() - wait_state["last"] < 15 and item.get("postponed", 0) < 4:
                item["postponed"] = item.get("postponed", 0) + 1
                threading.Timer(10, later).start()
                return
            with pending_lock:
                if item["delivered"]:
                    return
                item["delivered"] = True
                pending[:] = [p for p in pending if p is not item]
            if not item.get("waits") and not wait_state.get("hinted_today") == time.strftime("%Y-%m-%d"):
                wait_state["hinted_today"] = time.strftime("%Y-%m-%d")
                print("[siri] the Shortcut never called the waiting step for a late answer")
                announcer.announce(_late_text(item, for_reading=True) + "\n\n(Siri didn't wait for this answer: the Shortcut's "
                                   "waiting step isn't reaching Jarvis. See docs/SIRI_SHORTCUT.md, or send /shortcut.)",
                                   reply=True)
                return
            announcer.announce(_late_text(item, for_reading=True), reply=True)
        threading.Timer(HANDOFF_GRACE, later).start()

    def _similar(a: str, b: str) -> bool:
        import difflib

        norm = lambda x: re.sub(r"[^a-z0-9 ]", "", x.lower()).strip()
        return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio() > 0.75

    def _voice_sized(reply: str, asked: str = "") -> str:
        """Safety net for spoken answers: if one is still long (despite the instructions), speak
        the first part and send the whole answer to the phone, instead of a minute-long monologue."""
        from . import spoken

        if re.search(r"\b(all of it|full list|everything|whole thing|read (it|them) all|every one)\b", asked, re.I):
            return reply   # they asked for all of it
        say, full = spoken.for_voice(reply, smart=False)
        if full:
            announcer.push_full(full)
            return say
        return reply

    def ask_within_budget(text: str) -> str:
        """Siri gives up on slow requests, so always answer within the budget. A late answer is spoken
        at the start of your next Siri turn, or sent to Telegram if the conversation has ended."""
        rt.last_siri = time.time()
        earlier = _take_finished() + rt.take_siri_inbox()
        with pending_lock:
            anything_pending = any(not p["delivered"] for p in pending)
        # "Go on" / "is it ready?" waits for a pending answer; with nothing pending, "go ahead" is just
        # an ordinary reply (e.g. agreeing to something), so it goes to Claude as usual.
        if READY_CHECK.match(text.strip(" .!")) and (anything_pending or earlier or rt.active_awaiting()):
            with pending_lock:
                waiting = [p for p in pending if not p["delivered"]]
            if waiting and not earlier:   # wait (within budget) for the oldest unfinished answer
                concurrent.futures.wait([waiting[0]["future"]], timeout=config.siri_budget)
                earlier = _take_finished() + rt.take_siri_inbox()
            if not earlier and rt.active_awaiting():   # waiting on a Claude Code session's reply
                deadline = time.time() + config.siri_budget
                while time.time() < deadline and not rt.siri_inbox:
                    time.sleep(0.5)
                earlier = rt.take_siri_inbox()
            if earlier:
                return " ".join(earlier)
            if rt.active_awaiting():
                return "The session is still working on it. Ask me again in a moment."
            return "Still on it, sir. Say go on again in a moment." if waiting else "Nothing pending; ask away."

        if earlier and any(_similar(q, text) for _, q in recently_answered):
            return " ".join(earlier)   # the answer to this very question just arrived: don't ask twice
        with pending_lock:   # asked again (Siri said "one moment" and you repeated yourself)?
            same = [p for p in pending if not p["delivered"] and _similar(p["q"], text)]
        if same:
            item = same[0]
            try:   # don't start a second answer to the same question: wait for the first one
                item["future"].result(timeout=config.siri_budget)
            except concurrent.futures.TimeoutError:
                return " ".join(earlier + ["Still working on that one, sir. I'll tell you the moment it's ready."])
            with pending_lock:
                if item["delivered"]:
                    return " ".join(earlier + ["I've just sent you that answer, sir."])
                item["delivered"] = True
                pending[:] = [p for p in pending if p is not item]
            return " ".join(earlier + [item["future"].result()])

        def siri_ask(t: str) -> str:
            siri_waiting[0] += 1
            try:
                return rt.ask(t)
            finally:
                siri_waiting[0] -= 1

        future = pool.submit(siri_ask, text)
        try:
            reply = future.result(timeout=config.siri_budget)
        except concurrent.futures.TimeoutError:
            item = {"q": text, "future": future, "delivered": False, "asked_at": time.time(), "waits": 0}
            with pending_lock:
                pending.append(item)
            future.add_done_callback(lambda f: _notify_if_unclaimed(item))
            reply = STILL_WORKING
        return " ".join(earlier + [reply])

    # Apps that coding jobs build, viewable on the phone. Only reachable inside your private
    # Tailscale network (the public Funnel only exposes /notify).
    from fastapi.staticfiles import StaticFiles

    config.projects_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/preview", StaticFiles(directory=config.projects_dir, html=True), name="preview")

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/sw.js")
    def service_worker():
        """Keeps a copy of the app on the phone, so it opens at once even while the server is busy."""
        return FileResponse(WEB_DIR / "sw.js", media_type="application/javascript",
                            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

    @app.get("/api/recent")
    def recent(x_jarvis_token: str | None = Header(None)):
        """The last few exchanges from any channel (Siri, Telegram), so the app continues the chat."""
        check(x_jarvis_token)
        return {"turns": [t for t in rt.recent if time.time() - t["time"] < 1800]}

    @app.get("/api/status")
    def status(x_jarvis_token: str | None = Header(None)):
        check(x_jarvis_token)
        return {"ok": True, "user_name": config.user_name, "brain": config.brain,
                "telegram": rt.telegram is not None, "mode": announcer.mode}

    talks: dict[str, dict] = {}   # async web-app turns: id -> {"status", "result", "done_at", "fetched"}
    talks_lock = threading.Condition()   # also signals "something changed" to waiting phones

    speech_jobs: dict[str, dict] = {}   # id -> sentence audio for a web-app answer (see /api/speech)

    web_turn = threading.Lock()
    siri_waiting = [0]   # Siri requests waiting for Claude right now

    def _superseded(talk_id: str) -> bool:
        with talks_lock:
            return bool(talks.get(talk_id, {}).get("superseded"))

    def _process_talk(path: str = "", text: str = "", talk_id: str = "") -> dict:
        started = time.monotonic()
        if text:   # already turned into text on the phone (much faster than this small server)
            heard = text
        else:
            try:
                heard = rt.transcribe(path)
            finally:
                Path(path).unlink(missing_ok=True)
        heard_at = time.monotonic()
        print(f"\nYou (phone): {heard!r}")
        if len(heard.strip(" .!?,")) < 2:
            return {"heard": "", "reply": "", "speech": "", "audio": None}
        if _echo_of_jarvis(heard):   # Jarvis's own voice picked up by the mic: never a request
            print(f"[web] ignored Jarvis's own words: {heard!r}")
            return {"heard": "", "reply": "", "speech": "", "audio": None}
        if rt.dictation is None and is_standby(heard):   # "I'm done": no model call
            return {"heard": heard, "reply": "", "speech": "", "audio": None, "standby": True}
        queued_at = time.monotonic()
        with web_turn:   # one app message at a time, so a newer one can replace those still queued
            for _ in range(600):   # a Siri request goes first: Siri can only wait a few seconds
                if not siri_waiting[0]:
                    break
                time.sleep(0.1)
            if talk_id and _superseded(talk_id):   # you've already said something newer: skip this one
                print(f"[web] skipped an older message: {heard!r}")
                return {"heard": "", "reply": "", "speech": "", "audio": None}
            asked_at = time.monotonic()
            speech_id, job = _new_speech() if config.online_voice else ("", None)
            streamed: list[str] = []

            def early(sentence: str) -> None:   # a sentence of the answer, as soon as it's written
                from .clock import exact_times

                sentence = clean_for_speech(exact_times(sentence))
                if not sentence or job is None or sum(len(x) for x in streamed) > 260:
                    return   # long answers: speak the start only; the rest goes to the phone below
                streamed.append(sentence)
                _add_speech(job, sentence)
                if talk_id:
                    with talks_lock:
                        if not talks.get(talk_id, {}).get("speech_id"):
                            talks.get(talk_id, {})["speech_id"] = speech_id
                            talks_lock.notify_all()
            try:
                reply = rt.ask(heard, on_sentence=early if job is not None else None)
            except Exception as e:  # noqa: BLE001 - say what happened instead of going silent
                print(f"[web] answering failed: {e}")
                reply = "Sorry, sir, something went wrong while answering that. Please try again."
        metrics.record("web", time.monotonic() - started, stt=round(heard_at - started, 2),
                       queue=round(asked_at - queued_at, 2), think=round(time.monotonic() - asked_at, 2),
                       on_phone=bool(text))
        print(f"JARVIS: {reply}")
        # Voice, sentence by sentence: the first sentence is short, so its audio is ready almost at
        # once and Jarvis starts talking while the rest is still being generated (all in parallel,
        # starting now, before the phone even asks).
        try:
            spoken_reply = _voice_sized(reply, heard)
            parts = _speech_parts(clean_for_speech(spoken_reply)) if config.online_voice else []
        except Exception as e:  # noqa: BLE001
            print(f"[web] preparing the spoken answer failed: {e}")
            spoken_reply, parts = reply, [clean_for_speech(reply)[:400]]
        if job is not None:
            try:
                # Add whatever wasn't already spoken early. If what was streamed isn't the start of the
                # final answer (e.g. "Let me check" before a search), the whole answer follows it.
                norm = lambda x: " ".join(re.sub(r"[^a-z0-9 ]", " ", x.lower()).split())   # noqa: E731
                said, final = norm(" ".join(streamed)), norm(clean_for_speech(spoken_reply))
                if streamed and final.startswith(said):
                    rest, done_chars = [], 0
                    for sentence in re.split(r"(?<=[.!?])\s+", clean_for_speech(spoken_reply)):
                        if done_chars < len(said):
                            done_chars += len(norm(sentence)) + 1
                            continue
                        rest.append(sentence)
                    parts = [p for p in rest if p.strip()]
                elif streamed and len(reply) > len(spoken_reply):
                    parts = [spoken.FULL_ON_PHONE]   # long: the start was spoken, the whole text is on the phone
                if streamed:
                    # Never say a sentence twice: Claude's final answer often restates what it said
                    # before using a tool ("Yes, I can get your location. Let me test it now.").
                    import difflib

                    heard_before = [norm(x) for x in streamed]
                    parts = [p for p in parts if not any(
                        difflib.SequenceMatcher(None, norm(p), h).ratio() > 0.75 for h in heard_before)]
                for part in parts:
                    _add_speech(job, part)
            except Exception as e:  # noqa: BLE001
                print(f"[web] finishing the spoken answer failed: {e}")
                if not job["parts"]:
                    _add_speech(job, clean_for_speech(spoken_reply)[:400])
            finally:
                _end_speech(job)   # always: otherwise the phone waits in 'speaking' with nothing to say
        return {"heard": heard, "reply": reply, "speech": clean_for_speech(spoken_reply), "audio": None,
                "speech_id": speech_id, "speech_parts": job["parts"] if job is not None else []}

    def _echo_of_jarvis(heard: str) -> bool:
        """True if what the mic 'heard' is just a piece of Jarvis's last answer (it spoke on the
        loudspeaker and the mic caught it), e.g. after interrupting it by talking."""
        if not rt.recent or time.time() - rt.recent[-1]["time"] > 120:
            return False
        norm = lambda x: " ".join(re.sub(r"[^a-z0-9 ]", " ", x.lower()).split())   # noqa: E731
        said, last = norm(heard), norm(rt.recent[-1]["jarvis"])
        return len(said.split()) >= 3 and said in last

    def _speech_parts(text: str) -> list[str]:
        sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]
        if not sentences:
            return []
        parts = [sentences[0]]
        for sentence in sentences[1:]:
            if len(parts) > 1 and len(parts[-1]) + len(sentence) < 220:
                parts[-1] += " " + sentence
            else:
                parts.append(sentence)
        return parts[:12]

    # A speech job grows sentence by sentence (each sentence's audio is made as soon as it arrives)
    # and is marked done at the end; the phone plays part 0, 1, 2... until the server says "that's all".
    def _new_speech() -> tuple[str, dict]:
        import secrets as _secrets

        speech_id = _secrets.token_urlsafe(8)
        for old in [k for k, v in speech_jobs.items() if time.time() - v["created"] > 600]:
            speech_jobs.pop(old, None)
        job = {"created": time.time(), "parts": [], "audio": [], "ready": [], "done": False,
               "cond": threading.Condition()}
        speech_jobs[speech_id] = job
        return speech_id, job

    def _add_speech(job: dict, text: str) -> None:
        with job["cond"]:
            i = len(job["parts"])
            job["parts"].append(text)
            job["audio"].append(None)
            job["ready"].append(threading.Event())
            job["cond"].notify_all()

        def make() -> None:
            try:
                job["audio"][i] = synthesize_mp3(text, config.online_voice) or b""
            finally:
                job["ready"][i].set()
        threading.Thread(target=make, daemon=True).start()

    def _end_speech(job: dict) -> None:
        with job["cond"]:
            job["done"] = True
            job["cond"].notify_all()

    def _start_speech(parts: list[str]) -> str:
        speech_id, job = _new_speech()
        for part in parts:
            _add_speech(job, part)
        _end_speech(job)
        return speech_id

    @app.get("/api/speech/{speech_id}/{part}")
    def speech(speech_id: str, part: int, token: str | None = Query(None),
               x_jarvis_token: str | None = Header(None)):
        """One sentence of Jarvis's voice (MP3). Waits for that sentence if Claude is still writing.
        410 = no more sentences; 404 = no voice for it (the phone says the X-Text itself)."""
        from urllib.parse import quote

        from fastapi.responses import JSONResponse, Response

        check(x_jarvis_token or token)
        job = speech_jobs.get(speech_id)
        if not job or part < 0:
            raise HTTPException(status_code=404, detail="Unknown speech")
        with job["cond"]:
            job["cond"].wait_for(lambda: part < len(job["parts"]) or job["done"], timeout=60)
            if part >= len(job["parts"]):
                return JSONResponse(status_code=410, content={"detail": "end"})
            text = job["parts"][part]
        job["ready"][part].wait(timeout=20)
        audio = job["audio"][part]
        if not audio:
            return JSONResponse(status_code=404, content={"detail": "Voice unavailable", "text": text})
        return Response(audio, media_type="audio/mpeg",
                        headers={"Cache-Control": "no-store", "X-Text": quote(text[:500])})

    def _finish_talk(talk_id: str, future) -> None:
        try:
            result = future.result()
        except Exception as e:  # noqa: BLE001
            result = {"heard": "", "reply": f"Sorry, that failed: {e}", "speech": "", "audio": None}
        with talks_lock:
            talks[talk_id].update(status="done", result=result, done_at=time.time())
            talks_lock.notify_all()

        def unclaimed():   # the app was closed or frozen: send the answer to Telegram instead
            with talks_lock:
                item = talks.get(talk_id)
                if not item or item["fetched"] or item.get("superseded"):
                    return   # collected, or replaced by a newer message: nothing to forward
                item["fetched"] = True
            if result.get("reply"):
                announcer.announce(f"You asked: \"{result.get('heard', '')[:80]}\"\n{result['reply']}", reply=True)
        with talks_lock:
            handed_off = bool(talks.get(talk_id, {}).get("handed_off"))
        threading.Timer(1 if handed_off else 45, unclaimed).start()   # handed off: the app is waiting to be told

    @app.post("/api/talk")
    def talk(audio: UploadFile = File(...), x_jarvis_token: str | None = Header(None),
             wait: bool = Query(True)):
        """Voice in, voice out. wait=false (the web app): returns an id straight away and keeps
        working even if the app is swiped away; collect it from GET /api/talk/{id}."""
        check(x_jarvis_token)
        suffix = ".mp4" if "mp4" in (audio.content_type or "") else ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio.file.read())
            path = f.name
        if wait:
            return _process_talk(path)
        return {"id": _start_talk(path=path)}

    def _start_talk(**kwargs) -> str:
        import secrets as _secrets

        talk_id = _secrets.token_urlsafe(8)
        with talks_lock:
            for old in [k for k, v in talks.items() if time.time() - v["created"] > 3600]:
                talks.pop(old)
            # A new message from the app replaces any still waiting: answering a backlog of old
            # (repeated) messages one by one is what made answers trickle into Telegram minutes later.
            for item in talks.values():
                if item["status"] == "working":
                    item["superseded"] = True
            talks[talk_id] = {"status": "working", "result": None, "created": time.time(), "fetched": False}
        future = pool.submit(_process_talk, talk_id=talk_id, **kwargs)
        future.add_done_callback(lambda f: _finish_talk(talk_id, f))
        return talk_id

    last_text_talk: dict = {}

    @app.post("/api/talk_text")
    def talk_text(payload: dict = Body(...), x_jarvis_token: str | None = Header(None)):
        """Like /api/talk, but the phone already recognised the speech. Returns an id to collect."""
        check(x_jarvis_token)
        text = str(payload.get("text", "")).strip()
        if not text:
            raise HTTPException(status_code=400, detail="No text")
        # Guard: the same words again within a few seconds is a replay, not a new request; hand
        # back the first one's answer instead of asking Claude twice.
        key = re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()
        prev = last_text_talk.get("key"), last_text_talk.get("at", 0), last_text_talk.get("id")
        if prev[0] == key and time.time() - prev[1] < 15 and prev[2] in talks:
            print(f"[web] ignored a repeat of {text!r}")
            return {"id": prev[2]}
        talk_id = _start_talk(text=text)
        last_text_talk.update(key=key, at=time.time(), id=talk_id)
        return {"id": talk_id}

    @app.get("/api/talk/{talk_id}")
    def talk_result(talk_id: str, x_jarvis_token: str | None = Header(None), wait: float = Query(0)):
        """wait=N: hold the request up to N seconds until the answer (or its first sentence) is ready,
        so the phone hears about it the moment it happens instead of checking repeatedly."""
        check(x_jarvis_token)
        with talks_lock:
            item = talks.get(talk_id)
            if not item:
                raise HTTPException(status_code=404, detail="Unknown or expired request")
            had_speech = bool(item.get("speech_id"))
            if wait > 0 and item["status"] != "done":
                talks_lock.wait_for(lambda: item["status"] == "done" or (not had_speech and item.get("speech_id")),
                                    timeout=min(wait, 20))
            if item["status"] != "done":
                return {"status": "working", "speech_id": item.get("speech_id", "")}
            item["fetched"] = True
            return {"status": "done", **item["result"]}

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
        if not text:   # Siri heard nothing: an error here would make the Shortcut quit
            nothing = "Sorry, I didn't catch that. Go ahead."
            if format == "siri":
                return {"say": nothing}
            if format == "text":
                return PlainTextResponse(nothing)
            raise HTTPException(status_code=400, detail="No text")
        print(f"\nYou: {text}")
        if format == "siri":
            siritrace.record("you", text)
        if format == "siri" and rt.dictation is None and GOODBYE.match(text.strip()):
            # Tell the Shortcut to end the conversation (its own "bye" check misses "by", "that's all"...).
            return {"say": FAREWELLS[int(time.time()) % len(FAREWELLS)], "stop": "yes"}
        if format == "siri" and rt.dictation is None and fastpath.HANDOFF.match(text):
            # Hand the conversation to the web app: open it and end the Siri loop.
            rt.recent = (rt.recent + [{"you": text, "jarvis": "(switched to the app)", "time": time.time()}])[-8:]
            return {"say": "Over to the app, sir. Tap the screen once and carry on.",
                    "open": fastpath.app_link(rt), "stop": "yes"}
        if format == "siri":
            # For the Siri Shortcut: what to say, plus phone actions for the Shortcut to perform.
            started = time.monotonic()
            announcer.begin_capture()
            try:
                reply = clean_for_speech(_voice_sized(ask_within_budget(text), text))
            finally:
                actions = announcer.end_capture()
            metrics.record("siri", time.monotonic() - started, late=reply == STILL_WORKING)
            opens = [a for a in actions if a["type"] == "open"]
            # Only include "open" when there is a link: Shortcuts counts an empty string as
            # "has any value" and would try to open it.
            result = {"say": reply}
            # The Shortcut then calls /api/wait and speaks the answer when ready. Only right after a
            # quick "One moment" / "Sent to your session": a longer chain makes Siri give up.
            if reply == clean_for_speech(STILL_WORKING) or (reply.startswith("Sent to your") and rt.active_awaiting()):
                result["wait"] = "yes"
                from . import location

                if location.wanted():
                    result["location"] = "yes"   # the Shortcut sends the phone's location with its wait call
                if location.eta_wanted():
                    result["eta"] = location.eta_wanted()   # the Shortcut asks Apple Maps how long it takes
            late_link = announcer.take_recent_open()
            if opens:
                result["open"] = opens[-1]["url"]
            elif late_link:
                result["open"] = late_link
            for extra in opens[:-1]:   # only one link can open at a time; send the rest to Telegram
                announcer.push(f"{extra['text']}\n{extra['url']}")
            print(f"JARVIS: {result}")
            siritrace.record("jarvis", result.get("say", "") + (" [then wait]" if result.get("wait") else "")
                             + (" [then stop]" if result.get("stop") else ""), time.monotonic() - started,
                             expect=("Shortcut never called the waiting step after this (Siri ended it, or the "
                                     "Shortcut's Mode/wait part isn't set up)") if result.get("wait") else
                                    "Siri conversation ended (no reply from you)",
                             within=12 if result.get("wait") else 40)
            return result
        if format == "text":
            started = time.monotonic()
            reply = clean_for_speech(ask_within_budget(text))
            metrics.record("siri", time.monotonic() - started, late=reply == STILL_WORKING)
            print(f"JARVIS: {reply}")
            return PlainTextResponse(reply)
        return respond(rt.ask(text), heard=text, with_audio=bool(payload.get("audio", True)))

    @app.api_route("/api/wait", methods=["GET", "POST"])   # GET too: Shortcuts' default method
    def wait_for_answer(payload: dict | None = Body(default=None), x_jarvis_token: str | None = Header(None),
                        token: str | None = Query(None)):
        """Called by the Siri Shortcut after "One moment": waits (up to the Siri budget) for a late
        answer or a Claude Code session's reply, and returns it to be spoken. "wait": "yes" again
        if it's still not ready."""
        payload = payload or {}
        check(x_jarvis_token or token or payload.get("token"))
        siritrace.record("wait", "Shortcut called the waiting step")
        if payload.get("lat") not in (None, "") and payload.get("lon") not in (None, ""):
            try:
                from . import location

                location.set_location(_coord(payload["lat"]), _coord(payload["lon"]), "Siri Shortcut")
                siritrace.record("location", "phone sent its location")
            except ValueError:
                pass
        got_eta = bool(str(payload.get("eta") or "").strip())
        if got_eta:
            from . import location

            location.set_eta(str(payload["eta"]))
            siritrace.record("location", f"phone sent a travel time: {payload['eta']}")
        wait_started = time.monotonic()
        rt.last_siri = wait_state["last"] = time.time()
        print("[siri] waiting for a late answer...")
        with pending_lock:
            open_items = [p for p in pending if not p["delivered"]]
            for p in open_items:
                p["waits"] = p.get("waits", 0) + 1
        if open_items and all(time.time() - p.get("asked_at", time.time()) > 40 for p in open_items):
            # Siri has waited long enough: let the conversation go on; the answer is sent to the
            # phone (Telegram) the moment it's ready.
            return {"say": "This one's taking a while, sir. I'll send it to your phone when it's ready. Anything else?"}
        # Shorter than a normal turn: this call comes right after Siri spoke "One moment", and
        # Siri gives up on a step that takes ~10 seconds.
        # Siri ends a Shortcut that runs about 10 seconds without hearing from you, and the
        # question, "One moment" and this wait all count. So: one short wait, then hand back.
        # (a little longer when the phone just sent a travel time: the answer is only a moment away)
        deadline = time.time() + float(os.getenv("JARVIS_SIRI_WAIT", "3")) + (2 if got_eta else 0)
        while time.time() < deadline:
            ready = _take_finished() + rt.take_siri_inbox()
            if ready:
                print("[siri] late answer handed to Siri")
                announcer.begin_capture()
                link = announcer.take_recent_open()
                announcer.end_capture()
                result = {"say": clean_for_speech(" ".join(ready))}
                if link:
                    result["open"] = link
                siritrace.record("jarvis", "late answer: " + result["say"], time.monotonic() - wait_started,
                                 expect="Siri conversation ended (no reply from you)", within=40)
                return result
            with pending_lock:
                waiting = any(not p["delivered"] for p in pending)
            if not waiting and not rt.active_awaiting():
                return {"say": "Anything else, sir?"}
            time.sleep(0.4)
        # Not ready: let Siri listen again (that keeps it alive). "Go on" waits for the answer again.
        say = ("It's taking a little longer, sir. I'll send it to your phone the moment it's ready, "
               "or say go on to keep waiting.")
        siritrace.record("jarvis", "not ready yet: " + say, time.monotonic() - wait_started,
                         expect="Siri conversation ended (no reply from you)", within=40)
        return {"say": say}

    @app.post("/api/wake")
    def wake(payload: dict = Body(default={}), x_jarvis_token: str | None = Header(None),
             token: str | None = Query(None)):
        """Called by the iPhone wake-up automation: ends night mode and returns the overnight summary
        as plain text, ready for the Shortcut to speak."""
        check(x_jarvis_token or token or payload.get("token"))
        return PlainTextResponse(clean_for_speech(rt.morning()))

    @app.post("/api/event")
    def phone_event(name: str = Query(...), payload: dict = Body(default={}),
                    x_jarvis_token: str | None = Header(None), token: str | None = Query(None)):
        """The iPhone tells Jarvis something happened (arrive_home, leave_home, car, ...) via a
        Shortcuts automation. Returns what to say, so the automation can speak it."""
        check(x_jarvis_token or token or payload.get("token"))
        from .tools.reminders import EVENTS, fire_event

        if name not in EVENTS:
            raise HTTPException(status_code=400, detail=f"Unknown event; use one of {', '.join(EVENTS)}")
        texts = fire_event(rt.ctx, name)
        greeting = {"arrive_home": f"Welcome home, {config.user_name}."}.get(name, "")
        say = " ".join([greeting] + [f"Reminder: {t}" for t in texts]).strip()
        for t in texts:   # also to Telegram, in case the phone can't speak right now
            announcer.push(f"Reminder: {t}")
        return PlainTextResponse(clean_for_speech(say))

    @app.post("/api/notify")
    def notify(payload: dict = Body(default={}), x_jarvis_token: str | None = Header(None),
               token: str | None = Query(None), label: str = Query("")):
        """Claude Code finished a task. Called by its Stop hook (scripts/claude-notify-hook.sh), usually
        through the public Tailscale Funnel link, so it accepts the low-privilege notify token."""
        key = x_jarvis_token or token or ""
        if not (key and (hmac.compare_digest(key, config.notify_token) or hmac.compare_digest(key, config.token))):
            raise HTTPException(status_code=401, detail="Bad or missing token")
        if payload.get("stop_hook_active"):   # Claude is continuing because of another hook; not done yet
            return {"result": "ignored (still working)"}
        if not label:
            cwd = str(payload.get("cwd") or "")
            label = cwd.rstrip("/").rsplit("/", 1)[-1] if cwd else ""
        label = label or str(payload.get("label", ""))
        summary = str(payload.get("summary") or payload.get("last_assistant_message") or "")
        return {"result": rt.claude_code_finished(label, clean_for_speech(summary),
                                                  int(payload.get("seconds", -1) or -1), str(payload.get("session", "")))}

    # ---- dashboard -------------------------------------------------------------------------
    def _job_view(j) -> dict:
        now = time.time()
        return {
            "id": j.id, "task": j.task, "status": j.status, "result": j.result,
            "continues": j.continues, "activity": j.activity[-15:],
            "preview": f"/preview/{j.preview}" if getattr(j, "preview", "") else "",
            "cloud_url": getattr(j, "cloud_url", ""), "branch": getattr(j, "branch", ""),
            "seconds": int((j.finished or now) - (j.started or j.created)) if j.started else 0,
            "created": j.created,
        }

    @app.get("/api/dashboard")
    def dashboard(x_jarvis_token: str | None = Header(None)):
        check(x_jarvis_token)
        from . import admin
        from .tools.memory import load_facts

        jobs = sorted(rt.jobs.jobs.values(), key=lambda j: j.id, reverse=True)[:20] if rt.jobs else []
        return {
            "user_name": config.user_name,
            "status": admin.status(config, rt.jobs, brain),
            "mode": announcer.mode,
            "night": announcer.night,
            "held": list(announcer._held),
            "claude_watch": rt.claude_watch,
            "jobs": [_job_view(j) for j in jobs],
            "memory": load_facts(config.data_dir),
            "stats": metrics.report(config.data_dir),
        }

    @app.post("/api/jobs")
    def new_job(payload: dict = Body(...), x_jarvis_token: str | None = Header(None)):
        check(x_jarvis_token)
        if rt.jobs is None:
            raise HTTPException(status_code=400, detail="Background jobs aren't available")
        task = str(payload.get("task", "")).strip()
        if not task:
            raise HTTPException(status_code=400, detail="No task")
        follow = payload.get("follow_up_of")
        job = rt.jobs.submit(task, continues=int(follow) if follow else None)
        return {"id": job.id}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: int, x_jarvis_token: str | None = Header(None)):
        check(x_jarvis_token)
        return {"result": rt.jobs.cancel(job_id) if rt.jobs else "No jobs"}

    @app.post("/api/control")
    def control(payload: dict = Body(...), x_jarvis_token: str | None = Header(None)):
        """Dashboard buttons: delivery mode, Claude Code watch, held items, memory, update."""
        check(x_jarvis_token)
        from . import admin
        from .tools.memory import forget

        action = payload.get("action")
        if action == "mode":
            if payload.get("value") == "wake":
                return {"result": rt.morning()}
            return {"result": announcer.set_mode(str(payload.get("value")))}
        if action == "watch":
            rt.set_claude_watch(str(payload.get("value", "off")))
            return {"result": f"Claude Code announcements: {rt.claude_watch}"}
        if action == "clear_held":
            return {"result": f"Cleared {len(announcer.take_held())} item(s)."}
        if action == "forget":
            return {"result": forget(rt.ctx, int(payload.get("value")))}
        if action == "update":
            return {"result": admin.update() if admin.update_available() else "Already on the latest version."}
        raise HTTPException(status_code=400, detail="Unknown action")

    @app.post("/api/reset")
    def reset(x_jarvis_token: str | None = Header(None)):
        check(x_jarvis_token)
        brain.reset()
        return {"ok": True}

    @app.get("/api/events")
    def events(after: int = 0, talking: int = 0, x_jarvis_token: str | None = Header(None)):
        """Things Jarvis says unprompted (timers, reminders, finished work) and phone actions.
        talking=1: the web app is in a voice conversation and will say them out loud itself, so the
        Telegram copy goes out silently instead of dinging over the conversation."""
        check(x_jarvis_token)
        if talking:
            announcer.web_talking_until = time.time() + 15
        return {"events": announcer.events_since(after)}

    def _coord(v) -> float:
        """A coordinate from Shortcuts ('47,6062' in some regions, or '47.6062 °')."""
        return float(str(v).replace(",", ".").replace("°", "").strip())

    @app.post("/api/location")
    def phone_location(payload: dict = Body(...), x_jarvis_token: str | None = Header(None),
                       token: str | None = Query(None)):
        """The phone's location, sent because Jarvis asked for it (web app or a Shortcut)."""
        check(x_jarvis_token or token or payload.get("token"))
        from . import location

        try:
            location.set_location(_coord(payload["lat"]), _coord(payload["lon"]), str(payload.get("source", "phone"))[:30])
        except (KeyError, ValueError):
            raise HTTPException(status_code=400, detail="Need lat and lon")
        return {"ok": True}

    @app.post("/api/diag")
    def diag(payload: dict = Body(default={}), x_jarvis_token: str | None = Header(None)):
        """Microphone diagnostics from the web app (levels, recognition errors), printed for /logs."""
        check(x_jarvis_token)
        if payload.get("event") == "location-denied":
            from . import location

            location.last_denied = time.time()
        if payload.get("event") == "answer-slow" and payload.get("id"):
            with talks_lock:   # the app stopped waiting: announce the answer the moment it's ready
                if payload["id"] in talks:
                    talks[payload["id"]]["handed_off"] = True
            print(f"[web] answer taking long; will announce it when ready ({payload['id']})")
            return {"ok": True}
        if payload.get("event") == "timing" and isinstance(payload.get("e2e"), (int, float)):
            metrics.record("web_e2e", float(payload["e2e"]))   # you stop talking -> Jarvis starts talking
            return {"ok": True}
        if payload.get("event") == "timing" and isinstance(payload.get("gap"), (int, float)):
            metrics.record("web_gap", float(payload["gap"]))   # Jarvis stops talking -> you can talk
            return {"ok": True}
        print(f"[web mic] {json.dumps(payload)[:400]}")
        return {"ok": True}

    @app.post("/api/voice")
    def voice(payload: dict = Body(...), x_jarvis_token: str | None = Header(None)):
        """Jarvis's voice for any text (e.g. a 'job done' announcement the web app reads out)."""
        check(x_jarvis_token)
        if payload.get("announcement"):   # it's being read out now: "what did I miss" needn't repeat it
            announcer.mark_read(str(payload.get("text", "")))
        parts = _speech_parts(clean_for_speech(str(payload.get("text", ""))[:3000])) if config.online_voice else []
        return {"speech_id": _start_speech(parts) if parts else "", "speech_parts": parts}

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
