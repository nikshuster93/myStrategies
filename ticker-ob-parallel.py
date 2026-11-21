#!/usr/bin/env python3
"""
Fetch ticker and orderbook simultaneously in parallel threads for multiple pairs.
Compare best bid/ask from both to check consistency.
"""
import subprocess, json, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from collections import Counter

PAIRS = ["BTC-USD", "ETH-USD", "XRP-USD", "SOL-USD", "JUP-USD"]
INTERVAL = 5

def revx_json(args, timeout=5):
    try:
        r = subprocess.run(["revx"] + args, capture_output=True, text=True, timeout=timeout)
        return json.loads(r.stdout)
    except:
        return None

stats = {p: {"total": 0, "ok": 0, "mismatch": 0, "bid_deltas": [], "ask_deltas": []} for p in PAIRS}

print(f"Fetching ticker + orderbook simultaneously for {len(PAIRS)} pairs every {INTERVAL}s")
print(f"{'Time':12} {'Pair':10} {'T.Bid':10} {'T.Ask':10} {'OB.Bid':10} {'OB.Ask':10} {'Bid Δ':8} {'Ask Δ':8} Status")
print("-" * 105)

iteration = 0
try:
    while True:
        iteration += 1
        ts = datetime.utcnow().strftime("%H:%M:%S.%f")[:-3]

        # Fire all tickers and orderbooks simultaneously
        with ThreadPoolExecutor(max_workers=10) as ex:
            ticker_futures = {p: ex.submit(revx_json, ["market", "tickers",   p, "--output", "json"]) for p in PAIRS}
            ob_futures     = {p: ex.submit(revx_json, ["market", "orderbook", p, "--limit", "100", "--output", "json"]) for p in PAIRS}
            ticker_results = {p: f.result() for p, f in ticker_futures.items()}
            ob_results     = {p: f.result() for p, f in ob_futures.items()}

        for pair in PAIRS:
            try:
                t_bid = float(ticker_results[pair]["data"][0]["bid"])
                t_ask = float(ticker_results[pair]["data"][0]["ask"])
            except:
                print(f"{ts:12} {pair:10} TICKER ERROR", flush=True)
                continue

            try:
                ob_bid = max(float(b["price"]) for b in ob_results[pair]["data"]["bids"])
                ob_ask = min(float(a["price"]) for a in ob_results[pair]["data"]["asks"])
            except:
                print(f"{ts:12} {pair:10} OB ERROR", flush=True)
                continue

            bid_d = (ob_bid - t_bid) / t_bid * 10000
            ask_d = (ob_ask - t_ask) / t_ask * 10000

            s = stats[pair]
            s["total"] += 1
            s["bid_deltas"].append(bid_d)
            s["ask_deltas"].append(ask_d)

            flags = []
            if abs(bid_d) > 10: flags.append(f"BID{bid_d:+.0f}bps")
            if abs(ask_d) > 10: flags.append(f"ASK{ask_d:+.0f}bps")
            if ob_bid > t_ask:  flags.append("OB.BID>T.ASK")
            if ob_ask < t_bid:  flags.append("OB.ASK<T.BID")

            if flags:
                s["mismatch"] += 1
                status = "⚠️  " + " | ".join(flags)
            else:
                s["ok"] += 1
                status = "✅ ok"

            print(f"{ts:12} {pair:10} {t_bid:10.2f} {t_ask:10.2f} {ob_bid:10.2f} {ob_ask:10.2f} {bid_d:+8.1f} {ask_d:+8.1f}  {status}", flush=True)

        # Summary every 20 iterations
        if iteration % 20 == 0:
            print(f"\n--- SUMMARY after {iteration} iterations ---", flush=True)
            for p in PAIRS:
                s = stats[p]
                if s["total"]:
                    print(f"  {p:10}: ok={s['ok']:3}/{s['total']:3} ({s['ok']/s['total']*100:.0f}%)  mismatch={s['mismatch']:3} ({s['mismatch']/s['total']*100:.0f}%)", flush=True)
            print(flush=True)

        time.sleep(INTERVAL)

except KeyboardInterrupt:
    pass
finally:
    import statistics as st
    print(f"\n=== FINAL SUMMARY ===")
    for p in PAIRS:
        s = stats[p]
        if not s["total"]: continue
        bd = s["bid_deltas"]
        ad = s["ask_deltas"]
        print(f"\n{p}:")
        print(f"  ok={s['ok']}/{s['total']} ({s['ok']/s['total']*100:.0f}%)  mismatch={s['mismatch']} ({s['mismatch']/s['total']*100:.0f}%)")
        print(f"  Bid Δ: mean={sum(bd)/len(bd):+.1f}  min={min(bd):+.1f}  max={max(bd):+.1f}  stddev={st.stdev(bd):.1f}  >10bps={sum(1 for v in bd if abs(v)>10)/len(bd)*100:.0f}%")
        print(f"  Ask Δ: mean={sum(ad)/len(ad):+.1f}  min={min(ad):+.1f}  max={max(ad):+.1f}  stddev={st.stdev(ad):.1f}  >10bps={sum(1 for v in ad if abs(v)>10)/len(ad)*100:.0f}%")
