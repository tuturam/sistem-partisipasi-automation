#!/bin/sh
# Start a cloudflared Quick Tunnel (free, no token) and export its public HTTPS
# URL as the n8n webhook URL. The URL changes on every container start.
# Set DISABLE_TUNNEL=1 to skip and keep any existing WEBHOOK_URL.
if [ -z "$DISABLE_TUNNEL" ]; then
  cloudflared tunnel --no-autoupdate --url http://localhost:5678 >/tmp/cloudflared.log 2>&1 &
  URL=""
  for i in $(seq 1 40); do
    URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cloudflared.log | head -1)"
    [ -n "$URL" ] && break
    sleep 1
  done
  if [ -n "$URL" ]; then
    echo "[tunnel] public URL: $URL"
    export N8N_WEBHOOK_URL="$URL"
  else
    echo "[tunnel] failed to get tunnel URL:"; cat /tmp/cloudflared.log
  fi
fi
# Telegram keeps the previous (dead) tunnel URL registered as the bot webhook, which
# makes n8n refuse to register the new one ("webhook already claimed").
# Clear it for every bot token known to us: TELEGRAM_BOT_TOKEN from .env plus all
# Telegram credentials stored in n8n (read via the n8n CLI, no manual steps).
TOKENS="$TELEGRAM_BOT_TOKEN"
if n8n export:credentials --all --decrypted --output=/tmp/creds.json >/dev/null 2>&1; then
  TOKENS="$TOKENS $(grep -oE '"accessToken": *"[0-9]+:[^"]+"' /tmp/creds.json | sed -E 's/.*"([0-9]+:[^"]+)"$/\1/')"
fi
rm -f /tmp/creds.json
for T in $(echo "$TOKENS" | tr ' ' '\n' | sort -u); do
  [ -n "$T" ] && wget -qO- "https://api.telegram.org/bot$T/deleteWebhook" >/dev/null 2>&1 && echo "[tunnel] cleared old Telegram webhook for bot ${T%%:*}"
done
if [ -x /docker-entrypoint.sh ]; then exec /docker-entrypoint.sh "$@"; fi
exec n8n "$@"