# myStrategies

## usdc-usd-arb-monitor.py

USDC/USD arbitrage monitor for Revolut X.

### Strategy
Monitors price discrepancies between TOKEN/USDC and TOKEN/USD pairs on Revolut X.
When a profitable spread is detected (above threshold), executes:
1. Market buy on the cheaper pair
2. Market sell on the more expensive pair

### Configuration
- `TOKENS` — list of tokens to monitor
- `FEE` — taker fee per leg (0.0009 = 9 bps)
- `MIN_TICKER_BPS` — minimum spread threshold in basis points
- `TRADE_SIZES` — trade size tiers in USD (tries largest first)
- `BOT_TOKEN` — Telegram bot token for alerts
- `CHAT_ID` — Telegram chat ID for alerts

### Requirements
- [Revolut X CLI](https://github.com/revolut-engineering/revolut-x-api) (`revx`)
- Python 3.8+
- `requests` library

### Usage
```bash
python3 usdc-usd-arb-monitor.py
```

Logs to stdout. Run with `nohup` for background operation.
