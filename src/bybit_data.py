"""Download and cache Bybit USDT-perpetual candles.

Public market data only. No API key, no account credentials, nothing that can
place an order or read a balance. Read-only by construction.

Candles are cached to data/ as Parquet files so we download each symbol and
timeframe once and every later backtest reads the identical bytes off disk.
That is what makes a result reproducible.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

# api.bybit.com does not resolve on this machine (network-level DNS block on the
# main domain). api.bytick.com is Bybit's own official mirror and serves the
# identical v5 market endpoints, so the data is the same exchange's data.
HOSTS = ["https://api.bybit.com", "https://api.bytick.com", "https://api.bybit.nl"]

# Bybit's interval codes, keyed by the label we use everywhere else.
# 6H is here because Strategy #3's source reports its headline result on 6-hour
# bars specifically, and its own timeframe table shows the result changing with
# the bar size. Testing everything except the one configuration the source
# actually claims would not be a test of that source.
INTERVAL_CODE = {"1H": "60", "4H": "240", "6H": "360", "1D": "D"}
INTERVAL_MS = {"1H": 3_600_000, "4H": 14_400_000, "6H": 21_600_000, "1D": 86_400_000}

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_HOST_CACHE: list[str] = []


def reachable_host() -> str:
    """First Bybit API host this machine can actually reach (cached)."""
    if _HOST_CACHE:
        return _HOST_CACHE[0]
    for host in HOSTS:
        try:
            r = requests.get(f"{host}/v5/market/time", timeout=10)
            if r.ok and r.json().get("retCode") == 0:
                _HOST_CACHE.append(host)
                return host
        except requests.RequestException:
            continue
    raise RuntimeError("No reachable Bybit API host - check the network connection.")


def _fetch_page(host: str, symbol: str, interval: str, start_ms: int) -> list[list[str]]:
    r = requests.get(
        f"{host}/v5/market/kline",
        params={
            "category": "linear",
            "symbol": symbol,
            "interval": INTERVAL_CODE[interval],
            "start": start_ms,
            "limit": 1000,
        },
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("retCode") != 0:
        raise RuntimeError(f"Bybit error for {symbol} {interval}: {payload.get('retMsg')}")
    return payload.get("result", {}).get("list", [])


def download(symbol: str, interval: str, start: str = "2018-01-01") -> pd.DataFrame:
    """Page through Bybit's kline endpoint from `start` to now."""
    host = reachable_host()
    cursor = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp() * 1000)
    step = INTERVAL_MS[interval]
    now_ms = int(time.time() * 1000)
    frames: list[list[str]] = []

    while cursor < now_ms:
        rows = _fetch_page(host, symbol, interval, cursor)
        if not rows:
            break
        frames.extend(rows)
        newest_in_page = int(rows[0][0])  # Bybit returns newest-first
        next_cursor = newest_in_page + step
        if next_cursor <= cursor:  # guard against a non-advancing cursor
            break
        cursor = next_cursor
        time.sleep(0.12)  # stay well inside the public rate limit

    if not frames:
        raise RuntimeError(f"No candles returned for {symbol} {interval}")

    df = pd.DataFrame(
        frames, columns=["open_time", "open", "high", "low", "close", "volume", "turnover"]
    )
    df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume", "turnover"]:
        df[col] = pd.to_numeric(df[col], errors="raise")

    df = df.drop_duplicates(subset="open_time").sort_values("open_time").reset_index(drop=True)
    return df


def _cache_path(symbol: str, interval: str) -> Path:
    return DATA_DIR / f"{symbol}_{interval}.parquet"


def load(symbol: str, interval: str, refresh: bool = False) -> pd.DataFrame:
    """Return cached candles, downloading them the first time."""
    path = _cache_path(symbol, interval)
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df = download(symbol, interval)
    df.to_parquet(path, index=False)
    return df


def drop_forming_bar(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Remove the final candle if its period has not finished yet.

    The live candle is still moving. Including it would mean testing a decision
    against a high/low/close that had not happened yet - a lookahead bug that is
    easy to introduce and hard to see.
    """
    if df.empty:
        return df
    step_ms = INTERVAL_MS[interval]
    last_open_ms = int(df["open_time"].iloc[-1].timestamp() * 1000)
    if last_open_ms + step_ms > int(time.time() * 1000):
        return df.iloc[:-1].reset_index(drop=True)
    return df
