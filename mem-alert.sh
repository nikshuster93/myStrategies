#!/bin/bash
# Alert via Telegram when available memory drops below threshold

# Token lives in telegram.env (TELEGRAM_BOT_TOKEN)
[ -z "$TELEGRAM_BOT_TOKEN" ] && . /root/.openclaw/telegram.env
BOT_TOKEN="$TELEGRAM_BOT_TOKEN"
[ -z "$BOT_TOKEN" ] && { echo "TELEGRAM_BOT_TOKEN not set" >&2; exit 1; }
CHAT_ID="437052622"
THRESHOLD_MB=150

AVAILABLE_MB=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
TOTAL_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
USED_MB=$((TOTAL_MB - AVAILABLE_MB))

if [ "$AVAILABLE_MB" -lt "$THRESHOLD_MB" ]; then
    MSG="⚠️ LOW MEMORY ALERT
Available: ${AVAILABLE_MB}MB / ${TOTAL_MB}MB
Used: ${USED_MB}MB ($(( USED_MB * 100 / TOTAL_MB ))%)
Threshold: ${THRESHOLD_MB}MB"

    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${CHAT_ID}" \
        -d "text=${MSG}" > /dev/null
fi
