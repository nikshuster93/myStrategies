#!/usr/bin/env python3
"""
Check how frequently the same orderbook snapshot repeats.
Tracks hash of full ask+bid levels and reports repeat patterns.
"""
import subprocess, json, time, hashlib
from datetime import datetime

SYMBOL = "BTC-USD"
INTERVAL = 1  # seconds between fetches
HISTORY = 200  # keep last N hashes

def revx_json(args, timeout=5):
    try:
        r = subprocess.run(["revx"] + args, capture_output=True, text=True, timeout=timeout)
        return json.loads(r.stdout)
    except:
        return None

def ob_hash(data):
    try:
        asks = [(a["price"], a["quantity"]) for a in data["data"]["asks"]]
        bids = [(b["price"], b["quantity"]) for b in data["data"]["bids"]]
        key = str(asks) + str(bids)
        return hashlib.md5(key.encode()).hexdigest()[:10]
    except:
        return None

def best_ask(data):
    try: return min(float(a["price"]) for a in data["data"]["asks"])
    except: return None

def best_bid(data):
    try: return max(float(b["price"]) for b in data["data"]["bids"])
    except: return None

hashes = []       # list of (timestamp, hash, best_ask, best_bid)
seen = {}         # hash -> list of indices where it appeared
total = 0
repeats = 0

print(f"Monitoring {SYMBOL} orderbook every {INTERVAL}s — Ctrl+C to stop")
print(f"{'#':5} {'Time':12} {'Hash':12} {'Best Ask':10} {'Best Bid':10} {'Status'}")
print("-" * 70)

try:
    while True:
        ts = datetime.utcnow().strftime("%H:%M:%S.%f")[:-3]
        ob = revx_json(["market", "orderbook", SYMBOL, "--limit", "100", "--output", "json"])
        h = ob_hash(ob)
        ask = best_ask(ob)
        bid = best_bid(ob)

        if not h:
            print(f"{total:5} {ts:12} ERROR", flush=True)
            time.sleep(INTERVAL)
            continue

        total += 1

        if h in seen:
            repeats += 1
            prev_indices = seen[h]
            gaps = [total - 1 - i for i in prev_indices[-3:]]  # last 3 occurrences
            status = f"⚠️  REPEAT (seen at #{', #'.join(str(i+1) for i in prev_indices[-3:])} — gaps: {gaps})"
        else:
            status = "✅ new"

        seen.setdefault(h, []).append(total - 1)
        hashes.append((ts, h, ask, bid))

        print(f"{total:5} {ts:12} {h:12} {str(ask):10} {str(bid):10} {status}", flush=True)

        # Summary every 30 samples
        if total % 30 == 0:
            unique = len(seen)
            print(f"\n--- After {total} samples: {unique} unique snapshots, {repeats} repeats ({repeats/total*100:.0f}%) ---\n", flush=True)

        time.sleep(INTERVAL)

except KeyboardInterrupt:
    pass
finally:
    unique = len(seen)
    print(f"\n=== FINAL SUMMARY ===")
    print(f"Total samples:    {total}")
    print(f"Unique snapshots: {unique}")
    print(f"Repeated:         {repeats} ({repeats/total*100:.0f}%)")
    print(f"\nTop repeated snapshots:")
    top = sorted(seen.items(), key=lambda x: -len(x[1]))[:10]
    for h, indices in top:
        if len(indices) > 1:
            gaps = [indices[i+1]-indices[i] for i in range(len(indices)-1)]
            print(f"  {h}: seen {len(indices)}x at samples {indices[:5]}{'...' if len(indices)>5 else ''} | gaps: {gaps[:5]}")
