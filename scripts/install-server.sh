#!/usr/bin/env bash
# Jarvis server installer for Ubuntu (Google Cloud free e2-micro, or any Ubuntu server).
#
# Run it on the server with ONE paste:
#   curl -fsSL https://raw.githubusercontent.com/C0RUPTT/Jarvis/claude/zen-keller-np4wum/scripts/install-server.sh | bash
#
# Short version to type on a phone (no pasting needed):
#   curl -sL raw.githubusercontent.com/C0RUPTT/Jarvis/HEAD/setup|bash
#
# Safe to run again: finished steps are skipped. Your Telegram and iCloud details are read from
# the server's Google Cloud "custom metadata" (a normal web form, see docs/GOOGLE_CLOUD.md) or
# asked for in the terminal. Login links are sent to your Telegram, and you can reply there with
# any code the login asks for, so nothing has to be pasted into the terminal.
set -euo pipefail

REPO="https://github.com/C0RUPTT/Jarvis.git"
BRANCH="claude/zen-keller-np4wum"
DIR="$HOME/Jarvis"
ENV_FILE="$DIR/.env"
PORT=8765

bold() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; tg_send "Jarvis setup: $*" 2>/dev/null || true; }
ask()  { local prompt="$1" var; read -r -p "$prompt" var </dev/tty; printf '%s' "$var"; }
env_get() { [ -f "$ENV_FILE" ] && grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }
env_set() {
  touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
  if grep -qE "^$1=" "$ENV_FILE"; then sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"; else echo "$1=$2" >> "$ENV_FILE"; fi
}
meta() {      # Google Cloud custom metadata (set in the console: VM > Edit > Metadata)
  curl -fs -m 3 -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1" 2>/dev/null || true
}
from_meta_or_ask() {  # $1 = .env key, $2 = metadata key, $3 = prompt ('' = optional, skip if missing)
  [ -n "$(env_get "$1")" ] && return 0
  local v; v="$(meta "$2")"
  if [ -z "$v" ] && [ -n "$3" ]; then v="$(ask "$3")"; fi
  [ -n "$v" ] && env_set "$1" "$v"
  return 0
}
tg_send() {   # send a message (e.g. a login link) to the owner's Telegram
  local token user; token="$(env_get JARVIS_TELEGRAM_TOKEN)"; user="$(env_get JARVIS_TELEGRAM_USER_ID)"
  [ -n "$token" ] && [ -n "$user" ] || return 0
  curl -s -o /dev/null "https://api.telegram.org/bot${token}/sendMessage" \
    --data-urlencode "chat_id=${user}" --data-urlencode "text=$1" || true
}

bold "1/8 Memory: adding 2 GB swap (the free server only has 1 GB)"
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  echo 'vm.swappiness=60' | sudo tee /etc/sysctl.d/99-jarvis.conf >/dev/null
fi
echo "ok"

bold "2/8 System packages"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git python3-venv python3-dev curl ca-certificates >/dev/null
echo "ok"

bold "3/8 Jarvis code"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull -q --ff-only; else git clone -q -b "$BRANCH" "$REPO" "$DIR"; fi
cd "$DIR"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements-server.txt
echo "ok"

bold "4/8 Your details (from the VM's custom metadata, or typed here)"
[ -n "$(env_get JARVIS_USER_NAME)" ] || env_set JARVIS_USER_NAME sir
from_meta_or_ask JARVIS_TELEGRAM_TOKEN   jarvis-telegram-token   'Telegram bot token (from @BotFather): '
from_meta_or_ask JARVIS_TELEGRAM_USER_ID jarvis-telegram-user-id 'Your Telegram user ID (from @userinfobot): '
from_meta_or_ask JARVIS_ICLOUD_USER         jarvis-icloud-user     ''
from_meta_or_ask JARVIS_ICLOUD_APP_PASSWORD jarvis-icloud-password ''
if [ -z "$(env_get JARVIS_TELEGRAM_TOKEN)" ] || [ -z "$(env_get JARVIS_TELEGRAM_USER_ID)" ]; then
  echo "Telegram details are missing. Add them as metadata (docs/GOOGLE_CLOUD.md) and run again."; exit 1
fi
# Server profile: small-memory friendly defaults.
env_set JARVIS_BRAIN claude-code
[ -n "$(env_get JARVIS_CC_MODEL)" ]       || env_set JARVIS_CC_MODEL sonnet
[ -n "$(env_get JARVIS_WORKER_MODEL)" ]   || env_set JARVIS_WORKER_MODEL sonnet
[ -n "$(env_get JARVIS_WHISPER_MODEL)" ]  || env_set JARVIS_WHISPER_MODEL tiny.en
[ -n "$(env_get JARVIS_QUIET_START)" ]    || env_set JARVIS_QUIET_START 23:00
env_set JARVIS_HOST 127.0.0.1
env_set JARVIS_PORT "$PORT"
tg_send "Jarvis setup: connected to your Telegram. Login links will arrive here."
echo "ok (a test message was sent to your Telegram)"

bold "5/8 Claude Code"
export PATH="$HOME/.local/bin:$PATH"
if ! command -v claude >/dev/null; then curl -fsSL https://claude.ai/install.sh | bash; fi
grep -q '.local/bin' "$HOME/.bashrc" || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
claude_ok() { claude auth status 2>/dev/null | grep -q '"loggedIn": *true'; }
if ! claude_ok; then
  echo "Log in with your Claude Pro account. The login link is sent to your Telegram."
  echo "If the login page shows a code, send that code to your bot in Telegram; it's typed in here for you."
  .venv/bin/python scripts/relay_links.py --reply claude auth login </dev/tty
fi
claude_ok && echo "ok: Claude Code is logged in" || { echo "Claude login didn't finish. Run this installer again."; exit 1; }
mkdir -p "$HOME/jarvis-projects"

bold "6/8 Tailscale (private link to your iPhone)"
if ! command -v tailscale >/dev/null; then curl -fsSL https://tailscale.com/install.sh | sh; fi
sudo tailscale set --accept-dns=false 2>/dev/null || true
if ! tailscale status >/dev/null 2>&1; then
  echo "Sign in with the SAME Tailscale account as your iPhone. The link is also sent to your Telegram."
  # --accept-dns=false: on Google Cloud, Tailscale DNS can block the server from reaching
  # metadata.google.internal, which breaks the console SSH button.
  sudo .venv/bin/python scripts/relay_links.py tailscale up --hostname=jarvis --accept-dns=false
fi
echo "ok"

bold "7/8 Jarvis service (starts on boot, restarts if it crashes)"
sudo tee /etc/systemd/system/jarvis.service >/dev/null <<UNIT
[Unit]
Description=Jarvis assistant
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$DIR
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$DIR/.venv/bin/python -m jarvis serve
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable -q jarvis
sudo systemctl restart jarvis
sleep 4
systemctl is-active --quiet jarvis && echo "ok: Jarvis is running" || { echo "Jarvis didn't start. Recent log:"; sudo journalctl -u jarvis -n 30 --no-pager; }

bold "8/8 HTTPS address for Siri and the web app"
# If HTTPS isn't enabled on the tailnet yet, this prints a link and waits; give up after 90s.
timeout 90 sudo tailscale serve --bg "$PORT" 2>&1 | tee /tmp/jarvis-serve.txt || true
if grep -q "https://login.tailscale.com" /tmp/jarvis-serve.txt; then
  link="$(grep -o 'https://[^ ]*' /tmp/jarvis-serve.txt | head -1)"
  tg_send "Jarvis setup: approve HTTPS for your Tailscale network here: $link (then run the installer again)"
  echo "Open the link above (also sent to Telegram) to turn on HTTPS, then run the installer again."
  exit 0
fi

bold "Checking everything"
.venv/bin/python -m jarvis doctor || true
DNS="$(tailscale status --json | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
TOKEN="$(cat "$HOME/.jarvis/token")"
tg_send "Jarvis is installed and running. Siri URL: https://$DNS/api/ask?format=text  Token: $TOKEN  Web app: https://$DNS/?token=$TOKEN"
echo
echo "Done! Your Siri URL, token and web app link were sent to your Telegram."
echo "Next: build the Siri Shortcut (docs/TONIGHT.md, step 7) and say hi to your bot."
