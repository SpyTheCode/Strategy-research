from __future__ import annotations

import hashlib
import itertools
from pathlib import Path

import numpy as np
import pandas as pd

import runner as shared_runner
import s17r_dmi_adx as s17r
from discard_bar import BAR, breakeven_win_rate, describe, exit_death, verdict
from harness import Signal, Trade, forced_13_exit

NAME = "#17 DMI/ADX"
COINS = ["BTCUSDT", "SOLUSDT", "XRPUSDT"]
INTERVALS = ["1H", "4H", "1D"]
EXITS = ("native", "forced-1:3")
PERIODS = (10, 14, 20)
ADX_THRESHOLDS = (20, 25, 30)
STOP_MULTIPLES = (1.5, 2.0, 2.5)
FORCED_LIMIT = 30
ROOT = Path(__file__).resolve().parent.parent
TRADE_DIR = ROOT / "trade_lists" / "s17r"
REPORT_PATH = Path(r"C:\Users\MarketCoder\Desktop\s17r_report.txt")
SOURCE_LINE = (
    "**Source:** J. Welles Wilder Jr., *New Concepts in Technical Trading Systems* "
    "(1978), Directional Movement System. Buy +DI crossing above \u2212DI with ADX>25; "
    "short opposite cross with ADX>25; native exit on opposite DI cross. No TP. "
    "Stop 2\u00d7ATR(14), project placeholder."
)
CSV_COLUMNS = [
    "coin", "timeframe", "exit_variant", "direction", "entry_time",
    "entry_price", "exit_time", "exit_price", "exit_reason", "bars_held",
    "initial_stop", "R pre-fee", "R post-fee", "regime",
]


def fmt(value, digits: int = 2) -> str:
    try:
        if value is None or not np.isfinite(value):
            return "n/a"
    except TypeError:
        return "n/a"
    return f"{value:.{digits}f}"


def make_spec(period: int = 14, adx_threshold: float = 25.0, stop_atr: float = 2.0):
    return shared_runner.StrategySpec(
        name=f"{NAME} [period={period}, ADX>{adx_threshold:g}, stop={stop_atr:g} ATR]",
        add_indicators=lambda df: s17r.add_indicators(
            df, period=period, adx_threshold=adx_threshold, stop_atr=stop_atr
        ),
        entry=s17r.entry,
        native_exit=s17r.native_exit,
        warmup=s17r.warmup_for(period),
        native_time_limit=None,
    )


def write_trade_lists(res: dict, period: int, threshold: float, stop_atr: float):
    paths = []
    tag_stop = f"{stop_atr:g}".replace(".", "p")
    tag_threshold = f"{threshold:g}".replace(".", "p")
    for coin in COINS:
        for interval in INTERVALS:
            for label in EXITS:
                trades = sorted(
                    res["trades"][(coin, interval, label)], key=lambda trade: trade.entry_time
                )
                rows = [{
                    "coin": coin,
                    "timeframe": interval,
                    "exit_variant": label,
                    "direction": "long" if trade.direction > 0 else "short",
                    "entry_time": pd.Timestamp(trade.entry_time).strftime("%Y-%m-%d %H:%M:%S%z"),
                    "entry_price": trade.entry_price,
                    "exit_time": pd.Timestamp(trade.exit_time).strftime("%Y-%m-%d %H:%M:%S%z"),
                    "exit_price": trade.exit_price,
                    "exit_reason": trade.exit_reason,
                    "bars_held": trade.bars_held,
                    "initial_stop": trade.initial_stop,
                    "R pre-fee": trade.gross_r,
                    "R post-fee": trade.net_r,
                    "regime": trade.regime,
                } for trade in trades]
                exit_tag = "forced13" if label == "forced-1:3" else "native"
                output = TRADE_DIR / (
                    f"s17r_p{period}_a{tag_threshold}_s{tag_stop}_"
                    f"{coin}_{interval}_{exit_tag}.csv"
                )
                pd.DataFrame(rows, columns=CSV_COLUMNS).to_csv(
                    output, index=False, encoding="utf-8", lineterminator="\n"
                )
                paths.append((output, len(rows)))
    return paths


def reconcile_one(df, spec, label: str, completed_trades: list[Trade]) -> dict:
    times = pd.DatetimeIndex(df["open_time"])
    entry_fn = spec.entry(df)
    exit_fn = spec.native_exit(df) if label == "native" else forced_13_exit
    completed_keys = {
        (trade.direction, pd.Timestamp(trade.entry_time)) for trade in completed_trades
    }
    pending_entry: Signal | None = None
    pending_key = None
    pending_exit_reason = None
    position: Trade | None = None
    accepted = set()
    mirror_completed = set()
    counts = {
        "signals": 0, "taken": 0, "blocked_open": 0, "last_bar": 0,
        "zero_risk": 0, "open_end": 0, "other": 0,
    }
    time_limit = FORCED_LIMIT if label == "forced-1:3" else None
    signals = [entry_fn(df, i) for i in range(len(df))]

    for i in range(spec.warmup, len(df)):
        row = df.iloc[i]
        if position is not None and pending_exit_reason is not None:
            mirror_completed.add((position.direction, pd.Timestamp(position.entry_time)))
            position = None
            pending_exit_reason = None
        if position is None and pending_entry is not None:
            fill = float(row["open"])
            stop = pending_entry.resolve_stop(fill)
            if stop != fill:
                position = Trade(
                    direction=pending_entry.direction, entry_time=times[i],
                    entry_price=fill, initial_stop=stop,
                    regime=str(row.get("regime", "")),
                )
                if pending_key is None:
                    raise RuntimeError("Queued signal has no fill timestamp.")
                accepted.add(pending_key)
            else:
                counts["zero_risk"] += 1
            pending_entry, pending_key = None, None
        if position is not None:
            plan = exit_fn(df, i, position)
            hit_stop = plan.stop_level is not None and (
                row["low"] <= plan.stop_level if position.direction > 0
                else row["high"] >= plan.stop_level
            )
            hit_target = plan.target_level is not None and (
                row["high"] >= plan.target_level if position.direction > 0
                else row["low"] <= plan.target_level
            )
            if hit_stop or hit_target:
                mirror_completed.add((position.direction, pd.Timestamp(position.entry_time)))
                position = None
            else:
                if time_limit is not None:
                    position.bars_held += 1
                    if position.bars_held >= time_limit:
                        pending_exit_reason = "time"
                if pending_exit_reason is None and plan.close_exit:
                    pending_exit_reason = plan.reason or "signal"
        signal = signals[i]
        if signal is None:
            continue
        counts["signals"] += 1
        if i + 1 >= len(df):
            counts["last_bar"] += 1
        elif signal.stop_frac is not None and signal.stop_frac <= 0:
            counts["zero_risk"] += 1
        elif pending_entry is None and (position is None or pending_exit_reason is not None):
            pending_entry = signal
            pending_key = (signal.direction, times[i + 1])
        else:
            counts["blocked_open"] += 1

    open_keys = (
        {(position.direction, pd.Timestamp(position.entry_time))}
        if position is not None else set()
    )
    counts["taken"] = len(accepted & completed_keys)
    counts["open_end"] = len(accepted & open_keys)
    counts["other"] = len(accepted - completed_keys - open_keys)
    buckets = sum(counts[key] for key in (
        "taken", "blocked_open", "last_bar", "zero_risk", "open_end", "other"
    ))
    return {
        **counts,
        "reconciles": buckets == counts["signals"] and completed_keys == mirror_completed,
    }


def reconcile(spec, res):
    rows = []
    for coin in COINS:
        for interval in INTERVALS:
            df = shared_runner._prepare(spec, coin, interval)
            for label in EXITS:
                counts = reconcile_one(
                    df, spec, label, res["trades"][(coin, interval, label)]
                )
                rows.append({"coin": coin, "timeframe": interval, "exit": label, **counts})
    failed = [row for row in rows if not row["reconciles"]]
    if failed:
        raise RuntimeError(f"Signal reconciliation failed: {failed}")
    return rows


def coverage_rows(spec):
    rows = []
    for coin in COINS:
        for interval in INTERVALS:
            df = shared_runner._prepare(spec, coin, interval)
            start = pd.Timestamp(df["open_time"].iloc[0])
            end = pd.Timestamp(df["open_time"].iloc[-1])
            rows.append({
                "coin": coin, "timeframe": interval, "bars": len(df),
                "warmup": spec.warmup,
                "tradeable_bars": max(0, len(df) - spec.warmup),
                "start": start, "end": end,
                "days": (end - start).total_seconds() / 86400.0,
            })
    return rows



def result_table(res):
    lines = [
        "| Timeframe | Exit | Trades | Win% | RR | R pre-fee | R post-fee | R/trade | Sharpe | Max DD % | Max DD R | R-recovery | Fee cost/trade | Verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for interval in INTERVALS:
        for label in EXITS:
            m = res["pooled"][(interval, label)]
            verdict_text, _ = verdict(m, label)
            lines.append(
                f"| {interval} | {label} | {m['trades']} | {fmt(100*m['win_rate'],1)} | "
                f"{fmt(m['rr_achieved'])} | {fmt(m['r_sum_pre_fee'],2)} | "
                f"{fmt(m['r_sum_post_fee'],2)} | {fmt(m['expectancy_post_fee_r'],4)} | "
                f"{fmt(m['sharpe_post_fee'])} | {fmt(m['max_drawdown_pct'],2)} | "
                f"{fmt(m['max_drawdown_r'],2)} | {fmt(m['r_recovery'])} | "
                f"{fmt(m['avg_fee_cost_r'],4)} | **{verdict_text}** |"
            )
    return "\n".join(lines)


def per_coin_table(res):
    lines = [
        "| Coin | Timeframe | Exit | Trades | Win% | R pre-fee | R post-fee | R/trade | Sharpe | Verdict |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for coin in COINS:
        for interval in INTERVALS:
            for label in EXITS:
                m = res["per_cell"][(coin, interval, label)]
                verdict_text, _ = verdict(m, label)
                lines.append(
                    f"| {coin} | {interval} | {label} | {m['trades']} | "
                    f"{fmt(100*m['win_rate'],1)} | {fmt(m['r_sum_pre_fee'],2)} | "
                    f"{fmt(m['r_sum_post_fee'],2)} | {fmt(m['expectancy_post_fee_r'],4)} | "
                    f"{fmt(m['sharpe_post_fee'])} | {verdict_text} |"
                )
    return "\n".join(lines)


def reconciliation_table(rows):
    lines = [
        "| Coin | Timeframe | Exit | Signals | Taken/completed | Blocked/open | Last bar | Zero risk | Open at end/discarded | Other | Reconciles? |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['coin']} | {row['timeframe']} | {row['exit']} | {row['signals']} | "
            f"{row['taken']} | {row['blocked_open']} | {row['last_bar']} | "
            f"{row['zero_risk']} | {row['open_end']} | {row['other']} | "
            f"{'PASS' if row['reconciles'] else 'FAIL'} |"
        )
    return "\n".join(lines)


def coverage_table(rows):
    lines = [
        "| Coin | Timeframe | Bars | Warmup | Tradeable bars | First open UTC | Last open UTC | Calendar days |",
        "|---|---|---:|---:|---:|---|---|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['coin']} | {row['timeframe']} | {row['bars']} | {row['warmup']} | "
            f"{row['tradeable_bars']} | {row['start']:%Y-%m-%d %H:%M} | "
            f"{row['end']:%Y-%m-%d %H:%M} | {row['days']:.1f} |"
        )
    return "\n".join(lines)


def audit_table(audit):
    lines = ["| Dataset | Derived columns | Audit | Mismatches |", "|---|---:|---|---|"]
    for key, (passed, columns, problems) in audit.items():
        lines.append(
            f"| {key} | {len(columns)} | {'PASS' if passed else 'FAIL'} | "
            f"{'none' if not problems else '; '.join(map(str, problems[:3]))} |"
        )
    return "\n".join(lines)


def exit_composition(res):
    lines = [
        "| Timeframe | Exit | Exit reason | Trades | Mean post-fee R | Total post-fee R |",
        "|---|---|---|---:|---:|---:|",
    ]
    for interval in INTERVALS:
        for label in EXITS:
            trades = res["trades"][(interval, label)]
            reasons = sorted({trade.exit_reason for trade in trades})
            if not reasons:
                lines.append(f"| {interval} | {label} | none | 0 | n/a | n/a |")
            for reason in reasons:
                selected = [trade for trade in trades if trade.exit_reason == reason]
                values = np.array([trade.net_r for trade in selected], dtype=float)
                lines.append(
                    f"| {interval} | {label} | {reason} | {len(selected)} | "
                    f"{fmt(float(values.mean()),4)} | {fmt(float(values.sum()),2)} |"
                )
    return "\n".join(lines)


def side_table(res):
    lines = [
        "| Timeframe | Exit | Side | Trades | Win% | Total post-fee R | R/trade |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for interval in INTERVALS:
        for label in EXITS:
            trades = res["trades"][(interval, label)]
            for side, direction in (("long", 1), ("short", -1)):
                values = np.array([t.net_r for t in trades if t.direction == direction])
                lines.append(
                    f"| {interval} | {label} | {side} | {len(values)} | "
                    f"{fmt(float(np.mean(values > 0))*100,1) if len(values) else 'n/a'} | "
                    f"{fmt(float(values.sum()),2) if len(values) else 'n/a'} | "
                    f"{fmt(float(values.mean()),4) if len(values) else 'n/a'} |"
                )
    return "\n".join(lines)


def context_table(res):
    lines = [
        "| Timeframe | Exit | Regime | Trades | Post-fee R | R/trade |",
        "|---|---|---|---:|---:|---:|",
    ]
    for interval in INTERVALS:
        for label in EXITS:
            trades = res["trades"][(interval, label)]
            regimes = sorted({trade.regime or "unknown" for trade in trades})
            if not regimes:
                lines.append(f"| {interval} | {label} | none | 0 | n/a | n/a |")
            for regime in regimes:
                selected = [t for t in trades if (t.regime or "unknown") == regime]
                values = np.array([t.net_r for t in selected])
                lines.append(
                    f"| {interval} | {label} | {regime} | {len(values)} | "
                    f"{fmt(float(values.sum()),2)} | {fmt(float(values.mean()),4)} |"
                )
    return "\n".join(lines)


def exit_death_table(res):
    lines = [
        "| Timeframe | Native trades | Forced trades | Native R/trade | Forced R/trade | Exit-death flag | Diagnostic |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for interval in INTERVALS:
        native = res["pooled"][(interval, "native")]
        forced = res["pooled"][(interval, "forced-1:3")]
        flag, diagnostic = exit_death(native, forced)
        lines.append(
            f"| {interval} | {native['trades']} | {forced['trades']} | "
            f"{fmt(native['expectancy_post_fee_r'],4)} | "
            f"{fmt(forced['expectancy_post_fee_r'],4)} | {flag} | {diagnostic} |"
        )
    return "\n".join(lines)


def verdict_table(res):
    lines = [
        "| Timeframe | Exit | Trades >=30 | Expectancy >=0.10 | Sharpe >=0.70 | Recovery >=1.5 | Reward test | Discard conditions | Verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for interval in INTERVALS:
        for label in EXITS:
            m = res["pooled"][(interval, label)]
            v, _ = verdict(m, label)
            if label == "forced-1:3":
                required = breakeven_win_rate(m["avg_fee_cost_r"]) + BAR.keep_win_margin
                reward = f"win {fmt(100*m['win_rate'],1)}% {'PASS' if m['win_rate'] >= required else 'FAIL'}; need {required:.1%}"
            else:
                reward = f"RR {fmt(m['rr_achieved'])} {'PASS' if m['rr_achieved'] >= BAR.keep_rr_native else 'FAIL'}; need {BAR.keep_rr_native:.2f}"
            exp, sharpe, recovery = (
                m["expectancy_post_fee_r"], m["sharpe_post_fee"], m["r_recovery"]
            )
            discard = (
                f"exp<=0 {'yes' if exp <= 0 else 'no'}; "
                f"Sharpe<{BAR.discard_sharpe:.2f} {'yes' if sharpe < BAR.discard_sharpe else 'no'}; "
                f"recovery<{BAR.discard_r_recovery:.2f} {'yes' if recovery < BAR.discard_r_recovery else 'no'}"
            )
            lines.append(
                f"| {interval} | {label} | {m['trades'] >= BAR.min_trades} ({m['trades']}) | "
                f"{exp >= BAR.keep_expectancy_r} ({fmt(exp,4)}) | "
                f"{sharpe >= BAR.keep_sharpe} ({fmt(sharpe)}) | "
                f"{recovery >= BAR.keep_r_recovery} ({fmt(recovery)}) | {reward} | "
                f"{discard} | {v} |"
            )
    return "\n".join(lines)



def sweep(headline):
    rows = []
    variant_keep = {}
    written = []
    for period, threshold, stop_atr in itertools.product(PERIODS, ADX_THRESHOLDS, STOP_MULTIPLES):
        is_headline = (period, threshold, stop_atr) == (14, 25, 2.0)
        result = headline if is_headline else shared_runner.run(
            make_spec(period, threshold, stop_atr), COINS, INTERVALS, audit=False
        )
        written.extend(write_trade_lists(result, period, threshold, stop_atr))
        label = f"period={period}, ADX>{threshold:g}, stop={stop_atr:g} ATR"
        variant_keep[label] = False
        for interval in INTERVALS:
            for exit_label in EXITS:
                m = result["pooled"][(interval, exit_label)]
                verdict_text, _ = verdict(m, exit_label)
                variant_keep[label] = variant_keep[label] or verdict_text == "KEEP"
                rows.append({
                    "variant": label, "headline": is_headline,
                    "timeframe": interval, "exit": exit_label,
                    "trades": m["trades"], "win": m["win_rate"],
                    "total_r": m["r_sum_post_fee"],
                    "r_trade": m["expectancy_post_fee_r"],
                    "sharpe": m["sharpe_post_fee"], "verdict": verdict_text,
                })
    return rows, variant_keep, written


def sensitivity_table(rows, variant_keep):
    lines = [
        "| Variant | Timeframe | Exit | Trades | Win% | Post-fee total R | R/trade | Sharpe | Verdict |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        mark = " (headline reference)" if row["headline"] else ""
        lines.append(
            f"| {row['variant']}{mark} | {row['timeframe']} | {row['exit']} | "
            f"{row['trades']} | {fmt(100*row['win'],1)} | {fmt(row['total_r'],2)} | "
            f"{fmt(row['r_trade'],4)} | {fmt(row['sharpe'])} | {row['verdict']} |"
        )
    non_headline = [row for row in rows if not row["headline"]]
    count = len(variant_keep) - 1
    kept_variants = sum(
        flag for key, flag in variant_keep.items()
        if key != "period=14, ADX>25, stop=2 ATR"
    )
    kept_cells = sum(row["verdict"] == "KEEP" for row in non_headline)
    lines.extend([
        "",
        f"There are {count} non-headline variants (3 periods ? 3 thresholds ? 3 stop multiples = 27 total combinations, including the headline). "
        f"{kept_variants}/{count} non-headline variants have at least one KEEP; "
        f"{kept_cells}/{len(non_headline)} non-headline pooled timeframe/exit cells are KEEP.",
        "The headline is a reference row only; the sweep does not select or replace it.",
    ])
    return "\n".join(lines), count, kept_variants, kept_cells


def native_holding_table(res, reconciliation):
    lines = [
        "| Timeframe | Mean bars | Median bars | Maximum bars | Exit reason | Trades | Mean post-fee R | Signals blocked while open |",
        "|---|---:|---:|---:|---|---:|---:|---:|",
    ]
    for interval in INTERVALS:
        trades = res["trades"][(interval, "native")]
        bars = np.array([trade.bars_held for trade in trades], dtype=float)
        blocked = sum(
            row["blocked_open"] for row in reconciliation
            if row["timeframe"] == interval and row["exit"] == "native"
        )
        if not trades:
            lines.append(f"| {interval} | n/a | n/a | n/a | none | 0 | n/a | {blocked} |")
            continue
        reasons = sorted({trade.exit_reason for trade in trades})
        for index, reason in enumerate(reasons):
            selected = [trade for trade in trades if trade.exit_reason == reason]
            values = np.array([trade.net_r for trade in selected], dtype=float)
            avg_bars = fmt(float(np.mean(bars)), 2) if index == 0 else ""
            median_bars = fmt(float(np.median(bars)), 2) if index == 0 else ""
            max_bars = str(int(np.max(bars))) if index == 0 else ""
            blocked_text = str(blocked) if index == 0 else ""
            lines.append(
                f"| {interval} | {avg_bars} | {median_bars} | {max_bars} | {reason} | "
                f"{len(selected)} | {fmt(float(values.mean()),4)} | {blocked_text} |"
            )
    return "\n".join(lines)


def write_report(headline, audit, coverage, rec, sweep_rows, variant_keep, all_paths):
    passed = sum(bool(value[0]) for value in audit.values())
    checked = sum(len(value[1]) for value in audit.values())
    signal_total = sum(row["signals"] for row in rec)
    bucket_total = sum(
        row[key] for row in rec
        for key in ("taken", "blocked_open", "last_bar", "zero_risk", "open_end", "other")
    )
    row_sum = 0
    for csv_path, expected in all_paths:
        actual = len(pd.read_csv(csv_path, encoding="utf-8"))
        if actual != expected:
            raise RuntimeError(
                f"Trade-list row count mismatch: {csv_path} has {actual}, expected {expected}."
            )
        row_sum += actual

    strategy_text = Path(s17r.__file__).read_text(encoding="utf-8")
    runner_text = Path(__file__).read_text(encoding="utf-8")
    strategy_hash = hashlib.sha256(strategy_text.encode("utf-8")).hexdigest()
    runner_hash = hashlib.sha256(runner_text.encode("utf-8")).hexdigest()
    summary = "; ".join(
        f"{interval}/{label}: {headline['pooled'][(interval,label)]['trades']} trades, "
        f"{headline['pooled'][(interval,label)]['expectancy_post_fee_r']:+.4f}R/trade, "
        f"Sharpe {fmt(headline['pooled'][(interval,label)]['sharpe_post_fee'])}, "
        f"{verdict(headline['pooled'][(interval,label)], label)[0]}"
        for interval in INTERVALS for label in EXITS
    )
    ambiguity = "\n".join([
        "Ambiguities and choices, using the most literal reading of the spec:",
        "- Wilder seed: TR[0] is high?low and +DM[0]/?DM[0] are zero because no prior bar exists; TR and each DM series seed with the simple mean of the first n bars, then Wilder recursion.",
        "- ADX nesting: DX uses smoothed +DI/?DI; when their sum is zero DX is defined as 0. ADX seeds from the first n consecutive defined DX values with a simple mean, then Wilder recursion; no backfill. Headline first valid ADX is bar 2n?2 when data has nonzero TR.",
        "- The swept period applies to TR/+DM/?DM smoothing, ADX smoothing, and the ATR stop; only the ADX threshold and stop multiple vary separately across their specified grids.",
        "- Crosses use strict current-side superiority with prior equality allowed; entry also requires current ADX strictly > threshold. Native exits use the opposite DI cross without an ADX filter.",
        "- The ATR stop fraction is fixed from signal-bar ATR / signal-bar close and resolved at next-open fill through shared Signal.stop_frac; a price gap therefore scales the stop distance with fill.",
        "- A qualifying opposite entry on a native exit signal may reverse at the same next open under shared simulate; without ADX qualification the position only exits. Other signals while the position remains open are blocked.",
        "- Warmup is 3?period+50 bars. Signals form on closed bars and fill next open; ties go to the stop; gap-through stops fill at open; end-open trades are discarded. One position per coin/timeframe; coins pool only within timeframe.",
        "- Fixed setup: taker fee 0.055% per side; funding not modeled; forced stop 1R / target 3R / 30-bar limit; standard simulate path.",
    ])
    sensitivity_text, sweep_variant_count, sweep_kept_variants, sweep_kept_cells = (
        sensitivity_table(sweep_rows, variant_keep)
    )
    sections = [
        "## 1. Source and rule\n\n" + SOURCE_LINE + "\n\n" + ambiguity,
        "## 2. Wilder arithmetic\n\n"
        "For each bar, +DM is current high minus prior high only when positive and greater than the downward move; ?DM is prior low minus current low only when positive and greater than the upward move; ties set both DM values to zero. TR is max(high?low, |high?prior close|, |low?prior close|). Wilder-smoothed values seed from the simple mean of the first n observations and update recursively. DI is 100?smoothed DM / smoothed TR. DX is 100?|+DI??DI|/(+DI+?DI); ADX is its Wilder average. ATR for the stop is the corresponding Wilder average of TR. The implementation exposes +DI, ?DI, ADX, ATR and signal columns; invalid periods, thresholds or stop multiples raise ValueError.",
        "## 3. Fresh lookahead-bias audit\n\n"
        f"RAN: fresh shared cut-and-recompute audit on the headline indicators for {passed}/{len(audit)} required coin/timeframe datasets; {checked} derived-column checks total. A failed audit aborts before report creation.\n\n" + audit_table(audit),
        "## 4. Coverage and signal reconciliation\n\n" + coverage_table(coverage)
        + "\n\nHistory after the per-period warmup; open-ended trades are discarded. Each generated valid signal is categorized exactly once per exit path.\n\n"
        + reconciliation_table(rec)
        + f"\n\nReconciliation: {'PASSES' if all(row['reconciles'] for row in rec) else 'FAILS'}; {signal_total} signals assigned to {bucket_total} buckets.",
        "## 5. Pooled results\n\n" + result_table(headline),
        "## 6. Exit composition\n\n" + exit_composition(headline),
        "## 7. Direction split\n\n" + side_table(headline),
        "## 8. Exit-death check\n\n"
        "The shared fixed diagnostic compares headline native and forced-1:3 outcomes per timeframe; it is descriptive and does not alter either verdict.\n\n" + exit_death_table(headline),
        "## 9. Per-coin results\n\n" + per_coin_table(headline),
        "## 10. Market context\n\n"
        "Regime labels are carried by the shared runner for description only; they do not affect signals or execution.\n\n" + context_table(headline),
        "## 11. Fixed discard-bar verdict\n\nThe project fixed bar is applied after fees; verdicts are from the shared discard_bar implementation.\n\n````\n" + describe() + "\n````\n\n" + verdict_table(headline),
        "## 12. Parameter sensitivity\n\n" + sensitivity_text,
        "## 13. Fees and funding\n\n"
        "RAN: both entry and exit use the 0.055% taker fee through the shared simulator. Funding and slippage are not modeled; no funding-adjusted result is claimed. Post-fee R drives verdicts; Sharpe is from harness.metrics.",
        "## 14. Bottom line (facts only)\n\n" + summary + "\n\n"
        f"The grid has {sweep_variant_count} non-headline variants; "
        f"{sweep_kept_variants}/{sweep_variant_count} non-headline variants have at least one KEEP; "
        f"{sweep_kept_cells}/{(len(PERIODS) * len(ADX_THRESHOLDS) * len(STOP_MULTIPLES) - 1) * len(INTERVALS) * len(EXITS)} non-headline pooled timeframe/exit cells are KEEP. "
        "The sweep is reported as sensitivity, not used to select a replacement headline.",
        "## 14a. Native-exit holding behavior\n\n"
        "Statistics cover completed headline native trades. Blocked signals are the reconciled native stream's signals observed while a position is held.\n\n" + native_holding_table(headline, rec),
        "## 15. Limits and created files\n\n"
        "RAN: headline test, nine lookahead audits, six pooled cells, per-coin/context summaries, signal reconciliation, all 27 parameter combinations, and CSV row-count verification. DID NOT RUN: funding/slippage modeling, alternate/resting-order execution, and external downloads. No engine, spec, log, Opus artifact, tracked file, GitHub, or Git state was changed; no commit, push, stage, or fetch was performed.\n\n"
        f"Trade-list files: {len(all_paths)} (27 combinations ? 3 coins ? 3 timeframes ? 2 exits); completed rows: {row_sum}. Every CSV row count matched its in-memory trade list.\n\n"
        "| New source file | Lines | SHA-256 |\n|---|---:|---|\n"
        f"| src/s17r_dmi_adx.py | {len(strategy_text.splitlines())} | {strategy_hash} |\n"
        f"| src/run_s17r.py | {len(runner_text.splitlines())} | {runner_hash} |\n\n"
        f"Report: {REPORT_PATH}. The report is written only after all preceding checks pass."
    ]
    report = "# Strategy #17 independent DMI/ADX build\n\n" + "\n\n".join(sections) + "\n"
    with REPORT_PATH.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(report)


def main():
    if REPORT_PATH.exists():
        raise FileExistsError(f"Refusing to overwrite existing report: {REPORT_PATH}")
    expected_files = (
        len(PERIODS) * len(ADX_THRESHOLDS) * len(STOP_MULTIPLES)
        * len(COINS) * len(INTERVALS) * len(EXITS)
    )
    if TRADE_DIR.exists():
        if not TRADE_DIR.is_dir():
            raise NotADirectoryError(f"Trade-list output path is not a directory: {TRADE_DIR}")
        existing_files = list(TRADE_DIR.glob("*.csv"))
        if len(existing_files) != expected_files:
            raise FileExistsError(
                f"Refusing to overwrite unexpected trade-list contents: "
                f"{len(existing_files)} CSVs found, expected {expected_files}."
            )
    else:
        TRADE_DIR.mkdir(parents=True, exist_ok=False)
    headline_spec = make_spec()
    headline = shared_runner.run(headline_spec, COINS, INTERVALS, audit=True)
    if len(headline["audit"]) != 9 or not all(value[0] for value in headline["audit"].values()):
        raise RuntimeError("Headline must pass fresh audits for all nine datasets.")
    rec = reconcile(headline_spec, headline)
    coverage = coverage_rows(headline_spec)
    sweep_rows, variant_keep, all_paths = sweep(headline)
    combination_count = len(PERIODS) * len(ADX_THRESHOLDS) * len(STOP_MULTIPLES)
    expected_files = combination_count * len(COINS) * len(INTERVALS) * len(EXITS)
    if len(variant_keep) != combination_count or len(all_paths) != expected_files:
        raise RuntimeError("Sweep or trade-list count did not match the specified parameter matrix.")
    write_report(headline, headline["audit"], coverage, rec, sweep_rows, variant_keep, all_paths)
    print(f"RAN: headline audits 9/9; sweep rows {len(sweep_rows)}; trade-list CSVs {len(all_paths)}; report written.")


if __name__ == "__main__":
    main()
