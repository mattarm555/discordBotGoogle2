#!/usr/bin/env bash
# One-time server setup for JengBot on Ubuntu 22.04/24.04 (x86_64 or ARM).
# Usage (on the server):
#   curl -fsSL https://raw.githubusercontent.com/mattarm555/discordBotGoogle2/main/deploy/setup.sh | BRANCH=main bash
# or, from a clone:  BRANCH=main bash deploy/setup.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/mattarm555/discordBotGoogle2.git}"
BRANCH="${BRANCH:-main}"
BOT_DIR="${BOT_DIR:-$HOME/discordBotGoogle2}"
BOT_USER="$(id -un)"

echo "==> Installing system packages"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git ffmpeg libopus0 curl unzip docker.io

echo "==> Installing Deno (JS runtime yt-dlp needs for YouTube)"
if ! command -v deno >/dev/null 2>&1; then
  curl -fsSL https://deno.land/install.sh | sudo DENO_INSTALL=/usr/local sh -s -- -y
fi
deno --version | head -n1

echo "==> Starting bgutil PO-token provider (helps avoid YouTube 'confirm you're not a bot')"
sudo systemctl enable --now docker
sudo usermod -aG docker "$BOT_USER"
if ! sudo docker ps -a --format '{{.Names}}' | grep -qx bgutil-provider; then
  sudo docker run -d --name bgutil-provider --restart unless-stopped \
    -p 127.0.0.1:4416:4416 brainicism/bgutil-ytdlp-pot-provider
fi

echo "==> Getting the code ($BRANCH)"
if [ ! -d "$BOT_DIR/.git" ]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$BOT_DIR"
else
  git -C "$BOT_DIR" fetch origin && git -C "$BOT_DIR" checkout "$BRANCH" && git -C "$BOT_DIR" pull --ff-only
fi

echo "==> Python virtualenv + dependencies"
python3 -m venv "$BOT_DIR/venv"
"$BOT_DIR/venv/bin/pip" install -U pip
"$BOT_DIR/venv/bin/pip" install -U -r "$BOT_DIR/requirements.txt"

echo "==> Installing systemd service"
sed -e "s#__USER__#$BOT_USER#g" -e "s#__BOT_DIR__#$BOT_DIR#g" \
  "$BOT_DIR/deploy/jengbot.service" | sudo tee /etc/systemd/system/jengbot.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable jengbot

echo "==> Weekly auto-update (Mondays 05:00) to keep yt-dlp fresh"
CRON_LINE="0 5 * * 1 /bin/bash $BOT_DIR/deploy/update.sh >> $BOT_DIR/update.log 2>&1"
( crontab -l 2>/dev/null | grep -v 'deploy/update.sh' ; echo "$CRON_LINE" ) | crontab -
# update.sh restarts the service; allow that without a password prompt
echo "$BOT_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart jengbot" | sudo tee /etc/sudoers.d/jengbot >/dev/null
sudo chmod 440 /etc/sudoers.d/jengbot

if [ ! -f "$BOT_DIR/.env" ]; then
  echo
  echo "!! $BOT_DIR/.env is missing. Copy your data over (deploy/migrate.ps1 on Windows),"
  echo "   then run:  sudo systemctl start jengbot"
else
  sudo systemctl restart jengbot
  echo "==> Started. Follow logs with: journalctl -u jengbot -f"
fi
