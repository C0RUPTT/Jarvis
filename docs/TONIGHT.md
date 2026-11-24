# Tonight: phase 0 setup and test (about 60 minutes)

The goal is to prove the risky parts on your real iPhone before building more:
1. Siri works with the phone **locked**, fast enough.
2. Telegram chat and notifications work.
3. The connection from phone to computer stays reliable.
4. We measure how much Claude usage real use takes.

This runs on your **Kubuntu** laptop tonight. Moving to the free Oracle server later is the same steps on a different computer.

**Done on your phone already?**
- Telegram bot token and your user ID saved in Notes
- Oracle signup started
- Tailscale app installed on the iPhone

If not, those steps are at the end of this guide.

---

## Step 1: Install on the laptop (15 min)

### Kubuntu: open Konsole and paste
```bash
sudo apt update && sudo apt install -y git python3-venv python3-dev ffmpeg portaudio19-dev
curl -fsSL https://claude.ai/install.sh | bash
exec $SHELL            # reload the terminal so `claude` is found
claude                 # log in with your Claude Pro account in the browser, then type /exit
git clone -b claude/zen-keller-np4wum https://github.com/C0RUPTT/Jarvis.git ~/Jarvis
cd ~/Jarvis && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Windows (only if you use Windows instead): open PowerShell and paste
```powershell
winget install -e Python.Python.3.12 Git.Git Gyan.FFmpeg
irm https://claude.ai/install.ps1 | iex
# close and reopen PowerShell, then:
claude                 # log in with your Claude Pro account in the browser, then type /exit
git clone -b claude/zen-keller-np4wum https://github.com/C0RUPTT/Jarvis.git $HOME\Jarvis
cd $HOME\Jarvis; py -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```
> If PowerShell refuses to run `Activate.ps1`, run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try again.
>
> If `git clone` asks for a password, use a GitHub personal access token, or download the ZIP
> of the `claude/zen-keller-np4wum` branch from GitHub instead.

## Step 2: Fill in `.env` (2 min)

Open `.env` in a text editor (Kubuntu: `kate .env`; Windows: `notepad .env`) and set:
```ini
JARVIS_USER_NAME=sir                       # or what you'd like to be called
JARVIS_TELEGRAM_TOKEN=123456:ABC...        # from @BotFather (in your Notes)
JARVIS_TELEGRAM_USER_ID=123456789          # from @userinfobot (in your Notes)
JARVIS_ICLOUD_USER=you@icloud.com          # your Apple ID email
JARVIS_ICLOUD_APP_PASSWORD=abcd-efgh-ijkl-mnop   # app-specific password (in your Notes)
```

## Step 3: First check (2 min)
```bash
python -m jarvis doctor
```
Everything except Tailscale should show ✅. Fix anything marked ❌ using the hint printed under it.

## Step 4: Tailscale on the laptop (5 min)

- **Kubuntu:** `curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up`, then open the link it prints and sign in.
- **Windows:** download Tailscale from tailscale.com/download and sign in with the same account as on your phone.

## Step 5: Start Jarvis (1 min)
```bash
python -m jarvis serve
```
Leave this window open. In a **second** terminal (Windows: an **Administrator** PowerShell):
```bash
sudo tailscale serve --bg 8765        # Windows: tailscale serve --bg 8765
```
The first time, it prints a link to enable HTTPS on your Tailscale network. Open it, approve, then run the command again.

Then run `python -m jarvis doctor` again. It now prints your **Siri URL**, your **web app URL** and your **token**.

## Step 6: Telegram test (2 min)

Open your bot in Telegram on the iPhone:
1. Send "hi".
2. Send a voice note: "what's the weather in London?"
3. Send "Build me a tip calculator web app. Just do it."

You should get a text reply, a voice reply, and later a "Job 1 is done" notification.

## Step 7: Build the Siri Shortcut on the iPhone (10 min)

In the **Shortcuts** app, tap **+**, name it **Jarvis**, and add these actions in order:

1. **Repeat** › set to `20` times. Inside the repeat:
   1. **Dictate Text**. Tap the arrow to expand it: Stop Listening = **After Pause**.
   2. **If** › *Dictated Text* › **contains** › `goodbye`
      - inside the If: **Stop This Shortcut**
      - **End If**
   3. **Get Contents of URL**
      - URL: your **Siri URL** from step 5 (ends in `/api/ask?format=text`)
      - Tap the arrow to expand: Method **POST**
      - Headers: add `X-Jarvis-Token` = *your token*
      - Request Body: **JSON**, add a field: key `text`, type Text, value *Dictated Text*
   4. **Speak Text** › *Contents of URL*. Expand it and pick a voice (for example Daniel, English (UK)).
2. Tap **Done**.

Then on the iPhone:
- **Settings › Siri:** turn on **Allow Siri When Locked**.
- **Tailscale app:** turn on **VPN On Demand** in its settings (if offered), so the connection comes back by itself.
- **Action Button** (if you have one): Settings › Action Button › Shortcut › **Jarvis**.
- **Settings › Notifications › Announce Notifications:** turn on, then allow **Telegram**. Siri then reads Jarvis's messages through your AirPods.
- **"Hey Jarvis" (iOS 18):** Settings › Accessibility › **Vocal Shortcuts** › Set Up, choose the
  **Jarvis** Shortcut and say "Hey Jarvis" three times when asked. This works best with the phone
  unlocked; with it locked, use "Siri, Jarvis" or the Action Button.

### The wake-up automation (ends night mode and reads you the overnight summary)
Night mode starts at 11pm. To end it when you get up, in **Shortcuts › Automation › +**:
1. Choose **Alarm** › **Is Stopped** (your wake-up alarm). Pick **Run Immediately**.
2. Add **Get Contents of URL**: your Siri URL, but ending in `/api/wake` instead of
   `/api/ask?format=text`. Method **POST**, with the same `X-Jarvis-Token` header.
3. Add **Speak Text** › *Contents of URL*.

If you don't use an alarm, choose **Sleep** › **Wake Up** (Sleep Focus turning off), or any
automation you like. Simply talking to Jarvis after 4am also ends night mode.

## Step 8: The phase 0 tests (15 min)

Lock the phone, then do each test:

| # | Test | Pass if |
|---|---|---|
| 1 | "Siri, Jarvis" … "What's 17 times 23?" | Correct answer in under 5 seconds |
| 2 | Repeat test 1 ten times over 10 minutes (lock the phone between tries) | 10 out of 10 work |
| 3 | "Siri, Jarvis" … "Hold everything" … then "Build me a coin-flip web app" | Instant "Holding everything", then "On it" |
| 4 | Wait 3 minutes, then "Siri, Jarvis" … "What did I miss?" | It tells you the coin-flip job is done |
| 5 | "Back to normal", then "Build me a dice-roller web app" | A Telegram notification when it's done (read aloud if AirPods are in) |
| 6 | Follow-up: "Make the dice roller dark mode" | A new job that changes the same app |
| 7 | Telegram voice note: "What's the weather tomorrow?" | A voice reply |
| 8 | Turn Wi-Fi off (mobile data only) and repeat test 1 | Still works away from home Wi-Fi |
| 9 | "Siri, Jarvis" … "What's on my calendar this week?" | Your real Apple Calendar events |
| 10 | "Add lunch with Sam tomorrow at noon to my calendar" | Appears in the iPhone Calendar app |

Then on the laptop:
```bash
python -m jarvis stats
```
**Send me** the output of `stats`, plus which tests passed or failed. That tells us whether to stay with Tailscale or switch to Cloudflare Tunnel, how fast Siri really is, and how much usage things take.

---

## If you haven't done the phone steps yet

**Telegram bot:**
1. Install Telegram, search **@BotFather**, tap Start and send `/newbot`.
2. Pick a name and a username ending in `bot`.
3. Save the **token** it gives you.
4. Then message **@userinfobot** and save your **Id**.
5. Open your bot and tap **Start**.

**Apple Calendar password:**
1. In Safari, go to **account.apple.com** and sign in.
2. Open **Sign-In and Security › App-Specific Passwords**, tap **+** and name it "Jarvis".
3. Save the password it shows (like `abcd-efgh-ijkl-mnop`) in Notes.

This password only works for calendar-style access, not your full Apple account. You can revoke it at any time on the same page.

**Tailscale:** install it from the App Store and sign in with the same account you'll use on the laptop.

## Troubleshooting

| Problem | Fix |
|---|---|
| Siri says it couldn't connect | Open the Tailscale app: is it connected? Is `python -m jarvis serve` still running? |
| Siri answers "Bad or missing token" | Check the `X-Jarvis-Token` header in the Shortcut matches the token from `doctor` |
| Telegram bot doesn't answer | Did you tap Start in the bot? Is `JARVIS_TELEGRAM_USER_ID` your ID from @userinfobot? Check the serve window for errors |
| Replies mention a permission being denied | Set `JARVIS_CC_PERMISSION_MODE=acceptEdits` in `.env` and restart |
| "Still working on that…" a lot | That's the 7-second rule; the answer arrives on Telegram. Tell me how often it happens |
