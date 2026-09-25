"""Strategy #5 - Keltner Channel breakout on Bybit USDT perpetuals.

WHAT THE SOURCE ACTUALLY SAYS
-----------------------------
A short trade description rather than a paper. In full:

  * TRIGGER: buy when price CLOSES outside the upper Keltner Channel (a moving
    average with ATR-based bands); sell short on a close below the lower band.
  * STOP-LOSS: "back inside the channel / at the opposite band".
  * TAKE-PROFIT: "a fixed multiple of the channel width or ATR".
  * MARKET CONDITION: trending, expanding volatility.

Two results were attached to it:

  * 2.1:1 reward-to-risk on a 56% win rate, 500 stocks, 2010-2024 (TradeAlgo).
  * 57.8% win rate, Sharpe 1.33, 12.9% max drawdown, forex, 1-hour bars,
    2021-2025 (Pineify).

SOURCING: MEDIUM. Those numbers come from search-result summaries, not from
reading either methodology, so their fees, sizing and intrabar tie-break rules
are unknown. NEITHER TEST WAS ON CRYPTO - one is US equities on daily bars, the
other forex on hourly bars. This is therefore not a replication of a documented
crypto result; it is the first crypto test of a rule documented elsewhere.

WHAT THE SOURCE DOES NOT DISCLOSE
---------------------------------
Four numbers, and they are the four that define the indicator: the moving-
average length, the ATR length, the band multiplier, and the take-profit
multiple. The first three are set to the values in widest circulation for this
indicator - a 20-bar EMA, a 10-bar ATR, bands at 2.0 x ATR - and all three are
swept in the sensitivity tables rather than defended.

THE TAKE-PROFIT IS NOT INVENTED
-------------------------------
"A fixed multiple of ATR" with no multiple attached is not a rule, and picking
one would be inventing the strategy rather than testing it. So the native exit
carries NO target, and this project's second variant - the forced 1:3 - IS the
source's fixed-multiple exit, imposed. Both halves of the source's exit are
tested, just in different columns: its signal exit natively, its fixed-multiple
exit in the forced run. Its own documented ratio, 2.1:1, is additionally run as
a sensitivity so the claim itself is measured.

THE ONE GENUINE AMBIGUITY, AND HOW IT IS RESOLVED
-------------------------------------------------
"Back inside the channel / at the opposite band" names two different prices, and
the gap between them is the entire risk budget of the trade. Both readings were
measured before either was traded:

  * THE BAND JUST BROKEN ("back inside the channel", read literally). At entry
    price sits a hair above it, so 1R is a fraction of one candle - the exact
    disease Strategy #1 documented, where the engine's pessimistic intrabar
    tie-break decides the outcome instead of the strategy.
  * THE OPPOSITE BAND, read literally. That is 2 x mult x ATR away, so the
    forced variant's 3R target lands about 12 ATR from entry and cannot be
    reached inside any sane time limit.

Neither is usable as the headline, so the traded reading is declared rather than
smuggled: 1R RUNS FROM THE FILL TO THE CHANNEL'S MIDDLE LINE - the average the
bands are drawn around, the one level both of the source's phrasings bracket,
and about 2 x ATR wide, the same order as every other stop in this log. BOTH
LITERAL READINGS ARE RUN AS SENSITIVITIES and their expectancy reported, because
of the four KEEP tests only expectancy depends on this choice: Sharpe, achieved
RR and R-recovery are all scale-free.

WHAT THE NATIVE EXIT ACTUALLY IS
--------------------------------
Both of the source's stop phrasings are used, each in the role it can actually
play:

  * "at the opposite band" is a PRICE, so it is the hard stop - a level the
    candle's low (or high) can reach during the bar.
  * "back inside the channel" is a SIGNAL, so it is the exit decision - the
    first bar closing back inside the channel ends the trade at the next open.

Because the band moves with price, the second rule behaves as a trailing exit:
in a run the upper band rises, and the trade only ends once price falls back
under wherever the band has got to. And under the 1R definition above the
opposite-band hard stop sits about 2R below entry, so a native loser can lose
about two units of risk. That is the source's own placement, not a choice made
here, and it is why the native rows are read with the exit mix beside them.

ENTRY IS EDGE-TRIGGERED, NOT A STATE
------------------------------------
"Price is outside the band" is a state that can persist for many bars. Traded as
a state it re-enters on the bar after every exit while price is still outside,
which measures the exit's churn rather than the entry. The bar that first closes
outside is what is traded; the state version is run once as a sensitivity, the
same treatment Strategy #3 gave the same question.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan, Signal

# --- NOT STATED BY THE SOURCE - every one of these is a placeholder ---------
MA_LEN = 20         # the middle line: an EMA of the close
ATR_BARS = 10       # the ATR that sets how wide the bands sit
BAND_MULT = 2.0     # bands at middle +- BAND_MULT x ATR
SOURCE_RR = 2.1     # the source's own documented reward-to-risk. Used only as a
                    # sensitivity, never as the traded rule.

# The three readings of "stop back inside the channel / at the opposite band".
RISK_MIDDLE = "middle"      # traded: the channel's own centre line
RISK_OPPOSITE = "opposite"  # the source's second phrasing, read literally
RISK_BROKEN = "broken"      # the source's first phrasing, read literally
RISK_READINGS = [RISK_MIDDLE, RISK_OPPOSITE, RISK_BROKEN]


def _true_range(df: pd.DataFrame) -> pd.Series:
    """The standard true range, same definition used elsewhere in the project."""
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _mask_first(s: pd.Series, k: int) -> pd.Series:
    """Blank the first k values so an unwarmed average is never traded.

    Positional rather than time-based, which matters for the lookahead audit:
    the audit recomputes on history truncated at the END, so position 0 is the
    same bar in both passes and this mask lands on the same rows either way.
    """
    pos = pd.Series(np.arange(len(s)), index=s.index)
    return s.mask(pos < k)


def add_indicators(
    df: pd.DataFrame,
    ma_len: int = MA_LEN,
    atr_bars: int = ATR_BARS,
    mult: float = BAND_MULT,
    risk: str = RISK_MIDDLE,
    wilder: bool = False,
) -> pd.DataFrame:
    """The channel, the break flags and the 1R level. Nothing peeks forward.

    Every column is built from bar i and earlier. The two that are used as
    INTRABAR levels - prices a candle's own low or high is tested against while
    the bar is still trading - are shifted one bar on purpose:

      upper_prev / lower_prev  the native hard stop. The rails at bar i are
        computed from bar i's close AND bar i's high/low (true range), so a
        level taken from bar i and then compared with bar i's own low would be
        using the bar to place a stop inside itself. Shifted, the level is the
        one that was already on the chart when the bar opened.

    The unshifted rails are used only for DECISIONS ON A CLOSED BAR - the entry
    break and the "closed back inside" exit - which the engine fills at the next
    bar's open, so knowing bar i's close is legitimate there.
    """
    out = df.copy()
    tr = _true_range(out)
    if wilder:
        atr = _mask_first(tr.ewm(alpha=1.0 / atr_bars, adjust=False).mean(), atr_bars)
    else:
        atr = tr.rolling(atr_bars, min_periods=atr_bars).mean()
    ema = _mask_first(out["close"].ewm(span=ma_len, adjust=False).mean(), ma_len)

    out["kc_mid"] = ema
    out["kc_atr"] = atr
    out["kc_up"] = ema + mult * atr
    out["kc_lo"] = ema - mult * atr
    out["kc_up_prev"] = out["kc_up"].shift(1)
    out["kc_lo_prev"] = out["kc_lo"].shift(1)

    # State: price is outside the rail on this closed bar.
    out["out_up"] = out["close"] > out["kc_up"]
    out["out_lo"] = out["close"] < out["kc_lo"]
    # Edge: the FIRST closed bar of that state, which is what is traded.
    # `shift(1, fill_value=False)` rather than `.shift(1).fillna(False)`: the
    # second form leaves an OBJECT-dtype column, and `~` on object dtype applies
    # Python's integer bitwise NOT elementwise (~True is -2, ~False is -1, both
    # truthy), which silently collapses the edge back into the state. That is a
    # real bug this project hit once; the fill_value form keeps the column bool.
    out["long_entry"] = out["out_up"] & ~out["out_up"].shift(1, fill_value=False)
    out["short_entry"] = out["out_lo"] & ~out["out_lo"].shift(1, fill_value=False)
    # 1R: the level the fill's distance is measured to. Which level that is IS
    # the ambiguity in the source's wording, so all three readings are built by
    # the same code and only the traded one is called the result.
    if risk == RISK_MIDDLE:          # traded: the channel's centre line
        out["kc_risk_long"] = out["kc_mid"]
        out["kc_risk_short"] = out["kc_mid"]
    elif risk == RISK_OPPOSITE:      # "at the opposite band", literally
        out["kc_risk_long"] = out["kc_lo"]
        out["kc_risk_short"] = out["kc_up"]
    elif risk == RISK_BROKEN:        # "back inside the channel", literally
        out["kc_risk_long"] = out["kc_up"]
        out["kc_risk_short"] = out["kc_lo"]
    else:
        raise ValueError(f"unknown risk reading: {risk!r}")
    return out


def entry(df: pd.DataFrame, on_cross: bool = True):
    """Fires on the closed bar; the engine fills it at the next bar's open.

    `on_cross=False` swaps the edge for the raw state, which is the sensitivity
    that shows how much of the result is the entry and how much is re-entry
    churn while price sits outside the rail.
    """
    lo_col = "long_entry" if on_cross else "out_up"
    sh_col = "short_entry" if on_cross else "out_lo"
    go_long = df[lo_col].to_numpy()
    go_short = df[sh_col].to_numpy()
    r_long = df["kc_risk_long"].to_numpy()
    r_short = df["kc_risk_short"].to_numpy()
    close = df["close"].to_numpy()

    def fn(_d: pd.DataFrame, i: int):
        if go_long[i] and np.isfinite(r_long[i]) and r_long[i] < close[i]:
            return Signal(direction=1, stop_price=float(r_long[i]))
        if go_short[i] and np.isfinite(r_short[i]) and r_short[i] > close[i]:
            return Signal(direction=-1, stop_price=float(r_short[i]))
        return None

    return fn


def native_exit(df: pd.DataFrame, target_r: float | None = None):
    """The source's own exit: opposite-band hard stop + close back inside.

    `target_r` is normally None because the source never states its multiple.
    Passing 2.1 runs the source's own documented reward-to-risk as a labelled
    sensitivity.
    """
    up = df["kc_up"].to_numpy()
    lo = df["kc_lo"].to_numpy()
    up_prev = df["kc_up_prev"].to_numpy()
    lo_prev = df["kc_lo_prev"].to_numpy()
    close = df["close"].to_numpy()

    def fn(_d: pd.DataFrame, i: int, trade) -> ExitPlan:
        d = trade.direction
        level = lo_prev[i] if d > 0 else up_prev[i]
        plan = ExitPlan(stop_level=float(level) if np.isfinite(level) else None)
        if target_r is not None:
            plan.target_level = trade.entry_price + d * target_r * trade.risk_per_unit
        inside = (close[i] < up[i]) if d > 0 else (close[i] > lo[i])
        if inside:
            plan.close_exit = True
            plan.reason = "back inside"
        return plan

    return fn


def warmup_for(ma_len: int = MA_LEN, atr_bars: int = ATR_BARS) -> int:
    """Bars discarded before the first trade is allowed.

    The source's parameters are in BARS, not calendar days, so the warmup is a
    bar count and is the same number on every timeframe. Five MA lengths is the
    usual rule of thumb for an EMA to have forgotten its seed; the floor of 120
    is there so the reporting-only regime label (a 100-bar average plus a 20-bar
    slope) is populated by the time the first trade can happen.
    """
    return max(5 * ma_len, atr_bars + 5, 120) + 30
