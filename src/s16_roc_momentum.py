"""Strategy #16: Rate-of-change zero-cross momentum."""

from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan, Signal

ROC_PERIOD = 20
ATR_PERIOD = 20
STOP_ATR_MULT = 2.0
WARMUP = 250


def _true_range(df: pd.DataFrame) -> pd.Series:
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)


def add_indicators(
    df: pd.DataFrame,
    *,
    period: int = ROC_PERIOD,
    stop_atr: float = STOP_ATR_MULT,
) -> pd.DataFrame:
    """Compute percentage ROC and a signal-time ATR stop without future data."""
    if period <= 0:
        raise ValueError(f"ROC period must be positive, got {period}.")
    if stop_atr <= 0:
        raise ValueError(f"Stop ATR multiplier must be positive, got {stop_atr}.")

    out = df.copy()
    close = out["close"].to_numpy(dtype=float)
    prior_close = out["close"].shift(period).to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        roc = (close / prior_close - 1.0) * 100.0
    roc[~np.isfinite(prior_close) | (prior_close == 0)] = np.nan

    tr = _true_range(out)
    atr = tr.ewm(alpha=1.0 / ATR_PERIOD, adjust=False).mean()
    atr.iloc[:ATR_PERIOD] = np.nan
    roc_prev = np.roll(roc, 1)
    if len(roc_prev):
        roc_prev[0] = np.nan

    out["s16_roc"] = roc
    out["s16_roc_prev"] = roc_prev
    out["s16_atr20"] = atr
    out["s16_long_signal"] = (roc > 0.0) & (roc_prev <= 0.0)
    out["s16_short_signal"] = (roc < 0.0) & (roc_prev >= 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        out["s16_stop_frac"] = (
            stop_atr * atr.to_numpy(dtype=float) / close
        )
    return out


def entry(df: pd.DataFrame):
    long_signal = df["s16_long_signal"].to_numpy(dtype=bool)
    short_signal = df["s16_short_signal"].to_numpy(dtype=bool)
    stop_frac = df["s16_stop_frac"].to_numpy(dtype=float)

    def signal(_df: pd.DataFrame, i: int) -> Signal | None:
        frac = stop_frac[i]
        if not np.isfinite(frac) or frac <= 0:
            return None
        if long_signal[i]:
            return Signal(direction=1, stop_frac=float(frac))
        if short_signal[i]:
            return Signal(direction=-1, stop_frac=float(frac))
        return None

    return signal


def native_exit(df: pd.DataFrame):
    roc = df["s16_roc"].to_numpy(dtype=float)

    def exit_plan(_df: pd.DataFrame, i: int, trade) -> ExitPlan:
        plan = ExitPlan(stop_level=float(trade.initial_stop))
        if i == 0 or not (np.isfinite(roc[i]) and np.isfinite(roc[i - 1])):
            return plan
        if trade.direction > 0:
            crossed_zero = roc[i] <= 0.0 and roc[i - 1] > 0.0
        else:
            crossed_zero = roc[i] >= 0.0 and roc[i - 1] < 0.0
        if crossed_zero:
            plan.close_exit = True
            plan.reason = "opposite-ROC-zero-cross"
        return plan

    return exit_plan


def warmup_for(_interval: str) -> int:
    return WARMUP
