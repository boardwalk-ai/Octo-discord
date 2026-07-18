#!/usr/bin/env bash
#
# One-shot installer for the Octo Discord bot.
# Run it from the repository root on your server:
#
#     bash deploy/setup.sh
#
# It creates a virtualenv, installs dependencies, and registers a systemd
# service so Octo stays running (and restarts on reboot / crash).
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "==> Installing Octo from: $APP_DIR"

# 1. Python virtualenv + dependencies
if ! command -v python3 >/dev/null; then
    echo "python3 is required. Install it first (e.g. apt install -y python3 python3-venv)."
    exit 1
fi
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
echo "==> Dependencies installed."

# 2. .env file
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo "==> Created $APP_DIR/.env — EDIT IT and add your tokens before starting."
fi

# 3. systemd service
SERVICE_SRC="$APP_DIR/deploy/octo.service"
SERVICE_DST="/etc/systemd/system/octo.service"
sed "s#__APP_DIR__#$APP_DIR#g" "$SERVICE_SRC" > /tmp/octo.service
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
$SUDO cp /tmp/octo.service "$SERVICE_DST"
$SUDO systemctl daemon-reload
$SUDO systemctl enable octo >/dev/null 2>&1 || true
echo "==> systemd service installed and enabled."

cat <<EOF

Done. Next steps:
  1. Edit your secrets:   nano $APP_DIR/.env
                          (DISCORD_TOKEN, GUILD_ID, OPENROUTER_API_KEY)
  2. Start the bot:       ${SUDO:+sudo }systemctl start octo
  3. Watch the logs:      journalctl -u octo -f
  4. Restart after edits: ${SUDO:+sudo }systemctl restart octo
EOF
