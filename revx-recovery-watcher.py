#!/usr/bin/env python3
"""Recovery watcher (cron, every 5 min): once `revx` works again, re-enable the
pump scanner, then the arb bot if balances match the last known figures.

Healthy = `revx market currencies` and `revx account balances` both succeed in
2 consecutive runs. Removes its own cron line when finished."""
import json, os, subprocess, sys, time, urllib.parse, urllib.request

CHAT_ID = "437052622"
STATE = "/root/.openclaw/state/revx-recovery.json"
NEED_OK = 2                                  # consecutive healthy runs required
EXPECTED = {"USD": 4723.69, "USDC": 2947.98}  # last known balances, 19 Oct 18:45 UTC
TOLERANCE = 25.0                              # allowed drift per currency, in dollars
PUMP_MARK = "pump-scanner.py"
ARB_MARK = "arb-watchdog.sh"
SELF_MARK = "revx-recovery-watcher.py"


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


def revx(*args):
    try:
        r = subprocess.run(["revx", *args], capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return r.stdout if r.returncode == 0 else None


def parse_balances(out):
    """Return {currency: total} from `revx account balances --json`, or None."""
    try:
        data = json.loads(out)
    except (TypeError, ValueError):
        return None
    if isinstance(data, dict):
        data = data.get("balances") or data.get("data") or list(data.values())
    if not isinstance(data, list):
        return None
    res = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        cur = row.get("currency") or row.get("asset")
        total = row.get("total", row.get("balance"))
        if total is None:
            try:
                total = float(row.get("available", 0)) + float(row.get("reserved", 0))
            except (TypeError, ValueError):
                continue
        try:
            res[cur] = float(total)
        except (TypeError, ValueError):
            continue
    return res or None


def edit_cron(mark, enable=True, remove=False):
    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    out = []
    for line in cur.splitlines():
        if mark in line:
            if remove:
                continue
            if enable and line.startswith("#DISABLED# "):
                line = line[len("#DISABLED# "):]
        out.append(line)
    subprocess.run(["crontab", "-"], input="\n".join(out) + "\n", text=True, check=True)


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"ok": 0, "pump": False, "arb": False}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(st, f)


def main():
    st = load_state()
    cur_ok = revx("market", "currencies", "--json") is not None
    bal_out = revx("account", "balances", "--json") if cur_ok else None
    st["ok"] = st["ok"] + 1 if (cur_ok and bal_out is not None) else 0
    if st["ok"] < NEED_OK:
        save_state(st)
        return

    bal = parse_balances(bal_out)
    if not st["pump"]:
        edit_cron(PUMP_MARK)
        st["pump"] = True
        notify("✅ Revolut X API is working again (market + balance calls succeeded twice). "
               "Pump scanner re-enabled.")

    if not st["arb"]:
        if bal is None:
            notify("⚠️ revx works, but I couldn't read the balances output. "
                   "Arb bot NOT restarted. Tell me when to restart it.")
            st["arb"] = True  # stop retrying; needs a human
        else:
            drift = {c: bal.get(c, 0.0) - v for c, v in EXPECTED.items()}
            line = ", ".join(f"{c} ${bal.get(c, 0.0):,.2f}" for c in EXPECTED)
            if all(abs(d) <= TOLERANCE for d in drift.values()):
                edit_cron(ARB_MARK)
                st["arb"] = True
                notify(f"✅ Balances match the last known figures ({line}). "
                       "Arb bot watchdog re-enabled; the bot starts within 5 minutes.")
            else:
                st["arb"] = True
                diff = ", ".join(f"{c} {d:+,.2f}" for c, d in drift.items())
                notify(f"⚠️ Balances differ from the last known figures: now {line} "
                       f"(change: {diff}). Arb bot NOT restarted. "
                       "Check the account, then tell me to restart it.")

    if st["pump"] and st["arb"]:
        edit_cron(SELF_MARK, remove=True)
    save_state(st)


if __name__ == "__main__":
    main()
