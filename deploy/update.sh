#!/usr/bin/env bash
# Pull latest code, upgrade dependencies (especially yt-dlp), restart the bot.
set -euo pipefail
BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BOT_DIR"
echo "=== $(date -Is) update ==="
git pull --ff-only
venv/bin/pip install -U -r requirements.txt
docker pull brainicism/bgutil-ytdlp-pot-provider >/dev/null 2>&1 && \
  docker restart bgutil-provider >/dev/null 2>&1 || true
sudo systemctl restart jengbot
echo "done"
