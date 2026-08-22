#!/usr/bin/env python3
"""
Monitor USDC/USD arb opportunities on RevX.
Step 1: Screen with tickers (parallel fetches).
Step 2: Confirm with orderbook (parallel fetches for both pairs simultaneously).
Step 3: Execute — IOC limit buy at VWAP, market sell of exact qty received.
"""
import subprocess, json, time, requests
from concurrent.futures import ThreadPoolExecutor, as_completed

TOKENS = [
    "ADA","AVAX","BCH","BNB","BONK","BTC","DOGE","DOT","ENA","ETH",
    "HBAR","JUP","LINK","LTC","PEPE","SHIB","SOL","SUI","TON","TRUMP",
    "TRX","XLM","XRP"
]
FEE = 0.0009
MIN_TICKER_BPS = 5
TRADE_SIZES = [100.0, 50.0, 10.0]
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"

# Preload quote_step for all relevant pairs
def load_pair_configs():
    data = revx_json(["market", "pairs", "--output", "json"])
    configs = {}
    try:
        pairs = data if isinstance(data, list) else data.get("pairs", data.get("data", []))
        for p in pairs:
            sym = p.get("symbol", "").replace("/", "-")
            qs = p.get("quote_step")
            if qs:
                # Use Decimal to correctly handle scientific notation (e.g. 1e-05)
                from decimal import Decimal
                decimals = max(0, -Decimal(str(qs)).as_tuple().exponent)
                configs[sym] = decimals
    except:
        pass
    return configs

PAIR_DECIMALS = {}  # populated at startup

def round_to_step(price, symbol):
    """Round price to the quote_step precision for the given symbol."""
    decimals = PAIR_DECIMALS.get(symbol, 8)
    return round(price, decimals)

def revx_run(args, timeout=10):
    try:
        r = subprocess.run(["revx"] + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1

def revx_json(args, timeout=8):
    try:
        r = subprocess.run(["revx"] + args, capture_output=True, text=True, timeout=timeout)
        return json.loads(r.stdout)
    except:
        return None

def get_ticker(symbol):
    data = revx_json(["market", "tickers", symbol, "--output", "json"])
    try:
        t = data["data"][0]
        return float(t["ask"]), float(t["bid"])
    except:
        return None, None

def get_ticker_pair(token):
    """Fetch USDC and USD tickers in parallel."""
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_usdc = ex.submit(get_ticker, f"{token}-USDC")
        f_usd  = ex.submit(get_ticker, f"{token}-USD")
        usdc_ask, usdc_bid = f_usdc.result()
        usd_ask,  usd_bid  = f_usd.result()
    return usdc_ask, usdc_bid, usd_ask, usd_bid

def get_orderbooks(token):
    """Fetch both orderbooks simultaneously."""
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_usdc = ex.submit(revx_json, ["market", "orderbook", f"{token}-USDC", "--limit", "20", "--output", "json"])
        f_usd  = ex.submit(revx_json, ["market", "orderbook", f"{token}-USD",  "--limit", "20", "--output", "json"])
        ob_usdc = f_usdc.result()
        ob_usd  = f_usd.result()
    return ob_usdc, ob_usd

def get_balance(currency):
    data = revx_json(["account", "balances", currency, "--output", "json"])
    try:
        if isinstance(data, dict) and "available" in data:
            return float(data["available"])
        items = data.get("data", data) if isinstance(data, dict) else data
        for b in items:
            if b["currency"].upper() == currency.upper():
                return float(b["available"])
    except:
        pass
    return 0.0

def vwap_from_book(levels, size_usd, is_ask=True):
    """Returns (vwap, worst_price) or (None, None) if insufficient depth.
    worst_price = max ask level touched (for buy limit price) or min bid level touched."""
    sorted_levels = sorted(levels, key=lambda l: float(l["price"]), reverse=not is_ask)
    filled_usd = 0.0
    filled_qty = 0.0
    worst_price = None
    for level in sorted_levels:
        price = float(level["price"])
        qty   = float(level["quantity"])
        level_usd = qty * price
        needed = size_usd - filled_usd
        worst_price = price
        if level_usd >= needed:
            filled_qty += needed / price
            filled_usd += needed
            break
        else:
            filled_qty += qty
            filled_usd += level_usd
    if filled_usd < size_usd * 0.999:
        return None, None
    return filled_usd / filled_qty, worst_price

def send_alert(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=5
        )
    except:
        pass

def execute_arb(token, buy_pair, buy_currency, sell_pair, ticker_bps, asks_buy, bids_sell):
    buy_balance = get_balance(buy_currency)

    for size in TRADE_SIZES:
        buy_vwap,  buy_worst  = vwap_from_book(asks_buy,  size, is_ask=True)
        sell_vwap, sell_worst = vwap_from_book(bids_sell, size, is_ask=False)
        if not buy_vwap or not sell_vwap:
            print(f"  Insufficient depth at ${size:.0f} — trying smaller...", flush=True)
            continue

        net_bps = ((sell_vwap*(1-FEE)) - (buy_vwap/(1-FEE))) / buy_vwap * 10000
        if net_bps <= MIN_TICKER_BPS:
            print(f"  Not profitable at ${size:.0f}: {net_bps:.1f}bps — trying smaller...", flush=True)
            continue

        if buy_balance < size:
            print(f"  Insufficient {buy_currency} for ${size:.0f} ({buy_balance:.2f}) — trying smaller...", flush=True)
            continue

        print(f"  ✅ Executing at ${size:.0f} ({net_bps:.1f}bps) | buy_vwap={buy_vwap:.6f} sell_vwap={sell_vwap:.6f}", flush=True)

        # Leg 1: IOC limit buy — max price derived from profitability threshold
        print(f"  → BUY {buy_pair} --quote {size} --market", flush=True)
        buy_out, buy_rc = revx_run([
            "order", "place", buy_pair, "buy",
            "--quote", str(size),
            "--market",
            "--output", "json"
        ])
        print(f"  BUY result: {buy_out[:200]}", flush=True)

        # Step 1: Check place response for immediate cancellation
        if not buy_out or buy_out.strip() == "":
            print(f"  Buy returned empty — skipping", flush=True)
            send_alert(f"⚠️ BUY FAILED: {token}\nPair: {buy_pair} | Size: ${size:.0f}")
            return
        try:
            buy_place = json.loads(buy_out)
            place_state = buy_place.get("data", {}).get("state", "")
            buy_order_id = buy_place.get("data", {}).get("id", "") or buy_place.get("data", {}).get("venue_order_id", "")
            if place_state in ("cancelled", "rejected"):
                print(f"  Buy rejected (state={place_state})", flush=True)
                send_alert(f"⚠️ BUY FAILED: {token}\nPair: {buy_pair} | Size: ${size:.0f}\nState: {place_state}")
                return
        except:
            print(f"  Buy result not parseable — skipping", flush=True)
            return

        # Step 2: Fetch order by ID to get actual filled_quantity and total_fee
        print(f"  Fetching order details: {buy_order_id}", flush=True)
        buy_detail = revx_json(["order", "get", buy_order_id, "--output", "json"])
        if not buy_detail:
            send_alert(f"⚠️ ARB ERROR: {token} — could not fetch buy order {buy_order_id}")
            return

        buy_status     = (buy_detail.get("data", {}).get("status") or "").lower()
        buy_filled_qty = float(buy_detail.get("data", {}).get("filled_quantity") or 0)

        print(f"  status={buy_status} filled_qty={buy_filled_qty}", flush=True)

        if buy_status in ("cancelled", "rejected") or buy_filled_qty == 0:
            send_alert(f"⚠️ IOC BUY NOT FILLED: {token}\nStatus: {buy_status} | Filled qty: {buy_filled_qty}")
            return

        # Use actual available balance as sell qty (accounts for any fees deducted)
        token_balance = get_balance(token)
        print(f"  Available {token} balance for sell: {token_balance:.8f}", flush=True)

        if token_balance <= 0:
            send_alert(f"⚠️ ARB ERROR: {token} — no available balance to sell after buy")
            return

        # Leg 2: Market sell using filled_qty - base_fee from order details
        print(f"  → SELL {sell_pair} --qty {token_balance} --market", flush=True)
        sell_out, sell_rc = revx_run([
            "order", "place", sell_pair, "sell",
            "--qty", str(token_balance),
            "--market", "--output", "json"
        ])
        print(f"  SELL result: {sell_out[:200]}", flush=True)

        if not sell_out or sell_out.strip() == "":
            send_alert(f"⚠️ SELL FAILED: {token}\nSell {token_balance:.5f} via {sell_pair} returned empty.\nManual sell needed!")
            return

        # Compute actual P&L — reuse buy_detail already fetched, get sell details by ID
        actual_pnl_str = "(unknown)"
        try:
            sell_order_id = json.loads(sell_out).get("data", {}).get("id", "") or json.loads(sell_out).get("data", {}).get("venue_order_id", "")
            if sell_order_id:
                sell_detail = revx_json(["order", "get", sell_order_id, "--output", "json"])
                buy_paid   = float((buy_detail  or {}).get("data", {}).get("filled_amount") or 0)
                sell_gross = float((sell_detail or {}).get("data", {}).get("filled_amount") or 0)
                sell_fee   = float((sell_detail or {}).get("data", {}).get("total_fee")     or 0)
                sell_net   = sell_gross - sell_fee
                actual_pnl = sell_net - buy_paid
                actual_pnl_str = f"${actual_pnl:+.4f}"
                print(f"  Actual P&L: buy_paid={buy_paid:.4f} sell_gross={sell_gross:.4f} sell_fee={sell_fee:.4f} sell_net={sell_net:.4f} pnl={actual_pnl_str}", flush=True)
        except Exception as e:
            print(f"  P&L calc error: {e}", flush=True)

        msg = (
            f"⚡ ARB EXECUTED: {token}\n"
            f"Bought via {buy_pair} (market) for ${size:.0f}\n"
            f"Sold {token_balance:.5f} {token} via {sell_pair} (market)\n"
            f"Expected: {net_bps:.1f}bps | Actual P&L: {actual_pnl_str}\n"
            f"Buy: {'✅' if buy_rc == 0 else '❌'} | Sell: {'✅' if sell_rc == 0 else '❌'}"
        )
        send_alert(msg)
        return

    # All sizes failed — alert only if balance was the blocker
    profitable_sizes = []
    for size in TRADE_SIZES:
        bv, _ = vwap_from_book(asks_buy,  size, is_ask=True)
        sv, _ = vwap_from_book(bids_sell, size, is_ask=False)
        if bv and sv:
            bps = ((sv*(1-FEE)) - (bv/(1-FEE))) / bv * 10000
            if bps > MIN_TICKER_BPS:
                profitable_sizes.append((size, bps))

    if profitable_sizes and buy_balance < profitable_sizes[-1][0]:
        best_size, best_bps = profitable_sizes[0]
        msg = (
            f"⚠️ ARB MISSED (insufficient balance): {token}\n"
            f"Buy {buy_currency} needed: ${profitable_sizes[-1][0]:.0f} | Available: {buy_balance:.2f}\n"
            f"Best profitable size: ${best_size:.0f} at {best_bps:.1f}bps"
        )
        send_alert(msg)
    else:
        print(f"  No executable size for {token} (depth/profit issue)", flush=True)

def screen_token(token):
    """Ticker screen for a single token — called in parallel."""
    try:
        usdc_ask, usdc_bid, usd_ask, usd_bid = get_ticker_pair(token)
        if not all([usdc_ask, usdc_bid, usd_ask, usd_bid]):
            return None
        bps_1 = ((usd_bid*(1-FEE)) - (usdc_ask/(1-FEE))) / usdc_ask * 10000
        bps_2 = ((usdc_bid*(1-FEE)) - (usd_ask/(1-FEE))) / usd_ask  * 10000
        if bps_1 > MIN_TICKER_BPS or bps_2 > MIN_TICKER_BPS:
            return (token, bps_1, bps_2)
    except:
        pass
    return None

def check_and_execute():
    # Step 1: Ticker screen — all tokens in parallel (4 workers)
    candidates = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(screen_token, t): t for t in TOKENS}
        for f in as_completed(futures):
            result = f.result()
            if result:
                candidates.append(result)

    if not candidates:
        return

    # Step 2 + 3: Orderbook confirm and tiered execution
    for token, bps_1, bps_2 in candidates:
        print(f"  [{time.strftime('%H:%M:%S')}] Confirming {token} (L1={bps_1:.1f} L2={bps_2:.1f}bps)...", flush=True)

        # Fetch both orderbooks simultaneously
        ob_usdc, ob_usd = get_orderbooks(token)
        if not ob_usdc or not ob_usd:
            continue

        asks_usdc = ob_usdc["data"]["asks"]
        bids_usdc = ob_usdc["data"]["bids"]
        asks_usd  = ob_usd["data"]["asks"]
        bids_usd  = ob_usd["data"]["bids"]

        if bps_1 > MIN_TICKER_BPS:
            execute_arb(token, f"{token}-USDC", "USDC", f"{token}-USD", bps_1, asks_usdc, bids_usd)
            continue

        if bps_2 > MIN_TICKER_BPS:
            execute_arb(token, f"{token}-USD", "USD", f"{token}-USDC", bps_2, asks_usd, bids_usdc)

print("Loading pair configs...", flush=True)
PAIR_DECIMALS.update(load_pair_configs())
print(f"Loaded {len(PAIR_DECIMALS)} pair configs.", flush=True)
print(f"Starting USDC/USD arb monitor — parallel OB fetch, IOC limit buy, market sell, every 30s...", flush=True)
while True:
    try:
        check_and_execute()
        print(f"[{time.strftime('%H:%M:%S')}] Scan complete", flush=True)
    except Exception as e:
        print(f"Error: {e}", flush=True)
    time.sleep(30)
