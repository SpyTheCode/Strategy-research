"""Dry-run report for Strategy #15 - CCI zero-line trend system."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

import context_checks
import coverage
import runner
import s15_cci_trend as s15
from discard_bar import BAR, breakeven_win_rate, describe, exit_death, verdict
from harness import ExitPlan, Signal, Trade, forced_13_exit, metrics, simulate

NAME = "#15 CCI zero-line trend system"
IVS = ["1H", "4H", "1D"]
EXITS = ("native", "forced-1:3")
HOURS_PER_BAR = {"1H": 1.0, "4H": 4.0, "1D": 24.0}
BASE_FUNDING_RATE = 0.0001
SETTLEMENT_HOURS = 8.0
MIN_OVERLAP = 0.85
FORCED_LIMIT = 30
ROOT = Path(__file__).resolve().parent.parent
TRADE_DIR = ROOT / "trade_lists" / "s15"
REPORT_PATH = Path(r"C:\Users\MarketCoder\Desktop\s15_report_final.txt")


def make_spec(threshold: float = 100.0, stop_atr: float = 2.0) -> runner.StrategySpec:
    return runner.StrategySpec(
        name=f"{NAME} [threshold={threshold:g}, stop={stop_atr:g}xATR]",
        add_indicators=lambda df: s15.add_indicators(
            df, threshold=threshold, stop_atr=stop_atr
        ),
        entry=s15.entry,
        native_exit=s15.native_exit,
        warmup=s15.WARMUP,
        native_time_limit=None,
    )


def _fmt(value: float | int | None, digits: int = 2) -> str:
    if value is None or not np.isfinite(value):
        return "n/a"
    return f"{value:.{digits}f}"


def _risk_exit(label: str, df: pd.DataFrame):
    return s15.native_exit(df) if label == "native" else forced_13_exit


def sensitivity_results(headline: dict) -> list[dict]:
    variants = [
        ("Headline threshold=100, stop=2 ATR", 100.0, 2.0, headline),
        ("Entry threshold=80, stop=2 ATR", 80.0, 2.0, None),
        ("Entry threshold=120, stop=2 ATR", 120.0, 2.0, None),
        ("Stop=1.5 ATR, threshold=100", 100.0, 1.5, None),
        ("Stop=2.5 ATR, threshold=100", 100.0, 2.5, None),
    ]
    rows: list[dict] = []
    for name, threshold, stop_atr, result in variants:
        if result is None:
            result = runner.run(
                make_spec(threshold, stop_atr),
                runner.COINS,
                IVS,
                audit=threshold != 100.0,
            )
        for interval in IVS:
            for label in EXITS:
                m = result["pooled"][(interval, label)]
                v, _ = verdict(m, label)
                rows.append({
                    "variant": name,
                    "timeframe": interval,
                    "exit": label,
                    "trades": m["trades"],
                    "win": m["win_rate"],
                    "r": m["r_sum_post_fee"],
                    "r_trade": m["expectancy_post_fee_r"],
                    "sharpe": m["sharpe_post_fee"],
                    "verdict": v,
                })
    return rows


def write_trade_lists(res: dict) -> list[tuple[Path, int]]:
    TRADE_DIR.mkdir(parents=True, exist_ok=True)
    columns = [
        "coin", "timeframe", "exit_variant", "direction", "entry_time",
        "entry_price", "exit_time", "exit_price", "exit_reason", "bars_held",
        "R pre-fee", "R post-fee",
    ]
    written = []
    for coin in runner.COINS:
        for interval in IVS:
            for label in EXITS:
                trades = sorted(
                    res["trades"][(coin, interval, label)],
                    key=lambda trade: trade.entry_time,
                )
                rows = [{
                    "coin": coin,
                    "timeframe": interval,
                    "exit_variant": label,
                    "direction": "long" if trade.direction > 0 else "short",
                    "entry_time": trade.entry_time.strftime("%Y-%m-%d %H:%M"),
                    "entry_price": trade.entry_price,
                    "exit_time": trade.exit_time.strftime("%Y-%m-%d %H:%M")
                    if trade.exit_time is not None else "",
                    "exit_price": trade.exit_price
                    if trade.exit_price is not None else "",
                    "exit_reason": trade.exit_reason,
                    "bars_held": trade.bars_held,
                    "R pre-fee": trade.gross_r,
                    "R post-fee": trade.net_r,
                } for trade in trades]
                tag = "forced13" if label == "forced-1:3" else "native"
                path = TRADE_DIR / f"s15_{coin}_{interval}_{tag}.csv"
                pd.DataFrame(rows, columns=columns).to_csv(path, index=False)
                written.append((path, len(rows)))
    return written


def _occupancy_status(
    df: pd.DataFrame,
    interval: str,
    label: str,
    entry_fn,
    exit_fn,
    completed_trades: list,
) -> dict:
    """Mirror the shared market engine's entry-eligibility sequence for accounting."""
    closed_keys = {(t.direction, t.entry_time) for t in completed_trades}
    n = len(df)
    times = df["open_time"].reset_index(drop=True)
    pending_entry: Signal | None = None
    pending_signal_key: tuple[int, pd.Timestamp] | None = None
    pending_exit_reason: str | None = None
    position: Trade | None = None
    completed_mirror: set[tuple[int, pd.Timestamp]] = set()
    accepted: set[tuple[int, pd.Timestamp]] = set()
    counts = {
        "generated": 0, "taken": 0, "blocked_open": 0, "last_bar": 0,
        "zero_risk": 0, "open_end": 0, "other": 0, "reconciles": False,
    }
    time_limit = FORCED_LIMIT if label == "forced-1:3" else None

    for i in range(s15.WARMUP, n):
        row = df.iloc[i]
        if position is not None and pending_exit_reason is not None:
            completed_mirror.add((position.direction, position.entry_time))
            position = None
            pending_exit_reason = None
        if position is None and pending_entry is not None:
            entry_price = float(row["open"])
            stop = pending_entry.resolve_stop(entry_price)
            if stop != entry_price:
                position = Trade(
                    direction=pending_entry.direction,
                    entry_time=times.iloc[i],
                    entry_price=entry_price,
                    initial_stop=stop,
                    regime=str(row.get("regime", "")),
                )
                if pending_signal_key is None:
                    raise RuntimeError("Accepted entry has no originating signal key.")
                accepted.add(pending_signal_key)
            else:
                counts["zero_risk"] += 1
            pending_entry = None
            pending_signal_key = None

        if position is not None:
            plan: ExitPlan = exit_fn(df, i, position)
            direction = position.direction
            hit_stop = (
                plan.stop_level is not None
                and (row["low"] <= plan.stop_level if direction > 0
                     else row["high"] >= plan.stop_level)
            )
            hit_target = (
                plan.target_level is not None
                and (row["high"] >= plan.target_level if direction > 0
                     else row["low"] <= plan.target_level)
            )
            if hit_stop or hit_target:
                completed_mirror.add((direction, position.entry_time))
                position = None
            else:
                if time_limit is not None:
                    position.bars_held = getattr(position, "bars_held", 0) + 1
                    if position.bars_held >= time_limit:
                        pending_exit_reason = "time"
                if pending_exit_reason is None and plan.close_exit:
                    pending_exit_reason = plan.reason or "signal"

        sig = entry_fn(df, i)
        if sig is None:
            continue
        counts["generated"] += 1
        if i + 1 >= n:
            counts["last_bar"] += 1
        elif sig.stop_frac is not None and sig.stop_frac <= 0:
            counts["zero_risk"] += 1
        elif pending_entry is None and (
            position is None or pending_exit_reason is not None
        ):
            pending_entry = sig
            pending_signal_key = (sig.direction, times.iloc[i + 1])
        else:
            counts["blocked_open"] += 1

    open_end_keys = (
        {(position.direction, position.entry_time)}
        if position is not None else set()
    )
    counts["taken"] = len(accepted & closed_keys)
    counts["open_end"] = len(accepted & open_end_keys)
    counts["other"] = len(accepted - closed_keys - open_end_keys)
    bucket_total = (
        counts["taken"] + counts["blocked_open"] + counts["last_bar"]
        + counts["zero_risk"] + counts["open_end"] + counts["other"]
    )
    counts["reconciles"] = (
        bucket_total == counts["generated"]
        and closed_keys == completed_mirror
    )
    counts["interval"] = interval
    return counts


def reconcile(spec: runner.StrategySpec, res: dict) -> list[dict]:
    rows = []
    for coin in runner.COINS:
        for interval in IVS:
            df = runner._prepare(spec, coin, interval)
            entry_fn = spec.entry(df)
            for label in EXITS:
                trades = res["trades"][(coin, interval, label)]
                counts = _occupancy_status(
                    df, interval, label, entry_fn, _risk_exit(label, df), trades
                )
                counts.update({"coin": coin, "timeframe": interval, "exit": label})
                rows.append(counts)
    return rows


def final_bar_impact(spec: runner.StrategySpec, res: dict) -> list[str]:
    notes = []
    for coin in runner.COINS:
        for interval in IVS:
            df = runner._prepare(spec, coin, interval)
            times = df["open_time"].reset_index(drop=True)
            entry_fn = spec.entry(df)
            final_time = times.iloc[-1]
            penultimate_signal = entry_fn(df, len(df) - 2) is not None
            final_signal = entry_fn(df, len(df) - 1) is not None
            details = []
            if penultimate_signal:
                details.append("penultimate-bar signal filled at final open")
            final_entries = sum(
                t.entry_time == final_time
                for label in EXITS for t in res["trades"][(coin, interval, label)]
            )
            final_exits = sum(
                t.exit_time == final_time
                for label in EXITS for t in res["trades"][(coin, interval, label)]
            )
            if final_entries:
                details.append(f"{final_entries} trade entries at final open across exits")
            if final_exits:
                details.append(f"{final_exits} trade exits stamped at final bar")
            if final_signal:
                details.append("final-bar close signal has no next bar and is not filled")
            notes.append(
                f"- {coin} {interval}: final bar opens {final_time:%Y-%m-%d %H:%M} UTC; "
                + ("included trades are affected: " + "; ".join(details)
                   if final_entries or final_exits
                   else "no included trade entry/exit uses the final bar")
                + ("; final close signal present." if final_signal and not final_entries
                   else ".")
            )
    return notes


def result_table(res: dict, cov: dict, summary: dict) -> str:
    rows = [
        "| Timeframe | Exit | Trades | Days history per coin (BTC/SOL/XRP) | Win% | RR | "
        "R (pre-fee) | R (post-fee) | R/trade | Sharpe | Max DD % | Max DD (R) | "
        "R-recovery | Fee cost/trade | Verdict |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for interval in IVS:
        days = coverage.days_by_coin(cov, interval, runner.COINS)
        day_str = " / ".join(f"{coin} {days[coin]:.0f}" for coin in runner.COINS)
        for label in EXITS:
            m = res["pooled"][(interval, label)]
            prefix = "verdict_native" if label == "native" else "verdict_forced"
            rows.append(
                f"| {interval} | {label} | {m['trades']} | {day_str} | "
                f"{_fmt(100 * m['win_rate'], 1)} | {_fmt(m['rr_achieved'])} | "
                f"{_fmt(m['r_sum_pre_fee'], 1)} | {_fmt(m['r_sum_post_fee'], 1)} | "
                f"{_fmt(m['expectancy_post_fee_r'], 3)} | "
                f"{_fmt(m['sharpe_post_fee'])} | {_fmt(m['max_drawdown_pct'], 1)} | "
                f"{_fmt(m['max_drawdown_r'], 1)} | {_fmt(m['r_recovery'])} | "
                f"{_fmt(m['avg_fee_cost_r'], 3)} | **{summary[interval][prefix]}** |"
            )
    return "\n".join(rows)


def tstat_and_coin_table(res: dict) -> str:
    lines = [
        "| Timeframe | Exit | Trades | Post-fee R/trade | t-stat | vs ~2.0 noise threshold |",
        "|---|---|---:|---:|---:|---|",
    ]
    for interval in IVS:
        for label in EXITS:
            trades = res["trades"][(interval, label)]
            stat = context_checks.significance(trades)
            t = stat["t_net"]
            reading = (
                "positive beyond noise" if np.isfinite(t) and t >= 2
                else "negative beyond noise" if np.isfinite(t) and t <= -2
                else "inside/indeterminate"
            )
            lines.append(
                f"| {interval} | {label} | {stat['n']} | "
                f"{_fmt(stat['net_mean'], 4)} | {_fmt(t)} | {reading} |"
            )
    lines.extend([
        "",
        "| Coin | Timeframe | Exit | Trades | Win% | R/trade post-fee | "
        "Total R post-fee | Fixed-bar verdict |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ])
    for coin in runner.COINS:
        for interval in IVS:
            for label in EXITS:
                m = res["per_cell"][(coin, interval, label)]
                v, _ = verdict(m, label)
                lines.append(
                    f"| {coin} | {interval} | {label} | {m['trades']} | "
                    f"{_fmt(100 * m['win_rate'], 1)} | "
                    f"{_fmt(m['expectancy_post_fee_r'], 4)} | "
                    f"{_fmt(m['r_sum_post_fee'], 2)} | {v} |"
                )
    lines.append(
        "\nt is the sample mean post-fee R divided by its standard error; "
        "|t| around 2 is only a rough noise check, not proof of a durable edge."
    )
    return "\n".join(lines)


def concentration_table(res: dict) -> str:
    lines = [
        "| Timeframe | Exit | Trades | Best trade R | Best trade share of total | "
        "R without best trade | Best 5 R | Best 5 share of total | "
        "R without best 5 | Profitable without best 5? |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for interval in IVS:
        for label in EXITS:
            values = np.array([
                t.net_r for t in res["trades"][(interval, label)]
                if np.isfinite(t.net_r)
            ])
            if not len(values):
                lines.append(f"| {interval} | {label} | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
                continue
            total = float(values.sum())
            ordered = np.sort(values)[::-1]
            best1, best5 = float(ordered[0]), float(ordered[:5].sum())
            ex1, ex5 = total - best1, total - best5
            share1 = best1 / total * 100 if total > 0 else float("nan")
            share5 = best5 / total * 100 if total > 0 else float("nan")
            without = "yes" if ex5 > 0 else "no"
            lines.append(
                f"| {interval} | {label} | {len(values)} | {best1:+.3f} | "
                f"{_fmt(share1, 1)}% | {ex1:+.3f} | {best5:+.3f} | "
                f"{_fmt(share5, 1)}% | {ex5:+.3f} | {without} |"
            )
    lines.append(
        "\nShares are shown only when total post-fee R is positive; with non-positive "
        "total, the ratio would be misleading. 'Best' ranks individual trades by post-fee R."
    )
    return "\n".join(lines)


def side_table(res: dict) -> str:
    lines = [
        "| Timeframe | Exit | Side | Trades | Win% | R post-fee | R/trade |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for interval in IVS:
        for label in EXITS:
            for name, direction in (("long", 1), ("short", -1)):
                ts = [
                    t for t in res["trades"][(interval, label)]
                    if t.direction == direction
                ]
                if ts:
                    values = np.array([t.net_r for t in ts])
                    lines.append(
                        f"| {interval} | {label} | {name} | {len(ts)} | "
                        f"{(values > 0).mean() * 100:.1f} | {values.sum():+.2f} | "
                        f"{values.mean():+.3f} |"
                    )
                else:
                    lines.append(f"| {interval} | {label} | {name} | 0 | n/a | n/a | n/a |")
    return "\n".join(lines)


def _entry_key(trade) -> tuple[int, pd.Timestamp]:
    return trade.direction, trade.entry_time


def _shared_entry_rerun(res: dict, interval: str) -> tuple[dict, dict]:
    all_trades = {
        (coin, label): res["trades"][(coin, interval, label)]
        for coin in runner.COINS for label in EXITS
    }
    common_by_coin = {}
    for coin in runner.COINS:
        native = {_entry_key(t) for t in all_trades[(coin, "native")]}
        forced = {_entry_key(t) for t in all_trades[(coin, "forced-1:3")]}
        common_by_coin[coin] = native & forced

    results: dict[str, list] = {"native": [], "forced-1:3": []}
    spec = make_spec()
    for coin in runner.COINS:
        df = runner._prepare(spec, coin, interval)
        base_entry = spec.entry(df)
        times = df["open_time"].reset_index(drop=True)
        allowed = common_by_coin[coin]

        def filtered_entry(_df, i, *, _base=base_entry, _times=times, _allow=allowed):
            sig = _base(_df, i)
            if sig is None or i + 1 >= len(_times):
                return None
            return sig if (sig.direction, _times.iloc[i + 1]) in _allow else None

        for label in EXITS:
            exit_fn = (
                s15.native_exit(df) if label == "native" else forced_13_exit
            )
            trades = simulate(
                df,
                filtered_entry,
                exit_fn,
                warmup=spec.warmup_for(interval),
                time_limit_bars=FORCED_LIMIT if label == "forced-1:3" else None,
                entry_fee_rate=runner.TAKER_FEE_RATE,
                exit_fee_rate=runner.TAKER_FEE_RATE,
            )
            results[label].extend(trades)
    return (
        metrics(results["native"], interval=interval),
        metrics(results["forced-1:3"], interval=interval),
    )


def _trade_overlap(res: dict, interval: str) -> float:
    native = {_entry_key(t) for t in res["trades"][(interval, "native")]}
    forced = {_entry_key(t) for t in res["trades"][(interval, "forced-1:3")]}
    union = native | forced
    return len(native & forced) / len(union) if union else float("nan")


def exit_death_block(res: dict) -> str:
    lines = [
        "| Timeframe | Native trades | Forced trades | Entry overlap | Exit-death? | Diagnosis |",
        "|---|---:|---:|---:|---|---|",
    ]
    reruns = []
    for interval in IVS:
        native = res["pooled"][(interval, "native")]
        forced = res["pooled"][(interval, "forced-1:3")]
        overlap = _trade_overlap(res, interval)
        death, diagnosis = exit_death(native, forced)
        lines.append(
            f"| {interval} | {native['trades']} | {forced['trades']} | "
            f"{_fmt(100 * overlap, 1)}% | {death} | {diagnosis} |"
        )
        if np.isfinite(overlap) and overlap < MIN_OVERLAP:
            nat_shared, forced_shared = _shared_entry_rerun(res, interval)
            reruns.append(
                f"- {interval}: overlap below {MIN_OVERLAP:.0%}; shared-entry "
                f"re-run: native {nat_shared['trades']} trades, "
                f"{_fmt(nat_shared['expectancy_post_fee_r'], 4)} R/trade; "
                f"forced {forced_shared['trades']} trades, "
                f"{_fmt(forced_shared['expectancy_post_fee_r'], 4)} R/trade."
            )
    lines.append(
        "\nOverlap uses the common-entry share of the union of completed trade entries. "
        "When it falls below 85%, both exits are re-run using only their shared "
        "coin/time/direction entries."
    )
    if reruns:
        lines.extend(["", *reruns])
    else:
        lines.append("\nNo timeframe fell below the 85% overlap threshold; no shared-entry re-run was needed.")
    return "\n".join(lines)


def reentry_clustering(csv_paths: list[tuple[Path, int]]) -> str:
    lines = [
        "| Coin | Timeframe | Exit | Stop-outs | Next completed entry after stop | "
        "Median gap (bars) | Re-entry within 3 bars |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for path, _ in csv_paths:
        frame = pd.read_csv(path)
        if frame.empty:
            continue
        stops = frame[frame["exit_reason"] == "stop"]
        gaps = []
        for _, stop_trade in stops.iterrows():
            later = frame[
                pd.to_datetime(frame["entry_time"], utc=True)
                > pd.to_datetime(stop_trade["exit_time"], utc=True)
            ]
            if len(later):
                gap = (
                    pd.to_datetime(later["entry_time"].min(), utc=True)
                    - pd.to_datetime(stop_trade["exit_time"], utc=True)
                ) / pd.Timedelta(hours=HOURS_PER_BAR[stop_trade["timeframe"]])
                gaps.append(float(gap))
        lines.append(
            f"| {frame.iloc[0]['coin']} | {frame.iloc[0]['timeframe']} | "
            f"{frame.iloc[0]['exit_variant']} | {len(stops)} | {len(gaps)} | "
            f"{_fmt(float(np.median(gaps)) if gaps else float('nan'), 1)} | "
            f"{(sum(gap <= 3 for gap in gaps) / len(gaps) * 100):.1f}% "
            f"({sum(gap <= 3 for gap in gaps)}/{len(gaps)}) |"
            if gaps else
            f"| {frame.iloc[0]['coin']} | {frame.iloc[0]['timeframe']} | "
            f"{frame.iloc[0]['exit_variant']} | {len(stops)} | 0 | n/a | n/a |"
        )
    return "\n".join(lines)


def reason_means(csv_paths: list[tuple[Path, int]]) -> str:
    combined = pd.concat(
        [pd.read_csv(path) for path, _ in csv_paths],
        ignore_index=True,
    )
    lines = [
        "| Timeframe | Exit | Exit reason | Trades | Mean R post-fee |",
        "|---|---|---|---:|---:|",
    ]
    if combined.empty:
        return "\n".join(lines + ["| n/a | n/a | no completed trades | 0 | n/a |"])
    for interval in IVS:
        for label in EXITS:
            subset = combined[
                (combined["timeframe"] == interval)
                & (combined["exit_variant"] == label)
            ]
            for reason, group in subset.groupby("exit_reason", dropna=False):
                lines.append(
                    f"| {interval} | {label} | {reason} | {len(group)} | "
                    f"{group['R post-fee'].mean():+.4f} |"
                )
    return "\n".join(lines)


def funding_estimates(res: dict, summary: dict) -> str:
    lines = [
        "| Timeframe | Exit | Trades | Avg bars held | Median stop % | "
        "Estimated funding R/trade at 0.01% per 8h |",
        "|---|---|---:|---:|---:|---:|",
    ]
    count = 0
    for interval in IVS:
        for label in EXITS:
            key = "verdict_native" if label == "native" else "verdict_forced"
            if summary[interval][key] != "KEEP":
                continue
            trades = res["trades"][(interval, label)]
            m = res["pooled"][(interval, label)]
            stop_frac = float(np.median([
                abs(t.entry_price - t.initial_stop) / t.entry_price for t in trades
            ]))
            hours = m["avg_bars_held"] * HOURS_PER_BAR[interval]
            settles = hours / SETTLEMENT_HOURS
            estimate = settles * BASE_FUNDING_RATE / stop_frac
            lines.append(
                f"| {interval} | {label} | {m['trades']} | "
                f"{_fmt(m['avg_bars_held'], 1)} | {stop_frac * 100:.3f}% | "
                f"{estimate:.5f} R |"
            )
            count += 1
    if not count:
        lines.append("| none | none | 0 | n/a | n/a | no KEEP cell; no estimate stated |")
    lines.append(
        "\nFunding was not modeled. This rough base-rate estimate is shown only for KEEP "
        "cells and is not a measured funding series."
    )
    return "\n".join(lines)


def sensitivity_table(rows: list[dict]) -> str:
    lines = [
        "| Variant (independent sweep) | Timeframe | Exit | Trades | Win% | "
        "Post-fee total R | R/trade | Sharpe | Verdict |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['variant']} | {row['timeframe']} | {row['exit']} | "
            f"{row['trades']} | {_fmt(100 * row['win'], 1)} | "
            f"{_fmt(row['r'], 2)} | {_fmt(row['r_trade'], 4)} | "
            f"{_fmt(row['sharpe'])} | {row['verdict']} |"
        )
    lines.append(
        "\nOnly the spec's independent entry-threshold and stop-width sweeps are included. "
        "Each variant is diagnostic only; none replaces the predeclared headline."
    )
    return "\n".join(lines)


def regime_findings(res: dict) -> str:
    rows = [
        "| Timeframe | Exit | Reporting regime | Trades | Post-fee R | R/trade |",
        "|---|---|---|---:|---:|---:|",
    ]
    findings = []
    for interval in IVS:
        for label in EXITS:
            buckets = res["pooled"][(interval, label)]["regime_r"]
            scored = []
            for regime, info in sorted(buckets.items()):
                n, total = info["trades"], info["r_sum_post_fee"]
                per = total / n if n else float("nan")
                rows.append(
                    f"| {interval} | {label} | {regime} | {n} | {total:+.2f} | "
                    f"{per:+.3f} |"
                )
                if n:
                    scored.append((regime, per, n))
            if scored:
                high = max(scored, key=lambda item: item[1])
                low = min(scored, key=lambda item: item[1])
                findings.append(
                    f"{interval} {label}: highest observed R/trade was "
                    f"{high[0]} ({high[1]:+.3f}, n={high[2]}); lowest was "
                    f"{low[0]} ({low[1]:+.3f}, n={low[2]})."
                )
    rows.extend([
        "",
        "Plain findings: " + " ".join(findings),
        "The spec makes no performance claim or prediction by market condition; these are "
        "descriptive results, not a comparison to an attributed source claim. Regime labels "
        "are reporting-only and never enter the trading rule.",
    ])
    return "\n".join(rows)


def verdict_details(res: dict, summary: dict) -> str:
    lines = [
        "| Timeframe | Exit | Trades >=30 | Expectancy >0 | Sharpe >=0.70 | "
        "Recovery >=1.5 | Reward test | Discard test | Verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for interval in IVS:
        for label in EXITS:
            m = res["pooled"][(interval, label)]
            n = m["trades"]
            exp = m["expectancy_post_fee_r"]
            sharpe = m["sharpe_post_fee"]
            recovery = m["r_recovery"]
            if label == "forced-1:3":
                need = breakeven_win_rate(m["avg_fee_cost_r"]) + BAR.keep_win_margin
                reward_ok = m["win_rate"] >= need
                reward = f"win {m['win_rate']:.1%} {'PASS' if reward_ok else 'FAIL'}; need {need:.1%}"
            else:
                reward_ok = m["rr_achieved"] >= BAR.keep_rr_native
                reward = f"RR {_fmt(m['rr_achieved'])} {'PASS' if reward_ok else 'FAIL'}; need 1.50"
            discarded = (
                exp <= BAR.discard_expectancy_r
                or sharpe < BAR.discard_sharpe
                or recovery < BAR.discard_r_recovery
            )
            discard_detail = (
                f"DISCARD if exp<=0 ({'yes' if exp <= 0 else 'no'}), "
                f"Sharpe<0.30 ({'yes' if sharpe < 0.30 else 'no'}), "
                f"recovery<0.50 ({'yes' if recovery < 0.50 else 'no'})"
            )
            lines.append(
                f"| {interval} | {label} | {n >= BAR.min_trades} ({n}) | "
                f"{exp > 0} ({_fmt(exp, 4)}) | "
                f"{sharpe >= BAR.keep_sharpe} ({_fmt(sharpe)}) | "
                f"{recovery >= BAR.keep_r_recovery} ({_fmt(recovery)}) | "
                f"{reward} | {discard_detail}; any triggered={discarded} | "
                f"{summary[interval]['verdict_native' if label == 'native' else 'verdict_forced']} |"
            )
    lines.append(
        "\nFor fewer than 30 trades, the fixed-bar verdict is INCONCLUSIVE regardless of "
        "the other columns. KEEP requires all thresholds, including the reward test; "
        "DISCARD is triggered by any listed discard condition."
    )
    return "\n".join(lines)


def _source_comparison(res: dict, summary: dict) -> str:
    positives = []
    for interval in IVS:
        for label in EXITS:
            m = res["pooled"][(interval, label)]
            positives.append(
                f"{interval}/{label}: {m['expectancy_post_fee_r']:+.4f} R/trade "
                f"post-fee ({summary[interval]['verdict_native' if label == 'native' else 'verdict_forced']})."
            )
    return (
        'Spec source sentence, verbatim: "CCI identifies cyclical extremes; it does not '
        'uniquely prescribe a universal crypto stop/exit."\n\n'
        "The spec does not make a performance claim. The tested ±100 threshold-cross entry, "
        "zero-line-cross native exit, 2×ATR stop, and forced 1:3 comparison are the spec's "
        "pinned test interpretation/project convention, not rules attributed to Lambert. "
        "The source description therefore supplies no source performance number to replicate. "
        "Measured results: " + " ".join(positives)
    )


def _report(
    res: dict,
    summary: dict,
    cov: dict,
    audits: dict,
    rec: list[dict],
    final_notes: list[str],
    sensitivities: list[dict],
    csv_paths: list[tuple[Path, int]],
) -> str:
    all_reconciled = all(row["reconciles"] for row in rec)
    audit_passes = sum(1 for ok, _, _ in audits.values() if ok)
    audit_total = len(audits)
    audit_rows = "\n".join(
        f"| {name} | {len(columns)} | {'PASS' if ok else 'FAIL'} | "
        f"{'none' if ok else '; '.join(problems[:3])} |"
        for name, (ok, columns, problems) in audits.items()
    )
    rec_rows = "\n".join(
        f"| {row['coin']} | {row['timeframe']} | {row['exit']} | "
        f"{row['generated']} | {row['taken']} | {row['blocked_open']} | "
        f"{row['last_bar']} | {row['zero_risk']} | {row['open_end']} | "
        f"{row['other']} | {'PASS' if row['reconciles'] else 'FAIL'} |"
        for row in rec
    )
    csv_rows = "\n".join(
        f"| {path.relative_to(ROOT)} | {count} |"
        for path, count in csv_paths
    )
    code_info = []
    for name in ("s15_cci_trend.py", "run_s15.py"):
        content = (ROOT / "src" / name).read_bytes()
        line_count = len(content.decode("utf-8").splitlines())
        code_info.append(
            f"| src/{name} | {line_count} | {hashlib.sha256(content).hexdigest()} |"
        )
    count_by_verdict: dict[str, int] = {}
    for interval in IVS:
        for key in ("verdict_native", "verdict_forced"):
            value = summary[interval][key]
            count_by_verdict[value] = count_by_verdict.get(value, 0) + 1
    verdict_tally = ", ".join(f"{name}: {count}" for name, count in sorted(count_by_verdict.items()))
    days_note = coverage.summary_line(cov, runner.COINS, IVS)
    blocked_sum = sum(row["blocked_open"] for row in rec)
    return "\n\n".join([
        "## 1. Rule and source\n\n"
        "**Departures from the spec: none. Engine conventions that can alter a trade:** "
        "close-bar entries and native exits fill at the next open; the 2×ATR signal-time "
        "distance is carried through `stop_frac` and scales with fill/signal-close if there "
        "is an entry gap; stops win same-bar ties and gap-through stops fill at the bar open; "
        "an open trade at data end is discarded; one position per coin/timeframe. Fees are "
        "0.055% per side, taker; funding is not modeled.\n\n"
        "On a closed bar, enter long when CCI(20) crosses from at/below +100 to above +100; "
        "enter short when it crosses from at/above -100 to below -100. Fill at the next bar's "
        "open. The native exit is the opposite zero-line cross (long below zero, short above "
        "zero), decided on a closed bar and filled next open. Initial stop is 2×ATR(20); no "
        "native take-profit. A forced 1:3 stop/target with the shared 30-bar limit is the "
        "comparison exit.\n\n"
        "Spec source sentence, verbatim: “CCI identifies cyclical extremes; it does not "
        "uniquely prescribe a universal crypto stop/exit.” The spec makes no performance claim.",
        "## 2. Placeholders and adaptations declared plainly\n\n"
        "1. CCI uses typical price (H+L+C)/3, a 20-bar SMA, rolling 20-bar mean absolute "
        "deviation from that window's SMA, and divisor 0.015, as fixed in the spec.\n"
        "2. ATR smoothing is Wilder-style recursive smoothing with alpha 1/20, as a project "
        "convention; first 20 values are blanked. The spec does not separately pin ATR seed/"
        "smoothing.\n"
        "3. The engine expresses risk as a fraction of fill when the fill price is unknown at "
        "signal time. Implementation is stop_frac = 2×ATR(signal bar)/close(signal bar), "
        "then the engine resolves stop = fill×(1−direction×fraction). Thus a gap scales the "
        "distance from the exact 2×ATR by fill/signal-close. ATR is frozen at the signal bar.\n"
        "4. Crossing equality is explicit: entry crosses use previous CCI <= +100 / >= -100 "
        "and current CCI > +100 / < -100; native zero exits use previous >0/current <=0 "
        "for longs and previous <0/current >=0 for shorts. Zero mean deviation yields "
        "undefined CCI and no signal.\n"
        "5. Warmup is the spec-locked 250 bars on every timeframe. The spec matrix is 1H, "
        "4H, 1D; 6H is excluded. The forced comparison uses the project-wide 30-bar limit.",
        "## 3. Fresh lookahead-bias audit\n\n"
        f"Fresh cut-and-recompute audit: {audit_passes}/{audit_total} coin/timeframe datasets "
        f"passed ({sum(len(v[1]) for v in audits.values())} indicator/signal columns checked "
        "in total; 25 history cuts per dataset). The audit compares all derived CCI, ATR, "
        "signal and stop-fraction values at each cut against full-history values.\n\n"
        "Plainly: no trade is selected, skipped, or changed using information from the same "
        "bar's later outcome. Signals use closed-bar CCI only and fill next open; high/low "
        "are used only by the engine to test the already-active stop/target. ATR is frozen "
        "from the signal bar. "
        + "\n\n| Dataset | Derived columns | Result | Mismatches |\n|---|---:|---|---|\n"
        + audit_rows
        + "\n\nData disclosure: the existing cache files are dated 2026-09-04; no data was "
        "downloaded. The partial 1H final bar opening 2026-09-05 00:00 UTC and partial 6H "
        "bar opening 2026-09-05 12:00 UTC are retained because the clock-based forming-bar "
        "drop does not remove these historical cached bars. The tested matrix does not include "
        "6H. Per tested coin/timeframe, final-bar impact is:\n\n"
        + "\n".join(final_notes),
        "## 4. Results and signal reconciliation\n\n"
        + result_table(res, cov, summary)
        + "\n\nHistory covers the tradeable window after the 250-bar warmup. "
        + days_note
        + "\n\nSignal reconciliation: each raw qualifying signal is assigned once to "
        "completed trade, blocked while position open, final-bar/no-next-open, zero-risk, "
        "accepted entry left open and discarded at data end, or other. Counts must sum.\n\n"
        "| Coin | Timeframe | Exit | Signals generated | Completed entries | "
        "Blocked: position open | Final-bar signal | Zero-risk | "
        "Open trade discarded at end | Other | Adds up? |\n"
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|\n"
        + rec_rows
        + f"\n\nReconciliation {'PASSES' if all_reconciled else 'FAILS'} for all cells; "
        f"position-open blocked signals: {blocked_sum}.",
        "## 5. t-statistics versus the ~2.0 noise threshold\n\n"
        + tstat_and_coin_table(res),
        "## 6. Concentration check (both exits)\n\n"
        + concentration_table(res),
        "## 7. Long/short breakdown (both exits)\n\n"
        + side_table(res),
        "## 8. Exit-death check and entry overlap\n\n"
        + exit_death_block(res)
        + "\n\n### 8a. Re-entry clustering after stop-outs (saved CSVs)\n\n"
        + reentry_clustering(csv_paths)
        + "\n\n### 8b. Exit-reason split and mean post-fee R per reason (saved CSVs)\n\n"
        + reason_means(csv_paths),
        "## 9. Funding disclosure\n\n"
        + funding_estimates(res, summary),
        "## 10. Parameter sensitivity sweep\n\n"
        + sensitivity_table(sensitivities),
        "## 11. Market-condition breakdown\n\n"
        + regime_findings(res),
        "## 12. Source comparison and discrepancies\n\n"
        + _source_comparison(res, summary),
        "## 13. Fixed discard-bar verdict per cell\n\n"
        + "The fixed bar is applied post-fee:\n\n```\n"
        + describe()
        + "\n```\n\n"
        + verdict_details(res, summary),
        "## 14. Bottom line\n\n"
        + f"Verdicts across six pooled cells: {verdict_tally}. "
        + days_note
        + " The result is only interpreted through the fixed discard bar; per-coin "
        "evidence, t-statistics, concentration, market-condition split, and exit overlap "
        "are reported above. Sensitivity variants are not promoted to headline.",
        "## 15. Files changed\n\n"
        "Dry run only: no log, commit, or push. The only repository additions are the "
        "new Strategy #15 sources and its per-cell trade-list CSVs.\n\n"
        "| New source file | Lines | SHA-256 |\n|---|---:|---|\n"
        + "\n".join(code_info)
        + "\n\n| Trade-list file | Completed trade rows |\n|---|---:|\n"
        + csv_rows
        + "\n\nThe external final report is written to "
        "`C:\\Users\\MarketCoder\\Desktop\\s15_report_final.txt`.",
    ])


def main() -> None:
    missing = [
        runner.bd.DATA_DIR / f"{coin}_{interval}.parquet"
        for coin in runner.COINS for interval in IVS
        if not (runner.bd.DATA_DIR / f"{coin}_{interval}.parquet").is_file()
    ]
    if missing:
        raise FileNotFoundError(
            "Required cached datasets missing; refusing loader fallback/download: "
            + ", ".join(str(path) for path in missing)
        )

    spec = make_spec()
    res = runner.run(spec, runner.COINS, IVS, audit=True)
    summary = runner.summarise(spec, res, IVS)
    cov = coverage.collect(runner.COINS, IVS, spec.warmup_for)
    audits = res["audit"]
    rec = reconcile(spec, res)
    final_notes = final_bar_impact(spec, res)
    sensitivities = sensitivity_results(res)
    csv_paths = write_trade_lists(res)

    if not all(ok for ok, _, _ in audits.values()):
        raise RuntimeError("At least one fresh lookahead audit failed.")
    if not all(row["reconciles"] for row in rec):
        raise RuntimeError("At least one per-cell signal reconciliation failed.")

    report_text = _report(
        res, summary, cov, audits, rec, final_notes, sensitivities, csv_paths
    )
    REPORT_PATH.write_text(report_text + "\n", encoding="utf-8", newline="\n")
    print(
        f"REPORT_WRITTEN={REPORT_PATH}\n"
        f"AUDITS={sum(ok for ok, _, _ in audits.values())}/{len(audits)}\n"
        f"RECONCILIATION={'PASS' if all(row['reconciles'] for row in rec) else 'FAIL'}\n"
        f"CELLS={sum(1 for _ in IVS for _ in EXITS)}\n"
        f"TRADE_LISTS={len(csv_paths)}"
    )


if __name__ == "__main__":
    main()
