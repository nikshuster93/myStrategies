#!/bin/bash
# Start RevX EMA crossover monitors if not already running
LOG_DIR="$HOME/.openclaw/logs"
mkdir -p "$LOG_DIR"

start_monitor() {
  local direction=$1
  local logfile="$LOG_DIR/btc-ema-${direction}.log"
  
  if pgrep -f "revx monitor ema-cross BTC-USD --direction ${direction}" > /dev/null; then
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] ${direction} monitor already running, skipping." >> "$logfile"
  else
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Starting ${direction} monitor..." >> "$logfile"
    nohup revx monitor ema-cross BTC-USD --direction ${direction} --fast-period 12 --slow-period 48 --interval 60 >> "$logfile" 2>&1 &
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Started PID: $!" >> "$logfile"
  fi
}

start_monitor bullish
start_monitor bearish

# Grid bot is managed by systemd (revx-grid.service) — no manual restart needed
