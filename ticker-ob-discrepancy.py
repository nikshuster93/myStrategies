#!/usr/bin/env python3
"""
Monitor ticker vs orderbook discrepancies for BTC-USD.
Fetches ticker and orderbook simultaneously, compares bid/mid/ask.
Highlights discrepancies that could indicate stale data.
"""
import subprocess, json, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

SYMBOL = "BTC-USD"
INTERVAL = 2  # seconds

def revx_json(args, timeout=5):
    try:
        r = subprocess.run(["revx"] + args, capture_output=True, text=True, timeout=timeout)
        return json.loads(r.stdout)
    except:
        return None

def fetch_ticker():
    return revx_json(["market", "tickers", SYMBOL, "--output", "json"])

def fetch_ob():
    return revx_json(["market", "orderbook", SYMBOL, "--limit", "3", "--output", "json"])

print(f"Monitoring {SYMBOL} — ticker vs orderbook — every {INTERVAL}s")
print(f"{'Time':12} {'T.Bid':10} {'T.Ask':10} {'T.Mid':10} {'OB.Bid':10} {'OB.Ask':10} {'OB.Mid':10} {'Bid Δ':8} {'Ask Δ':8} {'Mid Δ':8} {'Note'}")
print("-" * 120)

while True:
    ts = datetime.utcnow().strftime("%H:%M:%S.%f")[:-3]

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_ticker = ex.submit(fetch_ticker)
        f_ob     = ex.submit(fetch_ob)
        ticker_data = f_ticker.result()
        ob_data     = f_ob.result()

    try:
        t = ticker_data["data"][0]
        t_bid = float(t["bid"])
        t_ask = float(t["ask"])
        t_mid = float(t["mid"])
    except:
        print(f"{ts:12} ERROR fetching ticker")
        time.sleep(INTERVAL)
        continue

    try:
        # Asks sorted high->low by API, so best (lowest) ask is last
        # Bids sorted high->low by API, so best (highest) bid is first
        ob_ask = min(float(a["price"]) for a in ob_data["data"]["asks"])
        ob_bid = max(float(b["price"]) for b in ob_data["data"]["bids"])
        ob_mid = (ob_bid + ob_ask) / 2
    except:
        print(f"{ts:12} ERROR fetching orderbook")
        time.sleep(INTERVAL)
        continue

    bid_delta = (ob_bid - t_bid) / t_bid * 10000   # bps
    ask_delta = (ob_ask - t_ask) / t_ask * 10000   # bps
    mid_delta = (ob_mid - t_mid) / t_mid * 10000   # bps

    # Flag discrepancies
    notes = []
    if abs(bid_delta) > 10: notes.append(f"BID MISMATCH {bid_delta:+.0f}bps")
    if abs(ask_delta) > 10: notes.append(f"ASK MISMATCH {ask_delta:+.0f}bps")
    if abs(mid_delta) > 10: notes.append(f"MID MISMATCH {mid_delta:+.0f}bps")
    if ob_bid > t_ask:      notes.append("⚠️ OB BID > TICKER ASK")
    if ob_ask < t_bid:      notes.append("⚠️ OB ASK < TICKER BID")
    if ob_bid >= ob_ask:    notes.append("⚠️ CROSSED OB")

    note_str = " | ".join(notes) if notes else "✅ ok"

    print(
        f"{ts:12} {t_bid:10.2f} {t_ask:10.2f} {t_mid:10.2f} "
        f"{ob_bid:10.2f} {ob_ask:10.2f} {ob_mid:10.2f} "
        f"{bid_delta:+8.1f} {ask_delta:+8.1f} {mid_delta:+8.1f}  {note_str}",
        flush=True
    )

    time.sleep(INTERVAL)
