#!/usr/bin/env python3
"""
Orderbook staleness monitor.
Fetches orderbooks for major pairs every second, logs:
- Best ask/bid prices
- Hash of top-5 ask levels (to detect duplicate snapshots)
- Age since last unique snapshot
- Cross-pair spread between USDC and USD versions
"""
import subprocess, json, time, hashlib, csv, os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

PAIRS = [
    ("BTC",  "BTC-USDC",  "BTC-USD"),
    ("ETH",  "ETH-USDC",  "ETH-USD"),
    ("XRP",  "XRP-USDC",  "XRP-USD"),
    ("SOL",  "SOL-USDC",  "SOL-USD"),
    ("DOGE", "DOGE-USDC", "DOGE-USD"),
]

INTERVAL = 1  # seconds between fetches
LOG_DIR = os.path.expanduser("~/.openclaw/logs/ob-staleness")
os.makedirs(LOG_DIR, exist_ok=True)

# Track rolling window of recent hashes per pair (last 30s)
from collections import deque
hash_window = {}   # sym -> deque of (timestamp, hash)
WINDOW_SECS = 30
stale_counts = {}
total_counts = {}

def revx_json(args, timeout=5):
    try:
        r = subprocess.run(["revx"] + args, capture_output=True, text=True, timeout=timeout)
        return json.loads(r.stdout)
    except:
        return None

def fetch_ob(symbol):
    return symbol, revx_json(["market", "orderbook", symbol, "--limit", "5", "--output", "json"])

def ob_hash(data):
    try:
        asks = data["data"]["asks"][:5]
        key = str([(a["price"], a["quantity"]) for a in asks])
        return hashlib.md5(key.encode()).hexdigest()[:8]
    except:
        return None

def best_prices(data):
    try:
        ask = float(data["data"]["asks"][0]["price"])
        bid = float(data["data"]["bids"][0]["price"])
        return ask, bid
    except:
        return None, None

# CSV log file (one per run)
run_ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
csv_path = os.path.join(LOG_DIR, f"staleness-{run_ts}.csv")
csv_file = open(csv_path, "w", newline="")
writer = csv.writer(csv_file)
writer.writerow([
    "timestamp", "token",
    "usdc_ask", "usdc_bid", "usdc_hash", "usdc_stale",
    "usd_ask",  "usd_bid",  "usd_hash",  "usd_stale",
    "cross_spread_bps"
])
csv_file.flush()

print(f"Logging to {csv_path}", flush=True)
print(f"Fetching {len(PAIRS)} token pairs every {INTERVAL}s — Ctrl+C to stop\n", flush=True)
print(f"{'Time':12} {'Token':6} {'USDC Ask':10} {'USD Ask':10} {'Spread':8} {'USDC Stale':12} {'USD Stale':10}", flush=True)
print("-" * 75, flush=True)

iteration = 0
try:
    while True:
        iteration += 1
        ts = datetime.utcnow().strftime("%H:%M:%S.%f")[:-3]
        now = time.time()

        # Fetch all pairs in parallel
        symbols = [p for token, usdc_sym, usd_sym in PAIRS for p in (usdc_sym, usd_sym)]
        results = {}
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(fetch_ob, sym): sym for sym in symbols}
            for f in futures:
                sym, data = f.result()
                results[sym] = data

        for token, usdc_sym, usd_sym in PAIRS:
            ob_usdc = results.get(usdc_sym)
            ob_usd  = results.get(usd_sym)

            h_usdc = ob_hash(ob_usdc)
            h_usd  = ob_hash(ob_usd)

            # Detect staleness: hash seen in rolling 30s window
            usdc_stale = False
            usd_stale  = False
            stale_age_usdc = 0
            stale_age_usd  = 0

            def check_stale(sym, h):
                if sym not in hash_window:
                    hash_window[sym] = deque()
                # Evict entries older than WINDOW_SECS
                while hash_window[sym] and now - hash_window[sym][0][0] > WINDOW_SECS:
                    hash_window[sym].popleft()
                # Check if hash appeared in window
                seen_at = next((t for t, hh in hash_window[sym] if hh == h), None)
                # Add current entry
                hash_window[sym].append((now, h))
                return seen_at  # None = fresh, timestamp = when we last saw this snapshot

            if h_usdc:
                seen_at = check_stale(usdc_sym, h_usdc)
                if seen_at:
                    usdc_stale = True
                    stale_age_usdc = round(now - seen_at, 1)
                    stale_counts[usdc_sym] = stale_counts.get(usdc_sym, 0) + 1
                total_counts[usdc_sym] = total_counts.get(usdc_sym, 0) + 1

            if h_usd:
                seen_at = check_stale(usd_sym, h_usd)
                if seen_at:
                    usd_stale = True
                    stale_age_usd = round(now - seen_at, 1)
                    stale_counts[usd_sym] = stale_counts.get(usd_sym, 0) + 1
                total_counts[usd_sym] = total_counts.get(usd_sym, 0) + 1

            usdc_ask, usdc_bid = best_prices(ob_usdc)
            usd_ask,  usd_bid  = best_prices(ob_usd)

            # Cross spread: buy USDC ask, sell USD bid
            cross_bps = None
            if usdc_ask and usd_bid:
                cross_bps = round((usd_bid - usdc_ask) / usdc_ask * 10000, 1)

            # Console output
            stale_usdc_str = f"STALE({stale_age_usdc}s)" if usdc_stale else "fresh"
            stale_usd_str  = f"STALE({stale_age_usd}s)"  if usd_stale  else "fresh"
            spread_str = f"{cross_bps:+.1f}bps" if cross_bps is not None else "N/A"
            print(f"{ts:12} {token:6} {str(usdc_ask):10} {str(usd_ask):10} {spread_str:8} {stale_usdc_str:12} {stale_usd_str}", flush=True)

            # CSV log
            writer.writerow([
                ts, token,
                usdc_ask, usdc_bid, h_usdc, usdc_stale,
                usd_ask,  usd_bid,  h_usd,  usd_stale,
                cross_bps
            ])

        csv_file.flush()

        # Print stale rate summary every 60 iterations
        if iteration % 60 == 0:
            print("\n=== STALENESS SUMMARY ===", flush=True)
            for sym in sorted(total_counts):
                total = total_counts[sym]
                stale = stale_counts.get(sym, 0)
                print(f"  {sym:12}: {stale}/{total} stale ({stale/total*100:.0f}%)", flush=True)
            print("=========================\n", flush=True)

        time.sleep(INTERVAL)

except KeyboardInterrupt:
    pass
finally:
    csv_file.close()
    print(f"\n=== FINAL STALENESS SUMMARY ===", flush=True)
    for sym in sorted(total_counts):
        total = total_counts[sym]
        stale = stale_counts.get(sym, 0)
        print(f"  {sym:12}: {stale}/{total} stale ({stale/total*100:.0f}%)", flush=True)
    print(f"\nLog saved to: {csv_path}", flush=True)
