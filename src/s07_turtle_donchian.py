"""Strategy #7 - Turtle / Donchian 20-day breakout, System 1.

WHAT THE SOURCE SAYS
--------------------
  * Trigger:      buy a new 20-day high; sell short a new 20-day low.
  * Stop-loss:    ATR-based, with position size scaled to volatility so that
                  every market risks the same amount of money.
  * Take-profit:  exit on a 10-day low (for longs). A trailing channel exit,
                  no fixed target.
  * Condition:    strong trends. Loses steadily in ranges.
  * Numbers:      43 futures markets INCLUDING Bitcoin and Ethereum, 2007-2025,
                  no curve-fitting.
  * Source:       "I Backtested the Legendary Turtle System", RogueQuant.
                  Sourcing: MEDIUM - the rules are verifiable, the results are not.

WHAT THE SOURCE DOES NOT DISCLOSE
---------------------------------
Every per-trade number. There is no win rate, no reward-to-risk, no Sharpe, no
drawdown and no trade count anywhere in it. The single figure published is
"$1,147,318 total profit across all 43 markets", which the author himself calls
"completely misleading" - a dollar total says nothing without the capital, the
sizing or the span behind it, and the per-trade metrics are paywalled.

So unlike Strategy #6 there is NO claimed win-rate band to test against. Nothing
here can be matched against the source on outcome, only on shape. Two further
gaps sit on top of that: the tested market is FUTURES over 2007-2025, not crypto
perpetuals over 2020-2026, and no bar size is named at all - though the original
system is a daily system, which is why 1D is the headline timeframe here.

THE ORIGINAL SYSTEM, AND WHERE THIS PORT DEPARTS FROM IT
--------------------------------------------------------
The published Turtle rules fill the gaps the article leaves. System 1: enter on a
20-day channel breakout, stop 2N away where N is the 20-day average true range,
exit on the 10-day channel in the opposite direction, risk about 1% of the account
per unit with the unit size divided by N, and pyramid up to four units at half-N
intervals. System 2 is the same shape at 55 days in and 20 days out.

Five departures, all declared before any number was produced:

  1. NO PYRAMIDING. The engine holds one position at a time, so this is a
     single-unit version of the system. That is a real difference, not a
     detail: pyramiding is what turns a Turtle winner into a large winner, and
     it also multiplies the loss when a breakout fails after the adds. Every
     number below is therefore a single unit, and the system's own documented
     return profile is NOT reproducible from it.
  2. SIZING. The Turtles sized each unit as 1% of equity divided by N. This
     project risks a fixed 1% of equity per trade with the stop 2N away, which
     is the same arithmetic reaching the same place - the money at risk does not
     depend on how volatile the market is - so the volatility-scaling intent
     survives even though the unit machinery does not.
  3. "20 DAYS" IS READ AS TWENTY DAYS, not as twenty bars. The rule is written in
     calendar days, so it is converted per timeframe: 20 days is 480 bars at 1H,
     120 at 4H, 80 at 6H and 20 at 1D. The same precedent was set on Strategies
     #2, #3 and #4. The other reading - twenty BARS on every timeframe, which is
     what a chart package does when you drop a Donchian-20 on an hourly chart -
     is run as a labelled sensitivity, because it is a genuinely different rule
     and no source picks between them.
  4. N IS A DAY-SCALE RANGE ON EVERY TIMEFRAME. N is the average true range of
     the last twenty DAYS, a daily quantity. Measuring it as an average HOURLY
     range on the 1H chart would put the stop about two hourly candles from the
     fill, which is not the rule and would be dead on arrival. So the true range
     is measured over a rolling day-length window of bars and then averaged over
     twenty days of them. On 1D that expression reduces exactly to the plain
     20-bar ATR - the original's own N - which is the test that it is the same
     quantity and not a new one.
  5. EXECUTION IS A CLOSED-BAR DECISION FILLED AT THE NEXT OPEN. The Turtles
     rested buy stops just above the channel and were filled inside the breakout
     bar. This project's default is to decide on a bar that has closed and fill
     at the next bar's open, which is strictly worse: it pays away the rest of
     the breakout bar and any gap after it. That default is the headline so this
     strategy stays comparable with the six already logged, and the original's
     own resting-stop execution is run beside it as a sensitivity, on identical
     trigger prices, so the cost of the difference is measured rather than argued.

THE CHANNEL EXIT DOES NOT RATCHET, AND THAT IS THE SOURCE'S RULE
---------------------------------------------------------------
"Exit on a 10-day low" is re-evaluated from scratch on every bar, so as price
falls the 10-day low can fall with it and the exit level LOOSENS. Strategy #3's
source specified a one-way trailing stop and got one; Strategies #5 and #6 did
not, and none was added, because a ratchet is a rule the source does not contain.
The same restraint applies here - but with one important consequence that is
specific to this rule: the 2N stop is a FIXED floor, and the level actually
enforced for a long is whichever of the two is HIGHER. So the 2N stop binds early
in the trade, the rising 10-day low takes over once it has climbed above it, and
the loss stays bounded near 1R throughout. That bound is a property of the
source's own pairing of a fixed stop with a channel exit, not something added
here. A ratcheting variant and a no-2N variant are both run so the claim is
visible rather than asserted.

BOTH SIDES ARE TRADED
---------------------
One retelling of this system calls it long-only and then, in the same breath,
lists selling below the 20-day low. The original traded both sides, and the
recovered source describes both, so both are traded here and the long-only
reading is run as a sensitivity.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan, Signal, Trade

# --- The original System 1, in its own units --------------------------------
ENTRY_DAYS = 20     # "a new 20-day high"
EXIT_DAYS = 10      # "exit on a 10-day low"
N_DAYS = 20         # N is the average true range of the last twenty days
STOP_N = 2.0        # "2N" - the published stop distance

# System 2, the original's slower pair. Run as a sensitivity, not as the result.
S2_ENTRY_DAYS = 55
S2_EXIT_DAYS = 20

# The two readings of "20 days" on an intraday chart. Only DAY is traded.
SCALE_DAY = "day"   # twenty calendar days, converted to bars per timeframe
SCALE_BAR = "bar"   # twenty bars, whatever a bar happens to be

BPD = {"1H": 24, "4H": 6, "6H": 4, "1D": 1}


def bars_per_day(df: pd.DataFrame) -> int:
    """Read the timeframe off the timestamps rather than being told it.

    Inferred so add_indicators keeps a one-argument signature and the lookahead
    audit can call it on a truncated frame unchanged. The median spacing is
    unaffected by chopping bars off the end, which is what that audit does.
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


def _day_scale_n(df: pd.DataFrame, n_days: int, bpd: int) -> pd.Series:
    """N: the average true range of the last `n_days` DAYS, on any bar size.

    The true range of "the last day" as seen from bar i is the range of the last
    `bpd` bars measured against the close a day earlier, so the three terms are
    the day-window high minus the day-window low and each of those against the
    close `bpd` bars back. Averaging that over `n_days * bpd` bars gives a
    twenty-day average of overlapping daily ranges - smoother than twenty
    discrete daily bars would be, and the same quantity in expectation.

    At 1D, bpd is 1: the day window is the bar itself, the reference close is the
    previous bar's, and this collapses to the standard true range averaged over
    twenty bars - which is exactly the original's N. That collapse is the reason
    to trust the expression on the other three timeframes.

    Every term reads bars at or before i. Nothing is shifted forward here because
    N is used to SIZE a decision made at the close of bar i, not to place a level
    inside bar i; the levels that are tested inside a bar are shifted below.
    """
    hi = df["high"].rolling(bpd).max()
    lo = df["low"].rolling(bpd).min()
    prev = df["close"].shift(bpd)
    tr = pd.concat([hi - lo, (hi - prev).abs(), (lo - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n_days * bpd).mean()


def add_indicators(
    df: pd.DataFrame,
    entry_days: int = ENTRY_DAYS,
    exit_days: int = EXIT_DAYS,
    n_days: int = N_DAYS,
    stop_n: float = STOP_N,
    scale: str = SCALE_DAY,
    long_only: bool = False,
    resting: bool = False,
) -> pd.DataFrame:
    """Build the two channels and the 2N risk unit. Four places needed care.

      * THE ENTRY CHANNEL EXCLUDES THE BAR IT JUDGES. `rolling(e).max().shift(1)`
        is the highest high of the e bars BEFORE bar i, so "a new 20-day high" is
        this bar's close against a level that was already on the chart when the
        bar opened. Without the shift the channel would contain the bar's own
        high, and `close > channel` could never be true at all - the bug would be
        silent and would simply produce no trades.
      * THE EXIT CHANNEL IS SHIFTED FOR THE SAME REASON, and it matters more,
        because that level is tested against the high and low of the bar it sits
        on. A stop must be knowable before the range it is compared with.
      * N IS NOT SHIFTED, and that is deliberate. It sizes a decision taken at
        the close of bar i, using bars up to and including bar i - all closed.
        The end-truncation audit cannot catch a same-bar read like this one, so
        it is argued here rather than left to the audit.
      * THE ENTRY IS THE FIRST BAR OF THE BREAKOUT, written
        `state & ~state.shift(1, fill_value=False)`. The other spelling,
        `.shift(1).fillna(False)`, leaves an object-dtype column on which `~` is
        Python's integer bitwise NOT - both -1 and -2 are truthy - so the edge
        collapses back into the state and the rule silently becomes "trade every
        bar of the breakout". That cost Strategy #5 a full run.
    """
    out = df.copy()
    bpd = bars_per_day(out) if scale == SCALE_DAY else 1
    e, x = entry_days * bpd, exit_days * bpd

    n = (_day_scale_n(out, n_days, bpd) if scale == SCALE_DAY
         else _true_range(out).rolling(n_days).mean())
    out["turt_n"] = n
    out["turt_risk"] = stop_n * n

    # The two channels, each excluding the bar it is compared against.
    out["turt_don_hi"] = out["high"].rolling(e).max().shift(1)
    out["turt_don_lo"] = out["low"].rolling(e).min().shift(1)
    out["turt_exit_lo"] = out["low"].rolling(x).min().shift(1)
    out["turt_exit_hi"] = out["high"].rolling(x).max().shift(1)

    # 1R as a fraction of the signal bar's close, so the engine can resolve the
    # 2N distance against the price it actually FILLS at rather than against the
    # close it was measured on. The Turtles measured 2N from the fill.
    close = out["close"]
    frac = out["turt_risk"] / close
    out["turt_stop_frac"] = frac.where((close > 0) & np.isfinite(frac))

    # State, then edge. The state is "this closed bar made a new 20-day extreme".
    long_state = (close > out["turt_don_hi"]).fillna(False).astype(bool)
    short_state = (close < out["turt_don_lo"]).fillna(False).astype(bool)
    if long_only:
        short_state = short_state & False
    out["turt_long_state"] = long_state
    out["turt_short_state"] = short_state
    out["turt_long_entry"] = long_state & ~long_state.shift(1, fill_value=False)
    out["turt_short_entry"] = short_state & ~short_state.shift(1, fill_value=False)

    if resting:
        # The original's own execution: two stop orders resting at the channel,
        # replaced every bar, filled inside whichever bar penetrates one. The
        # engine's resting path is written around sessions, so every bar is
        # declared its own session - which is what a continuously resting order
        # is. Both trigger prices and the risk unit are shifted one bar, because
        # here they are levels tested INSIDE bar i rather than inputs to a
        # decision taken at its close.
        out["buy_trig"] = out["turt_don_hi"]
        out["sell_trig"] = out["turt_don_lo"]
        out["risk_unit"] = out["turt_risk"].shift(1)
        out["armed"] = (out["buy_trig"].notna() & out["sell_trig"].notna()
                        & (out["risk_unit"] > 0)).fillna(False).astype(bool)
        out["session_first"] = True
        out["session_last"] = True
    return out


def entry(df: pd.DataFrame):
    """Fires on the closed breakout bar; the engine fills it at the next open.

    A signal is dropped when 1R is not yet measurable - N is still warming up, or
    the frame has a non-positive close. Dropping is not silent: the run script
    counts fired-versus-usable signals across all twelve datasets.
    """
    lo = df["turt_long_entry"].to_numpy()
    sh = df["turt_short_entry"].to_numpy()
    frac = df["turt_stop_frac"].to_numpy(dtype=float)

    def fn(_d: pd.DataFrame, i: int) -> Signal | None:
        f = frac[i]
        if not np.isfinite(f) or f <= 0:
            return None
        if lo[i]:
            return Signal(direction=1, stop_frac=float(f))
        if sh[i]:
            return Signal(direction=-1, stop_frac=float(f))
        return None

    return fn


def resting_entry_stub(df: pd.DataFrame):
    """The resting path never consults entry(); this exists so the spec is valid."""
    def fn(_d: pd.DataFrame, _i: int) -> Signal | None:
        return None
    return fn


def native_exit(df: pd.DataFrame, use_2n: bool = True, use_channel: bool = True,
                ratchet: bool = False, target_r: float | None = None):
    """The source's own exit: the 2N stop and the 10-day channel, whichever comes first.

    For a long both levels sit below price, so the one price reaches first on the
    way down is the HIGHER of the two - which is why the enforced level is a max
    for longs and a min for shorts. Early in a trade the 2N stop is the higher of
    the two and binds; once the 10-day low has climbed above it, the channel takes
    over and the stop trails. Nothing was added to make that happen; it falls out
    of pairing a fixed stop with a channel exit, which is what the source pairs.

    `use_2n` / `use_channel` split the rule in half so the run can show which
    half earns. With `use_channel` alone, 1R is still 2N - the risk the system
    intended - but no 2N level is enforced, so a loss can run past it and the
    tail is measured. `ratchet` is the variant the source does NOT describe: the
    level is held at its best value instead of being re-read each bar.
    """
    ex_lo = df["turt_exit_lo"].to_numpy(dtype=float)
    ex_hi = df["turt_exit_hi"].to_numpy(dtype=float)
    state: dict = {"trade": None, "level": None}

    def fn(_d: pd.DataFrame, i: int, trade: Trade) -> ExitPlan:
        d = trade.direction
        level = None
        if use_channel:
            cand = ex_lo[i] if d > 0 else ex_hi[i]
            if np.isfinite(cand):
                level = float(cand)
        if use_2n:
            base = float(trade.initial_stop)
            if level is None:
                level = base
            else:
                level = max(level, base) if d > 0 else min(level, base)
        if ratchet and level is not None:
            if state["trade"] is not trade:
                state["trade"], state["level"] = trade, level
            state["level"] = (max(state["level"], level) if d > 0
                              else min(state["level"], level))
            level = state["level"]
        target = (None if target_r is None
                  else trade.entry_price + d * target_r * trade.risk_per_unit)
        return ExitPlan(stop_level=level, target_level=target)

    return fn


def warmup_for(interval: str, entry_days: int = ENTRY_DAYS, n_days: int = N_DAYS,
               scale: str = SCALE_DAY) -> int:
    """Bars to skip before the rule may act.

    The entry channel needs `entry_days` days of bars plus the one-bar shift; N
    needs a day of bars to form one daily range and then `n_days` days of them to
    average. The 120-bar floor is the project's shared minimum, set by the regime
    label's 100-bar mean, and it is what binds at 6H and 1D.
    """
    if scale == SCALE_BAR:
        return max(entry_days + n_days + 5, 120)
    bpd = BPD[interval]
    return max((max(entry_days, n_days) + 1) * bpd + 5, 120)
