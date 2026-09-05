"""Data integrity + regime profile of the cached candles.

Two questions, both answered from the files that will actually be backtested:

  1. Is the data clean? (no duplicate timestamps, and how many candles the
     exchange simply never published - real outages exist and pretending
     otherwise would hide a hole in the history)
  2. Does each coin behave the way it was picked to behave? The coin choices
     claim one trends, one is high-beta, one chops. That is checkable rather
     than assertable: label every bar's regime and count them.

Run:  .venv\\Scripts\\python.exe src\\data_check.py
"""

from __future__ import annotations

import numpy as np

import bybit_data as bd
from harness import add_regime_columns

COINS = ["BTCUSDT", "SOLUSDT", "XRPUSDT"]
INTERVALS = ["1H", "4H", "1D"]


def gaps(df, interval: str) -> int:
    step_ms = bd.INTERVAL_MS[interval]
    t = df["open_time"].astype("int64") // 1_000_000
    deltas = t.diff().dropna()
    return int(((deltas / step_ms) - 1).clip(lower=0).sum())


if __name__ == "__main__":
    print("PART 1 - data integrity")
    print(f"{'symbol':<9} {'tf':<4} {'bars':>7} {'dupes':>6} {'missing':>8} {'zero/neg px':>12}")
    print("-" * 52)
    for sym in COINS:
        for iv in INTERVALS:
            df = bd.drop_forming_bar(bd.load(sym, iv), iv)
            dupes = int(df["open_time"].duplicated().sum())
            bad = int((df[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
            print(f"{sym:<9} {iv:<4} {len(df):>7} {dupes:>6} {gaps(df, iv):>8} {bad:>12}")

    print("\nPART 2 - regime profile, share of bars (%)")
    print(f"{'symbol':<9} {'tf':<4} " + " ".join(f"{k:>12}" for k in
          ["up/highvol", "up/lowvol", "down/highvol", "down/lowvol",
           "range/highvol", "range/lowvol"]))
    print("-" * 90)
    for sym in COINS:
        for iv in INTERVALS:
            df = add_regime_columns(bd.drop_forming_bar(bd.load(sym, iv), iv))
            known = df[~df["regime"].str.contains("unknown")]
            share = known["regime"].value_counts(normalize=True) * 100
            cells = " ".join(
                f"{share.get(k, 0.0):>12.1f}" for k in
                ["up/highvol", "up/lowvol", "down/highvol", "down/lowvol",
                 "range/highvol", "range/lowvol"]
            )
            print(f"{sym:<9} {iv:<4} {cells}")
        print()

    print("PART 3 - how much each coin actually moves (daily bars)")
    print(f"{'symbol':<9} {'ann. vol %':>11} {'median daily range %':>22} {'total return x':>16}")
    print("-" * 62)
    for sym in COINS:
        df = bd.drop_forming_bar(bd.load(sym, "1D"), "1D")
        ret = np.log(df["close"]).diff().dropna()
        ann = float(ret.std(ddof=1) * np.sqrt(365) * 100)
        rng = float(((df["high"] - df["low"]) / df["close"]).median() * 100)
        tot = float(df["close"].iloc[-1] / df["close"].iloc[0])
        print(f"{sym:<9} {ann:>11.1f} {rng:>22.2f} {tot:>16.2f}")
