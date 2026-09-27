"""Strategy #9 - Narrow Range 7 (NR7): consolidation, then expansion.

Crabel names the "narrow range day" as the conditioning framework for his
opening-range breakout and defers the measurement to paywalled chapters
(see s04_crabel_orb.py, which is where this project records that NR7 is the
next strategy in the lineage). The standard, fully-published form of that
pattern is Bulkowski's NR7, and that is what is tested here.

THE RULE, AS STATED BY THE SOURCE
---------------------------------
Thomas Bulkowski, "NR7", thepatternsite.com (Encyclopedia of Chart Patterns):

  * Setup - "The most recent bar must have a smaller high-low price range than
    the prior six bars (seven bars, total)." The range is high - low. Not true
    range: he is explicit that it is the high-low range.
  * Breakout - "A breakout occurs when price closes above the top or below the
    bottom of the NR7."
  * Entry, for the cryptocurrency test specifically - "I placed a buy stop a
    penny above the top of the NR7 and a stop loss order a penny below the
    bottom of the pattern."
  * Exit (the measure rule) - "Measure the height of pattern and add it to the
    highest price in the pattern to get an upward target or subtract it from
    the lowest low in the pattern to get a downward price target."
  * Published result on that exact exit, 38 cryptocurrencies: 48% win rate in
    an uptrend, 42% in a downtrend, average gain of winners 13% against an
    average loss of losers of -7% - and the pattern UNDERPERFORMS a
    buy-and-hold benchmark in both directions.

MAPPING ONTO THIS PROJECT'S ENGINE
----------------------------------
A narrow bar has closed. Before the next bar opens, two stop orders are placed:
a buy at the narrow bar's high and a sell at its low. The market picks the
direction. This is `simulate_resting`, not `simulate` - the same execution path
Strategy #4 needed, for the same reason: filling a breakout at the next bar's
OPEN would erase the pattern instead of trading it.

The risk unit is the narrow bar's own range. A long filled at the bar's high
has its stop exactly one range below, at the bar's low, because
`initial_stop = entry_px - d * risk_unit`. The stop the engine constructs is
therefore the stop the source describes, arrived at rather than imposed.

WHAT IS NOT IN THE SOURCE, AND IS A PLACEHOLDER
----------------------------------------------
"A penny" above and below. Bulkowski trades equities at non-trivial prices,
where a penny is a negligible fraction; on a $100,000 bitcoin it is nothing at
all. The trigger is placed exactly at the bar's high and low instead, and the
offset is run as a sensitivity (`offset_mult`) rather than assumed.

N is 7, because the source is "NR7". NR4 is a separately documented pattern and
is run as a sensitivity. The lookahead audit runs on the headline config.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan

# --- stated by the source -----------------------------------------------------
LOOKBACK = 7          # "the prior six bars (seven bars, total)"

# --- PLACEHOLDER - not in the source -----------------------------------------
# "a penny above the top" is not a tradeable fraction of a bitcoin. 0.0 puts
# the trigger exactly on the bar's edge; a positive multiple adds that fraction
# of the bar's own range beyond the edge, in our favour.
OFFSET_MULT = 0.0

# The source places the two stops after the narrow bar closes and says when the
# BREAKOUT is recognised, not when unfilled orders are cancelled. One bar - the
# next bar - is the literal reading of "a breakout occurs when price closes
# above the top", so that is the headline. Letting the orders rest longer is run
# as a sensitivity, since a real stop order does not expire at a bar's close.
REST_BARS = 1


def add_indicators(
    df: pd.DataFrame,
    lookback: int = LOOKBACK,
    offset_mult: float = OFFSET_MULT,
    rest_bars: int = REST_BARS,
) -> pd.DataFrame:
    """Mark the NR7 bar and place the two resting orders for the bars after it.

    Every column here is knowable BEFORE the bar it sits on begins to trade:

      * IS_NR7 compares this bar's range against the six bars before it. All
        seven bars are complete when bar D's range is measured, and the
        comparison is written on bar D itself, so it is a closed-bar fact.
      * THE TRIGGERS AND THE RISK UNIT are the MOST RECENT narrow bar's own
        high, low and range - `where(is_nr7).ffill().shift(1)`, which at bar i
        reads only bars at or before i-1.
      * ARMED, SESSION-FIRST AND SESSION-LAST all come from IS_NR7 alone, never
        from the clock and never from a neighbouring row. The "session" here is
        not a trading day; it is the opportunity window the source describes -
        the bar(s) after a narrow bar, during which the two stops are live. Tie
        it to the clock instead and an NR7 bar closing at 03:00 would arm orders
        for a session that began at midnight and already ended, silently
        discarding 23 of every 24 hourly signals.

    What this function deliberately does NOT touch is the current bar's high or
    low. Whether a resting order filled is the engine's question; whether to
    place it is this function's, answered from bars that already closed.
    """
    out = df.copy()

    rng = out["high"] - out["low"]

    # Bar D is narrow iff its range is smaller than EACH of the prior six.
    # rolling(min).shift(1) over the prior LOOKBACK-1 bars gives their strict
    # minimum, so an equally narrow earlier bar does NOT count as narrower -
    # matching "must have a smaller range than the prior six".
    prev_min = rng.rolling(lookback - 1, min_periods=lookback - 1).min().shift(1)
    out["is_nr7"] = (rng < prev_min).fillna(False)

    # The most recent narrow bar's own geometry, carried onto the bars that
    # follow it. ffill reaches back over closed bars only, shift(1) keeps the
    # narrow bar's own row from carrying its own levels.
    narrow = out["is_nr7"]
    out["nr_high"] = out["high"].where(narrow).ffill().shift(1)
    out["nr_low"] = out["low"].where(narrow).ffill().shift(1)
    out["nr_range"] = out["nr_high"] - out["nr_low"]

    # Armed for the REST_BARS after each narrow bar: a rolling-any over the
    # prior REST_BARS bars, so bar i looks only at bars i-1 and earlier.
    hit = narrow.astype("int64")
    armed = (hit.rolling(rest_bars).max().shift(1).fillna(0.0) > 0).to_numpy()

    # A session is exactly the armed window: it opens on the first bar after a
    # narrow bar and closes on the last. For REST_BARS = 1 the two coincide.
    out["session_first"] = narrow.shift(1).fillna(False).to_numpy(dtype=bool)
    out["session_last"] = narrow.shift(rest_bars).fillna(False).to_numpy(dtype=bool)

    # Only arm when the narrow bar has a usable range. A flat bar (high == low)
    # has no definable 1R, so its orders cannot be priced.
    nr_rng = out["nr_range"].to_numpy(dtype=float)
    ok = armed & np.isfinite(nr_rng) & (nr_rng > 0)

    # The two resting orders, and the risk unit used as a measuring stick.
    offset = offset_mult * out["nr_range"]
    out["buy_trig"] = np.where(ok, out["nr_high"] + offset, np.nan)
    out["sell_trig"] = np.where(ok, out["nr_low"] - offset, np.nan)
    out["risk_unit"] = np.where(ok, out["nr_range"], np.nan)
    out["armed"] = ok
    return out


def native_exit(df: pd.DataFrame):
    """The source's own exit, and nothing else: the measure rule.

    The pattern's height is projected from the entry in the trade's direction,
    which is the 1R target, and the stop is the opposite end of the same
    pattern, which the engine has already placed at exactly 1R. So this exit is
    a symmetric 1:1 - target one range beyond the entry, stop one range behind
    it - and both levels come from the narrow bar rather than being chosen.

    That the source's own exit is 1:1 while the project's comparison ruler is
    1:3 is the whole point of running both: the native exit is what the pattern
    claims, the forced exit is the common yardstick every other strategy is
    measured against.
    """
    def fn(_d: pd.DataFrame, _i: int, trade) -> ExitPlan:
        r = trade.risk_per_unit
        d = trade.direction
        return ExitPlan(
            stop_level=trade.initial_stop,
            target_level=trade.entry_price + d * 1.0 * r,
        )

    return fn


def no_entry(_df: pd.DataFrame):
    """Placeholder for StrategySpec.entry.

    The resting-order execution path takes its levels from the frame's columns
    rather than from a per-bar signal function, so this is never consulted. It
    exists so the spec keeps one shape for every strategy.
    """
    def fn(_d: pd.DataFrame, _i: int):
        return None
    return fn


def warmup_for(interval: str) -> int:
    """Six prior bars plus the narrow bar itself, plus one to trade into.

    The 120-bar floor is there so the reporting-only regime label (a 100-bar
    average) is populated rather than reading "unknown".
    """
    bpd = {"1H": 24, "4H": 6, "6H": 4, "1D": 1}[interval]
    return max((LOOKBACK + 2) * bpd, 120)
