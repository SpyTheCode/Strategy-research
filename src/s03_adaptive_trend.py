"""Strategy #3 - AdaptiveTrend, crypto trend-following on Bybit USDT perpetuals.

WHAT THE SOURCE ACTUALLY SAYS
-----------------------------
An academic preprint. 6-hour bars, Binance Futures, 150+ perpetual swaps,
Jan 2021 - Dec 2024 (in-sample 2021, held out 2022-2024).

  1. MOMENTUM ENTRY (its Eq. 2): MOM = (price now - price L bars ago) / price L
     bars ago. Long when MOM is above a threshold, short when it is below the
     negative of a threshold.
  2. A TWO-STAGE MONTHLY SCREEN decides which coins are even eligible, on the
     first trading day of each month. Stage one is market capitalisation: longs
     may only come from the top 15 by cap, shorts from the bottom. Stage two is
     a QUALITY GATE, not a ranking - a coin must have shown a SHARPE RATIO of
     at least 1.3 over the single preceding month to be a long candidate, and
     at least 1.7 to be a short candidate. The higher short bar is justified in
     the paper as "the elevated risk of short positions".
  3. NATIVE EXIT (its Eq. 3): a ratcheting ATR trailing stop. The level is
     max(yesterday's level, price - alpha x ATR) and can only ever move in the
     trade's favour. Exit when price closes through it. No take-profit exists.
  4. ALLOCATION (its Eq. 5): 70% of gross exposure to the long leg, 30% to the
     short leg, equal-weighted inside each leg, rebuilt monthly.

Costs modelled by the paper: 4 bps taker, size-dependent slippage, funding as a
rolling 8-hour charge, and a 4.5% risk-free rate.

Reported out-of-sample: 40.5% annual return, 16.8% volatility, SHARPE 2.41,
max drawdown -12.7%, Calmar 3.18. Its own ablation table is more useful than the
headline: strip the trailing stop and Sharpe falls to 1.68; strip the monthly
re-optimisation of the parameters and it falls to 1.34.

WHAT THE SOURCE DOES NOT DISCLOSE
---------------------------------
The momentum lookback L. Both entry thresholds. The ATR period k. The number of
short candidates K_S. All four are placeholders here, and L is the parameter
swept in the sensitivity check.

WHAT CANNOT BE TESTED HERE, AND WHY
-----------------------------------
THE MARKET-CAP FILTER. This project trades three coins, all of them large caps.
Under the paper's own stage one, none of the three could ever be a SHORT
candidate. Dropping the filter therefore makes the short leg tested here MORE
permissive than the paper's, not less - which is the honest direction to
declare, because it means a bad short result cannot be blamed on the filter's
absence.

THE 70/30 ALLOCATION. This harness risks a fixed 1% of equity per trade, so a
gross-exposure tilt has nothing to attach to. The two legs are reported
separately instead, which shows the same information without inventing a
portfolio weighting.

THE MONTHLY RE-OPTIMISATION. The paper re-fits L, the thresholds and alpha every
month on recent data. That is deliberately NOT reproduced: re-fitting a rule
monthly and then reporting the result as out-of-sample is curve-fitting, and the
paper's own ablation prices it at 1.07 Sharpe of the headline. So the honest
comparison target for the fixed-parameter test below is the paper's own
"fixed parameters, no optimisation" row - SHARPE 1.34 - and not its 2.41.
A SOURCE AMBIGUITY THAT HAD TO BE RESOLVED
------------------------------------------
"Sharpe ratio at least 1.7 to be a SHORT candidate" is incoherent if the Sharpe
is the coin's own: a coin with a strongly positive risk-adjusted return is
trending UP, and shorting it contradicts the paper's own momentum rule in the
very same system. The coherent reading is the Sharpe of the candidate POSITION,
so for a short it is the Sharpe of the inverse of the coin's returns. That is
what is implemented. The literal reading is also COUNTED - how many monthly
screens it would have permitted a short on - and reported, so the choice is
visible rather than buried.

HOW 1R IS DEFINED
-----------------
1R is alpha x ATR at entry, using the ATR OF THE TRADING TIMEFRAME rather than
Strategy #2's daily-equivalent range. That is deliberate and it is the opposite
choice to Strategy #2: here the source's formula is explicitly the trading
timeframe's ATR, and the source's own headline claim is that the 6-hour bar
beats the 1-hour and the daily one. Normalising the stop across timeframes would
erase exactly the effect being tested.

The consequence is that 1R is a different amount of real risk on each timeframe -
wider on the daily, narrower on the hourly - so the timeframes are NOT directly
comparable to one another here. They are each comparable to the paper's own
number for that timeframe, which is the comparison that matters.

WHY A FOURTH TIMEFRAME
----------------------
The source's headline result is on 6-hour bars, and its own timeframe table
(Sharpe 1.54 on 1H, 2.08 on 4H, 2.41 on 6H, 1.63 on 1D) makes the bar size part
of the claim. Testing everything except the configuration the source actually
claims would not be a test of the source, so 6H was added to the data layer for
this strategy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan, Signal

# --- stated by the source ---------------------------------------------------
SR_GATE_LONG = 1.3        # gamma_L, the long quality gate
SR_GATE_SHORT = 1.7       # gamma_S, deliberately higher than the long gate
SR_WINDOW_DAYS = 30       # "over the single preceding month"
ATR_MULT = 2.5            # alpha. Monthly-optimised in the paper, but its own
                          # sensitivity analysis centres here, with a flat
                          # plateau across 2.0-3.5.

# --- PLACEHOLDERS - not in the source --------------------------------------
MOM_LOOKBACK_DAYS = 14    # L in the momentum formula; never given a value
ENTRY_THRESHOLD = 0.0     # theta_entry; never given a value
ATR_BARS = 14             # k in "ATR over k periods"; never given a value

BPD = {"1H": 24, "4H": 6, "6H": 4, "1D": 1}
def bars_per_day(df: pd.DataFrame) -> int:
    """Read the timeframe off the timestamps rather than being told it.

    Inferred so add_indicators keeps a one-argument signature and the lookahead
    audit can call it on a truncated frame unchanged.
    """
    secs = float(df["open_time"].diff().dropna().median().total_seconds())
    return max(int(round(86400.0 / secs)), 1)


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


def add_indicators(
    df: pd.DataFrame,
    mom_days: int = MOM_LOOKBACK_DAYS,
    theta: float = ENTRY_THRESHOLD,
    stop_mult: float = ATR_MULT,
) -> pd.DataFrame:
    """Every column is built from bars that have already closed.

    Three places where that needs care on this strategy:

      * the TRAILING-STOP candidate uses close.shift(1) and atr.shift(1), never
        the current bar. The level in force during a bar has to be knowable
        before that bar's high and low are tested against it, otherwise the stop
        would be placed using the very range it is being compared with.
      * the MONTHLY SCREEN is measured on the window ending one bar BEFORE the
        month's first bar, then sampled only on that first bar and carried
        forward. A forward fill can only ever propagate a past value forward.
      * the ENTRY EDGE compares this bar's eligibility with the previous bar's,
        so it is built from two already-closed bars.
    """
    out = df.copy()
    bpd = bars_per_day(out)
    close = out["close"]

    # Momentum over L calendar days, expressed in bars for this timeframe.
    out["mom"] = close / close.shift(mom_days * bpd) - 1.0

    # 1R, and the trailing-stop candidate level for each direction.
    atr = _true_range(out).rolling(ATR_BARS, min_periods=ATR_BARS).mean()
    out["atr"] = atr
    out["stop_frac"] = stop_mult * atr / close
    out["trail_long"] = close.shift(1) - stop_mult * atr.shift(1)
    out["trail_short"] = close.shift(1) + stop_mult * atr.shift(1)
    # The monthly quality gate. Annualised Sharpe of this coin's own bar
    # returns over the preceding month, lagged one bar, then frozen at each
    # month's first bar and carried through the month.
    ret = close.pct_change()
    win = SR_WINDOW_DAYS * bpd
    mu = ret.rolling(win, min_periods=win).mean()
    sd = ret.rolling(win, min_periods=win).std(ddof=1)
    sr = (mu / sd) * np.sqrt(365.0 * bpd)

    stamps = pd.DatetimeIndex(out["open_time"])
    # tz dropped explicitly: the data is already UTC and calendar-month
    # bucketing does not need the offset. Left implicit it emits a warning.
    per = stamps.tz_convert(None).to_period("M") if stamps.tz is not None \
        else stamps.to_period("M")
    first_of_month = np.r_[True, per[1:] != per[:-1]]
    out["month_start"] = first_of_month

    ms = pd.Series(first_of_month, index=out.index)
    out["sr_screen"] = sr.shift(1).where(ms).ffill()

    # Coherent reading: for a short, the Sharpe of the SHORT position, which is
    # the negative of the coin's own. Literal reading kept alongside, counted
    # but never traded, so the ambiguity is measured instead of argued about.
    out["gate_long"] = out["sr_screen"] >= SR_GATE_LONG
    out["gate_short"] = out["sr_screen"] <= -SR_GATE_SHORT
    out["gate_short_literal"] = out["sr_screen"] >= SR_GATE_SHORT

    # Eligible-and-signalling. NaN momentum compares False, i.e. no trade.
    out["long_ok"] = out["gate_long"] & (out["mom"] > theta)
    out["short_ok"] = out["gate_short"] & (out["mom"] < -theta)

    # Edge-triggered version of the same condition. The paper states the entry
    # as a STATE ("long if MOM > theta"), but a state condition combined with a
    # trailing stop re-enters on the bar after every stop-out, which measures
    # the stop's churn rather than the strategy. Both are built; the edge is
    # traded and the state version is run once as a sensitivity.
    out["long_entry"] = out["long_ok"] & ~out["long_ok"].shift(1, fill_value=False)
    out["short_entry"] = out["short_ok"] & ~out["short_ok"].shift(1, fill_value=False)
    return out


def entry(df: pd.DataFrame, on_cross: bool = True):
    """Take the trade the moment the coin becomes eligible and momentum agrees.

    The long test is checked first. Under the coherent reading of the screen the
    two gates are mutually exclusive - a coin cannot have a monthly Sharpe both
    above +1.3 and below -1.7 - so the order is cosmetic rather than a tie-break.
    """
    lo = df["long_entry" if on_cross else "long_ok"].to_numpy()
    sh = df["short_entry" if on_cross else "short_ok"].to_numpy()
    frac = df["stop_frac"].to_numpy()

    def fn(_d: pd.DataFrame, i: int) -> Signal | None:
        f = frac[i]
        if not np.isfinite(f) or f <= 0:    # no measurable risk unit yet
            return None
        if lo[i]:
            return Signal(direction=1, stop_frac=float(f))
        if sh[i]:
            return Signal(direction=-1, stop_frac=float(f))
        return None

    return fn
def native_exit(df: pd.DataFrame):
    """The source's own exit: a trailing stop that only ever tightens.

    The ratchet is held in closure state rather than recomputed from the trade's
    history on every bar, which keeps it O(1) per bar. State is reset whenever a
    different trade object arrives, and starts at the trade's initial stop.

    The monthly rebalance is the second way out. The paper rebuilds the
    portfolio every month, so a coin that no longer passes its own screen is no
    longer held. That is logged as a separate exit reason, which makes the exit
    mix show how much of the result each of the two mechanisms produced.
    """
    tl = df["trail_long"].to_numpy()
    ts = df["trail_short"].to_numpy()
    ms = df["month_start"].to_numpy()
    lo = df["long_ok"].to_numpy()
    sh = df["short_ok"].to_numpy()
    state: dict = {"trade": None, "level": None}

    def fn(_d: pd.DataFrame, i: int, trade) -> ExitPlan:
        if state["trade"] is not trade:
            state["trade"] = trade
            state["level"] = float(trade.initial_stop)

        level = float(state["level"])
        cand = tl[i] if trade.direction > 0 else ts[i]
        if np.isfinite(cand):
            level = max(level, float(cand)) if trade.direction > 0 \
                else min(level, float(cand))
        state["level"] = level

        plan = ExitPlan(stop_level=level)
        if ms[i]:
            still_eligible = lo[i] if trade.direction > 0 else sh[i]
            if not still_eligible:
                plan.close_exit = True
                plan.reason = "rebalance"
        return plan

    return fn


def warmup_for(interval: str, mom_days: int = MOM_LOOKBACK_DAYS) -> int:
    """Bars to skip before trading, computed per timeframe from calendar days.

    The screen needs a full preceding month plus a one-bar lag, the momentum
    needs L days, and the floor of 120 bars is there so the reporting-only
    regime label (a 100-bar average) is populated rather than reading "unknown".
    """
    bpd = BPD[interval]
    days = max(mom_days, SR_WINDOW_DAYS + 1) + 5
    return max(days * bpd, ATR_BARS + 5, 120)
