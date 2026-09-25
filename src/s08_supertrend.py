"""Strategy #8: Supertrend (Olivier Seban).

Supertrend is a trend-following indicator that places a trailing stop based on ATR.
The indicator line sits below price in an uptrend, above price in a downtrend. When
price closes through the line, the indicator flips direction.

Entry: price closes above the Supertrend line (bullish flip).
Exit:  price closes below the Supertrend line (bearish flip).

Standard parameters: ATR period 10, multiplier 3.

Sources:
  - https://www.investopedia.com/supertrend-indicator-7976167
  - https://www.tradingtechnologies.com/help/fix-adapter-reference/pl-supertrend/
  - https://www.incrediblecharts.com/indicators/supertrend.php
"""

from __future__ import annotations

import pandas as pd

from harness import ExitPlan, Signal


ATR_PERIOD = 10
MULTIPLIER = 3.0


def add_indicators(df: pd.DataFrame,
                   atr_period: int = ATR_PERIOD,
                   multiplier: float = MULTIPLIER) -> pd.DataFrame:
    """Compute the Supertrend indicator.

    Defaults are ATR period 10, multiplier 3. They are parameters rather than
    constants because the literature does not agree on the default - TrendSpider's
    reference documents 14/3, most other sources 10/3 - so both have to be
    reachable for the sensitivity sweep.
    """
    # ATR
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift(1)).abs()
    lc = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = tr.rolling(atr_period).mean()

    # Basic bands
    hl2 = (df["high"] + df["low"]) / 2.0
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    # Supertrend logic: the line follows the lower band in an uptrend, the upper band
    # in a downtrend. When price crosses the line, it flips to the opposite band.
    # We'll track the line level and the direction (1 = bullish, -1 = bearish).
    st_line = pd.Series(index=df.index, dtype=float)
    st_dir = pd.Series(index=df.index, dtype=int)

    # Initialise: assume we start in no-trend (we'll set direction once we have enough data)
    # The standard Supertrend implementation sets the initial direction based on the first
    # close vs the first lower band. We'll handle warmup by setting direction = 0 until
    # we have ATR, then initialise from there.
    prev_line = None
    prev_dir = 0

    for i in df.index:
        close = df.loc[i, "close"]
        ub = upper_band.loc[i]
        lb = lower_band.loc[i]

        # If ATR is NaN (warmup), direction stays 0 and line is NaN
        if pd.isna(atr.loc[i]):
            st_line.loc[i] = float("nan")
            st_dir.loc[i] = 0
            prev_line = None
            prev_dir = 0
            continue

        # If this is the first bar with valid ATR, initialise direction
        if prev_dir == 0:
            # Standard init: if close > lower_band, start bullish; else bearish
            if close > lb:
                direction = 1
                line = lb
            else:
                direction = -1
                line = ub
        else:
            # Continue from previous state
            direction = prev_dir
            line = prev_line

            # Ratchet the bands: in an uptrend, the lower band can only rise (or stay);
            # in a downtrend, the upper band can only fall (or stay). This prevents the
            # stop from moving against the trend.
            if direction == 1:
                # Bullish: use lower band, ratchet up
                line = max(lb, prev_line) if not pd.isna(prev_line) else lb
            else:
                # Bearish: use upper band, ratchet down
                line = min(ub, prev_line) if not pd.isna(prev_line) else ub

            # Check for a flip: if price closes through the line, reverse direction
            if direction == 1 and close <= line:
                # Bullish trend broken, flip to bearish
                direction = -1
                line = ub  # no ratchet on the flip bar
            elif direction == -1 and close >= line:
                # Bearish trend broken, flip to bullish
                direction = 1
                line = lb  # no ratchet on the flip bar

        st_line.loc[i] = line
        st_dir.loc[i] = direction
        prev_line = line
        prev_dir = direction

    df["st_line"] = st_line
    df["st_dir"] = st_dir
    df["atr"] = atr

    return df


def entry(df: pd.DataFrame, long_only: bool = False):
    """Buy when Supertrend flips bullish; short when it flips bearish.

    `long_only` exists because the literature is genuinely split on whether this
    rule trades both directions. TrendSpider's reference describes a bearish flip
    as "a possible short entry or exit from long trades"; most retail treatments
    use the line only to time entries and exits of a long book. Both readings are
    therefore run, and which one was traded is stated in the write-up rather than
    buried in a flag.
    """

    def _entry(df_arg: pd.DataFrame, i: int):
        if i == 0:
            return None

        # Check for a flip this bar
        curr_dir = df.loc[i, "st_dir"]
        prev_dir = df.loc[i - 1, "st_dir"]

        if curr_dir == 1 and prev_dir != 1:
            # Bullish flip -> go long
            atr_val = df.loc[i, "atr"]
            if pd.isna(atr_val) or atr_val <= 0:
                return None
            return Signal(direction=1, stop_frac=atr_val / df.loc[i, "close"])

        if curr_dir == -1 and prev_dir != -1 and not long_only:
            # Bearish flip -> go short
            atr_val = df.loc[i, "atr"]
            if pd.isna(atr_val) or atr_val <= 0:
                return None
            return Signal(direction=-1, stop_frac=atr_val / df.loc[i, "close"])

        return None

    return _entry


def native_exit(df: pd.DataFrame):
    """Exit when Supertrend flips the other way."""

    def _exit(df_arg: pd.DataFrame, i: int, trade):
        if i == 0:
            return ExitPlan()

        curr_dir = df.loc[i, "st_dir"]
        prev_dir = df.loc[i - 1, "st_dir"]

        # Long trade wants out when the trend flips bearish
        if trade.direction == 1 and curr_dir == -1 and prev_dir == 1:
            return ExitPlan(close_exit=True, reason="supertrend flip bearish")

        # Short trade wants out when the trend flips bullish
        if trade.direction == -1 and curr_dir == 1 and prev_dir == -1:
            return ExitPlan(close_exit=True, reason="supertrend flip bullish")

        return ExitPlan()

    return _exit
