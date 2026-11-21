#!/bin/bash
# Watchdog: restart arb bot if not running
# Ensure correct CLI version
ln -sf /usr/lib/node_modules/@revolut/revolut-x-cli/dist/bin/revx.js /usr/bin/revx
if ! pgrep -f "usdc-usd-arb-monitor.py" > /dev/null; then
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Bot not running — restarting..." >> /root/.openclaw/logs/arb-watchdog.log
    nohup python3 /root/.openclaw/scripts/usdc-usd-arb-monitor.py >> /root/.openclaw/logs/usdc-usd-arb.log 2>&1 &
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Restarted PID: $!" >> /root/.openclaw/logs/arb-watchdog.log
fi
