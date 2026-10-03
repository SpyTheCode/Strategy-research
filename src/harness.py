"""Backtest engine.

Why a purpose-built engine instead of an off-the-shelf library:

  * The whole project hinges on comparing a strategy's own exit against a
    forced 1-risk-unit stop / 3-risk-unit target. Off-the-shelf libraries each
    make their own silent assumption about what happens when a single candle
    touches both the stop and the target, and that one assumption can flip a
    1:3 test from profitable to unprofitable. Here the assumption is written
    down, always pessimistic, and testable.
  * Every trade must report a fee-inclusive R-multiple. That is a first-class
    output here rather than something reverse-engineered from an equity curve.
  * Several strategies on the list are cross-sectional (rank many coins, hold
    the best) which single-asset libraries do not express.

Two rules protect against lookahead bias and are enforced here, not left to
each strategy to remember:

  1. A decision made from bar t's closed data is executed at bar t+1's OPEN.
     A strategy never trades at a price it needed the future to know.
  2. When one candle's range contains both the stop and the target, the STOP is
     assumed to have been hit first. Plain candle data cannot tell us the order,
     and assuming the target came first would flatter every result.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TAKER_FEE_RATE = 0.00055  # 0.055% - given by the project owner, not researched
MAKER_FEE_RATE = 0.0002   # 0.02%
RISK_FRACTION = 0.01      # each trade risks 1% of starting equity, never compounded


@dataclass(frozen=True)
class Signal:
    """A strategy's instruction, formed on a closed bar, filled at the next open.

    The 1R distance can be given two ways, and exactly one must be supplied:

      stop_price  an absolute price level (a swing high, a band, an ATR offset)
      stop_frac   a fraction of the entry price, for sources that specify a
                  "fixed percentage from entry". The entry price is not knowable
                  when the signal is formed - it is the next bar's open - so the
                  engine resolves this at fill time rather than letting a
                  strategy approximate it with the signal bar's close.
    """

    direction: int                      # +1 long, -1 short
    stop_price: float | None = None
    stop_frac: float | None = None

    def resolve_stop(self, entry_price: float) -> float:
        if (self.stop_price is None) == (self.stop_frac is None):
            raise ValueError("Signal needs exactly one of stop_price or stop_frac")
        if self.stop_price is not None:
            return float(self.stop_price)
        return float(entry_price * (1.0 - self.direction * self.stop_frac))


@dataclass
class ExitPlan:
    """What could end the trade on the bar being examined.

    stop_level / target_level are intrabar: the candle's low or high can reach
    them. close_exit is a decision made on the closed bar and filled next open.
    """

    stop_level: float | None = None
    target_level: float | None = None
    close_exit: bool = False
    reason: str = ""


@dataclass
class Trade:
    direction: int
    entry_time: pd.Timestamp
    entry_price: float
    initial_stop: float
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    bars_held: int = 0
    regime: str = ""
    entry_fee_rate: float = TAKER_FEE_RATE
    exit_fee_rate: float = TAKER_FEE_RATE

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry_price - self.initial_stop)

    @property
    def gross_r(self) -> float:
        if self.exit_price is None or self.risk_per_unit == 0:
            return float("nan")
        return (self.exit_price - self.entry_price) * self.direction / self.risk_per_unit

    @property
    def fee_per_unit(self) -> float:
        if self.exit_price is None:
            return float("nan")
        return self.entry_fee_rate * self.entry_price + self.exit_fee_rate * self.exit_price

    @property
    def net_r(self) -> float:
        """R-multiple after both legs of exchange fees. This drives every verdict."""
        if self.exit_price is None or self.risk_per_unit == 0:
            return float("nan")
        pnl = (self.exit_price - self.entry_price) * self.direction - self.fee_per_unit
        return pnl / self.risk_per_unit

    @property
    def fee_cost_r(self) -> float:
        if self.exit_price is None or self.risk_per_unit == 0:
            return float("nan")
        return self.fee_per_unit / self.risk_per_unit


def add_regime_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Label each bar's market condition using only data already closed.

    Trend  : where price sits relative to a 100-bar average, and whether that
             average is itself rising or falling over the last 20 bars.
    Volatility: whether recent true range is wide or narrow versus its own
             two-year-ish median on this timeframe.
    """
    out = df.copy()
    ma = out["close"].rolling(100, min_periods=100).mean()
    ma_prev = ma.shift(20)

    tr = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - out["close"].shift(1)).abs(),
            (out["low"] - out["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(14, min_periods=14).mean()
    atr_pct = atr / out["close"]
    atr_med = atr_pct.rolling(500, min_periods=100).median()

    trend = np.where(
        (out["close"] > ma) & (ma > ma_prev),
        "up",
        np.where((out["close"] < ma) & (ma < ma_prev), "down", "range"),
    )
    vol = np.where(atr_pct.isna() | atr_med.isna(), "unknown",
                   np.where(atr_pct > atr_med, "highvol", "lowvol"))

    out["atr14"] = atr
    out["regime"] = pd.Series(trend, index=out.index) + "/" + pd.Series(vol, index=out.index)
    return out


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _stop_hit(row: pd.Series, level: float, direction: int) -> bool:
    return row["low"] <= level if direction > 0 else row["high"] >= level


def _target_hit(row: pd.Series, level: float, direction: int) -> bool:
    return row["high"] >= level if direction > 0 else row["low"] <= level


def _stop_fill(row: pd.Series, level: float, direction: int) -> float:
    """Fill at the stop, or at the open if the bar gapped straight through it.

    A candle that opens beyond your stop does not fill you at the stop. Taking
    the worse of the two prices is the honest treatment of gap risk.
    """
    return float(min(level, row["open"])) if direction > 0 else float(max(level, row["open"]))


def simulate(
    df: pd.DataFrame,
    entry_fn,
    exit_fn,
    *,
    warmup: int,
    time_limit_bars: int | None = None,
    entry_fee_rate: float = TAKER_FEE_RATE,
    exit_fee_rate: float = TAKER_FEE_RATE,
) -> list[Trade]:
    """Walk the candles once, forward, never looking at a bar that has not closed.

    entry_fn(df, i) -> Signal | None   decided on closed bar i, filled at open i+1
    exit_fn(df, i, trade) -> ExitPlan  what could end the trade during bar i
    """
    trades: list[Trade] = []
    position: Trade | None = None
    pending_entry: Signal | None = None
    pending_exit_reason: str | None = None
    n = len(df)

    for i in range(warmup, n):
        row = df.iloc[i]

        # 1. A decision made last bar is filled at this bar's open.
        if position is not None and pending_exit_reason is not None:
            position.exit_time = row["open_time"]
            position.exit_price = float(row["open"])
            position.exit_reason = pending_exit_reason
            trades.append(position)
            position = None
            pending_exit_reason = None

        if position is None and pending_entry is not None:
            entry_px = float(row["open"])
            stop = pending_entry.resolve_stop(entry_px)
            if stop != entry_px:  # a zero-risk trade has no definable R
                position = Trade(
                    direction=pending_entry.direction,
                    entry_time=row["open_time"],
                    entry_price=entry_px,
                    initial_stop=stop,
                    regime=str(row.get("regime", "")),
                    entry_fee_rate=entry_fee_rate,
                    exit_fee_rate=exit_fee_rate,
                )
            pending_entry = None

        # 2. While holding, see what this candle does to the trade.
        if position is not None:
            plan = exit_fn(df, i, position)
            d = position.direction
            hit_stop = plan.stop_level is not None and _stop_hit(row, plan.stop_level, d)
            hit_target = plan.target_level is not None and _target_hit(row, plan.target_level, d)

            if hit_stop:  # pessimistic tie-break: the stop always wins
                position.exit_time = row["open_time"]
                position.exit_price = _stop_fill(row, float(plan.stop_level), d)
                position.exit_reason = "stop"
                trades.append(position)
                position = None
            elif hit_target:
                position.exit_time = row["open_time"]
                position.exit_price = float(plan.target_level)
                position.exit_reason = "target"
                trades.append(position)
                position = None
            else:
                position.bars_held += 1
                if time_limit_bars is not None and position.bars_held >= time_limit_bars:
                    pending_exit_reason = "time"
                elif plan.close_exit:
                    pending_exit_reason = plan.reason or "signal"

        # 3. Look for a fresh entry on this closed bar. Allowed while an exit is
        #    queued so reversal systems can flip at the same next open.
        if pending_entry is None and (position is None or pending_exit_reason is not None):
            sig = entry_fn(df, i)
            if sig is not None and i + 1 < n:
                pending_entry = sig

    # An open position at the end of the data is left out entirely rather than
    # marked to the last close, so no unresolved bet is counted as a result.
    return trades


def simulate_resting(
    df: pd.DataFrame,
    exit_fn,
    *,
    warmup: int,
    time_limit_bars: int | None = None,
    entry_fee_rate: float = TAKER_FEE_RATE,
    exit_fee_rate: float = TAKER_FEE_RATE,
    stats: dict | None = None,
) -> list[Trade]:
    """Second execution path: RESTING STOP ORDERS, filled during a bar.

    `simulate` above answers "what does a strategy decide on a closed bar", and
    fills that decision at the next open. Some strategies - Crabel's opening
    range breakout is the first here - do not decide on a closed bar at all.
    They place two stop orders at prices computed before the session starts and
    let the market choose. Routing that through `simulate` would fill at the
    next bar's open instead of at the order's own price, which is not the same
    strategy: on daily bars it would delete the breakout entirely.

    So this is a separate function rather than a flag inside `simulate`, and
    `simulate` is untouched, so nothing already measured can move.

    WHERE THE LINE BETWEEN LOOKAHEAD AND EXECUTION SITS
    --------------------------------------------------
    This function reads bar i's high and low. That is not a lookahead breach,
    and the distinction is worth being precise about:

      * the STRATEGY may not use bar i's high or low to decide whether to place
        an order. It does not: buy_trig and sell_trig are computed from days
        that have already closed plus the session's opening price.
      * the ENGINE must use bar i's high and low to decide whether an order
        already resting at a known price was penetrated. A real exchange does
        exactly that.

    The test is whether the trigger PRICE could have been known before the bar
    began. It could. Everything after that is fill mechanics.

    THREE HOUSE RULES - RULE 1 IS NOT CONSERVATIVE (SEE THE #9 ERRATUM)
    --------------------------------------------------------------------
      1. If one bar's range covers BOTH triggers, no trade is taken and the
         session is closed to further entries. Candle data cannot say which
         side traded first, so the count is returned in `stats` and must be
         reported. The skip is NOT conservative: on symmetric stops,
         first-touch fills inside the signal bar's range give winners and
         losers the same fill, while traded-at-open entries wait for the bar
         to move in their favour first - it is selection by outcome, not a
         guard (run_s09_rerun_v2.py books these sessions instead).
      2. A bar that opens beyond a resting stop fills at the OPEN, not at the
         trigger. Gapping through a stop order costs you the difference.
      3. A trade entered part-way through bar i is still tested against bar i's
         full range by `exit_fn`. Some of that range happened before entry, so
         this overstates stop-outs on the entry bar. `context_checks`
         measures the share of trades that die on their entry bar, which is
         exactly the size of this effect, so it is quantified rather than
         assumed away.

    Required columns: buy_trig, sell_trig, armed, risk_unit, session_first,
    session_last. One trade per session, no re-entry, no reversal.
    """
    for col in ("buy_trig", "sell_trig", "armed", "risk_unit",
                "session_first", "session_last"):
        if col not in df.columns:
            raise KeyError(f"simulate_resting needs a {col!r} column")

    o = df["open"].to_numpy(dtype=float)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    buy = df["buy_trig"].to_numpy(dtype=float)
    sell = df["sell_trig"].to_numpy(dtype=float)
    risk = df["risk_unit"].to_numpy(dtype=float)
    armed = df["armed"].to_numpy(dtype=bool)
    s_first = df["session_first"].to_numpy(dtype=bool)
    s_last = df["session_last"].to_numpy(dtype=bool)
    times = pd.DatetimeIndex(df["open_time"])
    regimes = (df["regime"].to_numpy(dtype=object) if "regime" in df.columns
               else np.array([""] * len(df), dtype=object))

    trades: list[Trade] = []
    position: Trade | None = None
    pending_exit_reason: str | None = None
    n = len(df)

    # Session accounting. None means "no session is being tracked yet", which is
    # the state until the first session boundary at or after warmup.
    state: str | None = None
    counts = {"sessions_armed": 0, "traded": 0, "ambiguous": 0,
              "blocked": 0, "no_touch": 0}

    for i in range(warmup, n):
        row = {"open": o[i], "high": hi[i], "low": lo[i]}

        # 1. An exit decided on the previous bar fills at this bar's open. For
        #    the native rule that open IS the next day's open.
        if position is not None and pending_exit_reason is not None:
            position.exit_time = times[i]
            position.exit_price = float(o[i])
            position.exit_reason = pending_exit_reason
            trades.append(position)
            position = None
            pending_exit_reason = None

        # 2. A new session starts: the two orders are placed, or they are not.
        if s_first[i]:
            if not armed[i]:
                state = None
            elif position is not None:
                # Still holding from a previous session, so this session's
                # orders could not have been ours. Only reachable in the forced
                # variant, whose time limit can outlast a session.
                counts["sessions_armed"] += 1
                counts["blocked"] += 1
                state = "blocked"
            else:
                counts["sessions_armed"] += 1
                state = "open"

        # 3. Are either of the resting orders penetrated on this bar?
        if state == "open" and position is None and armed[i] and risk[i] > 0:
            hit_buy = hi[i] >= buy[i]
            hit_sell = lo[i] <= sell[i]
            if hit_buy and hit_sell:
                counts["ambiguous"] += 1
                state = "ambiguous"
            elif hit_buy or hit_sell:
                d = 1 if hit_buy else -1
                # Gap protection: a stop order is filled at the worse of its own
                # level and the price the bar actually opened at.
                entry_px = (max(buy[i], o[i]) if d > 0 else min(sell[i], o[i]))
                position = Trade(
                    direction=d,
                    entry_time=times[i],
                    entry_price=float(entry_px),
                    initial_stop=float(entry_px - d * risk[i]),
                    regime=str(regimes[i]),
                    entry_fee_rate=entry_fee_rate,
                    exit_fee_rate=exit_fee_rate,
                )
                counts["traded"] += 1
                state = "traded"

        # 4. While holding, see what this candle does to the trade. Identical
        #    treatment to `simulate`: the stop wins every tie.
        if position is not None:
            plan = exit_fn(df, i, position)
            d = position.direction
            hit_stop = plan.stop_level is not None and _stop_hit(row, plan.stop_level, d)
            hit_target = plan.target_level is not None and _target_hit(row, plan.target_level, d)

            if hit_stop:
                position.exit_time = times[i]
                position.exit_price = _stop_fill(row, float(plan.stop_level), d)
                position.exit_reason = "stop"
                trades.append(position)
                position = None
            elif hit_target:
                position.exit_time = times[i]
                position.exit_price = float(plan.target_level)
                position.exit_reason = "target"
                trades.append(position)
                position = None
            else:
                position.bars_held += 1
                if time_limit_bars is not None and position.bars_held >= time_limit_bars:
                    pending_exit_reason = "time"
                elif plan.close_exit:
                    pending_exit_reason = plan.reason or "signal"

        # 5. Close the books on the session.
        if s_last[i]:
            if state == "open":
                counts["no_touch"] += 1
            state = None

    if stats is not None:
        stats.update(counts)
    # As in `simulate`, a position still open when the data ends is discarded
    # rather than marked to the last close.
    return trades


def forced_13_exit(df: pd.DataFrame, i: int, trade: Trade) -> ExitPlan:
    """Triple barrier: stop at 1R, target at 3R, plus the caller's time limit."""
    r = trade.risk_per_unit
    d = trade.direction
    return ExitPlan(
        stop_level=trade.initial_stop,
        target_level=trade.entry_price + d * 3.0 * r,
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

BARS_PER_YEAR = {"1H": 24 * 365, "4H": 6 * 365, "1D": 365}


def _daily_pnl(trades: list[Trade]) -> pd.Series:
    """Realised profit per calendar day, in fractions of starting equity."""
    if not trades:
        return pd.Series(dtype="float64")
    rows = [(t.exit_time, RISK_FRACTION * t.net_r) for t in trades if t.exit_time is not None]
    if not rows:
        return pd.Series(dtype="float64")
    s = pd.Series([v for _, v in rows], index=pd.DatetimeIndex([k for k, _ in rows]))
    s = s.groupby(s.index).sum().sort_index()
    full = pd.date_range(s.index.min().normalize(), s.index.max().normalize(), freq="D", tz="UTC")
    return s.resample("1D").sum().reindex(full, fill_value=0.0)


def metrics(trades: list[Trade], *, interval: str) -> dict:
    """Everything needed for a verdict. Every money figure here is post-fee."""
    closed = [t for t in trades if t.exit_price is not None and np.isfinite(t.net_r)]
    n = len(closed)
    base = {
        "trades": n,
        "win_rate": float("nan"),
        "rr_achieved": float("nan"),
        "r_sum_pre_fee": float("nan"),
        "r_sum_post_fee": float("nan"),
        "expectancy_post_fee_r": float("nan"),
        "sharpe_post_fee": float("nan"),
        "max_drawdown_pct": float("nan"),
        "max_drawdown_r": float("nan"),
        "r_recovery": float("nan"),
        "avg_fee_cost_r": float("nan"),
        "avg_bars_held": float("nan"),
        "exit_reason_mix": {},
        "regime_r": {},
        "best_regime": "n/a",
        "worst_regime": "n/a",
    }
    if n == 0:
        return base

    net = np.array([t.net_r for t in closed])
    gross = np.array([t.gross_r for t in closed])
    wins, losses = net[net > 0], net[net <= 0]

    base["win_rate"] = float(len(wins) / n)
    base["rr_achieved"] = (
        float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) and losses.mean() != 0
        else float("nan")
    )
    base["r_sum_pre_fee"] = float(gross.sum())
    base["r_sum_post_fee"] = float(net.sum())
    base["expectancy_post_fee_r"] = float(net.mean())
    base["avg_fee_cost_r"] = float(np.mean([t.fee_cost_r for t in closed]))
    base["avg_bars_held"] = float(np.mean([t.bars_held for t in closed]))

    reasons: dict[str, int] = {}
    for t in closed:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
    base["exit_reason_mix"] = reasons

    daily = _daily_pnl(closed)
    if len(daily) > 2 and daily.std(ddof=1) > 0:
        base["sharpe_post_fee"] = float(daily.mean() / daily.std(ddof=1) * np.sqrt(365))
    equity = 1.0 + daily.cumsum()
    if len(equity):
        peak = equity.cummax()
        base["max_drawdown_pct"] = float(((peak - equity) / peak).max() * 100.0)
        # Same drawdown measured in risk units, which does not depend on how
        # much money we chose to risk per trade.
        r_curve = daily.cumsum() / RISK_FRACTION
        base["max_drawdown_r"] = float((r_curve.cummax() - r_curve).max())
        if base["max_drawdown_r"] > 0:
            base["r_recovery"] = float(base["r_sum_post_fee"] / base["max_drawdown_r"])
        elif base["r_sum_post_fee"] > 0:
            base["r_recovery"] = float("inf")  # never had a losing stretch

    by_regime: dict[str, dict] = {}
    for t in closed:
        key = t.regime or "unknown"
        b = by_regime.setdefault(key, {"trades": 0, "r_sum_post_fee": 0.0})
        b["trades"] += 1
        b["r_sum_post_fee"] += t.net_r
    base["regime_r"] = {k: {"trades": v["trades"], "r_sum_post_fee": round(v["r_sum_post_fee"], 2)}
                        for k, v in sorted(by_regime.items())}
    scored = {k: v["r_sum_post_fee"] for k, v in by_regime.items() if v["trades"] >= 5}
    if scored:
        base["best_regime"] = max(scored, key=scored.get)
        base["worst_regime"] = min(scored, key=scored.get)
    return base
