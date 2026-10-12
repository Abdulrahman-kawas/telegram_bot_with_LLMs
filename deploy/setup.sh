#!/usr/bin/env bash
# Set up the uni-bot on a fresh Ubuntu 24.04 VM (AWS EC2, Oracle, GCP — same steps).
# Usage: copy the whole project folder to the server, then:  bash deploy/setup.sh
set -euo pipefail

APP_DIR=/opt/uni-bot
SRC="$(cd "$(dirname "$0")/.." && pwd)"

echo "== packages =="
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv rsync

echo "== copy project to $APP_DIR =="
sudo mkdir -p "$APP_DIR"
sudo rsync -a --delete \
    --exclude .venv --exclude .git --exclude data.json --exclude .env \
    --exclude '__pycache__' \
    "$SRC"/ "$APP_DIR"/

echo "== venv + deps =="
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
    sudo python3 -m venv "$APP_DIR/.venv"
fi
cd "$APP_DIR"
sudo "$APP_DIR/.venv/bin/pip" install -q -r requirements.txt

echo "== .env =="
if sudo [ ! -f "$APP_DIR/.env" ]; then
    sudo cp .env.example "$APP_DIR/.env"
    echo ">> created $APP_DIR/.env — edit it (TELEGRAM_BOT_TOKEN, LINE_*), then: sudo systemctl restart uni-bot"
fi
echo ">> reminder: LLM keys go in $APP_DIR/free-llms/.env (see free-llms/.env.example)"

echo "== systemd =="
sudo cp deploy/uni-bot.service /etc/systemd/system/uni-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now uni-bot
sudo systemctl --no-pager --full status uni-bot | head -12 || true
echo "== done. logs: sudo journalctl -u uni-bot -f =="
