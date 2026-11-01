#!/usr/bin/env bash
# Send a photo to Dylan's Telegram DM. Usage: tg_photo.sh <file> [caption]
set -euo pipefail
ENV_FILE="$HOME/.hermes/.env"
TOKEN=$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' "$ENV_FILE" | tr -d '"'"'" | xargs)
CHAT="${TG_CHAT:-8473685304}"
[ -z "${TOKEN:-}" ] && { echo "no token" >&2; exit 1; }
FILE="$1"; CAP="${2:-}"
if [ -n "$CAP" ]; then
  curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendPhoto" \
    -F "chat_id=${CHAT}" -F "photo=@${FILE}" -F "caption=${CAP}" >/dev/null
else
  curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendPhoto" \
    -F "chat_id=${CHAT}" -F "photo=@${FILE}" >/dev/null
fi
echo "sent $(basename "$FILE")"
