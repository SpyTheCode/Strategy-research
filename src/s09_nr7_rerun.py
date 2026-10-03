"""Strategy #9 RE-RUN - NR7 (Bulkowski). NEW file; never touches s09_nr7.py.

STEP 0 (engine inspection, done before this file was written): the shared
engine CAN already express resting stop-order entries. `harness.simulate_resting`
takes per-bar columns buy_trig / sell_trig (absolute trigger prices), armed
(orders live or cancelled), risk_unit (entry-to-stop distance for 1R sizing),
session_first / session_last (order placement and cancellation), fills on the
FIRST bar inside the session whose high >= buy_trig or low <= sell_trig, fills
a gap through the trigger at the worse of trigger and open, skips a bar that
touches BOTH triggers (counted in `stats["ambiguous"]`), holds one position,
enforces the stop-first tie rule, and discards trades still open at data end.
Nothing is missing, so no engine changes were built.

NR7 rule: bar D's range (high - low, NOT true range) strictly smaller than the
range of each of the six bars before it; ties do not qualify. Resting buy stop
at bar D's high, sell stop at bar D's low, live REST_BARS bars from bar D+1.
Stop = opposite end of the pattern (1R). Native exit = Bulkowski's measure
rule: target = pattern height beyond bar D's high (long) / low (short), which
at offset 0 is exactly 1R, a symmetric 1:1. Forced variant: 1R stop, 3R target,
30-bar time limit (the shared engine convention).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan

N = 7              # NR7 headline (NR4 sweep uses 4)
REST_BARS = 1      # orders live for bar D+1 only, headline
OFFSET_MULT = 0.0  # trigger offset as a fraction of bar D's range, headline


def add_indicators(df: pd.DataFrame, *, n: int = N, rest_bars: int = REST_BARS,
                   offset_mult: float = OFFSET_MULT) -> pd.DataFrame:
    """Build the resting-order columns the engine's session loop consumes.

    A "session" is the armed window: it opens on the first bar after the
    narrow bar and closes on the bar rest_bars later. For REST_BARS = 1 the
    session is exactly bar D+1. All inputs are bars that have already closed.
    """
    out = df.copy()
    rng = out["high"] - out["low"]                      # plain range, not true range
    narrow = pd.Series(True, index=out.index)
    for k in range(1, n):                               # strictly smaller than ALL k prior
        narrow &= rng < rng.shift(k)
    out["narrow"] = narrow

    # The pattern bar for any bar of the session: the narrow bar itself. Its
    # high/low/range are carried onto every bar of the armed window so the
    # measure-rule target is available on any bar the trade may end on.
    starts = narrow.shift(1).fillna(False).astype(bool)
    g = starts.cumsum()                                 # group id: increments at session start
    pat_high = out["high"].shift(1).where(starts)
    pat_low = out["low"].shift(1).where(starts)
    pat_rng = rng.shift(1).where(starts)
    out["pat_high"] = pat_high.groupby(g).transform("first")
    out["pat_low"] = pat_low.groupby(g).transform("first")
    out["pat_rng"] = pat_rng.groupby(g).transform("first")

    # Order lifetime: placed at session_first, cancelled after session_last.
    out["session_first"] = starts.to_numpy(dtype=bool)
    out["session_last"] = narrow.shift(rest_bars).fillna(False).to_numpy(dtype=bool)

    # Only arm when the pattern bar has a usable range: a flat bar (high==low)
    # gives a zero-risk trade the engine cannot size.
    ok = (out["pat_rng"] > 0) & np.isfinite(out["pat_rng"])
    offset = offset_mult * out["pat_rng"]
    out["buy_trig"] = np.where(ok, out["pat_high"] + offset, np.nan)
    out["sell_trig"] = np.where(ok, out["pat_low"] - offset, np.nan)
    # 1R = the actual entry-to-stop distance: from the trigger to the opposite
    # end of the pattern bar (range + offset on both sides).
    out["risk_unit"] = np.where(ok, out["pat_rng"] + offset, np.nan)
    out["armed"] = ok
    return out


def native_exit(df: pd.DataFrame):
    """Bulkowski's measure rule: pattern height beyond bar D's high/low.

    At offset 0 the entry is bar D's high (long) and the stop bar D's low, so
    the target entry + 1R IS bar D's high + range: a symmetric 1:1. No time
    limit; the stop stays active; the stop wins any same-bar tie (engine).
    """
    ph = df["pat_high"].to_numpy(dtype=float)
    pl = df["pat_low"].to_numpy(dtype=float)
    pr = df["pat_rng"].to_numpy(dtype=float)

    def fn(_d: pd.DataFrame, i: int, trade) -> ExitPlan:
        if trade.direction > 0:
            target = ph[i] + pr[i]
        else:
            target = pl[i] - pr[i]
        if not np.isfinite(target):
            return ExitPlan(stop_level=trade.initial_stop, reason="measure rule")
        return ExitPlan(stop_level=trade.initial_stop, target_level=float(target),
                        reason="measure rule")

    return fn


def no_entry(_df: pd.DataFrame):
    """Never consulted: the resting path takes its levels from the columns."""
    def fn(_d: pd.DataFrame, _i: int):
        return None
    return fn


def warmup_for(interval: str) -> int:
    """Seven bars for the pattern, padded so the reporting-only regime label
    (a 100-bar average) is populated rather than reading 'unknown'."""
    return 120
