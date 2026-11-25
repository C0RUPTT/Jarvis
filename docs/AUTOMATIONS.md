# iPhone automations: "when I get home" reminders and friends

Reminders like "remind me to take the trash out **when I get home**" fire when your iPhone tells
Jarvis you've arrived. Set each one up once (2 minutes each), only for the events you want.

First, get your token: send `/shortcut` to your bot. The token is the part after `token=` in the
links it sends.

## Arrive home
**Shortcuts › Automation › + › Arrive**:
1. **Location:** choose your home address. **When:** Arrive. Choose **Run Immediately**, then Next.
2. **New Blank Automation** › add **Get Contents of URL**:
   - URL: `https://jarvis.taild4a500.ts.net/api/event?name=arrive_home&token=YOUR_TOKEN`
   - Expand it: Method **POST**
3. Add **Speak Text** › **Contents of URL**. You'll hear "Welcome home, sir" and any reminders.
4. Done.

## Other events (same steps, different trigger and name)
| Trigger in Shortcuts | `name=` in the URL | Reminder phrase |
|---|---|---|
| **Leave** (home) | `leave_home` | "when I leave home" |
| **Arrive** (work address) | `arrive_work` | "when I get to work" |
| **Leave** (work address) | `leave_work` | "when I leave work" |
| **CarPlay › Connects** (or **Bluetooth** › your car) | `car` | "when I get in the car" |

Location automations need **Location Services** on for Shortcuts
(Settings › Privacy & Security › Location Services › Shortcuts › While Using).
