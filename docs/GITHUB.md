# Connect GitHub so Jarvis can work on your projects (5 minutes, on your phone)

Jarvis needs a GitHub **key** (a "fine-grained personal access token") to open your existing
repositories, such as flight-tracker, budget-app and habit-quest, work on them and save the changes back.

## 1. Make the key
1. In Safari, go to **github.com/settings/personal-access-tokens/new** and sign in.
2. **Token name:** `Jarvis`. **Expiration:** pick **1 year** (or "No expiration" if offered).
3. **Repository access:** **All repositories**.
4. **Permissions** › **Repository permissions**:
   - **Contents:** Read and write
   - **Pull requests:** Read and write
   - (Metadata: Read-only is added automatically)
5. Tap **Generate token** and **copy** it. It starts with `github_pat_`.

## 2. Give it to Jarvis
In Telegram, send your bot:
```
/github github_pat_xxxxxxxxxxxxxxxx
```
Jarvis checks the key, replies "Connected to GitHub as …", and **deletes your message** so the key
doesn't stay in the chat.

## 3. Use it
- "Open my flight tracker project and add a search by flight number"
- "What projects do I have?"
- "In budget-app, fix the chart on the summary page"

Jarvis downloads the project to your server, makes the changes, and pushes them to a **new branch**
named `jarvis/…`, so your main version is never changed without you knowing. To put the changes
straight onto main, say so: "…and push it to main".

To revoke access at any time, delete the token at github.com/settings/personal-access-tokens.
