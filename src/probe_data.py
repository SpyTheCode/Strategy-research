"""One-off probe: how much Bybit USDT-perpetual history is actually available?

Asks Bybit two questions for each candidate coin:
  1. When was the perpetual contract launched? (instruments-info -> launchTime)
  2. What is the oldest candle the kline endpoint will actually serve, per
     timeframe? (launch date and data availability are not always the same)

Public market data only - no API key, no account, nothing that can place an
order. Read-only.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

# This machine's network cannot resolve api.bybit.com, but Bybit's official
# mirror domains work. Same exchange, same v5 endpoints, same data.
HOSTS = ["https://api.bybit.com", "https://api.bytick.com", "https://api.bybit.nl"]
BASE = HOSTS[0]  # replaced at import time by pick_host()
CANDIDATES = ["BTCUSDT", "SOLUSDT", "XRPUSDT", "ETHUSDT", "LINKUSDT", "ADAUSDT"]
INTERVALS = {"1H": "60", "4H": "240", "1D": "D"}


def pick_host() -> str:
    """Return the first Bybit API host this machine can actually reach."""
    for host in HOSTS:
        try:
            r = requests.get(f"{host}/v5/market/time", timeout=10)
            if r.ok and r.json().get("retCode") == 0:
                return host
        except requests.RequestException:
            continue
    raise SystemExit("No reachable Bybit API host. Check the network connection.")


def ms_to_utc(ms: int | str) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def launch_time(symbol: str) -> str:
    r = requests.get(
        f"{BASE}/v5/market/instruments-info",
        params={"category": "linear", "symbol": symbol},
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    rows = payload.get("result", {}).get("list", [])
    if not rows:
        return f"NOT LISTED (retCode={payload.get('retCode')})"
    return ms_to_utc(rows[0]["launchTime"])


def oldest_bar(symbol: str, interval: str) -> tuple[str, int]:
    """Walk forward from 2018 to find the first candle Bybit will serve."""
    start = int(datetime(2018, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    r = requests.get(
        f"{BASE}/v5/market/kline",
        params={
            "category": "linear",
            "symbol": symbol,
            "interval": interval,
            "start": start,
            "limit": 1000,
        },
        timeout=30,
    )
    r.raise_for_status()
    rows = r.json().get("result", {}).get("list", [])
    if not rows:
        return "no data", 0
    # Bybit returns newest-first; the oldest in this page is the last element.
    return ms_to_utc(rows[-1][0]), len(rows)


def newest_bar(symbol: str, interval: str) -> str:
    r = requests.get(
        f"{BASE}/v5/market/kline",
        params={"category": "linear", "symbol": symbol, "interval": interval, "limit": 1},
        timeout=30,
    )
    r.raise_for_status()
    rows = r.json().get("result", {}).get("list", [])
    return ms_to_utc(rows[0][0]) if rows else "no data"


if __name__ == "__main__":
    BASE = pick_host()
    print(f"Reachable Bybit host: {BASE}\n")
    print(f"{'symbol':<10} {'perp launch (UTC)':<20} {'tf':<4} {'oldest candle':<18} {'newest candle':<18}")
    print("-" * 76)
    for sym in CANDIDATES:
        launched = launch_time(sym)
        for label, iv in INTERVALS.items():
            old, _ = oldest_bar(sym, iv)
            new = newest_bar(sym, iv)
            print(f"{sym:<10} {launched:<20} {label:<4} {old:<18} {new:<18}")
            time.sleep(0.15)  # be polite to the public endpoint
        print()
