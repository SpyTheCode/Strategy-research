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
    """A strategy's instruction, formed on a closed bar, filled at the next open."""

    direction: int      # +1 long, -1 short
    stop_price: float   # the price that defines "1 risk unit" (1R)


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
            stop = float(pending_entry.stop_price)
            entry_px = float(row["open"])
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
