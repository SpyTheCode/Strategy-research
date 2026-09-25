"""One runner, used by every strategy, so no strategy gets special treatment.

What it guarantees:

  * both exit variants run off the SAME entry signals and the SAME 1R distance,
    so any difference between them is attributable to the exit alone
  * coins are pooled inside a timeframe (one rule traded across three coins, the
    way it would actually be traded) but timeframes are never pooled with each
    other, because that would be counting the same signal three times
  * the lookahead audit runs before any result is produced, and a failed audit
    stops the run instead of producing numbers
  * every run reaches both log files through logbook.py, never by hand
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

import bybit_data as bd
import lookahead_check
from discard_bar import breakeven_win_rate, exit_death, verdict
from harness import (
    MAKER_FEE_RATE,
    TAKER_FEE_RATE,
    Trade,
    add_regime_columns,
    forced_13_exit,
    metrics,
    simulate,
    simulate_resting,
)

COINS = ["BTCUSDT", "SOLUSDT", "XRPUSDT"]
INTERVALS = ["1H", "4H", "1D"]
FORCED_TIME_LIMIT = 30  # placeholder, approved as such - never tuned


@dataclass
class StrategySpec:
    name: str
    add_indicators: Callable[[pd.DataFrame], pd.DataFrame]
    entry: Callable[[pd.DataFrame], Callable]
    native_exit: Callable[[pd.DataFrame], Callable]
    warmup: int
    native_time_limit: int | None = None
    entry_fee_rate: float = TAKER_FEE_RATE
    exit_fee_rate: float = TAKER_FEE_RATE
    notes: str = ""

    # --- optional hooks, for strategies a single coin's candles cannot express -
    # raw_extra    extra columns that count as RAW input rather than computed
    #              signal, so the lookahead audit truncates them instead of
    #              stripping them. Without this, a cross-coin column would be
    #              removed before the audit and the audit would silently stop
    #              testing that half of the rule.
    # prepare_extra(df, symbol, interval) -> df
    #              injects those raw columns. Runs BEFORE add_indicators, so
    #              anything derived from them is still audited for lookahead.
    # warmup_fn(interval) -> int
    #              per-timeframe warmup, for rules written in calendar days.
    #              A fixed bar count would either starve the hourly test or
    #              throw away a third of the daily history.
    # resting      the strategy places stop orders at prices known before the bar
    #              rather than deciding on a closed bar, so it needs the resting
    #              -order execution path instead of the next-open one. `entry` is
    #              never consulted for these. Defaults off, so no strategy
    #              already measured can change behaviour.
    # fast_simulate  an alternative execution loop that is proven to return the
    #              SAME trades as `simulate` for this strategy, used only by
    #              Strategy #8, whose full-depth report needs ~150 passes.
    #              s08_selftest pins the two together end to end; leave it None
    #              for every other strategy, which must keep using the shared
    #              engine.
    raw_extra: set[str] = field(default_factory=set)
    prepare_extra: Callable[[pd.DataFrame, str, str], pd.DataFrame] | None = None
    warmup_fn: Callable[[str], int] | None = None
    resting: bool = False
    fast_simulate: Callable | None = None

    def warmup_for(self, interval: str) -> int:
        return self.warmup_fn(interval) if self.warmup_fn else self.warmup


def _prepare(spec: StrategySpec, symbol: str, interval: str) -> pd.DataFrame:
    df = bd.drop_forming_bar(bd.load(symbol, interval), interval)
    df = add_regime_columns(df)          # for reporting only, never for decisions
    if spec.prepare_extra is not None:
        df = spec.prepare_extra(df, symbol, interval)
    return spec.add_indicators(df)


def run(spec: StrategySpec, coins=COINS, intervals=INTERVALS, audit: bool = True) -> dict:
    """Run every coin x timeframe x exit variant. Returns nested results.

    `audit=False` is only for re-running the SAME indicators with a different
    risk setting, where the audit would repeat identical work.
    """
    out: dict = {"per_cell": {}, "pooled": {}, "audit": {}, "trades": {}, "fills": {}}

    for interval in intervals:
        pooled: dict[str, list[Trade]] = {"native": [], "forced-1:3": []}
        warmup = spec.warmup_for(interval)
        for symbol in coins:
            df = _prepare(spec, symbol, interval)

            if audit:
                keep = lookahead_check.RAW | spec.raw_extra
                # Cut points must sit past the warmup. Auditing a bar where
                # every indicator is still NaN compares nothing to nothing and
                # would report a pass without having tested anything.
                ok, cols, problems = lookahead_check.audit(df.drop(columns=[
                    c for c in df.columns if c not in keep
                ]), spec.add_indicators, first_cut=max(300, warmup + 50))
                out["audit"][f"{symbol} {interval}"] = (ok, cols, problems)
                if not ok:
                    raise RuntimeError(
                        f"Lookahead audit FAILED for {spec.name} on {symbol} {interval}: "
                        f"{problems[:3]}"
                    )

            variants = {
                "native": (spec.native_exit(df), spec.native_time_limit),
                "forced-1:3": (forced_13_exit, FORCED_TIME_LIMIT),
            }
            for label, (exit_fn, tl) in variants.items():
                if spec.resting:
                    fills: dict = {}
                    trades = simulate_resting(
                        df, exit_fn,
                        warmup=warmup, time_limit_bars=tl,
                        entry_fee_rate=spec.entry_fee_rate,
                        exit_fee_rate=spec.exit_fee_rate,
                        stats=fills,
                    )
                    out["fills"][(symbol, interval, label)] = fills
                elif spec.fast_simulate is not None:
                    # Only Strategy #8 sets this, and only after s08_selftest has
                    # proven it returns the same trades as `simulate`. Keeping it
                    # off by default means every other strategy still runs the
                    # shared engine, so nothing already measured can move.
                    trades = spec.fast_simulate(
                        df, spec.entry(df), exit_fn,
                        warmup=warmup, time_limit_bars=tl,
                        entry_fee_rate=spec.entry_fee_rate,
                        exit_fee_rate=spec.exit_fee_rate,
                    )
                else:
                    trades = simulate(
                        df, spec.entry(df), exit_fn,
                        warmup=warmup, time_limit_bars=tl,
                        entry_fee_rate=spec.entry_fee_rate,
                        exit_fee_rate=spec.exit_fee_rate,
                    )
                out["per_cell"][(symbol, interval, label)] = metrics(trades, interval=interval)
                out["trades"][(symbol, interval, label)] = trades
                pooled[label].extend(trades)

        for label, trades in pooled.items():
            out["pooled"][(interval, label)] = metrics(trades, interval=interval)
            out["trades"][(interval, label)] = trades

    return out


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------

HEAD = (f"{'timeframe':<10} {'exit':<11} {'trades':>7} {'win%':>6} {'RR':>6} "
        f"{'R pre':>8} {'R post':>8} {'R/trade':>8} {'Sharpe':>7} {'DD%':>7} "
        f"{'DD R':>7} {'recov':>6}  verdict")


def _line(label_a: str, label_b: str, m: dict, v: str) -> str:
    def f(x, nd=2):
        return "n/a" if x is None or x != x else f"{x:.{nd}f}"
    wr = m["win_rate"] * 100 if m["win_rate"] == m["win_rate"] else float("nan")
    return (f"{label_a:<10} {label_b:<11} {m['trades']:>7} {f(wr,1):>6} "
            f"{f(m['rr_achieved']):>6} {f(m['r_sum_pre_fee'],1):>8} "
            f"{f(m['r_sum_post_fee'],1):>8} {f(m['expectancy_post_fee_r'],3):>8} "
            f"{f(m['sharpe_post_fee']):>7} {f(m['max_drawdown_pct'],1):>7} "
            f"{f(m['max_drawdown_r'],1):>7} {f(m['r_recovery']):>6}  {v}")


def summarise(spec: StrategySpec, res: dict, intervals=INTERVALS) -> dict:
    """Print the pooled table and return {interval: {...verdicts, exit-death...}}."""
    print(f"\n{spec.name} - three coins pooled per timeframe, post-fee")
    print(HEAD)
    print("-" * len(HEAD))
    summary: dict = {}
    for interval in intervals:
        n = res["pooled"][(interval, "native")]
        f13 = res["pooled"][(interval, "forced-1:3")]
        vn, rn = verdict(n, "native")
        vf, rf = verdict(f13, "forced-1:3")
        flag, diag = exit_death(n, f13)
        print(_line(interval, "native", n, vn))
        print(_line(interval, "forced-1:3", f13, vf))
        summary[interval] = {
            "native": n, "forced-1:3": f13,
            "verdict_native": vn, "reason_native": rn,
            "verdict_forced": vf, "reason_forced": rf,
            "exit_death": flag, "exit_death_diag": diag,
            "breakeven_wr_forced": breakeven_win_rate(f13.get("avg_fee_cost_r", float("nan"))),
        }
    return summary


def per_coin_table(res: dict, coins=COINS, intervals=INTERVALS) -> str:
    lines = [f"{'coin':<9} " + HEAD]
    lines.append("-" * len(lines[0]))
    for symbol in coins:
        for interval in intervals:
            for label in ["native", "forced-1:3"]:
                m = res["per_cell"][(symbol, interval, label)]
                v, _ = verdict(m, label)
                lines.append(f"{symbol:<9} " + _line(interval, label, m, v))
    return "\n".join(lines)
