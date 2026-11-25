# Installing Jarvis on Google Cloud from an iPhone (no pasting into the terminal)

Pasting into Google's browser terminal ("SSH-in-browser") often doesn't work on an iPhone. So:
1. Your details go into a normal web form, where pasting works.
2. You type one short command.
3. Login links come to Telegram; you tap them, and send any code back to your bot.

## 1. Put your details in the server's metadata (5 min)

In the Google Cloud console: ☰ › **Compute Engine** › **VM instances** › tap **jarvis** › **Edit** (top).
Scroll to **Metadata** › **Custom metadata** (or "Add item"). Add these as **key** / **value** pairs:

| Key | Value |
|---|---|
| `jarvis-telegram-token` | your bot token from @BotFather |
| `jarvis-telegram-user-id` | your numeric ID from @userinfobot |
| `jarvis-icloud-user` | your Apple ID email (optional) |
| `jarvis-icloud-password` | your app-specific password (optional) |

Tap **Save** at the bottom.

> Metadata is only visible to you, as the owner of this Google Cloud project. Once Jarvis is
> installed, the details are also stored on the server itself, so you can delete these metadata
> items afterwards (Edit › Metadata › remove › Save).

## 2. Type the install command (1 min)

Tap **SSH** on the `jarvis` row. In the black terminal, type exactly:

```
curl -sL raw.githubusercontent.com/C0RUPTT/Jarvis/HEAD/setup|bash
```

Typing tips:
- It's a zero in `C0RUPTT`, not the letter O, and it's case-sensitive.
- The `|` is on the iPhone keyboard under **123**, then **#+=**.
- Press return when done.

## 3. While it runs (15–20 min)
- You'll get a Telegram message: "connected to your Telegram".
- **Claude login:** tap the link in Telegram and approve. If the page shows a code, **send that code
  to your bot in Telegram**, and it's entered into the setup for you.
- **Tailscale login:** tap the link in Telegram, and sign in with the same account as your iPhone.
- **HTTPS approval:** if it sends this link, approve it, then type the install command again.
  Finished steps are skipped.
- **At the end:** Telegram receives your Siri URL, token and web app link.

If anything stops or errors, take a screenshot of the terminal and send it over.
