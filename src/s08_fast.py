"""Fast Supertrend, numerically identical to s08_supertrend.add_indicators.

The reference implementation in s08_supertrend.add_indicators costs ~12s per
1H dataset because it indexes a DataFrame row-by-row (`df.loc[i, ...]`) inside
the recursion. The full-depth Strategy #8 report needs roughly a hundred
recomputations of it (a 25-cut lookahead audit on nine datasets, plus
ATR / multiplier / direction sweeps), so that cost is what kept the report
from being produced at all.

This does the SAME recursion with the same semantics, but over bare numpy
arrays, which removes the indexing overhead. Correctness is asserted against
the reference on all nine datasets by s08_selftest, not assumed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def supertrend(df: pd.DataFrame, atr_period: int = 10,
               multiplier: float = 3.0) -> pd.DataFrame:
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    n = len(df)

    prev_close = np.concatenate(([np.nan], close[:-1]))
    # `pd.concat([hl, hc, lc], axis=1).max(axis=1)` skips NaN by default, so
    # the reference's TR is the true range even on the first bar (where hc and
    # lc are NaN) and ATR becomes valid one bar earlier than an elementwise
    # numpy maximum would give. nanmax reproduces that; the plain numpy form
    # would shift every indicator column by a bar.
    stack = np.stack([high - low,
                      np.abs(high - prev_close),
                      np.abs(low - prev_close)])
    tr = np.nanmax(stack, axis=0)
    all_nan = np.isnan(stack).all(axis=0)
    tr[all_nan] = np.nan

    atr = pd.Series(tr).rolling(atr_period).mean().to_numpy()

    hl2 = (high + low) / 2.0
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    st_line = np.full(n, np.nan)
    st_dir = np.zeros(n, dtype=np.int64)

    # ATR is NaN only in the warmup, and the warmup is a single contiguous
    # prefix. Skipping to the first valid bar once lets the hot loop drop a
    # per-bar NaN test, which is most of the cost of this function. The prefix
    # assumption is not load-bearing on real data - a rolling mean of a series
    # that is defined from bar 0 cannot produce an interior NaN - but it is
    # asserted rather than trusted, because if it ever broke, skipping would
    # silently feed a NaN through the recursion instead of resetting state.
    valid = np.nonzero(~np.isnan(atr))[0]
    first = int(valid[0]) if valid.size else n
    if valid.size and valid[-1] - first + 1 != valid.size:
        raise ValueError("ATR NaN values are not a contiguous warmup prefix")
    if first >= n:
        return _pack(df, st_line, st_dir, atr)

    prev_line = np.nan
    prev_dir = 0

    for i in range(first, n):
        ub = upper_band[i]
        lb = lower_band[i]
        c = close[i]

        if prev_dir == 0:
            direction = 1 if c > lb else -1
            line = lb if direction == 1 else ub
        else:
            direction = prev_dir
            if direction == 1:
                line = lb if prev_line != prev_line else max(lb, prev_line)
            else:
                line = ub if prev_line != prev_line else min(ub, prev_line)

            if direction == 1 and c <= line:
                direction = -1
                line = ub
            elif direction == -1 and c >= line:
                direction = 1
                line = lb

        st_line[i] = line
        st_dir[i] = direction
        prev_line = line
        prev_dir = direction

    return _pack(df, st_line, st_dir, atr)


def _pack(df: pd.DataFrame, st_line: np.ndarray, st_dir: np.ndarray,
          atr: np.ndarray) -> pd.DataFrame:
    out = df.copy()
    out["st_line"] = st_line
    out["st_dir"] = st_dir
    out["atr"] = atr
    return out


def add_indicators(df: pd.DataFrame, atr_period: int = 10,
                   multiplier: float = 3.0) -> pd.DataFrame:
    """Drop-in replacement for s08_supertrend.add_indicators."""
    return supertrend(df, atr_period, multiplier)
