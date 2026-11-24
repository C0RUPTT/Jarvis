# J.A.R.V.I.S.

A personal voice assistant in the spirit of Tony Stark's, with Claude as the brain.

Say **"Hey Jarvis"**, ask for something, and it does it: it searches the web, opens apps,
runs commands, looks at your screen, sets timers, checks the weather, manages files and
remembers things about you between sessions. Afterwards it keeps listening for a few
seconds, so follow-up questions don't need the wake word again.

```
"Hey Jarvis"  ──►  you speak  ──►  Whisper (local speech-to-text)
                                        │
                                        ▼
                         Claude (thinks, picks tools, acts)  ◄──►  tools on your computer
                                        │                          + web search / fetch
                                        ▼
                               spoken reply (text-to-speech)
```

## What it can do

| Ability | Examples |
|---|---|
| Web search & reading pages | "What's the latest on the SpaceX launch?", "Summarise this article" |
| Run any shell command (asks you first) | "Turn the volume down", "What's using all my CPU?", "Pull the latest changes in my project" |
| Open apps & websites | "Open Spotify", "Pull up YouTube videos about arc reactors" |
| See your screen | "What's this error on my screen?", "Read me this email" |
| Timers & reminders (spoken aloud) | "Set a timer for 10 minutes for the pasta", "Remind me at 5:30 to call Pepper" |
| Weather | "Do I need an umbrella tomorrow?" |
| Files | "Find my resume", "Make a shopping list file with eggs and milk" |
| Clipboard | "Copy that to my clipboard", "Summarise what I just copied" |
| Long-term memory | "Remember my sister's birthday is March 3rd" |
| System status | "How's my battery?", "Run diagnostics" |

The `run_command` tool lets it do nearly anything else your computer can do.

## Setup

You need **Python 3.10+**, a microphone and an **Anthropic API key** (from https://console.anthropic.com).

```bash
git clone <this repo> && cd Jarvis
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then put your API key in .env
```

Platform notes:
- **Linux:** `sudo apt install portaudio19-dev espeak-ng xclip` (microphone, voice, clipboard).
- **macOS:** works out of the box and uses the British "Daniel" voice. Grant your terminal microphone
  access (and Screen Recording access for "look at my screen").
- **Windows:** works out of the box with the built-in Windows voices.

## Run it

```bash
python -m jarvis            # voice mode: say "Hey Jarvis"
python -m jarvis --ptt      # push-to-talk: press Enter, then speak
python -m jarvis --text     # type instead of talking (good for a first test)
```

The first voice run downloads the speech-recognition and wake-word models (about 150 MB). After
that they run offline.

Voice commands:
- **"Goodbye" / "That will be all"** shuts Jarvis down.
- **"New conversation" / "Start over"** clears the current conversation. Long-term memories stay.

## Safety

Before running a shell command or writing a file, Jarvis says what it is about to do and waits
for your "yes". Set `JARVIS_UNSAFE_NO_CONFIRM=1` in `.env` to turn that off; only do it if you
understand the risk.

## Settings (`.env`)

| Variable | Default | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Your Claude API key |
| `JARVIS_USER_NAME` | `sir` | What Jarvis calls you |
| `JARVIS_MODEL` | `claude-opus-5-5` | Which Claude model is the brain |
| `JARVIS_EFFORT` | `low` | `low` gives the fastest replies; `medium` or `high` think harder |
| `JARVIS_WHISPER_MODEL` | `base.en` | `tiny.en` is faster; `small.en` is more accurate |
| `JARVIS_WAKE_THRESHOLD` | `0.5` | Raise it if Jarvis wakes up by accident; lower it if it doesn't hear you |
| `JARVIS_TTS_VOICE` | (auto) | Name of a system voice to use |
| `JARVIS_TTS_RATE` | `185` | Speaking speed |

## Adding new abilities

Create a file in `jarvis/tools/` and decorate a function. Jarvis picks it up on the next start:

```python
from . import tool

@tool("flip_coin", "Flip a coin.")
def flip_coin(ctx):
    import random
    return random.choice(["heads", "tails"])
```

Pass `dangerous=True` to make Jarvis ask for confirmation before using the tool.

## Project layout

```
jarvis/
  __main__.py      entry point: voice / push-to-talk / text loops
  brain.py         Claude conversation, persona, and the tool-use loop
  config.py        settings from .env
  tools/           everything Jarvis can do (one file per area)
  voice/
    listener.py    "Hey Jarvis" wake word + Whisper speech-to-text
    tts.py         text-to-speech
```
