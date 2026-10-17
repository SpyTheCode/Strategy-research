from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan, Signal

DEFAULT_CHANNEL = 20
DEFAULT_FAILURE_WINDOW = 3
DEFAULT_STOP_WIDTH = 1.0
WARMUP = 250


def add_indicators(
    df: pd.DataFrame,
    *,
    channel_period: int = DEFAULT_CHANNEL,
    failure_window: int = DEFAULT_FAILURE_WINDOW,
    stop_width: float = DEFAULT_STOP_WIDTH,
) -> pd.DataFrame:
    if channel_period <= 0:
        raise ValueError(f"Channel period must be positive, got {channel_period}.")
    if failure_window <= 0:
        raise ValueError(f"Failure window must be positive, got {failure_window}.")
    if not np.isfinite(stop_width) or stop_width <= 0:
        raise ValueError(f"Stop width must be positive, got {stop_width}.")

    out = df.copy()
    out["s18_channel_high"] = (
        out["high"].rolling(channel_period, min_periods=channel_period).max().shift(1)
    )
    out["s18_channel_low"] = (
        out["low"].rolling(channel_period, min_periods=channel_period).min().shift(1)
    )
    upper = out["s18_channel_high"].to_numpy(dtype=float)
    lower = out["s18_channel_low"].to_numpy(dtype=float)
    close = out["close"].to_numpy(dtype=float)
    n = len(out)
    direction = np.zeros(n, dtype=np.int8)
    stop_frac = np.full(n, np.nan, dtype=float)

    breakout_direction = 0
    breakout_index = -1
    episode_latched = False
    for i in range(n):
        if not (np.isfinite(close[i]) and np.isfinite(upper[i]) and np.isfinite(lower[i])):
            continue
        inside = lower[i] <= close[i] <= upper[i]
        if breakout_direction:
            if i > breakout_index and inside:
                width = upper[i] - lower[i]
                if width > 0:
                    direction[i] = -breakout_direction
                    stop_frac[i] = stop_width * width / close[i]
                breakout_direction = 0
                breakout_index = -1
                episode_latched = False
            elif i - breakout_index >= failure_window:
                breakout_direction = 0
                breakout_index = -1
                episode_latched = True
            continue

        if episode_latched:
            if inside:
                episode_latched = False
            continue
        if close[i] > upper[i]:
            breakout_direction = 1
            breakout_index = i
            episode_latched = True
        elif close[i] < lower[i]:
            breakout_direction = -1
            breakout_index = i
            episode_latched = True

    out["s18_signal_direction"] = direction
    out["s18_stop_frac"] = stop_frac
    out["s18_channel_midpoint"] = (out["s18_channel_high"] + out["s18_channel_low"]) / 2.0
    return out


def entry(df: pd.DataFrame):
    directions = df["s18_signal_direction"].to_numpy(dtype=np.int8)
    stop_fracs = df["s18_stop_frac"].to_numpy(dtype=float)

    def signal(_df: pd.DataFrame, i: int) -> Signal | None:
        direction = int(directions[i])
        fraction = stop_fracs[i]
        if direction == 0 or not np.isfinite(fraction) or fraction <= 0:
            return None
        return Signal(direction=direction, stop_frac=float(fraction))

    return signal


def native_exit(df: pd.DataFrame):
    close = df["close"].to_numpy(dtype=float)
    midpoint = df["s18_channel_midpoint"].to_numpy(dtype=float)

    def exit_plan(_df: pd.DataFrame, i: int, trade) -> ExitPlan:
        plan = ExitPlan(stop_level=float(trade.initial_stop))
        if not np.isfinite(midpoint[i]):
            return plan
        if trade.direction > 0 and close[i] >= midpoint[i]:
            plan.close_exit = True
            plan.reason = "midpoint"
        elif trade.direction < 0 and close[i] <= midpoint[i]:
            plan.close_exit = True
            plan.reason = "midpoint"
        return plan

    return exit_plan
