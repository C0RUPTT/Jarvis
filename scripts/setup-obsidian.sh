#!/usr/bin/env bash
# One-time setup: connect your Obsidian Sync vault to this server with Obsidian's official headless
# client, so Jarvis can add to your notes by voice. Run it in the Google Cloud SSH window:
#     bash ~/Jarvis/scripts/setup-obsidian.sh
# You type your Obsidian login and vault password into Obsidian's own prompts here; they never go
# through Jarvis or the chat. The vault is downloaded into an EMPTY folder, so the first sync can only
# download: nothing in your vault can be changed or deleted by setting this up.
set -euo pipefail
VAULT_DIR="$HOME/vault"
say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "1/6  Node.js 22 (needed by Obsidian's client)"
if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 22 ]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi
node --version

say "2/6  Obsidian's headless client"
command -v ob >/dev/null || sudo npm install -g obsidian-headless
OB="$(command -v ob)"; echo "ob: $OB"

say "3/6  Sign in to Obsidian (your email, password and 2FA code if you use it)"
"$OB" login

say "4/6  Your vaults"
"$OB" sync-list-remote
read -r -p "Type the vault name exactly as shown above: " VAULT_NAME

if [ -d "$VAULT_DIR" ] && [ -n "$(ls -A "$VAULT_DIR")" ]; then
  echo "$VAULT_DIR isn't empty. To keep your vault safe, this script only sets up into an empty folder."
  echo "If it's from an earlier attempt: mv $VAULT_DIR ${VAULT_DIR}.old   then run this again."
  exit 1
fi
mkdir -p "$VAULT_DIR"

say "5/6  Connect the vault (it asks for the vault's encryption password if it has one) and download it"
"$OB" sync-setup --vault "$VAULT_NAME" --path "$VAULT_DIR" --device-name "Jarvis server"
"$OB" sync --path "$VAULT_DIR"
echo "Downloaded: $(find "$VAULT_DIR" -name '*.md' | wc -l) notes"

say "6/6  Keep it synced in the background (also after restarts)"
sudo tee /etc/systemd/system/obsidian-sync.service >/dev/null <<UNIT
[Unit]
Description=Obsidian Sync (headless) for Jarvis
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
ExecStart=$OB sync --path $VAULT_DIR --continuous
Restart=always
RestartSec=15
MemoryMax=250M
Nice=10

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now obsidian-sync
grep -q '^JARVIS_VAULT=' "$HOME/Jarvis/.env" 2>/dev/null || echo "JARVIS_VAULT=$VAULT_DIR" >> "$HOME/Jarvis/.env"
sudo systemctl restart jarvis
sleep 3
systemctl is-active obsidian-sync && say "Done. Try: \"Jarvis, add test idea to App Ideas.\""
