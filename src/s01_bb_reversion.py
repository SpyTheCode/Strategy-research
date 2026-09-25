"""Strategy #1 - Bollinger Band Reversion (short only).

WHAT THE SOURCE ACTUALLY SAYS
-----------------------------
Bybit USDT perpetuals, 4-hour candles, short only, 1.5x fixed leverage, universe
of the top 30 coins by market cap rebuilt monthly (72 different pairs appear over
the test), 10,000 USDT start.

Enter short when ALL THREE are true on a closed candle:

  1. EMA(short) < EMA(medium)            - only short into an established downtrend
  2. the candle is the FIRST to close above the upper Bollinger band
  3. volume > SMA(volume, P)              - the spike is real, not a thin wick

Point 2 is the author's own emphasis: without the "first" condition, a long rally
keeps closing above the band and fires entry after entry, all of which stop out.

Exit: take profit when a candle closes at or below the LOWER Bollinger band.
Stop loss: "a fixed percentage from entry". No ROI/trailing table.

Reported by the source: win rate around 25%, winners roughly 3.5x the size of
losers, best year 2022, effectively dormant in 2021 and 2024, out-of-sample
positive but weaker than in-sample.

WHAT THE SOURCE DOES NOT DISCLOSE (paywalled)
---------------------------------------------
The EMA lengths, the volume SMA length P, the Bollinger period and standard
deviation multiplier, and the stop-loss percentage. Every one of those is a
placeholder below. The stop percentage is the most consequential: it defines 1R,
and 1R is the denominator of every number this project reports. That is why a
stop-size sensitivity check is run alongside the main result.
"""

from __future__ import annotations

import pandas as pd

from harness import ExitPlan, Signal

# ---------------------------------------------------------------------------
# PLACEHOLDER PARAMETERS - none of these came from the source
# ---------------------------------------------------------------------------
BB_PERIOD = 20        # Bollinger's own canonical default
BB_STD = 2.0          # Bollinger's own canonical default
EMA_SHORT = 20        # placeholder
EMA_MEDIUM = 50       # placeholder
VOL_SMA = 20          # placeholder
STOP_FRAC = 0.02      # placeholder: 2% from the fill price

WARMUP = 200          # long enough for EMA50, BB20, the 100-bar regime MA and ATR


def add_indicators(df: pd.DataFrame, stop_frac: float = STOP_FRAC) -> pd.DataFrame:
    """Every column here is computed from bars that have already closed.

    Rolling and expanding windows in pandas look backwards only. The EMA is the
    recursive form (adjust=False), whose value at a bar depends on that bar and
    the running average before it - never on a later bar. `first_close_above`
    compares this bar's close to this bar's band and the PREVIOUS bar's close to
    the PREVIOUS bar's band, using .shift(1), which moves data forwards in time.
    """
    out = df.copy()
    close = out["close"]

    mid = close.rolling(BB_PERIOD, min_periods=BB_PERIOD).mean()
    sd = close.rolling(BB_PERIOD, min_periods=BB_PERIOD).std(ddof=0)
    out["bb_mid"] = mid
    out["bb_upper"] = mid + BB_STD * sd
    out["bb_lower"] = mid - BB_STD * sd

    out["ema_short"] = close.ewm(span=EMA_SHORT, adjust=False).mean()
    out["ema_medium"] = close.ewm(span=EMA_MEDIUM, adjust=False).mean()
    out["vol_sma"] = out["volume"].rolling(VOL_SMA, min_periods=VOL_SMA).mean()

    above = close > out["bb_upper"]
    out["first_close_above"] = above & ~above.shift(1, fill_value=False)
    return out


def entry(df: pd.DataFrame, stop_frac: float = STOP_FRAC):
    """Short on the first close above the upper band, in a downtrend, on volume."""
    cross = df["first_close_above"].to_numpy()
    ema_s = df["ema_short"].to_numpy()
    ema_m = df["ema_medium"].to_numpy()
    vol = df["volume"].to_numpy()
    vsma = df["vol_sma"].to_numpy()

    def fn(_d: pd.DataFrame, i: int) -> Signal | None:
        if not cross[i]:
            return None
        if not (ema_s[i] < ema_m[i]):          # NaN comparisons are False -> no trade
            return None
        if not (vol[i] > vsma[i]):
            return None
        return Signal(direction=-1, stop_frac=stop_frac)

    return fn


def native_exit(df: pd.DataFrame):
    """The source's own exit: fixed-% stop, take profit on a close at the lower band.

    The stop is a resting order, so an intrabar touch fills it. The take profit is
    a decision read off a finished candle, so it fills at the next candle's open -
    the same rule that governs entries. If one candle both reaches the stop and
    closes below the lower band, the stop is taken; the engine always resolves
    that ambiguity against us.
    """
    close = df["close"].to_numpy()
    lower = df["bb_lower"].to_numpy()

    def fn(_d: pd.DataFrame, i: int, trade) -> ExitPlan:
        plan = ExitPlan(stop_level=trade.initial_stop)
        if close[i] <= lower[i]:                # NaN -> False -> keep holding
            plan.close_exit = True
            plan.reason = "bb_lower"
        return plan

    return fn
