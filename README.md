# J.A.R.V.I.S.

A personal assistant in the spirit of Tony Stark's that you talk to like the Claude or ChatGPT voice mode,
from your **iPhone, anywhere**. The brain is **Claude Code** running on your laptop under your
Claude Pro plan, so there's **no API bill**. Everything else is free.

```
iPhone  ──(Tailscale, private)──►  laptop: Whisper ► Claude Code ► tools ► spoken reply
 web app with hands-free conversation  │
 "Hey Siri, Jarvis" / Action Button    ├─ shell, files, code (Claude Code's own tools)
 ntfy notifications                    ├─ web search and reading pages
                                       ├─ see the screen, click, type: operate desktop apps
                                       ├─ open apps and links, run Shortcuts on the iPhone
                                       └─ timers, reminders, weather, clipboard, memory
```

**Start here: [docs/TONIGHT.md](docs/TONIGHT.md)** (phase 0 setup and test, about 60 minutes).
The full design and roadmap are in [docs/VISION.md](docs/VISION.md).

## What it can do

| Ability | Try saying |
|---|---|
| Conversation | Ask anything and follow up naturally. It remembers the conversation |
| Web | "What's the latest on the Artemis mission?", "Compare these two laptops for me" |
| Your computer | "What's using all my memory?", "Turn the volume down", "Find my resume" |
| Desktop apps | "What's on my screen?", "Pause Spotify", "Open VS Code and create a new file" |
| Claude Code | "In my website project, fix the broken contact form and commit it" |
| iPhone apps | "Directions to the nearest Target", "Text Sam I'm late", "Run my Good Night shortcut" |
| Timers & reminders | "Set a timer for 12 minutes", "Remind me at 5 to call Mom" (push notification) |
| Memory | "Remember my sister's birthday is March 3rd" (kept across conversations) |
| Weather, clipboard, system | "Do I need an umbrella?", "Summarise what I just copied", "How's my battery?" |

Because Claude Code can run commands and write code, it can usually find a way to do things that
don't have a dedicated tool.

## Ways to run it

```bash
python -m jarvis serve      # phone mode (main use): Siri, Telegram, web app
python -m jarvis doctor     # checks the setup and prints your Siri URL and token
python -m jarvis stats      # speed and Claude usage measurements
python -m jarvis --text     # type to Jarvis in the terminal (quick test)
python -m jarvis            # laptop voice mode: say "Hey Jarvis" to the laptop's microphone
python -m jarvis --ptt      # laptop voice mode with push-to-talk (Enter)
```

## Brains

| `JARVIS_BRAIN` | Cost | Notes |
|---|---|---|
| `claude-code` (default) | Included in Claude Pro/Max | Uses Claude Code's tools plus any MCP servers you've added to it. Subject to your plan's usage limits |
| `api` | Pay per use (API key) | Calls the Claude API directly, with its own built-in tool loop |

## Safety

- The phone server is reachable only over your private Tailscale network, and every request
  needs a secret token.
- With the Claude Code brain, Claude Code's `auto` permission mode screens each action:
  normal tasks run, and clearly risky ones are refused. See
  [PHONE_SETUP.md](docs/PHONE_SETUP.md#3-configure-env) to change that.
- With the API brain, shell commands and file writes need a spoken or typed "yes".

## Adding new abilities

Create a file in `jarvis/tools/` and decorate a function. Both brains pick it up when Jarvis next starts:

```python
from . import tool

@tool("flip_coin", "Flip a coin.")
def flip_coin(ctx):
    import random
    return random.choice(["heads", "tails"])
```

You can also add any MCP server to Claude Code itself (`claude mcp add ...`), for example
for Spotify, Home Assistant, Google Calendar or GitHub. Jarvis then gets those abilities too.

## Project layout

```
jarvis/
  __main__.py            entry point: serve / text / voice modes
  server.py              phone server (web app + API for iOS Shortcuts)
  web/index.html         the iPhone app: hands-free conversation UI
  runtime.py             wires everything together; every request goes fast path → Claude
  fastpath.py            instant commands without Claude (hold / quiet / what did I miss / job status)
  claude_code_brain.py   default brain: a lean, long-running Claude Code "talker" session
  jobs.py                background worker: full Claude Code for coding and building apps
  telegram.py            Telegram chat, voice notes and notifications
  metrics.py, doctor.py  measurements and the setup checker
  brain.py               alternative brain: the Claude API, plus brain selection
  mcp_bridge.py          gives Jarvis's tools to Claude Code (local MCP server)
  persona.py             Jarvis's personality and rules
  announcer.py           timers and phone actions go to the phone / ntfy
  tools/                 everything Jarvis can do (one file per area)
  voice/                 Whisper speech-to-text, wake word, text-to-speech
docs/PHONE_SETUP.md      setup guide
scripts/                 autostart scripts for Kubuntu and Windows
```
