"""Strategy #15: CCI threshold-cross trend entries with a zero-line exit."""

from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan, Signal

CCI_PERIOD = 20
CCI_DIVISOR = 0.015
ENTRY_THRESHOLD = 100.0
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
    threshold: float = ENTRY_THRESHOLD,
    stop_atr: float = STOP_ATR_MULT,
) -> pd.DataFrame:
    """Calculate rolling CCI and signal-time risk using only available bars."""
    out = df.copy()
    typical = (out["high"] + out["low"] + out["close"]) / 3.0
    sma = typical.rolling(CCI_PERIOD, min_periods=CCI_PERIOD).mean()
    mean_deviation = typical.rolling(
        CCI_PERIOD, min_periods=CCI_PERIOD
    ).apply(lambda window: np.mean(np.abs(window - window.mean())), raw=True)
    cci = (typical - sma) / (CCI_DIVISOR * mean_deviation)
    cci = cci.where(mean_deviation > 0)

    tr = _true_range(out)
    atr = tr.ewm(alpha=1.0 / CCI_PERIOD, adjust=False).mean()
    atr.iloc[:CCI_PERIOD] = np.nan

    cci_values = cci.to_numpy(dtype=float)
    cci_prev = np.roll(cci_values, 1)
    cci_prev[0] = np.nan
    out["s15_typical_price"] = typical
    out["s15_cci_sma20"] = sma
    out["s15_mean_deviation20"] = mean_deviation
    out["s15_cci"] = cci
    out["s15_atr20"] = atr
    out["s15_long_signal"] = (
        (cci_values > threshold) & (cci_prev <= threshold)
    )
    out["s15_short_signal"] = (
        (cci_values < -threshold) & (cci_prev >= -threshold)
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        out["s15_stop_frac"] = stop_atr * atr.to_numpy() / out["close"].to_numpy()
    return out


def entry(df: pd.DataFrame):
    long_signal = df["s15_long_signal"].to_numpy(dtype=bool)
    short_signal = df["s15_short_signal"].to_numpy(dtype=bool)
    stop_frac = df["s15_stop_frac"].to_numpy(dtype=float)

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
    cci = df["s15_cci"].to_numpy(dtype=float)

    def exit_plan(_df: pd.DataFrame, i: int, trade) -> ExitPlan:
        plan = ExitPlan(stop_level=float(trade.initial_stop))
        if i == 0 or not (np.isfinite(cci[i]) and np.isfinite(cci[i - 1])):
            return plan
        if trade.direction > 0:
            crossed_zero = cci[i] <= 0 and cci[i - 1] > 0
        else:
            crossed_zero = cci[i] >= 0 and cci[i - 1] < 0
        if crossed_zero:
            plan.close_exit = True
            plan.reason = "zero-line-cross"
        return plan

    return exit_plan


def warmup_for(_interval: str) -> int:
    return WARMUP
