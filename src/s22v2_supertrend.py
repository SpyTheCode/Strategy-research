"""Independent Strategy #22 build: Supertrend (7, 3)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan, Signal

ATR_PERIOD = 7
MULTIPLIER = 3.0
WARMUP = 250


def _supertrend(
    df: pd.DataFrame,
    *,
    period: int,
    multiplier: float,
    initial_direction: int = 1,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if period <= 0:
        raise ValueError(f"ATR period must be positive, got {period}.")
    if not np.isfinite(multiplier) or multiplier <= 0:
        raise ValueError(f"Multiplier must be finite and positive, got {multiplier}.")
    if initial_direction not in (-1, 1):
        raise ValueError(f"Initial direction must be -1 or 1, got {initial_direction}.")

    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    n = len(df)
    tr = np.full(n, np.nan, dtype=float)
    atr = np.full(n, np.nan, dtype=float)
    upper = np.full(n, np.nan, dtype=float)
    lower = np.full(n, np.nan, dtype=float)
    direction = np.zeros(n, dtype=np.int8)
    line = np.full(n, np.nan, dtype=float)

    if n:
        tr[0] = high[0] - low[0]
    if n > 1:
        tr[1:] = np.maximum.reduce((
            high[1:] - low[1:],
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        ))
    if n < period:
        return atr, upper, lower, direction

    seed = period - 1
    atr[seed] = float(np.mean(tr[:period]))
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    midpoint = (high + low) / 2.0
    basic_upper = midpoint + multiplier * atr
    basic_lower = midpoint - multiplier * atr
    upper[seed] = basic_upper[seed]
    lower[seed] = basic_lower[seed]
    direction[seed] = initial_direction

    for i in range(seed + 1, n):
        upper[i] = (
            basic_upper[i]
            if basic_upper[i] < upper[i - 1] or close[i - 1] > upper[i - 1]
            else upper[i - 1]
        )
        lower[i] = (
            basic_lower[i]
            if basic_lower[i] > lower[i - 1] or close[i - 1] < lower[i - 1]
            else lower[i - 1]
        )
        if close[i] > upper[i - 1]:
            direction[i] = 1
        elif close[i] < lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
    return atr, upper, lower, direction


def add_indicators(
    df: pd.DataFrame,
    *,
    period: int = ATR_PERIOD,
    multiplier: float = MULTIPLIER,
) -> pd.DataFrame:
    out = df.copy()
    atr, upper, lower, direction = _supertrend(
        out, period=period, multiplier=multiplier, initial_direction=1
    )
    line = np.where(direction > 0, lower, np.where(direction < 0, upper, np.nan))
    previous_direction = np.roll(direction, 1)
    if len(previous_direction):
        previous_direction[0] = 0
    out["s22v2_atr"] = atr
    out["s22v2_final_upper"] = upper
    out["s22v2_final_lower"] = lower
    out["s22v2_direction"] = direction
    out["s22v2_line"] = line
    out["s22v2_long_signal"] = (direction == 1) & (previous_direction == -1)
    out["s22v2_short_signal"] = (direction == -1) & (previous_direction == 1)
    return out


def entry(df: pd.DataFrame):
    long_signal = df["s22v2_long_signal"].to_numpy(dtype=bool)
    short_signal = df["s22v2_short_signal"].to_numpy(dtype=bool)
    line = df["s22v2_line"].to_numpy(dtype=float)

    def signal(_df: pd.DataFrame, i: int) -> Signal | None:
        stop = line[i]
        if not np.isfinite(stop):
            return None
        if long_signal[i]:
            return Signal(direction=1, stop_price=float(stop))
        if short_signal[i]:
            return Signal(direction=-1, stop_price=float(stop))
        return None

    return signal


def native_exit(df: pd.DataFrame):
    direction = df["s22v2_direction"].to_numpy(dtype=np.int8)
    previous = np.roll(direction, 1)
    if len(previous):
        previous[0] = 0

    def exit_plan(_df: pd.DataFrame, i: int, trade) -> ExitPlan:
        plan = ExitPlan(stop_level=float(trade.initial_stop))
        reversed_direction = (
            (trade.direction > 0 and direction[i] == -1 and previous[i] == 1)
            or (trade.direction < 0 and direction[i] == 1 and previous[i] == -1)
        )
        if reversed_direction:
            plan.close_exit = True
            plan.reason = "opposite-supertrend-flip"
        return plan

    return exit_plan
