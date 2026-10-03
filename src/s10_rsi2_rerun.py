"""Strategy #10 RE-RUN - RSI(2) trend-filtered mean reversion. NEW file.

Never touches s10_rsi2.py, run_s10.py, or any prior #10 output. The authority
is specs/s10_rsi2.md (final resolved contract), which contains no result
numbers - only parameters - so there was nothing to mask.

Rules implemented exactly per the contract:
  Long  entry state on a closed bar:  close > SMA200 AND RSI2 < 10.
  Short entry state on a closed bar:  close < SMA200 AND RSI2 > 90.
  Equality never qualifies; states, not crossing events. Fill at next open.
  Initial stop: fixed 2% from the ACTUAL fill (long entry*0.98, short*1.02);
  that distance is 1R (the engine resolves stop_frac at fill time).
  Native exit: RSI2 > 70 (long) / RSI2 < 30 (short) on a completed bar,
  queued for the next open; the stop stays active; no take-profit.
  Forced variant: shared engine 1R stop / 3R target / 30-bar limit.
  One position per coin/timeframe (engine convention), no pyramiding.
  Wilder RSI(2): alpha=1/2, adjust=False, min 2 changes; avg loss 0 & gain > 0
  -> 100; both 0 -> 50; avg gain 0 & loss > 0 -> 0 (RSI formula).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan, Signal

SMA_LEN = 200
STOP_FRAC = 0.02
LONG_TH = 10.0
SHORT_TH = 90.0
EXIT_LONG_TH = 70.0
EXIT_SHORT_TH = 30.0
WARMUP = 201


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """SMA200 (contemporaneous, unshifted) and Wilder RSI(2) from closed bars."""
    out = df.copy()
    close = out["close"]
    out["sma200"] = close.rolling(SMA_LEN, min_periods=SMA_LEN).mean()

    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    ag = gain.ewm(alpha=0.5, adjust=False, min_periods=2).mean()
    al = loss.ewm(alpha=0.5, adjust=False, min_periods=2).mean()
    rsi = 100.0 - 100.0 / (1.0 + ag / al)
    rsi = rsi.where(~((al == 0) & (ag == 0)), 50.0)   # both zero -> neutral
    rsi = rsi.where(~((al == 0) & (ag > 0)), 100.0)   # no loss yet -> 100
    rsi = rsi.where(~((ag == 0) & (al > 0)), 0.0)     # formula already gives 0
    out["rsi2"] = rsi
    return out


def entry(df: pd.DataFrame, *, stop_frac: float = STOP_FRAC,
          lo: float = LONG_TH, sh: float = SHORT_TH):
    """State-based entry decided on the closed bar, filled next open."""
    c = df["close"].to_numpy(dtype=float)
    sma = df["sma200"].to_numpy(dtype=float)
    rsi = df["rsi2"].to_numpy(dtype=float)

    def fn(_d: pd.DataFrame, i: int) -> Signal | None:
        if i < WARMUP or not (np.isfinite(sma[i]) and np.isfinite(rsi[i])):
            return None
        if c[i] > sma[i] and rsi[i] < lo:      # strict, equality never qualifies
            return Signal(direction=1, stop_frac=stop_frac)
        if c[i] < sma[i] and rsi[i] > sh:
            return Signal(direction=-1, stop_frac=stop_frac)
        return None

    return fn


def native_exit(df: pd.DataFrame):
    """RSI(2) exit state on a completed bar, queued for the next open.

    The stop remains active on every bar; the engine resolves stop-first ties.
    """
    rsi = df["rsi2"].to_numpy(dtype=float)

    def fn(_d: pd.DataFrame, i: int, trade) -> ExitPlan:
        close_exit = False
        reason = ""
        if np.isfinite(rsi[i]):
            if trade.direction > 0 and rsi[i] > EXIT_LONG_TH:
                close_exit, reason = True, "rsi>70"
            elif trade.direction < 0 and rsi[i] < EXIT_SHORT_TH:
                close_exit, reason = True, "rsi<30"
        return ExitPlan(stop_level=trade.initial_stop, close_exit=close_exit,
                        reason=reason)

    return fn


def warmup_for(_interval: str) -> int:
    """201 bars everywhere: 200 closes for the SMA plus one more."""
    return WARMUP
