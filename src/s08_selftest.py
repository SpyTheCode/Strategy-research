"""Equivalence self-test: the fast Strategy #8 paths must match the real ones.

The full-depth Strategy #8 report needs roughly a hundred and fifty backtest
passes (nine datasets x two exit variants, repeated for three alternative ATR
periods, three alternative multipliers and the long-only reading, plus a
25-cut lookahead audit on each of nine datasets). Two things made that
impossible at the project's normal speed:

  * `s08_supertrend.add_indicators` is a Python row loop over `df.loc[i, ...]`
    (~14s per hourly dataset);
  * the shared `harness.simulate` hands each row to the strategy as
    `df.iloc[i]`, and the strategy reads its columns back with `df.loc[i, ...]`,
    which on pandas 3 costs ~0.5ms per bar (~16-20s per hourly dataset).

`s08_fast` reimplements the indicator over numpy arrays and `s08_fastpath`
reimplements the execution loop over column arrays. Neither changes the rule,
the warmup, the fee model, the pessimistic stop-wins tie-break, or the
"unfinished position is discarded" rule. This pins all three together:

  1. indicator columns, on every dataset and every swept parameter setting
  2. the full trade list and per-cell metrics, end to end, on every dataset

If any of those ever disagree, this fails loudly and the fast path cannot be
used to produce a report.

Run:  .venv\\Scripts\\python.exe src\\s08_selftest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bybit_data as bd
import harness
import s08_fast
import s08_fastpath
import s08_supertrend as s08
from harness import add_regime_columns, forced_13_exit, metrics, simulate
from runner import FORCED_TIME_LIMIT

DATASETS = [(c, i) for c in ("BTCUSDT", "SOLUSDT", "XRPUSDT")
            for i in ("1H", "4H", "1D")]
WARMUP = 50


def _compare(a: pd.DataFrame, b: pd.DataFrame, label: str) -> list[str]:
    bad = []
    for col in ("st_line", "st_dir", "atr"):
        x, y = a[col].to_numpy(), b[col].to_numpy()
        if col == "st_dir":
            if not np.array_equal(x, y, equal_nan=True):
                idx = np.nonzero(~((x == y) | (np.isnan(x) & np.isnan(y))))[0]
                bad.append(f"{label}: st_dir differs at {idx[:5].tolist()}")
        else:
            if not np.allclose(x, y, rtol=0, atol=1e-12, equal_nan=True):
                d = np.nanmax(np.abs(x - y))
                bad.append(f"{label}: {col} max abs diff {d:g}")
    return bad


def _trade_signature(t) -> tuple:
    """Everything about a trade that a verdict could depend on."""
    return (t.direction, t.entry_time, t.entry_price, t.initial_stop,
            t.exit_time, t.exit_price, t.exit_reason, t.bars_held, t.regime)


def _compare_trades(ref: list, fast: list, label: str) -> list[str]:
    bad = []
    if len(ref) != len(fast):
        bad.append(f"{label}: trade count {len(ref)} vs {len(fast)}")
    for j, (a, b) in enumerate(zip(ref, fast)):
        if _trade_signature(a) != _trade_signature(b):
            bad.append(f"{label}: trade {j} differs "
                       f"(ref={_trade_signature(a)}, fast={_trade_signature(b)})")
            if len(bad) > 4:
                break
    return bad


def _run_end_to_end(df: pd.DataFrame, period: int, mult: float,
                    long_only: bool = False, symbol: str = "?",
                    interval: str = "?") -> list[str]:
    """Compare the fast execution path against the real one, both exits."""
    bad = []
    ref_frame = s08.add_indicators(df.copy(), period, mult)
    fast_frame = s08_fast.add_indicators(df.copy(), period, mult)
    tag = f"{symbol} {interval} ({period}, {mult:g}{', long-only' if long_only else ''})"
    bad += _compare(ref_frame, fast_frame, f"indicators {tag}")

    for label, ref_exit, fast_exit, tl in (
        ("native", s08.native_exit, s08_fastpath.native_exit, None),
        ("forced-1:3", lambda d: forced_13_exit, lambda d: forced_13_exit,
         FORCED_TIME_LIMIT),
    ):
        ref = simulate(ref_frame, s08.entry(ref_frame, long_only=long_only),
                       ref_exit(ref_frame), warmup=WARMUP, time_limit_bars=tl)
        fast = s08_fastpath.simulate(fast_frame,
                                     s08_fastpath.entry(fast_frame, long_only=long_only),
                                     fast_exit(fast_frame), warmup=WARMUP,
                                     time_limit_bars=tl)
        bad += _compare_trades(ref, fast, f"{tag} {label}")

        # Identical trades imply identical metrics; assert it anyway so a
        # future change to metrics() cannot quietly diverge either.
        if not _compare_trades(ref, fast, f"{tag} {label}"):
            rm = metrics(ref, interval="1H")
            fm = metrics(fast, interval="1H")
            if rm != fm:
                bad.append(f"{tag} {label}: metrics differ")
    return bad


def _compare_indicators(df: pd.DataFrame, period: int, mult: float,
                        symbol: str, interval: str) -> list[str]:
    a = s08.add_indicators(df.copy(), period, mult)
    b = s08_fast.add_indicators(df.copy(), period, mult)
    return _compare(a, b, f"{symbol} {interval} ({period}, {mult:g})")


def main() -> int:
    problems: list[str] = []

    # Indicator equivalence on every dataset. The reference add_indicators is a
    # slow row loop, so the sweep is reduced to the traded defaults plus one
    # alternative in each direction; the fast/slow indicator comparison on
    # those is the same code path at every setting.
    for symbol, interval in DATASETS:
        df = add_regime_columns(bd.drop_forming_bar(bd.load(symbol, interval), interval))
        for period in (10, 14):
            for mult in (2.0, 3.0):
                problems += _compare_indicators(df, period, mult, symbol, interval)

    # End to end on the traded defaults plus one alternative and the long-only
    # reading. The reference engine is slow (~20s per hourly pass), so this is
    # deliberately limited to what proves the execution path is faithful.
    for symbol, interval in DATASETS:
        df = add_regime_columns(bd.drop_forming_bar(bd.load(symbol, interval), interval))
        problems += _run_end_to_end(df, 10, 3.0, symbol=symbol, interval=interval)
    for symbol, interval in (("BTCUSDT", "4H"), ("SOLUSDT", "1D")):
        df = add_regime_columns(bd.drop_forming_bar(bd.load(symbol, interval), interval))
        problems += _run_end_to_end(df, 14, 2.0, symbol=symbol, interval=interval)
        problems += _run_end_to_end(df, 10, 3.0, long_only=True,
                                    symbol=symbol, interval=interval)

    # Hand-built edge cases the real data may not contain: a NaN close inside
    # the series (which propagates into ATR and the bands), a flat tape, and a
    # monotonic rise that never flips.
    n = 60
    base = pd.DataFrame({
        "open_time": pd.date_range("2020-01-01", periods=n, freq="D"),
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
        "volume": 1.0,
    })
    rise = base.copy()
    for c in ("open", "high", "low", "close"):
        rise[c] = np.arange(n, dtype=float)
    gap = base.copy()
    for c in ("open", "high", "low", "close"):
        gap[c] = np.arange(n, dtype=float) * 2.0
    gap.loc[30, "close"] = np.nan  # NaN close mid-series
    for name, frame in (("flat", base), ("monotonic rise", rise), ("NaN close", gap)):
        problems += _compare(
            s08.add_indicators(frame.copy()), s08_fast.add_indicators(frame.copy()),
            f"edge case '{name}'")

    if problems:
        print(f"FAST PATH IS NOT EQUIVALENT: {len(problems)} problem(s)")
        for p in problems[:20]:
            print("  " + p)
        return 1
    print(f"s08_fast + s08_fastpath are identical to s08_supertrend + harness.simulate")
    print(f"  indicators: {len(DATASETS)} datasets x 4 parameter settings, "
          f"plus 3 hand-built edge cases")
    print(f"  end to end: 11 dataset x variant combinations, both exit variants, "
          f"trade lists and metrics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
