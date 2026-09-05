"""Smoke test: does the engine behave sanely on 56,000 real candles?

The hand-built tests in selftest.py prove the arithmetic. They do not prove the
engine behaves sensibly at scale on real prices. This does, using the one
strategy whose answer is known in advance: a coin flip.

Enter on a fixed schedule, direction alternating, stop 1 ATR away, exit on a
forced 1-risk-unit / 3-risk-unit barrier. If price moves unpredictably, hitting
+3R before -1R should happen roughly a quarter of the time, so the result before
fees should sit near zero and after fees should sit slightly below it.

If this came out strongly profitable, the engine would be flattering results
somewhere and every later number would be worthless.

Run:  .venv\\Scripts\\python.exe src\\smoke_test.py
"""

from __future__ import annotations

import bybit_data as bd
from discard_bar import breakeven_win_rate, describe, verdict
from harness import Signal, add_regime_columns, forced_13_exit, metrics, simulate

EVERY = 40          # a new trade attempt every 40 bars
STOP_ATR_MULT = 1.0


def alternating_entry(df):
    def fn(d, i: int):
        if i % EVERY != 0:
            return None
        atr = d["atr14"].iloc[i]
        px = d["close"].iloc[i]
        if atr != atr or atr <= 0:
            return None
        direction = 1 if (i // EVERY) % 2 == 0 else -1
        return Signal(direction=direction, stop_price=px - direction * STOP_ATR_MULT * atr)
    return fn


if __name__ == "__main__":
    print("Coin-flip entries on a forced 1:3 barrier - expect ~0 before fees, worse after")
    print(f"{'symbol':<9} {'tf':<4} {'trades':>7} {'win%':>6} {'R pre-fee':>10} "
          f"{'R post-fee':>11} {'R/trade':>8} {'fee cost R':>11} {'breakeven%':>11}  verdict")
    print("-" * 100)
    for sym in ["BTCUSDT", "SOLUSDT", "XRPUSDT"]:
        for iv in ["1H", "4H", "1D"]:
            df = add_regime_columns(bd.drop_forming_bar(bd.load(sym, iv), iv))
            trades = simulate(df, alternating_entry(df), forced_13_exit,
                              warmup=200, time_limit_bars=30)
            m = metrics(trades, interval=iv)
            v, _ = verdict(m, "forced-1:3")
            be = breakeven_win_rate(m["avg_fee_cost_r"]) * 100
            print(f"{sym:<9} {iv:<4} {m['trades']:>7} {m['win_rate']*100:>6.1f} "
                  f"{m['r_sum_pre_fee']:>10.1f} {m['r_sum_post_fee']:>11.1f} "
                  f"{m['expectancy_post_fee_r']:>8.3f} {m['avg_fee_cost_r']:>11.4f} "
                  f"{be:>11.1f}  {v}")
        print()
    print("A coin flip must not produce a KEEP. If any line above says KEEP, the bar is broken.")
    print()
    print("The discard bar, as applied to every strategy from here on:")
    print(describe())

