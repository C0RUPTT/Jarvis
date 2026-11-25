#!/usr/bin/env bash
# Claude Code "Stop" hook: tells Jarvis that Claude Code finished a task, so Jarvis can announce it
# ("let me know when Claude Code is done"). Does nothing unless JARVIS_NOTIFY_URL is set, and never
# blocks or slows Claude Code down.
#
# JARVIS_NOTIFY_URL comes from your Jarvis bot's /notifysetup command. Set it as an environment
# variable: in your Claude Code cloud environment settings, or in your shell on a computer.
[ -n "${JARVIS_NOTIFY_URL:-}" ] || exit 0
label="$(basename "${CLAUDE_PROJECT_DIR:-$PWD}")"
curl -s -m 5 -o /dev/null -X POST "${JARVIS_NOTIFY_URL}&label=${label}" \
  -H "Content-Type: application/json" --data-binary @- >/dev/null 2>&1 || true
exit 0
