"""Strategy #6 - Ichimoku Cloud trend trading on Bybit USDT perpetuals.

WHAT THE SOURCE ACTUALLY SAYS
-----------------------------
A short trade description, not a paper. In full, verbatim:

  * TRIGGER: "Price breaks above the cloud with the conversion line crossing
    above the base line (bullish); mirror for shorts."
  * STOP-LOSS: "Below the cloud / below the base line."
  * TAKE-PROFIT: "Commonly the lagging span or a fixed multiple."
  * MARKET CONDITION: "Sustained trends. It's a lagging system and gets chopped
    up in ranges."
  * DOCUMENTED RR: "~1.5:1, with win rates ranging 39-58% depending on settings
    (Pineify)."

SOURCING: MEDIUM, and weaker than Strategy #5's. Two things #5 at least had are
missing here. The source does not say WHAT MARKET the 39-58% win rates came from,
and it does not say WHAT BAR SIZE. So there is no like-for-like column to build:
the claim cannot be matched against this test on market or timeframe, only on
shape. And the claim itself is a range, not a number - the source attributes the
range to "settings", which makes the settings sweep below mandatory rather than
optional. It is the source's own stated reason its results move.

WHAT THE SOURCE DOES NOT DISCLOSE
---------------------------------
Every number the indicator is made of. Ichimoku has four parameters and the
source states none of them: the conversion-line window, the base-line window,
the second cloud span's window, and how far forward the cloud is displaced. They
are set here to Goichi Hosoda's original 9 / 26 / 52 / 26 - the values in widest
circulation and the ones any chart package defaults to - and then swept over
three complete parameter sets, because the source says in as many words that its
win rate depends on them.

WHY THE TAKE-PROFIT CANNOT BE TAKEN LITERALLY
---------------------------------------------
"Commonly the lagging span or a fixed multiple" offers two exits and neither one
is usable as written:

  * THE LAGGING SPAN IS NOT A PRICE YOU CAN TRADE TO. The lagging span is simply
    the close, drawn 26 bars in the PAST. So the lagging-span value sitting at
    bar i on a chart is the close of bar i+26 - a price that does not exist yet
    when the decision is made. Using it as a take-profit level is not a
    parameter choice, it is time travel. This is the single biggest lookahead
    trap in this indicator and it is why the take-profit is not implemented.
  * "A FIXED MULTIPLE" names no multiple, so it is not a rule. Choosing one
    would be writing the strategy instead of testing it.

So the native exit carries NO target, exactly as in Strategy #5, and this
project's second variant - the forced 1:3 - IS the source's fixed-multiple exit,
imposed. The source's own documented ~1.5:1 is additionally run as a labelled
sensitivity so the claim itself gets measured rather than quoted.

The lagging span is not thrown away, though. It has one legitimate use: as a
CONFIRMATION, phrased in the only direction that does not consume the future -
"is today's close above the close 26 bars ago". That comparison uses two bars
that have both already happened. It is run as a sensitivity.

THE STOP IS A TWO-WAY AMBIGUITY, AND IT IS NOT SILENTLY RESOLVED
----------------------------------------------------------------
"Below the cloud / below the base line" names two different prices, and the gap
between them is the entire risk budget of the trade. Both are measured; the
traded one is declared in advance and on a structural argument, not on which
one scored better:

  * BELOW THE CLOUD (traded). For a long, 1R runs from the fill to the BOTTOM of
    the cloud. Entry requires a close above the cloud's TOP, and the bottom is by
    construction at or below the top, so this stop is ALWAYS on the correct side
    of the entry. No signal is ever discarded for having an impossible stop.
  * BELOW THE BASE LINE (sensitivity). The base line is a 26-bar midpoint. When
    price breaks out above a cloud that was drawn from data 26 bars old, the base
    line can easily sit ABOVE the entry - which is not a stop-loss at all, it is
    a level already passed. Those signals have to be thrown away, and the count
    of thrown-away signals is reported rather than hidden.

Of the discard bar's tests only expectancy depends on this choice; Sharpe,
achieved reward-to-risk and R-recovery are all scale-free.

THE STOP TRAILS, AND IT CAN ALSO LOOSEN
---------------------------------------
The cloud is re-read on every bar, so in a run the cloud bottom rises underneath
a long and the stop follows it up - the source's stop is a trailing stop by
construction, not by an added rule. But a cloud bottom can also FALL, and the
plain reading of "stop below the cloud" then puts the stop further away than it
was at entry. No ratchet is added to prevent that, because a ratchet is a rule
the source does not contain, and Strategy #5 set the precedent of letting a
source-placed stop be whatever the source placed. The consequence is that a
native loser can lose MORE than one unit of risk, so the worst single loss and
the share of losers beyond -1.2R are both measured and reported.

WHAT THE NATIVE EXIT ACTUALLY IS
--------------------------------
The trailing stop above, and nothing else. The source states no signal exit at
all: its two exits are an unknowable level and an unstated multiple. A trend
system held until its trailing stop is hit is the honest minimum, so that is the
native rule. The obvious candidate exit - close the trade when the entry
condition stops being true - is NOT in the source, so it is run as a labelled
sensitivity instead of being smuggled into the headline.

ENTRY IS EDGE-TRIGGERED, NOT A STATE
------------------------------------
"Price is above the cloud and the conversion line is above the base line" is a
state that can persist for hundreds of bars. Traded as a state, the rule
re-enters on the bar after every exit while the state holds, which measures the
exit's churn rather than the entry. The bar on which the pair FIRST becomes true
is what is traded; the state version is run once as a sensitivity, the same
treatment Strategies #3 and #5 gave the same question.

One further reading is declared rather than hidden: the source says the
conversion line "crossing" above the base line, which is an event, while "price
breaks above the cloud" is a second event. Requiring both on the same bar is
almost never satisfied. What is traded is the first bar on which BOTH conditions
hold - which fires on whichever of the two happens second - and that is the
closest thing to the source's sentence that produces a testable rule.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan, Signal

# --- NOT STATED BY THE SOURCE - every one of these is a placeholder ---------
CONV = 9        # conversion line (tenkan-sen): midpoint of the last 9 bars
BASE = 26       # base line (kijun-sen): midpoint of the last 26 bars
SPAN_B = 52     # the cloud's second edge: midpoint of the last 52 bars
DISP = 26       # how far forward the cloud is displaced
SOURCE_RR = 1.5  # the source's own documented reward-to-risk. Sensitivity only,
                 # never the traded rule.

# The two readings of "below the cloud / below the base line".
RISK_CLOUD = "cloud"   # traded: the far edge of the cloud
RISK_BASE = "base"     # the source's second phrasing, read literally
RISK_READINGS = [RISK_CLOUD, RISK_BASE]

# The three complete parameter sets swept below. The source says its win rate
# moves with "settings" and never says which, so the sweep is the source's own
# caveat made measurable. Only the first is traded.
SETTINGS = {
    "9/26/52 disp 26 (Hosoda's original, traded)": (9, 26, 52, 26),
    "10/30/60 disp 30": (10, 30, 60, 30),
    "20/60/120 disp 30 (the 24/7-market adjustment)": (20, 60, 120, 30),
}


def _mid(df: pd.DataFrame, n: int) -> pd.Series:
    """Ichimoku's building block: the midpoint of the last n bars' range.

    (highest high + lowest low) / 2, with min_periods equal to the window so a
    partly-filled window is NaN rather than a midpoint of fewer bars. Windows are
    positional, which is what the lookahead audit needs: it truncates history at
    the END, so bar i's window covers the same bars in both passes.
    """
    return (df["high"].rolling(n, min_periods=n).max()
            + df["low"].rolling(n, min_periods=n).min()) / 2.0


def add_indicators(
    df: pd.DataFrame,
    conv: int = CONV,
    base: int = BASE,
    span_b: int = SPAN_B,
    disp: int = DISP,
    risk: str = RISK_CLOUD,
    chikou: bool = False,
) -> pd.DataFrame:
    """The cloud, the trigger flags and the 1R level. Nothing peeks forward.

    THE DISPLACEMENT IS BACKWARD IN THE DATA, FORWARD ON THE CHART
    The two cloud edges are drawn `disp` bars to the RIGHT of the bars they were
    computed from. So the cloud a trader can see at bar i was computed from data
    at bar i - disp, which is `.shift(disp)` here - a shift into the PAST, using
    only bars that have already closed. The un-shifted series is deliberately not
    used for anything: it is the cloud that will be drawn `disp` bars from now,
    which is not the cloud on the chart today.

    THE INTRABAR LEVELS ARE TAKEN FROM THE PREVIOUS BAR
    `ich_stop_long_prev` / `ich_stop_short_prev` are the trailing stop, and a stop
    is a price the candle's own low or high is tested against while the bar is
    still trading. The base line at bar i is built from bar i's own high and low,
    so testing bar i's low against a base line computed from bar i would be
    placing a stop inside the candle it is meant to protect against. The cloud
    edges do not have that problem - they are already `disp` bars old - but both
    are shifted anyway so there is one rule to audit rather than two.
    """
    out = df.copy()
    tenkan = _mid(out, conv)
    kijun = _mid(out, base)

    # The two cloud edges, as they appear ON the chart at bar i.
    span_a = ((tenkan + kijun) / 2.0).shift(disp)
    span_b_line = _mid(out, span_b).shift(disp)

    out["ich_tenkan"] = tenkan
    out["ich_kijun"] = kijun
    out["ich_span_a"] = span_a
    out["ich_span_b"] = span_b_line
    edges = pd.concat([span_a, span_b_line], axis=1)
    out["ich_top"] = edges.max(axis=1)
    out["ich_bot"] = edges.min(axis=1)

    # State: the source's two conditions, both true on this closed bar.
    above = out["close"] > out["ich_top"]
    below = out["close"] < out["ich_bot"]
    bull = above & (tenkan > kijun)
    bear = below & (tenkan < kijun)
    if chikou:
        # The ONLY use of the lagging span that does not read the future: today's
        # close against the close `disp` bars ago. Both bars have closed.
        past = out["close"].shift(disp)
        bull = bull & (out["close"] > past)
        bear = bear & (out["close"] < past)
    out["ich_bull_state"] = bull.fillna(False).astype(bool)
    out["ich_bear_state"] = bear.fillna(False).astype(bool)

    # Edge: the FIRST closed bar of that state, which is what is traded.
    # `shift(1, fill_value=False)` rather than `.shift(1).fillna(False)`: the
    # second form leaves an OBJECT-dtype column, and `~` on object dtype applies
    # Python's integer bitwise NOT elementwise (~True is -2, ~False is -1, both
    # truthy), which silently collapses the edge back into the state. That bug
    # cost Strategy #5 a full run; the fill_value form keeps the column bool.
    out["long_entry"] = (out["ich_bull_state"]
                         & ~out["ich_bull_state"].shift(1, fill_value=False))
    out["short_entry"] = (out["ich_bear_state"]
                          & ~out["ich_bear_state"].shift(1, fill_value=False))

    # 1R: the level the fill's distance is measured to, and the level the stop
    # then trails along. WHICH level that is IS the ambiguity in the source's
    # wording, so both readings are built by the same code and only the traded
    # one is called the result.
    if risk == RISK_CLOUD:        # traded: the far edge of the cloud
        out["ich_stop_long"] = out["ich_bot"]
        out["ich_stop_short"] = out["ich_top"]
    elif risk == RISK_BASE:       # "below the base line", literally
        out["ich_stop_long"] = out["ich_kijun"]
        out["ich_stop_short"] = out["ich_kijun"]
    else:
        raise ValueError(f"unknown risk reading: {risk!r}")
    out["ich_stop_long_prev"] = out["ich_stop_long"].shift(1)
    out["ich_stop_short_prev"] = out["ich_stop_short"].shift(1)
    return out


def entry(df: pd.DataFrame, on_cross: bool = True):
    """Fires on the closed bar; the engine fills it at the next bar's open.

    A signal whose stop level is on the WRONG side of the close is dropped rather
    than traded backwards. Under the traded reading that can never happen - the
    cloud bottom is always below a close that is above the cloud top - but under
    the base-line reading it happens often, and dropping those is what makes the
    two readings comparable at all. The count is reported, not buried.

    `on_cross=False` swaps the edge for the raw state, which is the sensitivity
    that separates the entry from re-entry churn while the state persists.
    """
    lo_col = "long_entry" if on_cross else "ich_bull_state"
    sh_col = "short_entry" if on_cross else "ich_bear_state"
    go_long = df[lo_col].to_numpy()
    go_short = df[sh_col].to_numpy()
    r_long = df["ich_stop_long"].to_numpy()
    r_short = df["ich_stop_short"].to_numpy()
    close = df["close"].to_numpy()

    def fn(_d: pd.DataFrame, i: int):
        if go_long[i] and np.isfinite(r_long[i]) and r_long[i] < close[i]:
            return Signal(direction=1, stop_price=float(r_long[i]))
        if go_short[i] and np.isfinite(r_short[i]) and r_short[i] > close[i]:
            return Signal(direction=-1, stop_price=float(r_short[i]))
        return None

    return fn


def native_exit(df: pd.DataFrame, target_r: float | None = None,
                signal_exit: bool = False):
    """The source's own exit: the stop, re-read every bar, and nothing else.

    `target_r` is normally None because the source's take-profit is either a
    price that does not exist yet (the lagging span) or a multiple it never
    states. Passing 1.5 runs the source's own documented reward-to-risk as a
    labelled sensitivity.

    `signal_exit=True` adds "close the trade when the entry condition stops being
    true". That is NOT in the source, so it is a sensitivity, never the headline.
    """
    sl = df["ich_stop_long_prev"].to_numpy()
    ss = df["ich_stop_short_prev"].to_numpy()
    bull = df["ich_bull_state"].to_numpy()
    bear = df["ich_bear_state"].to_numpy()

    def fn(_d: pd.DataFrame, i: int, trade) -> ExitPlan:
        d = trade.direction
        level = sl[i] if d > 0 else ss[i]
        plan = ExitPlan(stop_level=float(level) if np.isfinite(level) else None)
        if target_r is not None:
            plan.target_level = trade.entry_price + d * target_r * trade.risk_per_unit
        if signal_exit and not (bull[i] if d > 0 else bear[i]):
            plan.close_exit = True
            plan.reason = "trigger gone"
        return plan

    return fn


def warmup_for(conv: int = CONV, base: int = BASE, span_b: int = SPAN_B,
               disp: int = DISP) -> int:
    """Bars discarded before the first trade is allowed.

    The cloud's slower edge needs `span_b` bars to fill its window and is then
    pushed `disp` bars to the right, so nothing on the chart is complete until
    bar span_b + disp. The floor of 120 is there so the reporting-only regime
    label (a 100-bar average plus a 20-bar slope) is populated by the time the
    first trade can happen. The source's parameters are in BARS, not calendar
    days, so this is the same bar count on every timeframe.
    """
    return max(span_b + disp, base, conv, 120) + 30
