"""Strategy #4 - Crabel's Opening Range Breakout, the "stretch".

WHAT THE SOURCE ACTUALLY SAYS
-----------------------------
Toby Crabel, writing on his own Substack in 2025 ("Opening Range Breakout: A
Century"). This is the originator stating his own rule, which is the best
sourcing in this project so far. Eighty-four futures markets, daily open/high/
low/close, January 1923 through 4 July 2025, equally weighted, each era holding
only the markets tradable in it.

The entire rule, in his words:

  * "Compute the distance, call it the stretch, and place a buy stop that far
    above the open and a sell stop that far below it."
  * "The stretch is set at 0.8 times the ten-day range, held the same way
    throughout this book."
  * "Whichever side trades first is the position."
  * "There is no protective stop."
  * "The trade is held until the next day's open, and exited there."
  * "One stretch, one exit rule, no stops, held constant across eighty-four
    markets and a hundred years of daily data."

He argues the no-stop choice rather than merely preferring it: "A stop is a
second decision layered on top of the first one", which would blend entry
quality with exit quality and break comparability across a century.

WHAT HE CLAIMS
--------------
Full-period stream-level SHARPE 1.40, stated as GROSS of commissions and
slippage. Decade averages of annual Sharpe "above six" in the 1970s-90s, then
2.92 in the 2000s and 0.91 in the 2010s. 22 of the 103 years negative. He
deliberately publishes no win rate and no reward-to-risk: "We think in dollars
and Sharpe here, not in percentages of winning trades." So there is no 1:3
claim attached to this strategy - it is on the list as a documented performer,
not as a documented 1:3 system.

THE ONE THING HE DOES NOT RESOLVE
---------------------------------
What "the ten-day range" measures. Two readings are available and they differ
by roughly three to four times:

  AVG   the mean of the last ten daily ranges          <- traded here
  SPAN  the highest high minus the lowest low over ten days

AVG is the coherent reading because it is the only one that puts the trigger a
plausible distance from the open; SPAN would place it 8-12% away on these coins
and would barely ever fill. SPAN is run as a sensitivity rather than argued
about. A third definition exists: Crabel's 1990 book is described by third
parties (MQL5 and TradingView indicator authors) as using the ten-day average
of the SMALLER of open-to-high and open-to-low, with no 0.8 multiplier. I have
not read the book, so that reading is attributed to those descriptions and not
to Crabel, and it is also run as a sensitivity.

WHAT CANNOT BE TESTED HERE, AND WHY
-----------------------------------
THE OPENING AUCTION. This is the largest adaptation in the project so far.
Crabel's edge sits in a pit that closes overnight, gaps, and reopens with an
auction that concentrates order flow into one moment. Crypto never closes.
00:00 UTC is used as the session boundary because it is what the exchange's own
daily candle uses, but it is a timestamp rather than an event. If this strategy
fails here, "crypto has no opening auction" is a sufficient explanation on its
own and the failure does not disprove Crabel.

EIGHTY-FOUR MARKETS. The claim is a portfolio claim: 84 equally weighted
futures streams across grains, metals, energies, rates and currencies. Three
correlated crypto perpetuals cannot reproduce that, and a Sharpe built on 84
weakly-correlated streams is not comparable to one built on three coins that
mostly move together. This is the single largest reason to expect a lower
number here, and it is a property of the test, not of the rule.

COMMISSIONS. His 1.40 is gross. Every number produced here is post-fee at the
project's Bybit rates, so the comparison is deliberately unfair to this test in
the honest direction.

HOW 1R IS DEFINED, AND WHY THAT NEEDED A DECISION
-------------------------------------------------
The source has no stop, so it has no natural risk unit. Inventing one and
calling it Crabel's would misrepresent him. Instead 1R is ONE STRETCH - the
same quantity that defines the entry - and it is used as a measuring stick, not
as an order. The native variant enforces no stop at all, exactly as written.
Only the project's forced 1:3 variant turns 1R into a real stop, which is what
that variant is for.

A consequence worth stating before any results: with 1R = one stretch, the
forced variant's stop lands exactly on the session open, because entry is one
stretch above it. That is a coincidence of the arithmetic rather than a choice.
1R = TWO stretches is run as a sensitivity, which puts the forced stop on the
opposite entry trigger - the classic stop-and-reverse level.

WHAT THE TIMEFRAME AXIS MEANS ON THIS STRATEGY
----------------------------------------------
Nothing about the rule changes with the bar size: the session is always the UTC
day and the trigger levels are always the day's open plus and minus one
stretch. What changes is only how finely the bars can resolve WHEN a resting
order was penetrated. So 1H/4H/6H/1D here are not four independent tests of the
idea - they are one test at four execution resolutions, and they should be read
that way. The finest resolution is the most faithful.

Two things can go wrong at coarse resolution, and they turn out to be very
different in size:

  THE BOTH-SIDES BAR. A bar whose range covers both triggers cannot say which
  side traded first, so those sessions are skipped and counted rather than
  guessed. This was expected to be a problem on daily bars and measurably is
  not: because the stretch is 0.8 of an average day's range on EACH side, a
  bar has to span 1.6 average ranges with the open near its middle. On BTC it
  happens 0 times in 2336 hourly sessions and 15 times in 2235 daily ones.
  The counts are reported anyway, but this is not what limits the test.

  THE ENTRY-BAR STOP. This one is severe, and only for the forced 1:3 variant.
  A trade entered part-way through a bar is still tested against that whole
  bar, including the part that happened before the order was penetrated. With
  1R = one stretch the forced stop sits exactly on the session open, and a
  daily candle's low is almost always at or below its own open - so on daily
  bars essentially every forced trade is recorded as stopped out on its entry
  day, whether or not the dip actually came after the entry. The distortion
  shrinks with the bar: on BTC it kills about a third of forced trades on the
  entry bar at 1H, three quarters at 6H, and all of them at 1D. The forced
  rows on coarse bars therefore measure the resolution of the data, not the
  rule, and are reported with that said out loud. The NATIVE rule has no stop
  at all, so it is completely untouched by this and is tested cleanly at every
  resolution - which is fortunate, because the native rule is Crabel's.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan

# --- stated by the source ---------------------------------------------------
STRETCH_MULT = 0.8            # "0.8 times the ten-day range"
STRETCH_LOOKBACK_DAYS = 10    # "the ten-day range"

# --- PLACEHOLDER - not in the source ---------------------------------------
# Crabel names a "narrow range day, or BNR" and a "wide range day, or BWR" as
# the conditioning framework, but defers whether either beats the baseline to
# paywalled chapters and never states N. 7 is used because NR7 is the standard
# form of that pattern and is itself Strategy #9 on this project's list.
COND_LOOKBACK_DAYS = 7

READINGS = ("avg", "span", "tail")


def bars_per_day(df: pd.DataFrame) -> int:
    """Read the timeframe off the timestamps rather than being told it."""
    secs = float(df["open_time"].diff().dropna().median().total_seconds())
    return max(int(round(86400.0 / secs)), 1)


def _daily(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse the frame to one row per UTC day.

    For an hourly frame the daily high is the maximum of that day's hourly
    highs, so this is exact rather than an approximation. For a daily frame it
    is the identity.
    """
    day = pd.DatetimeIndex(df["open_time"]).tz_convert("UTC").normalize()
    g = df.groupby(day, sort=True)
    out = pd.DataFrame({
        "open": g["open"].first(),
        "high": g["high"].max(),
        "low": g["low"].min(),
    })
    out.index.name = "day"
    return out


def add_indicators(
    df: pd.DataFrame,
    reading: str = "avg",
    r_mult: float = 1.0,
    cond: str = "all",
) -> pd.DataFrame:
    """Build the two resting order levels and the session bookkeeping.

    Every column here is knowable BEFORE the bar it sits on begins to trade.
    Three places where that needed care:

      * THE STRETCH is built from daily bars and then shifted one day, so a
        bar on day D uses days D-10 through D-1 and never its own day. Those
        ten days are complete in a truncated history and in the full history
        alike, which is what makes the lookahead audit meaningful here.
      * THE SESSION OPEN is the open of the day's first bar. At the moment that
        bar opens the price is known, and every later bar in the session can
        look back at it. This is the one place in the project where a decision
        uses the CURRENT bar's open, and it is legitimate: an open is knowable
        at the instant a bar starts, which is exactly when Crabel's two stop
        orders are placed.
      * SESSION-FIRST AND SESSION-LAST are derived from the timestamp and the
        bar duration, never by looking at the neighbouring row. Asking "does
        the next row belong to a different day" would give a different answer
        on the final bar of a truncated frame than on the same bar of the full
        frame, and the audit would - correctly - fail it.

    What this function deliberately does NOT touch is the current bar's high or
    low. Whether a resting order filled is the engine's question, answered at
    fill time; whether to place it is this function's question, answered from
    information that predates the bar.
    """
    if reading not in READINGS:
        raise ValueError(f"unknown stretch reading {reading!r}")

    out = df.copy()
    bpd = bars_per_day(out)
    stamps = pd.DatetimeIndex(out["open_time"]).tz_convert("UTC")
    day = stamps.normalize()

    d = _daily(out)
    rng = d["high"] - d["low"]
    L = STRETCH_LOOKBACK_DAYS

    if reading == "avg":
        # The coherent reading: 0.8 x the average of the last ten daily ranges.
        stretch_d = STRETCH_MULT * rng.rolling(L, min_periods=L).mean()
    elif reading == "span":
        # The other reading of "ten-day range": highest high to lowest low.
        span = d["high"].rolling(L, min_periods=L).max() - d["low"].rolling(L, min_periods=L).min()
        stretch_d = STRETCH_MULT * span
    else:
        # The 1990-book reading as described by third parties: the ten-day mean
        # of the smaller distance from the open, and no 0.8 multiplier.
        tail = pd.concat([d["open"] - d["low"], d["high"] - d["open"]], axis=1).min(axis=1)
        stretch_d = tail.rolling(L, min_periods=L).mean()

    # One day's lag: a bar on day D may only use days that already closed.
    stretch_d = stretch_d.shift(1)

    # The prior-day conditioning Crabel names but does not measure in the open
    # text. Comparing the last COMPLETED day's range with the N days before it.
    prev_rng = rng.shift(1)
    win = prev_rng.rolling(COND_LOOKBACK_DAYS, min_periods=COND_LOOKBACK_DAYS)
    if cond == "all":
        cond_d = pd.Series(True, index=d.index)
    elif cond == "bnr":
        cond_d = prev_rng <= win.min()
    elif cond == "bwr":
        cond_d = prev_rng >= win.max()
    else:
        raise ValueError(f"unknown conditioning {cond!r}")

    # Map the daily series back onto every bar of its own day.
    idx = pd.Index(day)
    out["stretch"] = stretch_d.reindex(idx).to_numpy()
    out["cond_ok"] = cond_d.reindex(idx).fillna(False).to_numpy()

    # The session open, carried to every bar of the session.
    sess_open = out.groupby(day, sort=True)["open"].transform("first")
    out["session_open"] = sess_open.to_numpy()

    # Session boundaries from the clock alone.
    step = pd.Timedelta(seconds=86400 // bpd)
    out["session_first"] = np.asarray(stamps == day)
    out["session_last"] = np.asarray((stamps + step).normalize() != day)

    # The two resting orders, and the risk unit used only as a measuring stick.
    ok = np.isfinite(out["stretch"].to_numpy()) & (out["stretch"].to_numpy() > 0)
    out["buy_trig"] = np.where(ok, out["session_open"] + out["stretch"], np.nan)
    out["sell_trig"] = np.where(ok, out["session_open"] - out["stretch"], np.nan)
    out["risk_unit"] = np.where(ok, r_mult * out["stretch"], np.nan)
    out["armed"] = ok & out["cond_ok"].to_numpy()
    return out


def native_exit(df: pd.DataFrame):
    """The source's own exit, and nothing else: out at the next day's open.

    No stop level and no target level are ever returned, so the engine has
    nothing to enforce intrabar - which is the point. `close_exit` on the
    session's final bar is filled at the following bar's open, and the bar
    following a session's last bar is the next session's first bar, so that
    fill IS the next day's open.
    """
    last = df["session_last"].to_numpy()

    def fn(_d: pd.DataFrame, i: int, _trade) -> ExitPlan:
        return ExitPlan(close_exit=bool(last[i]), reason="next open")

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
    """Ten completed days for the stretch, seven more for the conditioning.

    The 120-bar floor is there so the reporting-only regime label (a 100-bar
    average) is populated rather than reading "unknown".
    """
    bpd = {"1H": 24, "4H": 6, "6H": 4, "1D": 1}[interval]
    days = STRETCH_LOOKBACK_DAYS + COND_LOOKBACK_DAYS + 2
    return max(days * bpd, 120)
