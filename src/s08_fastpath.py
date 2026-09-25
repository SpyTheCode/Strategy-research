"""Fast execution path for Strategy #8, verified trade-identical to the standard one.

WHY THIS EXISTS
---------------
`runner.run` is the shared, strategy-agnostic path every strategy in this log
uses, and it is deliberately not optimised: it walks the candles one at a time
and hands each row to the strategy as `df.iloc[i]`, and the strategy reads its
own indicator columns with `df.loc[i, ...]`. On pandas 3 that pair of lookups
costs roughly half a millisecond per bar, so a 56,000-bar hourly dataset takes
about 20 seconds per simulate pass.

Strategy #8's full-depth report needs that pass roughly 150 times: nine
datasets x two exit variants for the headline, the same again for each of three
alternative ATR periods, three alternative multipliers and the long-only
reading, plus a 25-cut lookahead audit on each of nine datasets. At 20 seconds
a pass that is the better part of an hour, which is why the previous attempt at
this report never finished.

WHAT THIS DOES
--------------
Replaces only the two slow lookups, and only for this strategy:

  * the indicator columns are read from numpy arrays instead of `df.loc`
  * `harness.simulate` is replaced by a local loop over column arrays that
    implements the same fill, tie-break, time-limit and gap rules

It does NOT change the rule, the warmup, the fee model, the pessimistic
stop-wins tie-break, the "open position at end of data is discarded" rule, or
anything about how a verdict is computed. Those are the project's invariants.

CORRECTNESS
-----------
`s08_selftest` pins this to the reference end to end: for every dataset and
every parameter setting it asserts that the fast path returns the same trades
(same direction, entry time, entry price, stop, exit time, exit price, exit
reason, bars held, regime) as `runner.run` does, and therefore the same per-cell
metrics. If the two ever disagree the selftest fails loudly and no report is
produced from the fast path.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import harness
from harness import ExitPlan, Signal, Trade


# ---------------------------------------------------------------------------
# Array-backed entry and exit: same logic as s08_supertrend, no per-bar .loc
# ---------------------------------------------------------------------------

def _flips(d: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Bullish / bearish flip flags, and the direction of the previous bar.

    Mirrors `s08_supertrend.entry` (`curr_dir != prev_dir`) and
    `s08_supertrend.native_exit` exactly, including that bar 0 can never fire
    because there is no previous bar to compare against.
    """
    prev = np.concatenate(([0], d[:-1]))
    bull = (d == 1) & (prev != 1)
    bear = (d == -1) & (prev != -1)
    flip_bear = (d == -1) & (prev == 1)
    flip_bull = (d == 1) & (prev == -1)
    # Bar 0 has no previous bar, so neither an entry nor an exit can fire there.
    for arr in (bull, bear, flip_bear, flip_bull):
        arr[0] = False
    return bull, bear, flip_bear, flip_bull


def entry(df: pd.DataFrame, long_only: bool = False):
    """Array-backed equivalent of s08_supertrend.entry."""
    st_dir = df["st_dir"].to_numpy()
    atr = df["atr"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    bull, bear, _, _ = _flips(st_dir)

    def _entry(df_arg, i: int):
        if i == 0:
            return None
        if bull[i]:
            a = atr[i]
            if not np.isfinite(a) or a <= 0:
                return None
            return Signal(direction=1, stop_frac=a / close[i])
        if bear[i] and not long_only:
            a = atr[i]
            if not np.isfinite(a) or a <= 0:
                return None
            return Signal(direction=-1, stop_frac=a / close[i])
        return None

    return _entry


def native_exit(df: pd.DataFrame):
    """Array-backed equivalent of s08_supertrend.native_exit."""
    st_dir = df["st_dir"].to_numpy()
    _, _, flip_bear, flip_bull = _flips(st_dir)

    def _exit(df_arg, i: int, trade: Trade):
        if i == 0:
            return ExitPlan()
        # A long wants out on a bearish flip; a short on a bullish flip.
        if trade.direction == 1 and flip_bear[i]:
            return ExitPlan(close_exit=True, reason="supertrend flip bearish")
        if trade.direction == -1 and flip_bull[i]:
            return ExitPlan(close_exit=True, reason="supertrend flip bullish")
        return ExitPlan()

    return _exit


# ---------------------------------------------------------------------------
# Fast simulate: same rules as harness.simulate, column arrays instead of rows
# ---------------------------------------------------------------------------

def simulate(df: pd.DataFrame, entry_fn, exit_fn, *, warmup: int,
             time_limit_bars: int | None = None,
             entry_fee_rate: float = harness.TAKER_FEE_RATE,
             exit_fee_rate: float = harness.TAKER_FEE_RATE) -> list[Trade]:
    """Trade-identical reimplementation of harness.simulate for this strategy.

    The row `df.iloc[i]` is replaced by direct array reads. Every rule is the
    same: a decision on closed bar i fills at bar i+1's open; a gap through the
    stop fills at the worse open; the stop wins when one candle holds both
    barriers; an unfinished position at the end of the data is dropped.
    """
    n = len(df)
    open_time = df["open_time"].to_numpy()
    o = df["open"].to_numpy(dtype=float)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    regime = (df["regime"].to_numpy(dtype=object) if "regime" in df.columns
              else np.array([""] * n, dtype=object))

    trades: list[Trade] = []
    position: Trade | None = None
    pending_entry: Signal | None = None
    pending_exit_reason: str | None = None

    for i in range(warmup, n):
        # 1. A decision made last bar fills at this bar's open.
        if position is not None and pending_exit_reason is not None:
            position.exit_time = open_time[i]
            position.exit_price = float(o[i])
            position.exit_reason = pending_exit_reason
            trades.append(position)
            position = None
            pending_exit_reason = None

        if position is None and pending_entry is not None:
            entry_px = float(o[i])
            stop = pending_entry.resolve_stop(entry_px)
            if stop != entry_px:  # a zero-risk trade has no definable R
                position = Trade(
                    direction=pending_entry.direction,
                    entry_time=open_time[i],
                    entry_price=entry_px,
                    initial_stop=stop,
                    regime=str(regime[i]),
                    entry_fee_rate=entry_fee_rate,
                    exit_fee_rate=exit_fee_rate,
                )
            pending_entry = None

        # 2. While holding, see what this candle does to the trade.
        if position is not None:
            plan = exit_fn(df, i, position)
            d = position.direction
            hit_stop = (plan.stop_level is not None
                        and harness._stop_hit({"low": lo[i], "high": hi[i]},
                                              plan.stop_level, d))
            hit_target = (plan.target_level is not None
                          and harness._target_hit({"low": lo[i], "high": hi[i]},
                                                  plan.target_level, d))

            if hit_stop:  # pessimistic tie-break: the stop always wins
                position.exit_time = open_time[i]
                position.exit_price = harness._stop_fill(
                    {"open": o[i], "high": hi[i], "low": lo[i]},
                    float(plan.stop_level), d)
                position.exit_reason = "stop"
                trades.append(position)
                position = None
            elif hit_target:
                position.exit_time = open_time[i]
                position.exit_price = float(plan.target_level)
                position.exit_reason = "target"
                trades.append(position)
                position = None
            else:
                position.bars_held += 1
                if time_limit_bars is not None and position.bars_held >= time_limit_bars:
                    pending_exit_reason = "time"
                elif plan.close_exit:
                    pending_exit_reason = plan.reason or "signal"

        # 3. Look for a fresh entry on this closed bar. Allowed while an exit
        #    is queued so reversal systems can flip at the same next open.
        if pending_entry is None and (position is None or pending_exit_reason is not None):
            sig = entry_fn(df, i)
            if sig is not None and i + 1 < n:
                pending_entry = sig

    # An open position at the end of the data is left out entirely rather than
    # marked to the last close, so no unresolved bet is counted as a result.
    return trades
