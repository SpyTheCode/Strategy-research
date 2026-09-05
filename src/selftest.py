"""Self-tests for the engine.

I wrote the engine, so the engine is exactly where a silent bug would live and
quietly flatter every result. These tests use hand-built candles where the right
answer is known by arithmetic, so a wrong answer is unambiguous.

Run:  .venv\\Scripts\\python.exe src\\selftest.py
"""

from __future__ import annotations

import sys

import pandas as pd

from harness import (
    TAKER_FEE_RATE,
    ExitPlan,
    Signal,
    forced_13_exit,
    metrics,
    simulate,
)

FAILURES: list[str] = []


def bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """rows are (open, high, low, close); one bar per hour from a fixed date."""
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["open_time"] = pd.date_range("2024-01-01", periods=len(df), freq="1h", tz="UTC")
    df["volume"] = 1.0
    df["regime"] = "up/lowvol"
    return df


def check(name: str, got, want, tol: float = 1e-9) -> None:
    ok = abs(got - want) <= tol if isinstance(want, float) else got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILURES.append(name)


def entry_once(stop: float, direction: int = 1, at_bar: int = 0):
    """Signal on exactly one bar, so each test has exactly one trade."""
    def fn(df: pd.DataFrame, i: int) -> Signal | None:
        return Signal(direction=direction, stop_price=stop) if i == at_bar else None
    return fn


def hand_net_r(entry: float, exit_px: float, stop: float, direction: int) -> float:
    risk = abs(entry - stop)
    fee = TAKER_FEE_RATE * entry + TAKER_FEE_RATE * exit_px
    return ((exit_px - entry) * direction - fee) / risk


def test_fill_at_next_open() -> None:
    print("\n1. A signal on a closed bar fills at the NEXT bar's open (no lookahead)")
    df = bars([(100, 100, 100, 100), (102, 103, 101, 102), (102, 102, 102, 102)])
    trades = simulate(df, entry_once(99.0), lambda d, i, t: ExitPlan(), warmup=0,
                      time_limit_bars=1)
    check("entry price is bar 1's open, not bar 0's close", trades[0].entry_price, 102.0)
    check("entry timestamp is bar 1", trades[0].entry_time, df["open_time"].iloc[1])


def test_clean_3r_target() -> None:
    print("\n2. Forced 1:3 target hit cleanly -> exactly +3R gross, less fees net")
    df = bars([(100, 100, 100, 100), (100, 106, 99.5, 105), (105, 105, 105, 105)])
    trades = simulate(df, entry_once(99.0), forced_13_exit, warmup=0, time_limit_bars=30)
    t = trades[0]
    check("exit reason", t.exit_reason, "target")
    check("exit price is the 3R level", t.exit_price, 103.0)
    check("gross R", t.gross_r, 3.0)
    check("net R matches hand arithmetic", t.net_r, hand_net_r(100.0, 103.0, 99.0, 1))
    check("fee cost in R", t.fee_cost_r, TAKER_FEE_RATE * (100.0 + 103.0))


def test_stop_wins_ties() -> None:
    print("\n3. One candle touching BOTH stop and target must resolve as the STOP")
    df = bars([(100, 100, 100, 100), (100, 106, 98, 105), (105, 105, 105, 105)])
    trades = simulate(df, entry_once(99.0), forced_13_exit, warmup=0, time_limit_bars=30)
    t = trades[0]
    check("exit reason is stop, not target", t.exit_reason, "stop")
    check("gross R", t.gross_r, -1.0)
    check("net R matches hand arithmetic", t.net_r, hand_net_r(100.0, 99.0, 99.0, 1))


def test_gap_through_stop() -> None:
    print("\n4. A candle that gaps past the stop fills at the open, not at the stop")
    df = bars([(100, 100, 100, 100), (100, 101, 99.5, 100.5), (95, 96, 94, 95), (95, 95, 95, 95)])
    trades = simulate(df, entry_once(99.0), forced_13_exit, warmup=0, time_limit_bars=30)
    t = trades[0]
    check("exit reason", t.exit_reason, "stop")
    check("filled at the gap open of 95, not the 99 stop", t.exit_price, 95.0)
    check("loss is worse than -1R because of the gap", t.gross_r, -5.0)


def test_time_limit() -> None:
    print("\n5. The time limit ends a trade that never reaches stop or target")
    flat = [(100, 100.2, 99.8, 100)] * 6
    df = bars([(100, 100, 100, 100)] + flat)
    trades = simulate(df, entry_once(99.0), forced_13_exit, warmup=0, time_limit_bars=3)
    t = trades[0]
    check("exit reason", t.exit_reason, "time")
    check("bars held", t.bars_held, 3)


def test_short_side() -> None:
    print("\n6. Short trades mirror correctly and still pay fees")
    df = bars([(100, 100, 100, 100), (100, 100.5, 96, 97), (97, 97, 97, 97)])
    trades = simulate(df, entry_once(101.0, direction=-1), forced_13_exit, warmup=0,
                      time_limit_bars=30)
    t = trades[0]
    check("exit reason", t.exit_reason, "target")
    check("3R below entry for a short", t.exit_price, 97.0)
    check("gross R", t.gross_r, 3.0)
    check("net R matches hand arithmetic", t.net_r, hand_net_r(100.0, 97.0, 101.0, -1))


def test_unfinished_trade_dropped() -> None:
    print("\n7. A trade still open when the data ends is discarded, not marked to market")
    df = bars([(100, 100, 100, 100), (100, 100.5, 99.9, 100), (100, 100.5, 99.9, 100)])
    trades = simulate(df, entry_once(99.0), forced_13_exit, warmup=0, time_limit_bars=99)
    check("no completed trades recorded", len(trades), 0)


def test_metrics_arithmetic() -> None:
    print("\n8. Win rate, achieved RR and R-sum add up from the trade list")
    df = bars([(100, 100, 100, 100), (100, 106, 99.5, 105), (105, 105, 105, 105)])
    trades = simulate(df, entry_once(99.0), forced_13_exit, warmup=0, time_limit_bars=30)
    m = metrics(trades, interval="1H")
    check("trade count", m["trades"], 1)
    check("win rate", m["win_rate"], 1.0)
    check("pre-fee R-sum is the clean 3R", m["r_sum_pre_fee"], 3.0)
    check("post-fee R-sum is lower than pre-fee", m["r_sum_post_fee"] < m["r_sum_pre_fee"], True)


if __name__ == "__main__":
    print("Engine self-tests - hand-built candles, arithmetic answers")
    for fn in [
        test_fill_at_next_open,
        test_clean_3r_target,
        test_stop_wins_ties,
        test_gap_through_stop,
        test_time_limit,
        test_short_side,
        test_unfinished_trade_dropped,
        test_metrics_arithmetic,
    ]:
        fn()
    print("\n" + "=" * 62)
    if FAILURES:
        print(f"{len(FAILURES)} CHECK(S) FAILED: {', '.join(FAILURES)}")
        sys.exit(1)
    print("All engine self-tests passed.")
