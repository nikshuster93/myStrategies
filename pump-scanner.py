#!/usr/bin/env python3
"""Pump scanner: alert when a RevX pair's last price rises more than STEP_PCT
between each of STREAK consecutive runs (cron, every 5 min) and 24h quote
volume grew in each of those runs too."""
import json, os, subprocess, sys, time, urllib.parse, urllib.request

STEP_PCT = 5.0          # growth required in each run vs the previous run
STREAK = 3              # consecutive runs that must each exceed STEP_PCT
VOL_GROWTH = True       # require 24h quote volume to rise in each of those runs
COOLDOWN_S = 3600       # don't re-alert the same pair within this window
MAX_GAP_S = 900         # a gap longer than this between runs breaks the streak
STATE = "/root/.openclaw/state/pump-scanner.json"
CHAT_ID = "437052622"


def load_token():
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    if tok:
        return tok
    with open("/root/.openclaw/telegram.env") as f:
        for line in f:
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip("'\"")
    sys.exit("TELEGRAM_BOT_TOKEN missing")


def notify(text):
    url = f"https://api.telegram.org/bot{load_token()}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text}).encode()
    urllib.request.urlopen(url, data, timeout=15).read()


def num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def fetch():
    r = subprocess.run(["revx", "market", "tickers", "--json"],
                       capture_output=True, text=True, timeout=45)
    rows = json.loads(r.stdout)["data"]
    out = {}
    for t in rows:
        p = num(t.get("last_price"))
        if p is None:
            continue
        bid, ask = num(t.get("bid")), num(t.get("ask"))
        spread = (ask - bid) / ((ask + bid) / 2) * 100 if bid and ask else None
        out[t["symbol"]] = {"p": p, "vol": num(t.get("quote_volume_24h")) or 0.0,
                            "spread": spread}
    return out


def main():
    now = int(time.time())
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    try:
        st = json.load(open(STATE))
    except (OSError, ValueError):
        st = {}
    hist = st.get("hist", {})      # symbol -> [[ts, price, 24h vol], ...] newest last
    alerted = st.get("alerted", {})  # symbol -> ts of last alert
    prices = fetch()

    hits = []
    for sym, d in prices.items():
        h = [e for e in hist.get(sym, []) if len(e) == 3]  # drop pre-volume entries
        if h and now - h[-1][0] > MAX_GAP_S:
            h = []                  # missed runs: start a fresh streak
        h.append([now, d["p"], d["vol"]])
        h = h[-(STREAK + 1):]
        hist[sym] = h
        if len(h) < STREAK + 1:
            continue
        steps = [(h[i + 1][1] / h[i][1] - 1) * 100 for i in range(STREAK)]
        vsteps = [(h[i + 1][2] / h[i][2] - 1) * 100 if h[i][2] else 0.0 for i in range(STREAK)]
        if not all(s > STEP_PCT for s in steps):
            continue
        if VOL_GROWTH and not all(v > 0 for v in vsteps):
            continue
        if now - alerted.get(sym, 0) > COOLDOWN_S:
            alerted[sym] = now
            hits.append((sym, steps, vsteps, h[0][1], h[-1][1], h[0][2], h[-1][2], d["spread"]))

    # drop pairs no longer listed
    hist = {s: v for s, v in hist.items() if s in prices}
    json.dump({"hist": hist, "alerted": alerted}, open(STATE, "w"))

    if hits:
        lines = ["🚀 Fast growth on Revolut X"]
        for sym, steps, vsteps, p0, p1, v0, v1, spread in hits:
            sp = f"{spread:.2f}%" if spread is not None else "n/a"
            lines.append(
                f"\n{sym}: {p0:g} → {p1:g}\n"
                f"📈 Cumulative: +{(p1 / p0 - 1) * 100:.1f}% over {STREAK} runs ({STREAK * 5} min)\n"
                f"steps: " + ", ".join(f"+{s:.1f}%" for s in steps) + "\n"
                f"📊 24h volume: ${v0:,.0f} → ${v1:,.0f}\n"
                f"volume steps: " + ", ".join(f"{v:+.1f}%" for v in vsteps) + "\n"
                f"↔️ Spread now: {sp}")
        notify("\n".join(lines))


if __name__ == "__main__":
    main()
