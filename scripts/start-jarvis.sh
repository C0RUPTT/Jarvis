#!/usr/bin/env bash
# Starts the Jarvis phone server and restarts it if it ever crashes. Used for autostart on login.
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.local/bin:$PATH"   # where the Claude Code installer puts `claude`
mkdir -p "$HOME/.jarvis"
while true; do
  .venv/bin/python -m jarvis serve >> "$HOME/.jarvis/server.log" 2>&1
  echo "$(date): Jarvis stopped, restarting in 5s" >> "$HOME/.jarvis/server.log"
  sleep 5
done
