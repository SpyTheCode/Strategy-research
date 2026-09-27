"""Strategy #10 - RSI(2) short-term mean reversion.

Connors/Williams-style daily setup: trade only in the direction permitted by
the 200-period simple moving average. Buy RSI(2) below 10 in an uptrend; short
RSI(2) above 90 in a downtrend. Close a long when RSI(2) rises above 70 and a
short when RSI(2) falls below 30. A fixed 2% stop is a research convention,
not part of the source rule, and is disclosed as such in the report.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan, Signal

RSI_PERIOD = 2
TREND_PERIOD = 200
OVERSOLD = 10.0
OVERBOUGHT = 90.0
LONG_EXIT = 70.0
SHORT_EXIT = 30.0
STOP_FRAC = 0.02
WARMUP = TREND_PERIOD + 1


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    delta = out["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD,
                        adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD,
                        adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    # A sequence of gains has RSI 100; a flat sequence has neutral RSI 50.
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    out["rsi2"] = rsi
    out["sma200"] = out["close"].rolling(TREND_PERIOD, min_periods=TREND_PERIOD).mean()
    return out


def entry(df: pd.DataFrame, oversold: float = OVERSOLD,
          overbought: float = OVERBOUGHT, stop_frac: float = STOP_FRAC):
    close = df["close"].to_numpy()
    sma = df["sma200"].to_numpy()
    rsi = df["rsi2"].to_numpy()

    def fn(_df: pd.DataFrame, i: int) -> Signal | None:
        if not np.isfinite(sma[i]) or not np.isfinite(rsi[i]):
            return None
        if close[i] > sma[i] and rsi[i] < oversold:
            return Signal(direction=1, stop_frac=stop_frac)
        if close[i] < sma[i] and rsi[i] > overbought:
            return Signal(direction=-1, stop_frac=stop_frac)
        return None

    return fn


def native_exit(df: pd.DataFrame):
    rsi = df["rsi2"].to_numpy()

    def fn(_df: pd.DataFrame, i: int, trade) -> ExitPlan:
        plan = ExitPlan(stop_level=trade.initial_stop)
        if trade.direction > 0 and rsi[i] > LONG_EXIT:
            plan.close_exit, plan.reason = True, "rsi_reversion"
        elif trade.direction < 0 and rsi[i] < SHORT_EXIT:
            plan.close_exit, plan.reason = True, "rsi_reversion"
        return plan

    return fn