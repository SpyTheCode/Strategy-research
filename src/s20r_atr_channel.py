from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan, Signal

DEFAULT_ENTRY = 20
DEFAULT_EXIT = 10
ATR_PERIOD = 20
DEFAULT_STOP_ATR = 2.0
WARMUP = 250


def _true_range(df: pd.DataFrame) -> pd.Series:
    previous_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _wilder_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    if period <= 0:
        raise ValueError(f"ATR period must be positive, got {period}.")
    tr = _true_range(df).to_numpy(dtype=float)
    values = np.full(len(tr), np.nan, dtype=float)
    if len(tr) >= period:
        values[period - 1] = float(np.mean(tr[:period]))
        for i in range(period, len(tr)):
            values[i] = (values[i - 1] * (period - 1) + tr[i]) / period
    return pd.Series(values, index=df.index, name="s20r_atr20")


def add_indicators(
    df: pd.DataFrame,
    *,
    entry_period: int = DEFAULT_ENTRY,
    exit_period: int = DEFAULT_EXIT,
    stop_atr: float = DEFAULT_STOP_ATR,
) -> pd.DataFrame:
    if entry_period <= 0:
        raise ValueError(f"Entry period must be positive, got {entry_period}.")
    if exit_period <= 0:
        raise ValueError(f"Exit period must be positive, got {exit_period}.")
    if not np.isfinite(stop_atr) or stop_atr <= 0:
        raise ValueError(f"Stop ATR multiplier must be positive, got {stop_atr}.")

    out = df.copy()
    out["s20r_entry_high"] = (
        out["high"].rolling(entry_period, min_periods=entry_period).max().shift(1)
    )
    out["s20r_entry_low"] = (
        out["low"].rolling(entry_period, min_periods=entry_period).min().shift(1)
    )
    out["s20r_exit_high"] = (
        out["high"].rolling(exit_period, min_periods=exit_period).max().shift(1)
    )
    out["s20r_exit_low"] = (
        out["low"].rolling(exit_period, min_periods=exit_period).min().shift(1)
    )
    atr = _wilder_atr(out, ATR_PERIOD)
    out["s20r_atr20"] = atr
    close = out["close"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out["s20r_stop_frac"] = stop_atr * atr.to_numpy(dtype=float) / close
    out["s20r_long_signal"] = out["close"] > out["s20r_entry_high"]
    out["s20r_short_signal"] = out["close"] < out["s20r_entry_low"]
    return out


def entry(df: pd.DataFrame):
    long_signal = df["s20r_long_signal"].to_numpy(dtype=bool)
    short_signal = df["s20r_short_signal"].to_numpy(dtype=bool)
    stop_frac = df["s20r_stop_frac"].to_numpy(dtype=float)

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
    close = df["close"].to_numpy(dtype=float)
    prior_high = df["s20r_exit_high"].to_numpy(dtype=float)
    prior_low = df["s20r_exit_low"].to_numpy(dtype=float)

    def exit_plan(_df: pd.DataFrame, i: int, trade) -> ExitPlan:
        plan = ExitPlan(stop_level=float(trade.initial_stop))
        if trade.direction > 0 and np.isfinite(prior_low[i]) and close[i] < prior_low[i]:
            plan.close_exit = True
            plan.reason = "opposite-channel"
        elif trade.direction < 0 and np.isfinite(prior_high[i]) and close[i] > prior_high[i]:
            plan.close_exit = True
            plan.reason = "opposite-channel"
        return plan

    return exit_plan
