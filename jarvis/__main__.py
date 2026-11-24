"""Run Jarvis.

    python -m jarvis serve      # phone mode: Siri, Telegram and the web app (docs/TONIGHT.md)
    python -m jarvis doctor     # check the setup and say what to fix
    python -m jarvis stats      # speed and Claude usage measurements
    python -m jarvis            # laptop voice mode: say "Hey Jarvis", then talk
    python -m jarvis --ptt      # laptop voice mode, press Enter to talk instead of the wake word
    python -m jarvis --text     # type instead of talking (handy for testing)
"""

from __future__ import annotations

import argparse
import re
import sys

from . import runtime
from .config import Config

YES = re.compile(r"\b(yes|yeah|yep|sure|ok|okay|go ahead|do it|confirm|affirmative|please do)\b", re.I)
EXIT = re.compile(r"\b(goodbye|good bye|shut down|power down|that will be all|exit|quit)\b", re.I)
RESET = re.compile(r"\b(new conversation|start over|forget this conversation|reset)\b", re.I)


def run_text(config: Config) -> None:
    def confirm_text(question: str) -> bool:
        answer = input(f"JARVIS: {question} [y/N] ").strip().lower()
        return answer in {"y", "yes"} or YES.search(answer) is not None

    rt = runtime.build(config, speak=lambda t: print(f"\nJARVIS: {t}\nYou: ", end="", flush=True),
                       on_interim=lambda t: print(f"JARVIS: {t}"), confirm=confirm_text, telegram=False)
    brain = rt.brain
    print(f"JARVIS: At your service, {config.user_name}. (type 'exit' to quit, 'reset' for a new conversation)")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text.lower() in {"exit", "quit"}:
            brain.close()
            break
        if text.lower() in {"reset", "new conversation"}:
            brain.reset()
            print("JARVIS: Fresh slate.")
            continue
        print(f"JARVIS: {rt.ask(text)}")


def run_voice(config: Config, push_to_talk: bool) -> None:
    from .voice.listener import Listener
    from .voice.tts import Speaker

    speaker = Speaker(voice=config.tts_voice, rate=config.tts_rate)
    listener = Listener(config.whisper_model, config.wake_threshold, use_wake_word=not push_to_talk)

    def confirm(question: str) -> bool:
        speaker.say(question)
        answer = listener.listen(start_timeout=6)
        print(f"You: {answer}")
        return YES.search(answer) is not None

    rt = runtime.build(config, speak=lambda t: speaker.say(t, wait=False),
                       on_interim=lambda t: speaker.say(t), confirm=confirm, telegram=False)
    brain = rt.brain

    wake = listener.has_wake_word
    speaker.say(f"Jarvis online. {'Say Hey Jarvis' if wake else 'Press Enter'} when you need me, {config.user_name}.")

    while True:
        try:
            if wake:
                print("\n[listening for 'Hey Jarvis'...]")
                listener.wait_for_wake_word()
                speaker.say(f"Yes, {config.user_name}?")
            else:
                input("\n[press Enter and speak] ")

            # Conversation mode: after each reply, keep listening briefly for a follow-up.
            timeout = 8.0
            while True:
                print("[listening...]")
                text = listener.listen(start_timeout=timeout)
                if not text:
                    break
                print(f"You: {text}")
                if EXIT.search(text) and len(text.split()) <= 6:
                    speaker.say(f"Very good, {config.user_name}. Powering down.")
                    brain.close()
                    return
                if RESET.search(text) and len(text.split()) <= 6:
                    brain.reset()
                    speaker.say("Fresh slate.")
                    break
                speaker.say(rt.ask(text))
                timeout = 5.0
        except KeyboardInterrupt:
            print()
            speaker.say("Shutting down.")
            brain.close()
            return


def main() -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="A voice assistant powered by Claude.")
    parser.add_argument("mode", nargs="?", choices=["serve", "doctor", "stats"],
                        help="serve: phone server | doctor: check setup | stats: measurements")
    parser.add_argument("--speak-on-laptop", action="store_true",
                        help="with serve: also say timers/reminders out loud on the laptop")
    parser.add_argument("--text", action="store_true", help="type instead of speaking")
    parser.add_argument("--ptt", action="store_true", help="push-to-talk (Enter) instead of the wake word")
    args = parser.parse_args()

    config = Config.load()
    if args.mode == "doctor":
        from .doctor import run_doctor

        sys.exit(run_doctor(config))
    if args.mode == "stats":
        from .metrics import report

        print(report(config.data_dir))
        return
    if args.mode == "serve":
        try:
            from .server import serve
        except ImportError as e:
            sys.exit(f"Phone mode needs extra packages ({e}). Run: pip install -r requirements.txt")
        serve(config, speak_on_laptop=args.speak_on_laptop)
        return
    if args.text:
        run_text(config)
        return
    try:
        run_voice(config, push_to_talk=args.ptt)
    except ImportError as e:
        sys.exit(f"Voice mode needs extra packages ({e}). Run: pip install -r requirements.txt\n"
                 "Or try text mode: python -m jarvis --text")


if __name__ == "__main__":
    main()
