"""Strategy #11: MACD line/signal crossover (Gerald Appel, 1979).

MACD line = 12-EMA − 26-EMA; signal = 9-EMA of MACD line.
Entry: MACD crosses above signal AND close > 200-SMA (long);
       MACD crosses below signal AND close < 200-SMA (short).
Native exit: opposite MACD/signal cross. No separate TP.
Initial stop: 2 × ATR(14) Wilder from next-bar-open fill price.

Source: Gerald Appel, The Moving Average Convergence-Divergence Trading
Method (1979). The source describes MACD/signal crossovers but does not
define a universal crypto stop or exit. Stop placeholder is the project's
own extrapolation.
"""

from __future__ import annotations

import pandas as pd

from harness import ExitPlan, Signal


# ── defaults ────────────────────────────────────────────────────────────────
ATR_PERIOD: int = 14


def add_indicators(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal_ema: int = 9,
    sma_period: int = 200,
) -> pd.DataFrame:
    """Compute MACD, 200-SMA trend filter, and ATR (Wilder).

    EMA uses standard exponential smoothing (alpha = 2/(span+1)) as per
    the canonical MACD formula used by TradingView and all major platforms.
    ATR uses Wilder's smoothing (SMA of True Range), as named in the spec.
    """
    # ── MACD ────────────────────────────────────────────────────────────────
    ema_fast = df["close"].ewm(span=fast,  adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow,  adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal = macd_line.ewm(span=signal_ema, adjust=False).mean()

    # ── trend filter ────────────────────────────────────────────────────────
    sma200 = df["close"].rolling(sma_period).mean()

    # ── ATR (Wilder: rolling mean of True Range) ────────────────────────────
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift(1)).abs()
    tr3 = (df["low"]  - df["close"].shift(1)).abs()
    tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(ATR_PERIOD).mean()   # Wilder SMA

    df["macd_line"]   = macd_line
    df["macd_signal"] = macd_signal
    df["sma200"]      = sma200
    df["atr"]         = atr

    return df


def entry(
    df: pd.DataFrame,
    fast: int   = 12,
    slow: int   = 26,
    stop_mult: float = 2.0,
) -> callable:
    """MACD crossover entry with 200-SMA trend filter.

    stop_mult: ATR multiplier for the initial stop (default 2× from spec).
               The ATR distance is captured from the SIGNAL BAR and translated
               to the fill price only at next-bar-open, per the lookahead trap.
    """

    def _entry(df_arg: pd.DataFrame, i: int):
        if i < 1:
            return None

        macd    = df.loc[i, "macd_line"]
        sig     = df.loc[i, "macd_signal"]
        prev_m  = df.loc[i - 1, "macd_line"]
        prev_s  = df.loc[i - 1, "macd_signal"]
        close   = df.loc[i, "close"]
        sma     = df.loc[i, "sma200"]
        atr     = df.loc[i, "atr"]

        if (pd.isna(macd)  or pd.isna(sig)  or pd.isna(sma)  or
            pd.isna(atr)  or atr <= 0       or pd.isna(prev_m) or pd.isna(prev_s)):
            return None

        # ── long: MACD crosses above signal AND in uptrend ─────────────────
        crossed_up = (macd > sig) and (prev_m <= prev_s)
        if crossed_up and close > sma:
            stop_frac = stop_mult * atr / close   # ≈ 2ATR/close
            return Signal(
                direction=1,
                stop_frac=stop_frac,
            )

        # ── short: MACD crosses below signal AND in downtrend ─────────────
        crossed_dn = (macd < sig) and (prev_m >= prev_s)
        if crossed_dn and close < sma:
            stop_frac = stop_mult * atr / close
            return Signal(
                direction=-1,
                stop_frac=stop_frac,
            )

        return None

    return _entry


def native_exit(df: pd.DataFrame) -> callable:
    """Exit when MACD crosses the other way (opposite of entry cross)."""

    def _exit(df_arg: pd.DataFrame, i: int, trade):
        if i < 1:
            return ExitPlan()

        macd   = df.loc[i,     "macd_line"]
        sig    = df.loc[i,     "macd_signal"]
        prev_m = df.loc[i - 1, "macd_line"]
        prev_s = df.loc[i - 1, "macd_signal"]

        # Long wants out when MACD crosses below signal
        if trade.direction == 1 and (macd < sig) and (prev_m >= prev_s):
            return ExitPlan(close_exit=True, reason="macd cross below signal")

        # Short wants out when MACD crosses above signal
        if trade.direction == -1 and (macd > sig) and (prev_m <= prev_s):
            return ExitPlan(close_exit=True, reason="macd cross above signal")

        return ExitPlan()

    return _exit