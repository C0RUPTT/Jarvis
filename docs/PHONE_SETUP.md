# Jarvis on your iPhone: setup guide

**Total cost: $0** beyond the Claude Pro plan you already have.

```
 iPhone (anywhere)                                   Your laptop (at home, always on)
┌──────────────────────┐    private, encrypted     ┌───────────────────────────────────────────┐
│ Jarvis web app       │ ───── Tailscale ────────► │ Jarvis server                             │
│  - hands-free talk   │                           │  - Whisper turns your voice into text     │
│ "Hey Siri, Jarvis"   │ ◄──────────────────────── │  - Claude Code thinks and acts            │
│ Action Button        │   reply text + voice      │      (your Pro plan, no API bill)         │
│ ntfy notifications   │                           │  - tools: shell, web, apps, screen, mouse │
└──────────────────────┘                           │    and keyboard, timers, memory, phone    │
                                                   └───────────────────────────────────────────┘
```

| Piece | What it does | Cost |
|---|---|---|
| Claude Code | The brain. Runs on the laptop under your Claude Pro login | included in Pro |
| Whisper | Speech to text, runs on the laptop | free |
| Edge neural voice | Natural British voice ("Ryan") | free |
| Tailscale | Private link from phone to laptop from anywhere, with HTTPS | free (personal plan) |
| ntfy | Push notifications for timers, reminders and things Jarvis sends you | free |

> **Usage limits:** Claude Pro has usage limits that reset every few hours. Casual Jarvis
> use fits comfortably, but long coding sessions through Jarvis count toward the same
> limits as your normal Claude use.

---

## 1. Pick the laptop OS

You said Kubuntu or Windows. Both work.

- **Windows** if you want Jarvis to operate Windows desktop apps you use (clicking, typing).
  Mouse and keyboard control works out of the box.
- **Kubuntu** if the laptop is mostly a Jarvis server. It's lighter and more stable for
  running all the time. For mouse and keyboard control of apps, log in with the
  **"Plasma (X11)"** session (pick it on the login screen, if offered). Under Wayland, the
  screenshot and click tools can't see or control other apps. Everything else works either way.

## 2. Install on the laptop

### Kubuntu
```bash
sudo apt install -y git python3-venv python3-dev portaudio19-dev espeak-ng xclip ffmpeg
curl -fsSL https://claude.ai/install.sh | bash        # Claude Code
claude                                                # log in with your Claude account, then type /exit

git clone https://github.com/C0RUPTT/Jarvis.git ~/Jarvis && cd ~/Jarvis
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                  # then edit .env (step 3)
```

### Windows (PowerShell)
```powershell
winget install Python.Python.3.12 Git.Git
irm https://claude.ai/install.ps1 | iex               # Claude Code
claude                                                # log in with your Claude account, then type /exit

git clone https://github.com/C0RUPTT/Jarvis.git $HOME\Jarvis; cd $HOME\Jarvis
py -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env                                # then edit .env (step 3)
```

## 3. Configure `.env`

The defaults work. These are the settings worth changing:

```ini
JARVIS_USER_NAME=sir              # or your name
JARVIS_CC_MODEL=sonnet            # sonnet = fast and smart; opus = smartest, slower
JARVIS_NTFY_TOPIC=                # see step 6
```

Test it before involving the phone:

```bash
python -m jarvis --text
```

Ask something like "What's on my desktop?" or "Search the web for today's top news". If it
answers, the brain works.

> **If replies say something was "denied" or "not permitted":** Jarvis uses Claude Code's
> `auto` permission mode, where a safety check approves normal actions and blocks risky ones.
> If your account doesn't offer `auto`, set `JARVIS_CC_PERMISSION_MODE=acceptEdits` (file edits
> allowed; other commands may be refused). Use `bypassPermissions` only if you accept that
> Jarvis can run anything without asking.

## 4. Connect the phone privately with Tailscale

1. Create a free account at https://tailscale.com and install Tailscale on the **laptop**
   (Kubuntu: `curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up`;
   Windows: download the app and sign in).
2. Install **Tailscale** from the App Store on the **iPhone** and sign in with the same account.
3. Start Jarvis on the laptop:
   ```bash
   python -m jarvis serve
   ```
   It prints a link ending in `?token=...`. Keep that token secret.
4. In a second terminal on the laptop, give it an HTTPS address. The iPhone only allows
   microphone access over HTTPS.
   ```bash
   sudo tailscale serve --bg 8765        # Windows: run in an Administrator terminal, without sudo
   ```
   The first time, it prints a link for enabling HTTPS in your Tailscale admin console. Open it,
   then run the command again. It prints your address, like
   `https://my-laptop.tail1234.ts.net`.

Only your own devices on your Tailscale network can reach this address. It isn't on the public internet.

## 5. Set up the iPhone

### A. The Jarvis app (conversation mode)
1. In **Safari**, open `https://my-laptop.tail1234.ts.net/?token=YOUR_TOKEN`.
2. Tap **Share, then Add to Home Screen**. You now have a Jarvis icon.
3. Open it and tap the orb. Allow the microphone. Then just talk:
   - It listens, notices when you stop talking, answers out loud, and listens again.
   - Tap the orb while it's talking to interrupt. Tap again to stop the conversation.
   - Say "goodbye" or "that's all" to end the conversation.
   - The screen stays on while a conversation is active. Keep the app in front: iOS pauses
     web apps in the background.

### B. "Hey Siri, Jarvis" (hands-free, works with AirPods)
In the **Shortcuts** app, tap **+** and build:

1. **Repeat** 20 times:
   1. **Dictate Text** (tap it: Stop Listening **After Pause**)
   2. **If** *Dictated Text* **contains** `goodbye` then **Stop This Shortcut**, End If
   3. **Get Contents of URL**
      - URL: `https://my-laptop.tail1234.ts.net/api/ask?format=text`
      - Method: **POST**
      - Headers: `X-Jarvis-Token` = *your token*
      - Request Body: **JSON**, with key `text` = *Dictated Text*
   4. **Speak Text**: *Contents of URL* (open the options to pick a British voice like Daniel)
2. Name the shortcut **Jarvis**.

Now you can say **"Hey Siri, Jarvis"** with the phone in your pocket and AirPods in, ask
something, hear the answer, then ask a follow-up. It keeps going until you say goodbye.

**Action Button** (iPhone 15 Pro or later): Settings, then Action Button, then Shortcut, then **Jarvis**.
Press it from anywhere, even the lock screen, to talk to Jarvis.

### C. Notifications (timers, reminders, things Jarvis sends you)
1. Install **ntfy** from the App Store (free).
2. Make up a hard-to-guess topic name, like `jarvis-7f3k9q2x`, and subscribe to it in the ntfy app.
3. Put it in the laptop's `.env` as `JARVIS_NTFY_TOPIC=jarvis-7f3k9q2x`, then restart Jarvis.

Now "set a timer for 20 minutes" or "send me that recipe" arrives as a notification, even
when the Jarvis app is closed.

## 6. Let Jarvis use iPhone apps

Jarvis runs on the laptop, so it reaches the phone two ways:

- **Links that open apps:** directions in Maps, calling or texting someone, playing music,
  opening a website. This works automatically while the Jarvis app is open; otherwise it
  arrives as an ntfy notification you tap.
- **Your Shortcuts:** "run my Good Morning shortcut" or "add a calendar event". Jarvis can run
  any Shortcut by name. Shortcuts can set alarms, add calendar events and reminders, send
  iMessages, control HomeKit, change Focus modes and more. Make small Shortcuts for the things
  you want, and tell Jarvis their names (it remembers).

## 7. Keep it running

### Keep the laptop awake with the lid closed
- **Kubuntu:** System Settings, then Power Management: set "When laptop lid closed" to
  **Do nothing** and turn off sleep while plugged in.
- **Windows:** Control Panel, then Power Options, then "Choose what closing the lid does":
  set it to **Do nothing** when plugged in, and set Sleep to **Never** when plugged in.

### Start Jarvis automatically
- **Kubuntu:** System Settings, then Autostart, then **Add Login Script**, and pick
  `~/Jarvis/scripts/start-jarvis.sh`. Turn on automatic login if you want it to come back
  after a reboot without you.
- **Windows:** press Win+R, type `shell:startup`, and put a shortcut to
  `scripts\start-jarvis.bat` in that folder.

`tailscale serve --bg` keeps running and survives reboots, so you only run it once.

## 8. Things to try

- "What's the weather tomorrow? Do I need a jacket?"
- "Search for the best-rated ramen near me and send me the address"
- "What's on my screen right now?" / "Click the play button in Spotify"
- "In my project folder, find why the tests fail and fix it" (Claude Code at work)
- "Set a timer for 12 minutes for the pasta"
- "Remember that my gym is closed on Sundays"
- "Text Sam that I'm running 10 minutes late" (opens Messages with it typed out)
- "Run my Good Night shortcut"

## Troubleshooting

| Problem | Fix |
|---|---|
| The page says "Bad token" | Open the link with `?token=` again. The token is in `~/.jarvis/token` on the laptop |
| The microphone won't start | You must use the `https://...ts.net` address, not `http://` or an IP. Check Settings, then Safari, then Microphone |
| The voice sounds robotic | The free neural voice needs internet on the laptop. Otherwise the phone's own voice is used |
| Slow replies | Set `JARVIS_CC_MODEL=haiku` for speed, or `JARVIS_WHISPER_MODEL=tiny.en` on slow laptops |
| "Claude Code isn't installed" | Run `claude` in a terminal. If it's not found, re-run the installer from step 2 |
| Mouse and screen tools fail on Kubuntu | Log in with the "Plasma (X11)" session |
