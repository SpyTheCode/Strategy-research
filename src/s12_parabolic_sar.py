"""Strategy #12: Parabolic SAR reversal (J. Welles Wilder Jr., 1978).

The Parabolic Time/Price System: a stop-and-reverse level that ratchets
toward price as the trend extends.

Entry: close crosses above the active SAR (long) / below it (short),
filled at the next bar's open.
Native exit: the active SAR itself - the position is stopped out when
price touches the SAR, and a close on the wrong side of the SAR closes
the trade at the next open.
Initial stop: the signal bar's active SAR (absolute level), which defines 1R.

Spec pins (specs/s12_parabolic_sar.md): acceleration factor starts at 0.02,
increments 0.02 per new extreme, capped at 0.20. Direction seeded from the
first two closed bars; initial SAR at the opposite extreme of those bars,
EP at the trend extreme. Long SAR clamped below the prior two lows, short
SAR above the prior two highs. Sensitivity sweeps max AF 0.10/0.30 and
step 0.01/0.03 independently.

No lookahead: the SAR value used for bar t's decision is fully determined
by bars up to and including t's close (the recursion itself only reads
bars < t; the reversal/EP update reads bar t's range, which is closed by
the time the decision is made for a next-open fill).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan, Signal


# ── defaults (spec section 2: canonical Wilder values) ──────────────────────
AF_STEP: float = 0.02
AF_MAX: float = 0.20


def add_indicators(
    df: pd.DataFrame,
    step: float = AF_STEP,
    af_max: float = AF_MAX,
) -> pd.DataFrame:
    """Wilder's parabolic SAR, computed strictly from closed bars.

    Seeded on the first two closed bars (never from later extrema, never
    backfilled from the full sample), then advanced one bar at a time:

      SAR[t]      = SAR[t-1] + AF[t-1] * (EP[t-1] - SAR[t-1]), clamped
                    against the prior two bars' lows (long) or highs (short)
      reversal    if the bar trades through SAR, direction flips and
                    SAR[t] resets to the prior EP
      EP / AF     updated with the bar's own extreme after its close

    All of that is settled by the time bar t has closed, so a decision on
    bar t only reads values that were knowable at that moment.
    """
    o = df["open"].to_numpy(dtype=float)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    cl = df["close"].to_numpy(dtype=float)
    n = len(df)

    sar = np.full(n, np.nan)
    sar_stop = np.full(n, np.nan)
    valid = np.zeros(n, dtype=bool)
    sdir = np.zeros(n, dtype=float)
    if n < 3:
        out = df.copy()
        out["sar"], out["sar_stop"], out["sar_valid"] = sar, sar_stop, valid
        return out

    # Seed from the first two closed bars only (spec section 2).
    direction = 1.0 if cl[1] >= cl[0] else -1.0
    ep = max(hi[0], hi[1]) if direction > 0 else min(lo[0], lo[1])
    level = min(lo[0], lo[1]) if direction > 0 else max(hi[0], hi[1])
    af = step

    for t in range(2, n):
        # SAR for bar t: from closed bars alone, known before bar t opens.
        raw = level if t == 2 else level + af * (ep - level)
        if direction > 0:
            raw = min(raw, lo[t - 1], lo[t - 2])
        else:
            raw = max(raw, hi[t - 1], hi[t - 2])

        # sar_stop: the trailing stop active during bar t for the trade holding into bar t.
        sar_stop[t] = raw

        # Bar t's own range decides whether the trend reverses on it.
        if direction > 0 and lo[t] <= raw:
            direction, level, ep, af = -1.0, ep, lo[t], step
        elif direction < 0 and hi[t] >= raw:
            direction, level, ep, af = 1.0, ep, hi[t], step
        elif direction > 0 and hi[t] > ep:
            ep, af = hi[t], min(af + step, af_max)
            level = raw
        elif direction < 0 and lo[t] < ep:
            ep, af = lo[t], min(af + step, af_max)
            level = raw
        else:
            level = raw

        sar[t] = level
        sdir[t] = direction
        valid[t] = True

    out = df.copy()
    out["sar"] = sar
    out["sar_stop"] = sar_stop
    out["sar_valid"] = valid
    out["sar_dir"] = sdir
    return out


def entry(df: pd.DataFrame) -> callable:
    """Close crossing the prior-known active SAR, filled at the next open.

    Long: close crossed above the SAR this bar (close > SAR now, close <= SAR
    on the prior bar). Short: the mirror cross below. The initial stop is the
    signal bar's active SAR - an absolute level, so it is passed as
    stop_price and resolved against the actual next-open fill price. A signal
    bar whose close sits exactly on the SAR produces a zero-risk trade the
    engine discards by construction.
    """

    def _entry(df_arg: pd.DataFrame, i: int):
        if i < 3:
            return None
        sar = df_arg.loc[i, "sar"]
        sar_prev = df_arg.loc[i - 1, "sar"]
        close = df_arg.loc[i, "close"]
        prev_close = df_arg.loc[i - 1, "close"]
        if pd.isna(sar) or pd.isna(sar_prev) or sar <= 0:
            return None

        crossed_up = (close > sar) and (prev_close <= sar_prev)
        if crossed_up:
            return Signal(direction=1, stop_price=float(sar))

        crossed_dn = (close < sar) and (prev_close >= sar_prev)
        if crossed_dn:
            return Signal(direction=-1, stop_price=float(sar))

        return None

    return _entry


def native_exit(df: pd.DataFrame) -> callable:
    """Source-native exit: the active SAR is the stop/reversal level.

    While holding, the current bar's trailing SAR rides as the intrabar stop level,
    so a bar that trades through the SAR exits at the SAR (or at the open when
    the bar gapped through it - the engine's conservative stop fill). Under the
    shared engine the reversal leg executes at the next open, never same-bar.
    """

    def _exit(df_arg: pd.DataFrame, i: int, trade):
        if i < 2:
            return ExitPlan()
        stop = df_arg.loc[i, "sar_stop"]
        if pd.isna(stop) or stop <= 0:
            return ExitPlan()
        return ExitPlan(stop_level=float(stop), reason="SAR reversal")

    return _exit