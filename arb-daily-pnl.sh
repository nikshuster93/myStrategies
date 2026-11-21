#!/bin/bash
# Daily P&L summary — uses revx transaction list (v1.0.49+)
set -a; . /root/.openclaw/telegram.env; set +a
BOT_TOKEN="${TELEGRAM_BOT_TOKEN:?missing in telegram.env}"
CHAT_ID="437052622"

# Ensure correct CLI version
ln -sf /usr/lib/node_modules/@revolut/revolut-x-cli/dist/bin/revx.js /usr/bin/revx

# Check if bot is running
if pgrep -f "usdc-usd-arb-monitor.py" > /dev/null; then
    STATUS="✅ Running"
else
    STATUS="❌ Stopped"
fi

# Fetch last 24h buy/sell transactions and compute P&L
STATS=$(python3 << 'EOF'
import subprocess, json

r = subprocess.run(
    ["revx", "transaction", "list", "--start-date", "24h", "--statuses", "completed", "--types", "buy,sell", "--output", "json"],
    capture_output=True, text=True, timeout=15
)
data = json.loads(r.stdout)
txns = data.get("data", [])

buys  = [t for t in txns if t["type"] == "buy"]
sells = [t for t in txns if t["type"] == "sell"]

sum_buys  = sum(float(t["source"]["amount"])      for t in buys)
sum_sells = sum(float(t["destination"]["amount"])  for t in sells)
pnl = sum_sells - sum_buys

print(f"{len(buys)}|{len(sells)}|{pnl:.4f}")
EOF
)

BUYS=$(echo "$STATS" | cut -d'|' -f1)
SELLS=$(echo "$STATS" | cut -d'|' -f2)
TOTAL=$(echo "$STATS" | cut -d'|' -f3)

MSG=$(printf "📊 Daily Arb P&L Summary\nDate: %s 08:00 UTC\nBot: %s\n\nLast 24h:\n  Buys:    %s\n  Sells:   %s\n  Net P&L: $%s" \
    "$(date -u '+%Y-%m-%d')" "$STATUS" "$BUYS" "$SELLS" "$TOTAL")

curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT_ID}" \
    --data-urlencode "text=${MSG}" > /dev/null
