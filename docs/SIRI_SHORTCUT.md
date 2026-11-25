# The Jarvis Siri Shortcut (one loop, handles slow answers and restarts)

Get your two links, with your token already in them: send **/shortcut** to the Jarvis bot in
Telegram, then long-press each link message and tap **Copy**.
- **ASK link:** ends in `/api/ask?format=siri&token=…`
- **WAIT link:** ends in `/api/wait?token=…`

## What it does
- You talk. Jarvis answers within about 8 seconds, or says "One moment, sir."
- After "One moment", the Shortcut waits for the real answer and speaks it, saying "Still working on it" every few seconds.
- After about 40 seconds it says "I'll send it to your phone", and the answer arrives on Telegram.
- If Jarvis is restarting (about 20 seconds after an update), the Shortcut says it couldn't reach Jarvis instead of crashing, and keeps listening.
- "Bye", "that's all" and similar end it. Jarvis recognises those itself.

## Build it (new Shortcut named **Jarvis**)
Variables are created by **Set Variable**. Type the names exactly: `Prompt`, `Mode`, `Response`.

1. **Text** `Yes, sir?` → **Set Variable** `Prompt`
2. **Text** `ask` → **Set Variable** `Mode`
3. **Repeat** `30` times
4. &nbsp;&nbsp;**If** `Mode` **is** `ask`
5. &nbsp;&nbsp;&nbsp;&nbsp;**Ask for Input** (Text) with prompt `Prompt`
6. &nbsp;&nbsp;&nbsp;&nbsp;**Get Contents of URL**: the **ASK link**.
   Method **POST**, Request Body **JSON**, add a **Text** field: key `text`, value **Provided Input**.
7. &nbsp;&nbsp;&nbsp;&nbsp;**Set Variable** `Response` to **Contents of URL**
8. &nbsp;&nbsp;**Otherwise**
9. &nbsp;&nbsp;&nbsp;&nbsp;**Speak Text** `Prompt`
10. &nbsp;&nbsp;&nbsp;**Get Contents of URL**: the **WAIT link**. Method **POST**.
11. &nbsp;&nbsp;&nbsp;**Set Variable** `Response` to **Contents of URL** (this new one)
12. &nbsp;&nbsp;**End If**
13. &nbsp;&nbsp;**If** `Response` **contains** `say`
    (if "contains" isn't offered, tap `Response` and set its type to **Text**)
14. &nbsp;&nbsp;&nbsp;&nbsp;**Get Dictionary Value** `say` in `Response` → **Set Variable** `Prompt`
15. &nbsp;&nbsp;&nbsp;&nbsp;**Get Dictionary Value** `open` in `Response` → **If** it **has any value** → **Open URLs** (Dictionary Value) → **End If**
16. &nbsp;&nbsp;&nbsp;&nbsp;**Get Dictionary Value** `stop` in `Response` → **If** it **has any value** → **Speak Text** `Prompt` → **Stop This Shortcut** → **End If**
17. &nbsp;&nbsp;&nbsp;&nbsp;**Get Dictionary Value** `wait` in `Response` → **If** it **has any value** → **Text** `wait` → **Set Variable** `Mode` → **Otherwise** → **Text** `ask` → **Set Variable** `Mode` → **End If**
18. &nbsp;&nbsp;**Otherwise**
19. &nbsp;&nbsp;&nbsp;&nbsp;**Text** `Sorry sir, I couldn't reach Jarvis. Say that again in a few seconds.` → **Set Variable** `Prompt`
20. &nbsp;&nbsp;&nbsp;&nbsp;**Text** `ask` → **Set Variable** `Mode`
21. &nbsp;&nbsp;**End If**
22. **End Repeat**

Run it with **"Hey Siri, Jarvis"** or the Action Button.

## Checking it works
Ask something slow ("search the web for today's top tech news"). You should hear "One moment, sir", then the answer, without touching the phone. Then send **/logs**: you should see `[siri] waiting for a late answer...`.
If an answer ever arrives on Telegram with "Siri didn't wait for this answer", the waiting part (steps 8–11 and 17) isn't set up right.
