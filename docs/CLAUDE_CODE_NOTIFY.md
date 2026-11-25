# "Claude Code is done" announcements: setup for other places

Your **Default** Claude Code environment is already set up. To get announcements from sessions in
another environment, or from Claude Code on a computer, add the same three pieces.

Your notify link (from `/notifysetup` in Telegram) looks like `https://ntfy.sh/jarvis-done-...`.

## Another Claude Code cloud environment
claude.ai › Code › environment menu › **Edit** the environment:
1. **Network › Allowed domains:** add `ntfy.sh`
2. **Environment variables:** `JARVIS_NOTIFY_URL=https://ntfy.sh/jarvis-done-...`
3. **Setup script:** copy the whole setup script from your **Default** environment (Edit › Setup
   script › select all › copy) and paste it in.

New sessions, and old ones the next time they wake up, then report to Jarvis.

## Claude Code on a computer (macOS / Linux)
```bash
curl -fsSL https://raw.githubusercontent.com/C0RUPTT/Jarvis/HEAD/scripts/claude-notify-hook.sh \
  -o ~/.claude/jarvis-notify && chmod +x ~/.claude/jarvis-notify
echo 'export JARVIS_NOTIFY_URL=https://ntfy.sh/jarvis-done-...' >> ~/.bashrc   # or ~/.zshrc
```
Then add this to `~/.claude/settings.json` (merge with what's there):
```json
{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "~/.claude/jarvis-notify", "timeout": 10}]}]}}
```

## Voice controls
- On by default for work that takes 30 seconds or more.
- "Tell me about every reply" (no minimum) / "Only tell me about long tasks" (2 minutes or more)
- "Stop telling me about Claude" / "Always tell me when Claude Code finishes"
- "Let me know when Claude Code is done" (just the next one, even when announcements are off)
- "Pick up on my Jarvis session: ..." (sends the message into that session)
