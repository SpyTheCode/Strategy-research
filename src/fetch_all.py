"""Download the three chosen coins on all three timeframes and cache them.

Run once. Every later backtest reads these exact Parquet files off disk, so a
result can be reproduced byte-for-byte instead of depending on what the API
returned that day.

Run:  .venv\\Scripts\\python.exe src\\fetch_all.py
"""

from __future__ import annotations

import bybit_data as bd

COINS = ["BTCUSDT", "SOLUSDT", "XRPUSDT"]
INTERVALS = ["1H", "4H", "1D"]

if __name__ == "__main__":
    print(f"Bybit host in use: {bd.reachable_host()}\n")
    print(f"{'symbol':<9} {'tf':<4} {'bars':>8}  {'first candle (UTC)':<18} {'last candle (UTC)':<18} {'years':>6}")
    print("-" * 76)
    for sym in COINS:
        for iv in INTERVALS:
            df = bd.load(sym, iv)
            df = bd.drop_forming_bar(df, iv)
            first, last = df["open_time"].iloc[0], df["open_time"].iloc[-1]
            years = (last - first).days / 365.25
            print(f"{sym:<9} {iv:<4} {len(df):>8}  {first:%Y-%m-%d %H:%M}    "
                  f"{last:%Y-%m-%d %H:%M}    {years:>5.2f}")
        print()
