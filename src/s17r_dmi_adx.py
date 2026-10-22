from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan, Signal

DEFAULT_PERIOD = 14
DEFAULT_ADX_THRESHOLD = 25.0
DEFAULT_STOP_ATR = 2.0
WARMUP_EXTRA = 50


def _true_range(df: pd.DataFrame) -> np.ndarray:
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    tr = np.full(len(df), np.nan, dtype=float)
    if not len(df):
        return tr
    tr[0] = high[0] - low[0]
    if len(df) > 1:
        tr[1:] = np.maximum.reduce((
            high[1:] - low[1:],
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        ))
    return tr


def _wilder_average(values: np.ndarray, period: int) -> np.ndarray:
    """Seed with the first period's simple mean, then use Wilder recursion."""
    out = np.full(len(values), np.nan, dtype=float)
    if len(values) < period or not np.isfinite(values[:period]).all():
        return out
    out[period - 1] = float(np.mean(values[:period]))
    for i in range(period, len(values)):
        if np.isfinite(values[i]) and np.isfinite(out[i - 1]):
            out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return out


def _wilder_sum(values: np.ndarray, period: int) -> np.ndarray:
    return _wilder_average(values, period) * period


def add_indicators(
    df: pd.DataFrame,
    *,
    period: int = DEFAULT_PERIOD,
    adx_threshold: float = DEFAULT_ADX_THRESHOLD,
    stop_atr: float = DEFAULT_STOP_ATR,
) -> pd.DataFrame:
    if period <= 0:
        raise ValueError(f"DMI/ADX period must be positive, got {period}.")
    if not np.isfinite(adx_threshold) or adx_threshold < 0:
        raise ValueError(f"ADX threshold must be finite and nonnegative, got {adx_threshold}.")
    if not np.isfinite(stop_atr) or stop_atr <= 0:
        raise ValueError(f"Stop ATR multiple must be finite and positive, got {stop_atr}.")

    out = df.copy()
    high = out["high"].to_numpy(dtype=float)
    low = out["low"].to_numpy(dtype=float)
    up_move = np.full(len(out), np.nan, dtype=float)
    down_move = np.full(len(out), np.nan, dtype=float)
    if len(out):
        up_move[0] = 0.0
        down_move[0] = 0.0
    if len(out) > 1:
        up_move[1:] = high[1:] - high[:-1]
        down_move[1:] = low[:-1] - low[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    if len(out):
        plus_dm[0] = 0.0
        minus_dm[0] = 0.0

    tr = _true_range(out)
    tr_smooth = _wilder_sum(tr, period)
    plus_smooth = _wilder_sum(plus_dm, period)
    minus_smooth = _wilder_sum(minus_dm, period)
    plus_di = np.full(len(out), np.nan, dtype=float)
    minus_di = np.full(len(out), np.nan, dtype=float)
    valid_tr = np.isfinite(tr_smooth) & (tr_smooth > 0)
    plus_di[valid_tr] = 100.0 * plus_smooth[valid_tr] / tr_smooth[valid_tr]
    minus_di[valid_tr] = 100.0 * minus_smooth[valid_tr] / tr_smooth[valid_tr]

    dx = np.full(len(out), np.nan, dtype=float)
    valid_di = np.isfinite(plus_di) & np.isfinite(minus_di)
    denominator = plus_di + minus_di
    moving = valid_di & (denominator > 0)
    dx[moving] = 100.0 * np.abs(plus_di[moving] - minus_di[moving]) / denominator[moving]
    dx[valid_di & (denominator == 0)] = 0.0

    adx = np.full(len(out), np.nan, dtype=float)
    seed_end = None
    for i in range(len(out)):
        if not np.isfinite(dx[i]):
            continue
        if seed_end is None:
            start = i - period + 1
            if start >= 0 and np.isfinite(dx[start:i + 1]).all():
                adx[i] = float(np.mean(dx[start:i + 1]))
                seed_end = i
        elif i == seed_end + 1:
            adx[i] = (adx[seed_end] * (period - 1) + dx[i]) / period
            seed_end = i
        else:
            seed_end = None
            start = i - period + 1
            if start >= 0 and np.isfinite(dx[start:i + 1]).all():
                adx[i] = float(np.mean(dx[start:i + 1]))
                seed_end = i

    atr = tr_smooth / period
    close = out["close"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        stop_frac = stop_atr * atr / close
    previous_plus = np.roll(plus_di, 1)
    previous_minus = np.roll(minus_di, 1)
    if len(out):
        previous_plus[0] = np.nan
        previous_minus[0] = np.nan

    out["s17r_plus_di"] = plus_di
    out["s17r_minus_di"] = minus_di
    out["s17r_adx"] = adx
    out["s17r_atr"] = atr
    out["s17r_stop_frac"] = stop_frac
    out["s17r_long_signal"] = (
        (plus_di > minus_di) & (previous_plus <= previous_minus)
        & (adx > adx_threshold)
    )
    out["s17r_short_signal"] = (
        (minus_di > plus_di) & (previous_minus <= previous_plus)
        & (adx > adx_threshold)
    )
    out["s17r_long_exit"] = (
        (minus_di > plus_di) & (previous_minus <= previous_plus)
    )
    out["s17r_short_exit"] = (
        (plus_di > minus_di) & (previous_plus <= previous_minus)
    )
    return out


def entry(df: pd.DataFrame):
    long_signal = df["s17r_long_signal"].to_numpy(dtype=bool)
    short_signal = df["s17r_short_signal"].to_numpy(dtype=bool)
    stop_frac = df["s17r_stop_frac"].to_numpy(dtype=float)

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
    long_exit = df["s17r_long_exit"].to_numpy(dtype=bool)
    short_exit = df["s17r_short_exit"].to_numpy(dtype=bool)

    def exit_plan(_df: pd.DataFrame, i: int, trade) -> ExitPlan:
        plan = ExitPlan(stop_level=float(trade.initial_stop))
        if trade.direction > 0 and long_exit[i]:
            plan.close_exit = True
            plan.reason = "opposite-DI-cross"
        elif trade.direction < 0 and short_exit[i]:
            plan.close_exit = True
            plan.reason = "opposite-DI-cross"
        return plan

    return exit_plan


def warmup_for(period: int = DEFAULT_PERIOD) -> int:
    if period <= 0:
        raise ValueError(f"DMI/ADX period must be positive, got {period}.")
    return 3 * period + WARMUP_EXTRA
