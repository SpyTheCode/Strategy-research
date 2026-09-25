"""Strategy #2 - Dual Momentum on Bybit USDT perpetuals.

WHAT THE SOURCE ACTUALLY SAYS
-----------------------------
Bybit USDT perpetuals, universe of the top 20 coins by market cap.

  1. Rank the universe on its trailing N-day return, DELIBERATELY IGNORING THE
     MOST RECENT BAR, and go long the top-ranked names.
  2. Go short any name with a negative absolute return over an 8-DAY window.
  3. A regime filter sits on top: if BITCOIN closes below its 30-DAY moving
     average, the whole book is flattened - longs and shorts alike.

Exit: no stop, no target. Positions are re-ranked WEEKLY, PINNED TO MONDAY.
Average hold about 13 days. Risk is controlled by inverse-volatility sizing
(smaller size in wilder coins) plus the Bitcoin switch cutting exposure to zero.

Reported: Jan 2022 - May 2026, +117% total, 19.4% CAGR, 10.8% max drawdown,
Sharpe 1.11, Calmar 12.95. The naive version WITHOUT the skip-a-bar rule and
WITHOUT the regime filter made +3% with a 38% drawdown lasting 471 days.

WHAT THE SOURCE DOES NOT DISCLOSE
---------------------------------
The long leg's lookback N. The 8-day short window and the 30-day Bitcoin
average are stated; N is not. It is a placeholder here and is the parameter
swept in the sensitivity check.

WHAT CANNOT BE TESTED HERE, AND WHY
-----------------------------------
Rule 1 is CROSS-SECTIONAL: it ranks twenty coins against each other. This
project has three. Ranking three names is not a small version of ranking
twenty, it is a different rule, so the ranking leg is NOT reproduced. What is
reproduced is the absolute-momentum leg with the same skip and the same
Bitcoin switch: long when this coin's own skip-adjusted trailing return is
positive, short when its 8-day return is negative, flat when Bitcoin is below
its 30-day average. That is half of "dual" momentum and is labelled as such
everywhere it is reported.

Two source caveats that travel with every number below: the coin list is the
2026 top-20 applied backwards (survivorship bias), and the academic paper the
author cites concludes the OPPOSITE on shorts - that momentum profits come
almost entirely from the long leg while the short leg loses money.

HOW 1R IS DEFINED, GIVEN THE SOURCE DISCLOSES NO STOP
-----------------------------------------------------
A stop is needed because R is the denominator of every number this project
reports, and because an unstopped perpetual short is unbounded risk that
nobody would actually trade. The stop used is a multiple of a DAILY-EQUIVALENT
average range, not of the trading bar's range. That choice matters: a 14-bar
ATR on hourly candles is a 14-hour stop on a 13-day trade, which would stop
out almost immediately and would measure the stop rather than the strategy. A
daily-equivalent stop makes 1R the same amount of real risk on all three
timeframes, so the three are comparable to each other.

It also happens to be a faithful reading of the source's own risk control:
risking a fixed 1% of equity against a volatility-scaled stop IS inverse-
volatility sizing - a wilder coin automatically gets a smaller position.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import bybit_data as bd
from harness import ExitPlan, Signal

# --- stated by the source ---------------------------------------------------
SHORT_LOOKBACK_DAYS = 8    # "negative absolute return over an 8-day window"
BTC_MA_DAYS = 30           # "if Bitcoin closes below its 30-day moving average"
SKIP_DAYS = 1              # "deliberately ignoring the most recent bar"
REBALANCE_DOW = 0          # "re-ranked weekly, pinned to Monday" - 0 = Monday

# --- PLACEHOLDERS - not in the source --------------------------------------
MOM_LOOKBACK_DAYS = 30     # the long leg's trailing N-day return; N undisclosed
ATR_STOP_MULT = 2.0        # the source discloses no stop at all
ATR_DAYS = 14              # horizon of the daily-equivalent range average

BTC_SYMBOL = "BTCUSDT"
RAW_EXTRA = {"btc_close"}  # counts as raw input for the lookahead audit


def bars_per_day(df: pd.DataFrame) -> int:
    """Read the timeframe off the timestamps rather than being told it.

    Inferred so that add_indicators keeps a one-argument signature and the
    lookahead audit can call it on a truncated frame unchanged.
    """
    secs = float(df["open_time"].diff().dropna().median().total_seconds())
    return max(int(round(86400.0 / secs)), 1)


def inject_btc(df: pd.DataFrame, symbol: str, interval: str) -> pd.DataFrame:
    """Add Bitcoin's closes to this coin's frame as a RAW column.

    The Bitcoin switch is half the rule, so it has to be auditable for
    lookahead like everything else. Loading Bitcoin's full history inside
    add_indicators would defeat that: the audit truncates the frame it is
    given, and a full-history load would ignore the truncation and quietly
    stop testing the switch. Injecting it as raw data means the audit cuts it
    off at the same bar as everything else.

    Alignment is a backward fill onto this coin's timestamps, so a bar only
    ever sees the most recent Bitcoin bar that had already closed.
    """
    out = df.copy()
    if symbol == BTC_SYMBOL:
        out["btc_close"] = out["close"].to_numpy()
        return out
    btc = bd.drop_forming_bar(bd.load(BTC_SYMBOL, interval), interval)
    series = pd.Series(btc["close"].to_numpy(), index=pd.DatetimeIndex(btc["open_time"]))
    out["btc_close"] = series.reindex(
        pd.DatetimeIndex(out["open_time"]), method="ffill"
    ).to_numpy()
    return out


def add_indicators(
    df: pd.DataFrame,
    mom_days: int = MOM_LOOKBACK_DAYS,
    stop_mult: float = ATR_STOP_MULT,
) -> pd.DataFrame:
    """Every column is built from bars that have already closed.

    `.shift(k)` moves data FORWARD in time, so a shifted value at a bar came
    from k bars earlier. `.rolling(w)` looks only backwards. The momentum
    windows are shifted twice on purpose: once to skip the most recent bar as
    the source requires, then again to reach back to the start of the window.
    """
    out = df.copy()
    bpd = bars_per_day(out)
    close = out["close"]

    # Momentum, measured from the bar BEFORE this one (the source's skip).
    ref = close.shift(SKIP_DAYS * bpd)
    out["mom_long"] = ref / ref.shift(mom_days * bpd) - 1.0
    out["mom_short"] = ref / ref.shift(SHORT_LOOKBACK_DAYS * bpd) - 1.0

    # The Bitcoin switch. NaN during warmup compares False, i.e. stay flat.
    win = BTC_MA_DAYS * bpd
    out["btc_ma"] = out["btc_close"].rolling(win, min_periods=win).mean()
    out["btc_on"] = out["btc_close"] > out["btc_ma"]

    # Daily-equivalent average range, so 1R means the same real risk on 1H,
    # 4H and 1D. On 1D this is just a 14-day average of the daily range.
    span = out["high"].rolling(bpd, min_periods=bpd).max() - \
        out["low"].rolling(bpd, min_periods=bpd).min()
    out["atr_day"] = span.rolling(ATR_DAYS * bpd, min_periods=ATR_DAYS * bpd).mean()
    out["stop_frac"] = stop_mult * out["atr_day"] / close

    stamps = pd.DatetimeIndex(out["open_time"])
    out["rebalance"] = (stamps.dayofweek == REBALANCE_DOW) & (stamps.hour == 0)
    return out


def entry(df: pd.DataFrame):
    """Decide only on a Monday bar, and only while Bitcoin's switch is on.

    Where the source would rank twenty coins and take the best, three coins
    cannot be ranked, so the long leg is the absolute-momentum test the source
    applies on top of its ranking: is this coin's own skip-adjusted trailing
    return positive. The long leg is checked first because it is the source's
    primary leg; the 8-day short leg only gets a look if the long test failed.
    """
    reb = df["rebalance"].to_numpy()
    on = df["btc_on"].to_numpy()
    mom_l = df["mom_long"].to_numpy()
    mom_s = df["mom_short"].to_numpy()
    frac = df["stop_frac"].to_numpy()

    def fn(_d: pd.DataFrame, i: int) -> Signal | None:
        if not reb[i] or not on[i]:        # NaN/False -> no trade
            return None
        f = frac[i]
        if not np.isfinite(f) or f <= 0:   # no measurable risk unit yet
            return None
        if mom_l[i] > 0:
            return Signal(direction=1, stop_frac=float(f))
        if mom_s[i] < 0:
            return Signal(direction=-1, stop_frac=float(f))
        return None

    return fn


def native_exit(df: pd.DataFrame):
    """The source's own exit: re-rank weekly, plus the Bitcoin switch.

    Nothing is re-examined between Mondays - that is the source's cadence, not
    a simplification. The volatility stop is a backstop the source does not
    have; the exit mix in the write-up shows how often it, rather than the
    weekly re-rank, was what actually ended the trade.
    """
    reb = df["rebalance"].to_numpy()
    on = df["btc_on"].to_numpy()
    mom_l = df["mom_long"].to_numpy()
    mom_s = df["mom_short"].to_numpy()

    def fn(_d: pd.DataFrame, i: int, trade) -> ExitPlan:
        plan = ExitPlan(stop_level=trade.initial_stop)
        if not reb[i]:
            return plan
        if not on[i]:
            plan.close_exit = True
            plan.reason = "btc_switch_off"
            return plan
        holds = (mom_l[i] > 0) if trade.direction > 0 else (mom_s[i] < 0)
        if not holds:
            plan.close_exit = True
            plan.reason = "rerank"
        return plan

    return fn


def warmup_for(interval: str, mom_days: int = MOM_LOOKBACK_DAYS) -> int:
    """Bars to skip before trading, computed per timeframe from calendar days.

    The rule is written in days, so a single fixed bar count would either
    starve the hourly test of history or throw away a third of the daily one.
    The floor of 120 bars is there so the reporting-only regime label (a
    100-bar average) is populated rather than reading "unknown".
    """
    bpd = {"1H": 24, "4H": 6, "1D": 1}[interval]
    days = max(mom_days + SKIP_DAYS, BTC_MA_DAYS, ATR_DAYS + SKIP_DAYS) + 3
    return max(days * bpd, 120)


