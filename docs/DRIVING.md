# Jarvis hands-free: driving, Maps open, phone locked

## What works and what doesn't

| Option | Works with Maps open or the phone locked? | Cost | Notes |
|---|---|---|---|
| **Siri Shortcut** ("Hey Siri, Jarvis") | **Yes**, including CarPlay and Bluetooth car audio | $0 | **Use this for driving.** Siri appears over Maps, and the conversation loop keeps talking until you say "bye". |
| Web app (Safari or home-screen app) | **No.** iPhone pauses web pages in the background and turns their microphone off. | $0 | Best for sit-down conversations. Switching apps now resumes listening without a tap when you come back. |
| Telegram | Partly. With CarPlay or AirPods, iPhone can read Jarvis's messages aloud (Announce Notifications). You can dictate a reply by voice. | $0 | Good for results that come in later, like finished jobs. |
| Native iPhone app (always listening in the background) | Would work: apps can keep the mic on in the background | See below | Not possible for free without a Mac |

## Driving setup (5 minutes, once)
1. **Settings → Siri → Talk to Siri → "Siri" or "Hey Siri"** on, and **Allow Siri When Locked** on.
2. **Settings → Notifications → Announce Notifications** on, plus **Telegram** on, plus **CarPlay** on (and **Headphones** on).
   Finished jobs and relayed replies are then read aloud in the car.
3. In the car: say **"Hey Siri, Jarvis"**, then talk normally. Say **"bye"** to end. Maps stays on screen.

## A native app later: costs and time
A real iPhone app can keep the microphone on with the screen off. Apple's "audio" background mode allows it, and that's how voice assistants and walkie-talkie apps do it.
- **Apple Developer Program: $99/year.** Needed to install your own app long-term. Without it, a free Apple ID install expires every 7 days and needs a Mac with Xcode to reinstall.
- **A Mac** to build it. Alternatives: a cloud Mac at about $20–30/month, or GitHub Actions macOS builds (limited free minutes on private repos).
- **Work:** about 1–2 weeks of Claude Code time. A small Swift app that streams the mic to this server, plays Jarvis's voice, and keeps going in the background. A CarPlay screen needs a further entitlement from Apple.
- **Recommendation:** use the Siri Shortcut for driving now. Consider the native app only if Siri's turn-by-turn style keeps getting in the way.
