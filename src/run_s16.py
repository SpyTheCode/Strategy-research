"""Dry-run report for Strategy #16 - ROC momentum."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

import context_checks
import coverage
import runner
import s16_roc_momentum as s16
from discard_bar import BAR, breakeven_win_rate, describe, exit_death, verdict
from harness import Signal, Trade, forced_13_exit, metrics, simulate

NAME = "#16 ROC zero-cross momentum"
IVS = ["1H", "4H", "1D"]
EXITS = ("native", "forced-1:3")
HOURS_PER_BAR = {"1H": 1.0, "4H": 4.0, "1D": 24.0}
BASE_FUNDING_RATE = 0.0001
SETTLEMENT_HOURS = 8.0
MIN_OVERLAP = 0.85
FORCED_LIMIT = 30
ROOT = Path(__file__).resolve().parent.parent
TRADE_DIR = ROOT / "trade_lists" / "s16"
REPORT_PATH = Path(r"C:\Users\MarketCoder\Desktop\s16_report_final.txt")


def make_spec(period: int = 20, stop_atr: float = 2.0) -> runner.StrategySpec:
    return runner.StrategySpec(
        name=f"{NAME} [ROC={period}, stop={stop_atr:g}xATR]",
        add_indicators=lambda df: s16.add_indicators(
            df, period=period, stop_atr=stop_atr
        ),
        entry=s16.entry,
        native_exit=s16.native_exit,
        warmup=s16.WARMUP,
        native_time_limit=None,
    )


def fmt(value: float | int | None, digits: int = 2) -> str:
    if value is None or not np.isfinite(value):
        return "n/a"
    return f"{value:.{digits}f}"


def exit_function(label: str, df: pd.DataFrame):
    return s16.native_exit(df) if label == "native" else forced_13_exit


def sensitivity_results(headline: dict) -> list[dict]:
    variants = [
        ("Headline ROC=20, stop=2 ATR", 20, 2.0, headline),
        ("ROC=10, stop=2 ATR", 10, 2.0, None),
        ("ROC=50, stop=2 ATR", 50, 2.0, None),
        ("ROC=20, stop=1.5 ATR", 20, 1.5, None),
        ("ROC=20, stop=2.5 ATR", 20, 2.5, None),
    ]
    rows = []
    for name, period, stop_atr, result in variants:
        if result is None:
            result = runner.run(
                make_spec(period, stop_atr), runner.COINS, IVS, audit=True
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
                suffix = "forced13" if label == "forced-1:3" else "native"
                path = TRADE_DIR / f"s16_{coin}_{interval}_{suffix}.csv"
                pd.DataFrame(rows, columns=columns).to_csv(path, index=False)
                written.append((path, len(rows)))
    return written


def _simulate_reconciliation(
    df: pd.DataFrame,
    label: str,
    entry_fn,
    exit_fn,
    completed_trades: list[Trade],
) -> dict:
    """Replay market-engine state and categorize each eligible signal once."""
    times = df["open_time"].reset_index(drop=True)
    closed_keys = {(t.direction, t.entry_time) for t in completed_trades}
    pending_entry: Signal | None = None
    pending_signal_key: tuple[int, pd.Timestamp] | None = None
    pending_exit_reason: str | None = None
    position: Trade | None = None
    accepted: set[tuple[int, pd.Timestamp]] = set()
    completed_mirror: set[tuple[int, pd.Timestamp]] = set()
    counts = {
        "signals": 0, "taken": 0, "blocked_open": 0, "last_bar": 0,
        "zero_risk": 0, "open_end": 0, "other": 0,
    }
    time_limit = FORCED_LIMIT if label == "forced-1:3" else None
    entry_signals = [
        entry_fn(df, i) for i in range(len(df))
    ]

    for i in range(s16.WARMUP, len(df)):
        row = df.iloc[i]
        if position is not None and pending_exit_reason is not None:
            completed_mirror.add((position.direction, position.entry_time))
            position = None
            pending_exit_reason = None

        if position is None and pending_entry is not None:
            fill = float(row["open"])
            stop = pending_entry.resolve_stop(fill)
            if stop != fill:
                position = Trade(
                    direction=pending_entry.direction,
                    entry_time=times.iloc[i],
                    entry_price=fill,
                    initial_stop=stop,
                    regime=str(row.get("regime", "")),
                )
                if pending_signal_key is None:
                    raise RuntimeError("Queued signal has no fill timestamp.")
                accepted.add(pending_signal_key)
            else:
                counts["zero_risk"] += 1
            pending_entry = None
            pending_signal_key = None

        if position is not None:
            plan = exit_fn(df, i, position)
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
                    position.bars_held += 1
                    if position.bars_held >= time_limit:
                        pending_exit_reason = "time"
                if pending_exit_reason is None and plan.close_exit:
                    pending_exit_reason = plan.reason or "signal"

        sig = entry_signals[i]
        if sig is None:
            continue
        counts["signals"] += 1
        if i + 1 >= len(df):
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
        {(position.direction, position.entry_time)} if position is not None else set()
    )
    counts["taken"] = len(accepted & closed_keys)
    counts["open_end"] = len(accepted & open_end_keys)
    counts["other"] = len(accepted - closed_keys - open_end_keys)
    total_buckets = sum(
        counts[key] for key in
        ("taken", "blocked_open", "last_bar", "zero_risk", "open_end", "other")
    )
    return {
        **counts,
        "reconciles": total_buckets == counts["signals"] and closed_keys == completed_mirror,
    }


def reconcile(spec: runner.StrategySpec, res: dict) -> list[dict]:
    rows = []
    for coin in runner.COINS:
        for interval in IVS:
            df = runner._prepare(spec, coin, interval)
            entry_fn = spec.entry(df)
            for label in EXITS:
                counts = _simulate_reconciliation(
                    df, label, entry_fn, exit_function(label, df), res["trades"][
                        (coin, interval, label)
                    ],
                )
                rows.append({
                    "coin": coin, "timeframe": interval, "exit": label, **counts,
                })
    return rows


def final_bar_notes(spec: runner.StrategySpec, res: dict) -> list[str]:
    notes = []
    for coin in runner.COINS:
        for interval in IVS:
            df = runner._prepare(spec, coin, interval)
            times = df["open_time"].reset_index(drop=True)
            entry_fn = spec.entry(df)
            last_time = times.iloc[-1]
            penultimate = entry_fn(df, len(df) - 2) is not None
            final_signal = entry_fn(df, len(df) - 1) is not None
            entries = sum(
                t.entry_time == last_time
                for label in EXITS for t in res["trades"][(coin, interval, label)]
            )
            exits = sum(
                t.exit_time == last_time
                for label in EXITS for t in res["trades"][(coin, interval, label)]
            )
            effects = []
            if penultimate:
                effects.append("penultimate-bar signal fills at final open")
            if entries:
                effects.append(f"{entries} entries use final open across exits")
            if exits:
                effects.append(f"{exits} exits are stamped at final bar")
            if final_signal:
                effects.append("final close signal has no next bar and is unfilled")
            notes.append(
                f"- {coin} {interval}: final bar opens {last_time:%Y-%m-%d %H:%M} UTC; "
                + ("; ".join(effects) if effects else
                   "no signal or completed trade entry/exit is affected")
                + "."
            )
    return notes


def results_table(res: dict, cov: dict, summary: dict) -> str:
    lines = [
        "| Timeframe | Exit | Trades | Days history per coin (BTC/SOL/XRP) | Win% | RR | "
        "R (pre-fee) | R (post-fee) | R/trade | Sharpe | Max DD % | Max DD (R) | "
        "R-recovery | Fee cost/trade | Verdict |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for interval in IVS:
        days = coverage.days_by_coin(cov, interval, runner.COINS)
        day_text = " / ".join(f"{coin} {days[coin]:.0f}" for coin in runner.COINS)
        for label in EXITS:
            m = res["pooled"][(interval, label)]
            verdict_key = "verdict_native" if label == "native" else "verdict_forced"
            lines.append(
                f"| {interval} | {label} | {m['trades']} | {day_text} | "
                f"{fmt(100*m['win_rate'],1)} | {fmt(m['rr_achieved'])} | "
                f"{fmt(m['r_sum_pre_fee'],1)} | {fmt(m['r_sum_post_fee'],1)} | "
                f"{fmt(m['expectancy_post_fee_r'],3)} | {fmt(m['sharpe_post_fee'])} | "
                f"{fmt(m['max_drawdown_pct'],1)} | {fmt(m['max_drawdown_r'],1)} | "
                f"{fmt(m['r_recovery'])} | {fmt(m['avg_fee_cost_r'],3)} | "
                f"**{summary[interval][verdict_key]}** |"
            )
    return "\n".join(lines)


def tstat_coin_table(res: dict) -> str:
    lines = [
        "| Timeframe | Exit | Trades | R/trade post-fee | t-stat | ~2.0 noise read |",
        "|---|---|---:|---:|---:|---|",
    ]
    for interval in IVS:
        for label in EXITS:
            stat = context_checks.significance(res["trades"][(interval, label)])
            t = stat["t_net"]
            read = (
                "positive beyond noise" if np.isfinite(t) and t >= 2
                else "negative beyond noise" if np.isfinite(t) and t <= -2
                else "inside/indeterminate"
            )
            lines.append(
                f"| {interval} | {label} | {stat['n']} | {fmt(stat['net_mean'],4)} | "
                f"{fmt(t)} | {read} |"
            )
    lines += [
        "",
        "| Coin | Timeframe | Exit | Trades | Win% | R/trade post-fee | "
        "Total R post-fee | Fixed-bar verdict |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for coin in runner.COINS:
        for interval in IVS:
            for label in EXITS:
                m = res["per_cell"][(coin, interval, label)]
                v, _ = verdict(m, label)
                lines.append(
                    f"| {coin} | {interval} | {label} | {m['trades']} | "
                    f"{fmt(100*m['win_rate'],1)} | "
                    f"{fmt(m['expectancy_post_fee_r'],4)} | "
                    f"{fmt(m['r_sum_post_fee'],2)} | {v} |"
                )
    lines.append(
        "\nt is mean post-fee R divided by the standard error; |t| near 2 is a rough "
        "noise comparison, not proof of a durable edge."
    )
    return "\n".join(lines)


def concentration_table(res: dict) -> str:
    lines = [
        "| Timeframe | Exit | Trades | Best trade R | Best trade share | "
        "R without best | Best 5 R | Best 5 share | R without best 5 | "
        "Profitable without best 5? |",
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
            best_one, best_five = float(ordered[0]), float(ordered[:5].sum())
            lines.append(
                f"| {interval} | {label} | {len(values)} | {best_one:+.3f} | "
                f"{fmt(100*best_one/total,1) if total > 0 else 'n/a'} | "
                f"{total-best_one:+.3f} | {best_five:+.3f} | "
                f"{fmt(100*best_five/total,1) if total > 0 else 'n/a'} | "
                f"{total-best_five:+.3f} | {'yes' if total-best_five > 0 else 'no'} |"
            )
    return "\n".join(lines)


def side_table(res: dict) -> str:
    lines = [
        "| Timeframe | Exit | Side | Trades | Win% | R post-fee | R/trade |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for interval in IVS:
        for label in EXITS:
            trades = res["trades"][(interval, label)]
            for name, direction in (("long", 1), ("short", -1)):
                side = [trade for trade in trades if trade.direction == direction]
                if not side:
                    lines.append(f"| {interval} | {label} | {name} | 0 | n/a | n/a | n/a |")
                    continue
                values = np.array([trade.net_r for trade in side])
                lines.append(
                    f"| {interval} | {label} | {name} | {len(side)} | "
                    f"{100*np.mean(values > 0):.1f} | {values.sum():+.2f} | "
                    f"{values.mean():+.4f} |"
                )
    return "\n".join(lines)


def entry_key(trade: Trade) -> tuple[int, pd.Timestamp]:
    return trade.direction, trade.entry_time


def overlap(res: dict, interval: str) -> float:
    native = {entry_key(t) for t in res["trades"][(interval, "native")]}
    forced = {entry_key(t) for t in res["trades"][(interval, "forced-1:3")]}
    union = native | forced
    return len(native & forced) / len(union) if union else float("nan")


def shared_entry_rerun(res: dict, interval: str) -> tuple[dict, dict]:
    shared_by_coin = {}
    for coin in runner.COINS:
        native = {
            entry_key(t) for t in res["trades"][(coin, interval, "native")]
        }
        forced = {
            entry_key(t) for t in res["trades"][(coin, interval, "forced-1:3")]
        }
        shared_by_coin[coin] = native & forced
    spec = make_spec()
    outcomes: dict[str, list[Trade]] = {"native": [], "forced-1:3": []}
    for coin in runner.COINS:
        df = runner._prepare(spec, coin, interval)
        base_entry = spec.entry(df)
        times = df["open_time"].reset_index(drop=True)
        common = shared_by_coin[coin]

        def only_common(_df, i, *, _entry=base_entry, _times=times, _common=common):
            signal = _entry(_df, i)
            if signal is None or i + 1 >= len(_times):
                return None
            return signal if (signal.direction, _times.iloc[i + 1]) in _common else None

        for label in EXITS:
            trades = simulate(
                df, only_common,
                s16.native_exit(df) if label == "native" else forced_13_exit,
                warmup=spec.warmup_for(interval),
                time_limit_bars=FORCED_LIMIT if label == "forced-1:3" else None,
                entry_fee_rate=runner.TAKER_FEE_RATE,
                exit_fee_rate=runner.TAKER_FEE_RATE,
            )
            outcomes[label].extend(trades)
    return (
        metrics(outcomes["native"], interval=interval),
        metrics(outcomes["forced-1:3"], interval=interval),
    )


def exit_death_section(res: dict) -> tuple[str, dict]:
    lines = [
        "| Timeframe | Native trades | Forced trades | Entry overlap | "
        "Exit-death? | Diagnosis |",
        "|---|---:|---:|---:|---|---|",
    ]
    shared_stats = {}
    for interval in IVS:
        native = res["pooled"][(interval, "native")]
        forced = res["pooled"][(interval, "forced-1:3")]
        ov = overlap(res, interval)
        death, diagnosis = exit_death(native, forced)
        lines.append(
            f"| {interval} | {native['trades']} | {forced['trades']} | "
            f"{fmt(100*ov,1)}% | {death} | {diagnosis} |"
        )
        if np.isfinite(ov) and ov < MIN_OVERLAP:
            nstat, fstat = shared_entry_rerun(res, interval)
            shared_stats[interval] = (nstat, fstat)
            lines.append(
                f"| | | | | | Shared-entry re-run below 85%: native "
                f"{nstat['trades']} trades, {fmt(nstat['expectancy_post_fee_r'],4)}R/trade; "
                f"forced {fstat['trades']} trades, "
                f"{fmt(fstat['expectancy_post_fee_r'],4)}R/trade. |"
            )
    lines.append(
        "\nOverlap is the share of the union of completed entry keys (direction and "
        "timestamp) that is common to both exits. A shared-entry market-path rerun is "
        "performed whenever overlap is below 85%."
    )
    return "\n".join(lines), shared_stats


def reentry_section(csv_paths: list[tuple[Path, int]]) -> str:
    lines = [
        "| Coin | Timeframe | Exit | Stop-outs | Later completed re-entry | "
        "Median gap (bars) | Within 3 bars |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for path, _ in csv_paths:
        frame = pd.read_csv(path)
        if frame.empty:
            continue
        stops = frame[frame["exit_reason"] == "stop"]
        gaps = []
        for _, trade in stops.iterrows():
            later = frame[
                pd.to_datetime(frame["entry_time"], utc=True)
                > pd.to_datetime(trade["exit_time"], utc=True)
            ]
            if not later.empty:
                gap = (
                    pd.to_datetime(later["entry_time"].min(), utc=True)
                    - pd.to_datetime(trade["exit_time"], utc=True)
                ) / pd.Timedelta(hours=HOURS_PER_BAR[trade["timeframe"]])
                gaps.append(float(gap))
        if gaps:
            near = sum(gap <= 3 for gap in gaps)
            median = float(np.median(gaps))
            lines.append(
                f"| {frame.iloc[0]['coin']} | {frame.iloc[0]['timeframe']} | "
                f"{frame.iloc[0]['exit_variant']} | {len(stops)} | {len(gaps)} | "
                f"{median:.1f} | {100*near/len(gaps):.1f}% ({near}/{len(gaps)}) |"
            )
        else:
            lines.append(
                f"| {frame.iloc[0]['coin']} | {frame.iloc[0]['timeframe']} | "
                f"{frame.iloc[0]['exit_variant']} | {len(stops)} | 0 | n/a | n/a |"
            )
    return "\n".join(lines)


def reason_section(csv_paths: list[tuple[Path, int]]) -> str:
    combined = pd.concat(
        [pd.read_csv(path) for path, _ in csv_paths], ignore_index=True
    )
    lines = [
        "| Timeframe | Exit | Exit reason | Trades | Mean R post-fee |",
        "|---|---|---|---:|---:|",
    ]
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


def funding_section(res: dict, summary: dict) -> str:
    lines = [
        "| Timeframe | Exit | Trades | Avg bars held | Median stop % | "
        "Base-rate funding estimate R/trade at 0.01%/8h |",
        "|---|---|---:|---:|---:|---:|",
    ]
    shown = 0
    for interval in IVS:
        for label in EXITS:
            verdict_key = "verdict_native" if label == "native" else "verdict_forced"
            if summary[interval][verdict_key] != "KEEP":
                continue
            trades = res["trades"][(interval, label)]
            m = res["pooled"][(interval, label)]
            stop_frac = float(np.median([
                abs(t.entry_price-t.initial_stop)/t.entry_price for t in trades
            ]))
            settlements = (
                m["avg_bars_held"] * HOURS_PER_BAR[interval] / SETTLEMENT_HOURS
            )
            estimate = settlements * BASE_FUNDING_RATE / stop_frac
            lines.append(
                f"| {interval} | {label} | {m['trades']} | "
                f"{fmt(m['avg_bars_held'],1)} | {stop_frac*100:.3f}% | "
                f"{estimate:.5f} |"
            )
            shown += 1
    if not shown:
        lines.append("| none | none | 0 | n/a | n/a | no KEEP cell; no estimate |")
    lines.append(
        "\nFunding was not modeled. The estimate is a rough 0.01% per 8-hour "
        "settlement base rate and is reported only for KEEP cells."
    )
    return "\n".join(lines)


def sensitivity_section(rows: list[dict]) -> str:
    lines = [
        "| Variant | Timeframe | Exit | Trades | Win% | Post-fee total R | "
        "R/trade | Sharpe | Verdict |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['variant']} | {row['timeframe']} | {row['exit']} | "
            f"{row['trades']} | {fmt(100*row['win'],1)} | {fmt(row['r'],2)} | "
            f"{fmt(row['r_trade'],4)} | {fmt(row['sharpe'])} | {row['verdict']} |"
        )
    lines.append(
        "\nThe period and stop-width sweeps are independent; the headline is "
        "included as a reference row. No swept setting replaces the headline."
    )
    return "\n".join(lines)


def regime_section(res: dict) -> str:
    lines = [
        "| Timeframe | Exit | Regime | Trades | Post-fee R | R/trade |",
        "|---|---|---|---:|---:|---:|",
    ]
    findings = []
    for interval in IVS:
        for label in EXITS:
            buckets = res["pooled"][(interval, label)]["regime_r"]
            valid = []
            for regime, record in sorted(buckets.items()):
                count = record["trades"]
                total = record["r_sum_post_fee"]
                mean = total/count if count else float("nan")
                lines.append(
                    f"| {interval} | {label} | {regime} | {count} | "
                    f"{total:+.2f} | {fmt(mean,3)} |"
                )
                if count:
                    valid.append((regime, mean, count))
            if valid:
                high = max(valid, key=lambda item: item[1])
                low = min(valid, key=lambda item: item[1])
                findings.append(
                    f"{interval}/{label}: highest observed {high[0]} "
                    f"{high[1]:+.3f}R/trade (n={high[2]}), lowest {low[0]} "
                    f"{low[1]:+.3f}R/trade (n={low[2]})."
                )
    lines.append("\nPlain findings: " + " ".join(findings))
    lines.append(
        "The spec makes no performance claim by market condition. These are "
        "descriptive regime splits; regime labels do not affect signals or exits."
    )
    return "\n".join(lines)


def verdict_section(res: dict, summary: dict) -> str:
    lines = [
        "| Timeframe | Exit | Trades >=30 | Expectancy >=0.10 | Sharpe >=0.70 | "
        "Recovery >=1.5 | Reward test | Discard conditions | Verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for interval in IVS:
        for label in EXITS:
            m = res["pooled"][(interval, label)]
            if label == "forced-1:3":
                required = breakeven_win_rate(m["avg_fee_cost_r"]) + BAR.keep_win_margin
                reward = f"win {m['win_rate']:.1%} {'PASS' if m['win_rate'] >= required else 'FAIL'}; need {required:.1%}"
            else:
                reward = f"RR {fmt(m['rr_achieved'])} {'PASS' if m['rr_achieved'] >= BAR.keep_rr_native else 'FAIL'}; need 1.50"
            exp = m["expectancy_post_fee_r"]
            shp = m["sharpe_post_fee"]
            rec = m["r_recovery"]
            discard_bits = (
                f"exp<=0 {'yes' if exp <= 0 else 'no'}; "
                f"Sharpe<0.30 {'yes' if shp < BAR.discard_sharpe else 'no'}; "
                f"recovery<0.50 {'yes' if rec < BAR.discard_r_recovery else 'no'}"
            )
            verdict_key = "verdict_native" if label == "native" else "verdict_forced"
            lines.append(
                f"| {interval} | {label} | {m['trades'] >= BAR.min_trades} "
                f"({m['trades']}) | {exp >= BAR.keep_expectancy_r} ({exp:+.4f}) | "
                f"{shp >= BAR.keep_sharpe} ({fmt(shp)}) | "
                f"{rec >= BAR.keep_r_recovery} ({fmt(rec)}) | {reward} | "
                f"{discard_bits} | {summary[interval][verdict_key]} |"
            )
    lines.append("\n" + describe())
    return "\n".join(lines)


def source_section(res: dict, summary: dict) -> str:
    outputs = []
    for interval in IVS:
        for label in EXITS:
            m = res["pooled"][(interval, label)]
            vkey = "verdict_native" if label == "native" else "verdict_forced"
            outputs.append(
                f"{interval}/{label}: {m['expectancy_post_fee_r']:+.4f}R/trade "
                f"post-fee ({summary[interval][vkey]})."
            )
    return (
        'Spec source sentence, verbatim: "ROC=(close/close[n]-1)×100; source '
        'literature does not settle universal entries/stops."\n\n'
        "The spec does not make a performance claim. The period-20 zero-cross "
        "entry, reverse-cross native exit, and 2×ATR stop are the pinned test "
        "interpretation/project convention, not a universal rule attributed to "
        "Pring. " + " ".join(outputs)
    )


def _csv_cell(csv_paths: list[tuple[Path, int]], interval: str, label: str) -> pd.DataFrame:
    selected = []
    for path, _ in csv_paths:
        if f"_{interval}_" in path.name and (
            ("forced13" in path.name) == (label == "forced-1:3")
        ):
            selected.append(pd.read_csv(path))
    if not selected:
        return pd.DataFrame()
    frame = pd.concat(selected, ignore_index=True)
    frame["entry_dt"] = pd.to_datetime(frame["entry_time"], utc=True)
    frame["exit_dt"] = pd.to_datetime(frame["exit_time"], utc=True)
    frame["exit_year"] = frame["exit_dt"].dt.year
    return frame


def _cell_detail(frame: pd.DataFrame, interval: str, label: str) -> dict:
    best = frame.sort_values("R post-fee", ascending=False).head(5).copy()
    total = float(frame["R post-fee"].sum())
    best5_r = float(best["R post-fee"].sum())
    remainder = frame.drop(index=best.index)
    by_direction = {
        direction: group for direction, group in
        remainder.groupby("direction", sort=True)
    }
    annual = frame.groupby("exit_year", sort=True)["R post-fee"].agg(
        trades="count", total="sum", mean="mean"
    )
    per_coin_year = frame.groupby(
        ["exit_year", "coin"], sort=True
    )["R post-fee"].agg(trades="count", total="sum", mean="mean")
    coin_totals = frame.groupby("coin")["R post-fee"].sum().sort_values(
        ascending=False
    )
    year_totals = annual["total"].sort_values(ascending=False)
    top_years = [int(year) for year in year_totals.head(2).index]
    top_year_sum = float(year_totals.iloc[0]) if len(year_totals) else 0.0
    top_two_sum = float(year_totals.head(2).sum())
    top_coin = str(coin_totals.index[0]) if len(coin_totals) else "n/a"
    top_coin_r = float(coin_totals.iloc[0]) if len(coin_totals) else 0.0
    return {
        "interval": interval,
        "exit": label,
        "frame": frame,
        "best": best,
        "total": total,
        "trades": len(frame),
        "best5_r": best5_r,
        "best5_share": best5_r / total if total > 0 else float("nan"),
        "without5": remainder,
        "without5_total": float(remainder["R post-fee"].sum()),
        "without5_mean": float(remainder["R post-fee"].mean())
        if len(remainder) else float("nan"),
        "by_direction": by_direction,
        "annual": annual,
        "per_coin_year": per_coin_year,
        "top_years": top_years,
        "top_year_r": top_year_sum,
        "top_two_year_r": top_two_sum,
        "without_top_year_r": total-top_year_sum,
        "without_top_two_year_r": total-top_two_sum,
        "coin_totals": coin_totals,
        "top_coin": top_coin,
        "top_coin_r": top_coin_r,
        "without_top_coin_r": total-top_coin_r,
        "year_share": top_year_sum/total if total > 0 else float("nan"),
        "top_two_year_share": top_two_sum/total if total > 0 else float("nan"),
        "coin_share": top_coin_r/total if total > 0 else float("nan"),
    }


def concentration_detail(
    res: dict,
    csv_paths: list[tuple[Path, int]],
    sensitivities: list[dict],
    shared_stats: dict,
    funding_values: dict,
) -> tuple[str, dict]:
    details = {}
    for interval in IVS:
        for label in EXITS:
            m = res["pooled"][(interval, label)]
            summary_verdict = verdict(m, label)[0]
            qualifies = (
                summary_verdict == "KEEP"
                or m["expectancy_post_fee_r"] >= 0.10
            )
            if qualifies:
                frame = _csv_cell(csv_paths, interval, label)
                if len(frame) != m["trades"]:
                    raise RuntimeError(
                        f"Saved CSV rows ({len(frame)}) do not match {interval} "
                        f"{label} metric trades ({m['trades']})."
                    )
                details[(interval, label)] = _cell_detail(frame, interval, label)

    if not details:
        return (
            "No headline cell is KEEP or has post-fee expectancy >= +0.10R; "
            "there are no qualifying cell-level concentration details.",
            details,
        )

    lines = [
        "Eligible cells are those with KEEP verdict or headline post-fee "
        "expectancy >= +0.10R/trade. All trade and calendar-year calculations "
        "below were independently derived from that cell's saved trade-list CSVs."
    ]
    for (interval, label), detail in details.items():
        lines.extend([
            "",
            f"### {interval} / {label}",
            "",
            "Best five completed trades by post-fee R:",
            "",
            "| Coin | Direction | Entry time (UTC) | Exit time (UTC) | Bars held | "
            "Entry price | Exit price | R post-fee |",
            "|---|---|---|---|---:|---:|---:|---:|",
        ])
        for _, trade in detail["best"].iterrows():
            lines.append(
                f"| {trade['coin']} | {trade['direction']} | "
                f"{trade['entry_dt']:%Y-%m-%d %H:%M} | "
                f"{trade['exit_dt']:%Y-%m-%d %H:%M} | {int(trade['bars_held'])} | "
                f"{float(trade['entry_price']):.8f} | "
                f"{float(trade['exit_price']):.8f} | "
                f"{float(trade['R post-fee']):+.4f} |"
            )
        lines.extend([
            "",
            "Calendar-year breakdown; year is assigned by exit timestamp (UTC):",
            "",
            "| Year | Pooled trades | Pooled post-fee R | Pooled R/trade | "
            "BTC n | BTC R | BTC R/trade | SOL n | SOL R | SOL R/trade | "
            "XRP n | XRP R | XRP R/trade |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        years = sorted(int(year) for year in detail["annual"].index)
        for year in years:
            pooled = detail["annual"].loc[year]
            coin_bits = []
            for coin in runner.COINS:
                try:
                    row = detail["per_coin_year"].loc[(year, coin)]
                    coin_bits.extend([
                        str(int(row["trades"])),
                        f"{row['total']:+.4f}",
                        f"{row['mean']:+.4f}",
                    ])
                except KeyError:
                    coin_bits.extend(["0", "0.0000", "n/a"])
            lines.append(
                f"| {year} | {int(pooled['trades'])} | {pooled['total']:+.4f} | "
                f"{pooled['mean']:+.4f} | " + " | ".join(coin_bits) + " |"
            )
        lines.extend([
            "",
            "Overall and direction results after removing the best five trades:",
            "",
            "| Remainder | Trades | Post-fee R | R/trade |",
            "|---|---:|---:|---:|",
            f"| All directions | {len(detail['without5'])} | "
            f"{detail['without5_total']:+.4f} | {fmt(detail['without5_mean'],4)} |",
        ])
        for direction in ("long", "short"):
            group = detail["by_direction"].get(direction)
            if group is None:
                lines.append(f"| {direction} | 0 | 0.0000 | n/a |")
            else:
                lines.append(
                    f"| {direction} | {len(group)} | "
                    f"{group['R post-fee'].sum():+.4f} | "
                    f"{group['R post-fee'].mean():+.4f} |"
                )
        lines.extend([
            "",
            "Concentration and stability facts:",
            f"- Best-five share of total post-fee R: "
            f"{fmt(100*detail['best5_share'],1)}% "
            f"(top-five R {detail['best5_r']:+.4f}; total R {detail['total']:+.4f}).",
            f"- Largest annual contribution: {detail['top_years'][0]} "
            f"{detail['top_year_r']:+.4f}R ({fmt(100*detail['year_share'],1)}% "
            f"of total); top two years {detail['top_years']} contribute "
            f"{detail['top_two_year_r']:+.4f}R "
            f"({fmt(100*detail['top_two_year_share'],1)}%).",
            f"- Largest coin contribution: {detail['top_coin']} "
            f"{detail['top_coin_r']:+.4f}R "
            f"({fmt(100*detail['coin_share'],1)}% of total).",
            f"- Removing the top year leaves {detail['without_top_year_r']:+.4f}R; "
            f"removing the top two years leaves "
            f"{detail['without_top_two_year_r']:+.4f}R; removing "
            f"{detail['top_coin']} leaves {detail['without_top_coin_r']:+.4f}R.",
        ])
        if detail["without_top_year_r"] <= 0 or detail["without_top_two_year_r"] <= 0:
            year_fact = "The positive aggregate turns non-positive after removing the stated leading year(s)."
        else:
            year_fact = "The aggregate remains positive after removing its leading year and its leading two years."
        if detail["without_top_coin_r"] <= 0:
            coin_fact = f"The aggregate turns non-positive after removing {detail['top_coin']}."
        else:
            coin_fact = f"The aggregate remains positive after removing {detail['top_coin']}."
        lines.append(f"- {year_fact} {coin_fact}")
        lines.append(
            f"- Fixed-bar headline verdict: {verdict(res['pooled'][(interval,label)], label)[0]}; "
            f"sweep KEEP count for this timeframe/exit: "
            f"{sum(row['verdict']=='KEEP' for row in sensitivities if row['timeframe']==interval and row['exit']==label)}/5."
        )
        if (interval, label) in shared_stats:
            nstat, fstat = shared_stats[(interval, label)]
            lines.append(
                f"- Shared-entry rerun: native {nstat['trades']} trades, "
                f"{nstat['expectancy_post_fee_r']:+.4f}R/trade; forced "
                f"{fstat['trades']} trades, "
                f"{fstat['expectancy_post_fee_r']:+.4f}R/trade."
            )
        if (interval, label) in funding_values:
            lines.append(
                f"- Base-rate funding estimate: {funding_values[(interval,label)]:.5f}R/trade; "
                f"headline expectancy less that estimate is "
                f"{res['pooled'][(interval,label)]['expectancy_post_fee_r']-funding_values[(interval,label)]:+.5f}R/trade."
            )
        else:
            lines.append("- No base-rate funding estimate is stated because this cell did not reach KEEP.")
    return "\n".join(lines), details


def bottom_line(
    res: dict,
    summary: dict,
    sensitivities: list[dict],
    details: dict,
    shared_stats: dict,
    funding_values: dict,
    cov: dict,
) -> str:
    tally = {}
    for interval in IVS:
        for key in ("verdict_native", "verdict_forced"):
            verdict_name = summary[interval][key]
            tally[verdict_name] = tally.get(verdict_name, 0) + 1
    tally_text = ", ".join(f"{key}: {value}" for key, value in sorted(tally.items()))
    paragraphs = [
        f"Verdicts across six pooled cells: {tally_text}. "
        + coverage.summary_line(cov, runner.COINS, IVS)
    ]
    for (interval, label), detail in details.items():
        m = res["pooled"][(interval, label)]
        side_values = {}
        for direction, side in ((1, "long"), (-1, "short")):
            trades = [
                t for t in res["trades"][(interval, label)]
                if t.direction == direction
            ]
            side_values[side] = (
                float(np.mean([t.net_r for t in trades])) if trades else float("nan")
            )
        shared_text = "shared-entry rerun not triggered"
        if interval in shared_stats:
            ns, fs = shared_stats[interval]
            shared_text = (
                f"shared-entry native {ns['expectancy_post_fee_r']:+.4f}R/trade "
                f"({ns['trades']} trades) versus forced "
                f"{fs['expectancy_post_fee_r']:+.4f}R/trade ({fs['trades']} trades)"
            )
        sweeps_keep = sum(
            r["verdict"] == "KEEP" for r in sensitivities
            if r["timeframe"] == interval and r["exit"] == label
        )
        funding_text = (
            f"base-rate funding estimate {funding_values[(interval,label)]:.5f}R/trade; "
            f"expectancy less this estimate "
            f"{m['expectancy_post_fee_r']-funding_values[(interval,label)]:+.5f}R/trade"
            if (interval, label) in funding_values
            else "no funding estimate (cell did not reach KEEP)"
        )
        paragraphs.append(
            f"{interval}/{label}: best five contribute "
            f"{fmt(detail['best5_share']*100,1)}% of net R; without them "
            f"{detail['without5_mean']:+.4f}R/trade. Long versus short headline "
            f"R/trade is {side_values['long']:+.4f} versus "
            f"{side_values['short']:+.4f}. Native versus forced-1:3 headline "
            f"R/trade is {res['pooled'][(interval,'native')]['expectancy_post_fee_r']:+.4f} "
            f"versus {res['pooled'][(interval,'forced-1:3')]['expectancy_post_fee_r']:+.4f}; "
            f"{shared_text}. Sensitivity variants KEEP in {sweeps_keep}/5; "
            f"{funding_text}."
        )
    handful = [
        f"{interval}/{label}" for (interval, label), detail in details.items()
        if detail["best5_share"] >= 0.5 or detail["without5_total"] <= 0
    ]
    if handful:
        paragraphs.append(
            "A qualifying cell whose result is concentrated in a handful of trades "
            "by the printed best-five check is: " + ", ".join(handful) + "."
        )
    else:
        paragraphs.append(
            "No qualifying cell has a best-five share of at least 50% or a "
            "non-positive total after removing its best five trades."
        )
    return "\n\n".join(paragraphs)


def build_report(
    res: dict,
    summary: dict,
    cov: dict,
    audits: dict,
    rec: list[dict],
    final_notes: list[str],
    sensitivities: list[dict],
    csv_paths: list[tuple[Path, int]],
    shared_stats: dict,
    funding_values: dict,
    detail_text: str,
    details: dict,
) -> str:
    all_reconciled = all(row["reconciles"] for row in rec)
    audit_passes = sum(ok for ok, _, _ in audits.values())
    audit_rows = "\n".join(
        f"| {name} | {len(cols)} | {'PASS' if ok else 'FAIL'} | "
        f"{'none' if ok else '; '.join(problems[:3])} |"
        for name, (ok, cols, problems) in audits.items()
    )
    rec_rows = "\n".join(
        f"| {row['coin']} | {row['timeframe']} | {row['exit']} | "
        f"{row['signals']} | {row['taken']} | {row['blocked_open']} | "
        f"{row['last_bar']} | {row['zero_risk']} | {row['open_end']} | "
        f"{row['other']} | {'PASS' if row['reconciles'] else 'FAIL'} |"
        for row in rec
    )
    source_rows = []
    for filename in ("s16_roc_momentum.py", "run_s16.py"):
        content = (ROOT / "src" / filename).read_bytes()
        line_count = len(content.decode("utf-8").splitlines())
        source_rows.append(
            f"| src/{filename} | {line_count} | "
            f"{hashlib.sha256(content).hexdigest()} |"
        )
    csv_rows = "\n".join(
        f"| {path.relative_to(ROOT)} | {count} |" for path, count in csv_paths
    )
    for path, expected_rows in csv_paths:
        actual_rows = len(pd.read_csv(path))
        if actual_rows != expected_rows:
            raise RuntimeError(
                f"Trade CSV row count changed for {path}: "
                f"{actual_rows} != {expected_rows}."
            )
    recon_total = sum(row["signals"] for row in rec)
    bucket_total = sum(
        row["taken"] + row["blocked_open"] + row["last_bar"]
        + row["zero_risk"] + row["open_end"] + row["other"]
        for row in rec
    )
    return "\n\n".join([
        "## 1. Rule and source\n\n"
        "**Departures from the spec: none. Engine conventions that can alter a trade:** "
        "closed-bar ROC entries and native exits fill at the next bar's open; the "
        "signal-time 2×ATR distance is carried using `stop_frac`, so an entry gap "
        "scales the stop distance by fill/signal-close; same-bar stop ties go to the "
        "stop, gap-through stops fill at the bar open, open trades at data end are "
        "discarded, and one position per coin/timeframe is allowed. Taker fees are "
        "0.055% per side; funding is not modeled.\n\n"
        "ROC is (close / close 20 bars earlier − 1) × 100. Enter long on the closed "
        "bar when ROC crosses from at/below zero to above zero; enter short when it "
        "crosses from at/above zero to below zero. Entries fill at the next open. "
        "The native exit is the opposite zero cross, also filled at the next open. "
        "Initial stop is 2×ATR(20); no target. The comparison exit is shared forced "
        "1:3 with the fixed 30-bar limit.\n\n"
        'Spec source sentence, verbatim: "ROC=(close/close[n]-1)×100; source '
        'literature does not settle universal entries/stops." The spec makes no '
        "performance claim.",
        "## 2. Placeholders and adaptations declared plainly\n\n"
        "1. ROC uses the close at t divided by the close exactly 20 bars earlier, "
        "minus one, multiplied by 100. No trend filter, smoothing, or second "
        "momentum indicator is applied.\n"
        "2. ATR uses standard True Range and Wilder-style recursive smoothing "
        "(alpha 1/20, adjust=False); its first 20 values are blanked. The spec pins "
        "ATR(20) but does not specify smoothing or seed convention.\n"
        "3. Equality convention: long entry is prior ROC <= 0 and current ROC > 0; "
        "short entry is prior ROC >= 0 and current ROC < 0. Long native exit is "
        "prior ROC > 0 and current ROC <= 0; short exit is prior ROC < 0 and "
        "current ROC >= 0. A zero denominator close is invalid and produces no ROC "
        "signal.\n"
        "4. ATR is frozen at the signal bar. Because the engine resolves risk from "
        "the next-open fill, stop_frac = 2×ATR(signal)/close(signal); the realized "
        "distance is scaled by fill/signal-close if those prices differ.\n"
        "5. Project defaults: 250-bar warmup; headline ROC period 20 and stop 2×ATR; "
        "1H, 4H, 1D only. Forced comparison time limit is 30 bars.",
        "## 3. Fresh lookahead-bias audit\n\n"
        f"Fresh cut-and-recompute audit passed {audit_passes}/{len(audits)} "
        f"coin/timeframe datasets (25 cuts each; "
        f"{sum(len(value[1]) for value in audits.values())} derived columns checked).\n\n"
        "No trade is selected, skipped, or changed using information from the same "
        "bar's later outcome. ROC uses only close t and close t−n; signals compare "
        "current and previous ROC on closed bars; entries fill next open. Intrabar "
        "high/low are used only by the engine to evaluate an already-set stop or "
        "target. The initial ATR is frozen at signal time.\n\n"
        "| Dataset | Derived columns | Audit | Mismatches |\n"
        "|---|---:|---|---|\n" + audit_rows
        + "\n\nThe existing cache is dated 2026-09-04; no data was downloaded. "
        "The partial 1H final bar opening 2026-09-05 00:00 UTC and partial 6H "
        "bar opening 2026-09-05 12:00 UTC remain in their cache files because "
        "the clock-based forming-bar drop does not remove these historical bars. "
        "The tested matrix excludes 6H. Final-bar impact by tested dataset:\n\n"
        + "\n".join(final_notes),
        "## 4. Results and signal reconciliation\n\n"
        + results_table(res, cov, summary)
        + "\n\nHistory days are the tradeable window after 250 warmup bars. "
        + coverage.summary_line(cov, runner.COINS, IVS)
        + "\n\nPer-cell accounting distinguishes all generated valid entry signals: "
        "taken entries that closed, blocked because a position remained open at the "
        "signal decision, final-bar signals with no next-open fill, zero-risk skips, "
        "accepted positions still open and discarded at data end, and other. The "
        "position-open label does not imply an outcome for a blocked signal.\n\n"
        "| Coin | Timeframe | Exit | Signals generated | Taken and completed | "
        "Blocked: position open | Last-bar/no next open | Zero-risk | "
        "Open at data end/discarded | Other | Adds up? |\n"
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|\n"
        + rec_rows
        + f"\n\nReconciliation {'PASSES' if all_reconciled else 'FAILS'}: "
        f"{recon_total} signals, {bucket_total} assigned to exactly one category.",
        "## 5. t-statistics and per-coin results\n\n" + tstat_coin_table(res),
        "## 6. Concentration check (both exits)\n\n" + concentration_table(res)
        + "\n\nShares are meaningful only when total post-fee R is positive; otherwise "
        "they are shown as n/a. Trades are ranked by their post-fee R.",
        "## 7. Long/short breakdown (both exits)\n\n" + side_table(res),
        "## 8. Exit-death check\n\n"
        + exit_death_section(res)[0]
        + "\n\n### 8a. Re-entry clustering after stop-outs (saved CSVs)\n\n"
        + reentry_section(csv_paths)
        + "\n\n### 8b. Exit-reason split and mean post-fee R (saved CSVs)\n\n"
        + reason_section(csv_paths),
        "## 9. Funding disclosure\n\n" + funding_section(res, summary),
        "## 10. Parameter sensitivity sweep\n\n" + sensitivity_section(sensitivities),
        "## 11. Market-condition breakdown\n\n" + regime_section(res),
        "## 12. Source comparison and discrepancies\n\n" + source_section(res, summary),
        "## 13. Fixed discard-bar verdict per cell\n\n"
        "The approved fixed bar is applied after fees:\n\n```\n"
        + describe() + "\n```\n\n" + verdict_section(res, summary),
        "## 14. Bottom line\n\n"
        + bottom_line(
            res, summary, sensitivities, details, shared_stats,
            funding_values, cov,
        ),
        "## 14a. Concentration and stability detail (from the saved trade CSVs)\n\n"
        + detail_text,
        "## 15. Files created\n\n"
        "Dry run only: no strategy logs were changed; no git add, commit, or push "
        "was run. Source file hashes are computed from their final UTF-8 bytes.\n\n"
        "| New source file | Lines | SHA-256 |\n|---|---:|---|\n"
        + "\n".join(source_rows)
        + "\n\n| Trade-list file | Completed trade rows |\n|---|---:|\n"
        + csv_rows
        + "\n\nFinal report path: `C:\\Users\\MarketCoder\\Desktop\\s16_report_final.txt`.",
    ])


def main() -> None:
    missing = [
        runner.bd.DATA_DIR / f"{coin}_{interval}.parquet"
        for coin in runner.COINS for interval in IVS
        if not (runner.bd.DATA_DIR / f"{coin}_{interval}.parquet").is_file()
    ]
    if missing:
        raise FileNotFoundError(
            "Required cache files are missing; refusing loader fallback/download: "
            + ", ".join(str(path) for path in missing)
        )
    if REPORT_PATH.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing requested report: {REPORT_PATH}"
        )
    spec = make_spec()
    headline = runner.run(spec, runner.COINS, IVS, audit=True)
    summary = runner.summarise(spec, headline, IVS)
    cov = coverage.collect(runner.COINS, IVS, spec.warmup_for)
    rec = reconcile(spec, headline)
    if not all(ok for ok, _, _ in headline["audit"].values()):
        raise RuntimeError("Fresh headline lookahead audit failed.")
    if not all(row["reconciles"] for row in rec):
        raise RuntimeError("At least one headline reconciliation cell failed.")
    finals = final_bar_notes(spec, headline)
    sensitivities = sensitivity_results(headline)
    csv_paths = write_trade_lists(headline)

    _, shared_stats = exit_death_section(headline)
    funding_values = {}
    for interval in IVS:
        for label in EXITS:
            key = "verdict_native" if label == "native" else "verdict_forced"
            if summary[interval][key] == "KEEP":
                m = headline["pooled"][(interval, label)]
                trades = headline["trades"][(interval, label)]
                stop_frac = float(np.median([
                    abs(t.entry_price-t.initial_stop)/t.entry_price for t in trades
                ]))
                settlements = (
                    m["avg_bars_held"]*HOURS_PER_BAR[interval]/SETTLEMENT_HOURS
                )
                funding_values[(interval,label)] = (
                    settlements*BASE_FUNDING_RATE/stop_frac
                )
    detail_text, details = concentration_detail(
        headline, csv_paths, sensitivities, shared_stats, funding_values
    )
    report = build_report(
        headline, summary, cov, headline["audit"], rec, finals,
        sensitivities, csv_paths, shared_stats, funding_values,
        detail_text, details,
    )
    REPORT_PATH.write_text(report + "\n", encoding="utf-8", newline="\n")

    all_reconciled = all(row["reconciles"] for row in rec)
    print(
        f"REPORT_WRITTEN={REPORT_PATH}\n"
        f"AUDITS={sum(ok for ok, _, _ in headline['audit'].values())}/"
        f"{len(headline['audit'])}\n"
        f"RECONCILIATION={'PASS' if all_reconciled else 'FAIL'}\n"
        f"TRADE_LISTS={len(csv_paths)}"
    )


if __name__ == "__main__":
    main()
