from __future__ import annotations

import hashlib
import itertools
from pathlib import Path

import numpy as np
import pandas as pd

import context_checks
import coverage
import runner
import s20r_atr_channel as s20r
from discard_bar import BAR, breakeven_win_rate, describe, exit_death, verdict
from harness import Signal, Trade, forced_13_exit, metrics, simulate

NAME = "#20 ATR channel breakout"
COINS = ["BTCUSDT", "SOLUSDT", "XRPUSDT"]
INTERVALS = ["1H", "4H", "1D"]
EXITS = ("native", "forced-1:3")
HOURS_PER_BAR = {"1H": 1.0, "4H": 4.0, "1D": 24.0}
ENTRY_GRID = (10, 20, 55)
EXIT_GRID = (5, 10, 20)
STOP_GRID = (1.5, 2.0, 2.5)
FORCED_LIMIT = 30
ROOT = Path(__file__).resolve().parent.parent
TRADE_DIR = ROOT / "trade_lists" / "s20r"
REPORT_PATH = Path(r"C:\Users\MarketCoder\Desktop\s20r_report.txt")
COMPARE_PATH = Path(r"C:\Users\MarketCoder\Desktop\s20r_compare.txt")
SOURCE_LINE = (
    "**Source:** J. Welles Wilder Jr., *New Concepts in Technical Trading Systems* "
    "(1978), Volatility System / ATR-based stops. Pinned rule adaptation: enter long "
    "when close exceeds prior 20-bar high; short below prior 20-bar low. Initial stop "
    "2×ATR(20); native exit on opposite 10-bar channel. No profit target."
)
CSV_COLUMNS = [
    "coin", "timeframe", "exit_variant", "direction", "entry_time",
    "entry_price", "exit_time", "exit_price", "exit_reason", "bars_held",
    "initial_stop", "R pre-fee", "R post-fee", "regime",
]


def make_spec(entry_period: int = 20, exit_period: int = 10, stop_atr: float = 2.0):
    return runner.StrategySpec(
        name=f"{NAME} [entry={entry_period}, exit={exit_period}, stop={stop_atr:g} ATR]",
        add_indicators=lambda df: s20r.add_indicators(
            df, entry_period=entry_period, exit_period=exit_period, stop_atr=stop_atr
        ),
        entry=s20r.entry,
        native_exit=s20r.native_exit,
        warmup=s20r.WARMUP,
        native_time_limit=None,
    )


def fmt(value, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    try:
        if not np.isfinite(value):
            return "n/a"
    except TypeError:
        return "n/a"
    return f"{value:.{digits}f}"


def cell_keyed_trades(res: dict, interval: str, label: str):
    return [
        (coin, trade)
        for coin in COINS
        for trade in res["trades"][(coin, interval, label)]
    ]


def write_variant_lists(res: dict, entry_period: int, exit_period: int, stop_atr: float):
    paths = []
    stop_tag = f"{stop_atr:g}".replace(".", "p")
    for coin in COINS:
        for interval in INTERVALS:
            for label in EXITS:
                trades = sorted(
                    res["trades"][(coin, interval, label)], key=lambda t: t.entry_time
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
                suffix = "forced13" if label == "forced-1:3" else "native"
                path = TRADE_DIR / (
                    f"s20r_e{entry_period}_x{exit_period}_s{stop_tag}_"
                    f"{coin}_{interval}_{suffix}.csv"
                )
                if path.exists():
                    raise FileExistsError(f"Refusing to overwrite trade list: {path}")
                pd.DataFrame(rows, columns=CSV_COLUMNS).to_csv(
                    path, index=False, encoding="utf-8", lineterminator="\n"
                )
                paths.append((path, len(rows)))
    return paths


def build_sweep(headline: dict):
    rows, all_paths = [], []
    variant_keep = {}
    for entry_period, exit_period, stop_atr in itertools.product(
        ENTRY_GRID, EXIT_GRID, STOP_GRID
    ):
        is_headline = (entry_period, exit_period, stop_atr) == (20, 10, 2.0)
        result = headline if is_headline else runner.run(
            make_spec(entry_period, exit_period, stop_atr), COINS, INTERVALS,
            audit=False,
        )
        all_paths.extend(write_variant_lists(result, entry_period, exit_period, stop_atr))
        variant = f"Entry={entry_period}, exit={exit_period}, stop={stop_atr:g} ATR"
        variant_keep[variant] = False
        for interval in INTERVALS:
            for label in EXITS:
                m = result["pooled"][(interval, label)]
                v, _ = verdict(m, label)
                variant_keep[variant] = variant_keep[variant] or v == "KEEP"
                rows.append({
                    "variant": variant, "entry": entry_period,
                    "exit_period": exit_period, "stop": stop_atr,
                    "headline": is_headline, "timeframe": interval,
                    "exit": label, "trades": m["trades"],
                    "win": m["win_rate"], "r": m["r_sum_post_fee"],
                    "r_trade": m["expectancy_post_fee_r"],
                    "sharpe": m["sharpe_post_fee"], "verdict": v,
                })
    return rows, all_paths, variant_keep


def _simulate_reconciliation(df, label, entry_fn, exit_fn, completed_trades):
    times = df["open_time"].reset_index(drop=True)
    closed_keys = {(t.direction, pd.Timestamp(t.entry_time)) for t in completed_trades}
    pending_entry: Signal | None = None
    pending_signal_key = None
    pending_exit_reason = None
    position: Trade | None = None
    accepted, completed_mirror = set(), set()
    counts = {
        "signals": 0, "taken": 0, "blocked_open": 0,
        "last_bar": 0, "zero_risk": 0, "open_end": 0, "other": 0,
    }
    time_limit = FORCED_LIMIT if label == "forced-1:3" else None
    signals = [entry_fn(df, i) for i in range(len(df))]
    for i in range(s20r.WARMUP, len(df)):
        row = df.iloc[i]
        if position is not None and pending_exit_reason is not None:
            completed_mirror.add((position.direction, pd.Timestamp(position.entry_time)))
            position = None
            pending_exit_reason = None
        if position is None and pending_entry is not None:
            fill = float(row["open"])
            stop = pending_entry.resolve_stop(fill)
            if stop != fill:
                position = Trade(
                    direction=pending_entry.direction,
                    entry_time=pd.Timestamp(times.iloc[i]), entry_price=fill,
                    initial_stop=stop, regime=str(row.get("regime", "")),
                )
                if pending_signal_key is None:
                    raise RuntimeError("Queued signal has no fill timestamp.")
                accepted.add(pending_signal_key)
            else:
                counts["zero_risk"] += 1
            pending_entry, pending_signal_key = None, None
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
                completed_mirror.add((position.direction, pd.Timestamp(position.entry_time)))
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
            pending_signal_key = (signal.direction, pd.Timestamp(times.iloc[i + 1]))
        else:
            counts["blocked_open"] += 1
    open_end_keys = (
        {(position.direction, pd.Timestamp(position.entry_time))} if position is not None else set()
    )
    counts["taken"] = len(accepted & closed_keys)
    counts["open_end"] = len(accepted & open_end_keys)
    counts["other"] = len(accepted - closed_keys - open_end_keys)
    bucket_total = sum(counts[k] for k in (
        "taken", "blocked_open", "last_bar", "zero_risk", "open_end", "other"
    ))
    return {
        **counts,
        "reconciles": bucket_total == counts["signals"] and closed_keys == completed_mirror,
    }


def reconcile(spec, res):
    rows = []
    for coin in COINS:
        for interval in INTERVALS:
            df = runner._prepare(spec, coin, interval)
            entry_fn = spec.entry(df)
            for label in EXITS:
                counts = _simulate_reconciliation(
                    df, label, entry_fn,
                    spec.native_exit(df) if label == "native" else forced_13_exit,
                    res["trades"][(coin, interval, label)],
                )
                rows.append({"coin": coin, "timeframe": interval, "exit": label, **counts})
    return rows


def final_bar_notes(spec, res):
    notes = []
    for coin in COINS:
        for interval in INTERVALS:
            df = runner._prepare(spec, coin, interval)
            times = df["open_time"].reset_index(drop=True)
            entry_fn = spec.entry(df)
            last_time = pd.Timestamp(times.iloc[-1])
            effects = []
            if entry_fn(df, len(df) - 2) is not None:
                effects.append("penultimate-bar signal fills at final open")
            entries = sum(
                pd.Timestamp(t.entry_time) == last_time
                for label in EXITS for t in res["trades"][(coin, interval, label)]
            )
            exits = sum(
                pd.Timestamp(t.exit_time) == last_time
                for label in EXITS for t in res["trades"][(coin, interval, label)]
            )
            if entries:
                effects.append(f"{entries} entries use final open across exits")
            if exits:
                effects.append(f"{exits} exits are stamped at final bar")
            if entry_fn(df, len(df) - 1) is not None:
                effects.append("final close signal has no next bar and is unfilled")
            notes.append(
                f"- {coin} {interval}: final bar opens {last_time:%Y-%m-%d %H:%M} UTC; "
                + ("; ".join(effects) if effects else "no signal or completed trade entry/exit is affected") + "."
            )
    return notes


def result_table(res, summary):
    lines = [
        "| Timeframe | Exit | Trades | Win% | RR | R pre-fee | R post-fee | R/trade | Sharpe | Max DD % | Max DD R | R-recovery | Fee cost/trade | Verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for interval in INTERVALS:
        for label in EXITS:
            m = res["pooled"][(interval, label)]
            lines.append(
                f"| {interval} | {label} | {m['trades']} | {fmt(100*m['win_rate'],1)} | "
                f"{fmt(m['rr_achieved'])} | {fmt(m['r_sum_pre_fee'],2)} | "
                f"{fmt(m['r_sum_post_fee'],2)} | {fmt(m['expectancy_post_fee_r'],4)} | "
                f"{fmt(m['sharpe_post_fee'])} | {fmt(m['max_drawdown_pct'],2)} | "
                f"{fmt(m['max_drawdown_r'],2)} | {fmt(m['r_recovery'])} | "
                f"{fmt(m['avg_fee_cost_r'],4)} | **{summary[(interval,label)]}** |"
            )
    return "\n".join(lines)


def per_coin_table(res):
    lines = [
        "| Coin | Timeframe | Exit | Trades | Win% | RR | R pre-fee | R post-fee | R/trade | Sharpe | Max DD % | Max DD R | R-recovery | Fee cost/trade | Verdict |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for coin in COINS:
        for interval in INTERVALS:
            for label in EXITS:
                m = res["per_cell"][(coin, interval, label)]
                v, _ = verdict(m, label)
                lines.append(
                    f"| {coin} | {interval} | {label} | {m['trades']} | "
                    f"{fmt(100*m['win_rate'],1)} | {fmt(m['rr_achieved'])} | "
                    f"{fmt(m['r_sum_pre_fee'],2)} | {fmt(m['r_sum_post_fee'],2)} | "
                    f"{fmt(m['expectancy_post_fee_r'],4)} | {fmt(m['sharpe_post_fee'])} | "
                    f"{fmt(m['max_drawdown_pct'],2)} | {fmt(m['max_drawdown_r'],2)} | "
                    f"{fmt(m['r_recovery'])} | {fmt(m['avg_fee_cost_r'],4)} | {v} |"
                )
    return "\n".join(lines)


def concentration_table(res):
    lines = [
        "| Timeframe | Exit | Trades | Best trade R | Best trade share | R without best | Best 5 R | Best 5 share | R without best 5 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for interval in INTERVALS:
        for label in EXITS:
            values = np.array([t.net_r for t in res["trades"][(interval,label)] if np.isfinite(t.net_r)])
            if not len(values):
                lines.append(f"| {interval} | {label} | 0 | n/a | n/a | n/a | n/a | n/a | n/a |")
                continue
            ordered = np.sort(values)[::-1]
            total = float(values.sum())
            best_one, best_five = float(ordered[0]), float(ordered[:5].sum())
            lines.append(
                f"| {interval} | {label} | {len(values)} | {best_one:+.3f} | "
                f"{fmt(100*best_one/total,1) if total > 0 else 'n/a'} | "
                f"{total-best_one:+.3f} | {best_five:+.3f} | "
                f"{fmt(100*best_five/total,1) if total > 0 else 'n/a'} | {total-best_five:+.3f} |"
            )
    return "\n".join(lines)


def side_table(res):
    lines = [
        "| Timeframe | Exit | Side | Trades | Win% | R post-fee | R/trade |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for interval in INTERVALS:
        for label in EXITS:
            trades = res["trades"][(interval,label)]
            for side, direction in (("long", 1), ("short", -1)):
                selected = [t for t in trades if t.direction == direction]
                values = np.array([t.net_r for t in selected])
                lines.append(
                    f"| {interval} | {label} | {side} | {len(selected)} | "
                    f"{fmt(100*np.mean(values > 0),1) if len(values) else 'n/a'} | "
                    f"{fmt(values.sum(),2) if len(values) else 'n/a'} | "
                    f"{fmt(values.mean(),4) if len(values) else 'n/a'} |"
                )
    return "\n".join(lines)


def overlap_keys(res, interval, label):
    return {
        (coin, trade.direction, pd.Timestamp(trade.entry_time))
        for coin, trade in cell_keyed_trades(res, interval, label)
    }


def _shared_entry_rerun(res, interval, spec):
    outcomes = {"native": [], "forced-1:3": []}
    common_all = overlap_keys(res, interval, "native") & overlap_keys(res, interval, "forced-1:3")
    for coin in COINS:
        common = {(direction, timestamp) for c, direction, timestamp in common_all if c == coin}
        df = runner._prepare(spec, coin, interval)
        base_entry = spec.entry(df)
        times = df["open_time"].reset_index(drop=True)

        def only_common(_df, i, *, _entry=base_entry, _times=times, _common=common):
            signal = _entry(_df, i)
            if signal is None or i + 1 >= len(_times):
                return None
            key = (signal.direction, pd.Timestamp(_times.iloc[i + 1]))
            return signal if key in _common else None

        for label in EXITS:
            trades = simulate(
                df, only_common,
                spec.native_exit(df) if label == "native" else forced_13_exit,
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


def exit_death_section(res, spec):
    lines = [
        "| Timeframe | Native trades | Forced trades | Entry overlap | Exit-death? | Diagnosis |",
        "|---|---:|---:|---:|---|---|",
    ]
    shared = {}
    for interval in INTERVALS:
        native_keys = overlap_keys(res, interval, "native")
        forced_keys = overlap_keys(res, interval, "forced-1:3")
        union = native_keys | forced_keys
        overlap = len(native_keys & forced_keys) / len(union) if union else float("nan")
        native = res["pooled"][(interval,"native")]
        forced = res["pooled"][(interval,"forced-1:3")]
        decision, diagnosis = exit_death(native, forced)
        lines.append(
            f"| {interval} | {native['trades']} | {forced['trades']} | "
            f"{fmt(100*overlap,1)}% | {decision} | {diagnosis} |"
        )
        if np.isfinite(overlap) and overlap < 0.85:
            nstat, fstat = _shared_entry_rerun(res, interval, spec)
            shared[interval] = (nstat, fstat)
            lines.append(
                f"| | | | | | Shared-entry rerun (<85% overlap): native "
                f"{nstat['trades']} trades at {fmt(nstat['expectancy_post_fee_r'],4)}R/trade; "
                f"forced {fstat['trades']} trades at {fmt(fstat['expectancy_post_fee_r'],4)}R/trade. |"
            )
    lines.append(
        "\nEntry overlap uses the union of coin/direction/fill-timestamp keys. "
        "When overlap is below 85%, a shared-entry replay applies both exits to the same eligible entry set."
    )
    return "\n".join(lines), shared


def reentry_section(headline_paths):
    lines = [
        "| Coin | Timeframe | Exit | Stop-outs | Later completed re-entry | Median gap (bars) | Within 3 bars |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for path, _ in headline_paths:
        frame = pd.read_csv(path)
        if frame.empty:
            continue
        stops = frame[frame["exit_reason"] == "stop"]
        entries = pd.to_datetime(frame["entry_time"], utc=True)
        exits = pd.to_datetime(frame["exit_time"], utc=True)
        interval = str(frame.iloc[0]["timeframe"])
        gaps = []
        for index in stops.index:
            later = entries[entries > exits.loc[index]]
            if not later.empty:
                gaps.append(float((later.min() - exits.loc[index]) / pd.Timedelta(hours=HOURS_PER_BAR[interval])))
        if gaps:
            near = sum(gap <= 3 for gap in gaps)
            lines.append(
                f"| {frame.iloc[0]['coin']} | {interval} | {frame.iloc[0]['exit_variant']} | "
                f"{len(stops)} | {len(gaps)} | {np.median(gaps):.1f} | {100*near/len(gaps):.1f}% ({near}/{len(gaps)}) |"
            )
        else:
            lines.append(
                f"| {frame.iloc[0]['coin']} | {interval} | {frame.iloc[0]['exit_variant']} | "
                f"{len(stops)} | 0 | n/a | n/a |"
            )
    return "\n".join(lines)


def reason_section(headline_paths):
    combined = pd.concat([pd.read_csv(path) for path, _ in headline_paths], ignore_index=True)
    lines = [
        "| Timeframe | Exit | Exit reason | Trades | Mean R post-fee |",
        "|---|---|---|---:|---:|",
    ]
    for (interval, label), group in combined.groupby(["timeframe", "exit_variant"], sort=False):
        for reason, part in group.groupby("exit_reason", dropna=False):
            lines.append(
                f"| {interval} | {label} | {reason} | {len(part)} | "
                f"{part['R post-fee'].mean():+.4f} |"
            )
    return "\n".join(lines)


def sensitivity_section(rows, variant_keep):
    lines = [
        "| Variant | Timeframe | Exit | Trades | Win% | Post-fee total R | R/trade | Sharpe | Verdict |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        marker = " (headline reference)" if row["headline"] else ""
        lines.append(
            f"| {row['variant']}{marker} | {row['timeframe']} | {row['exit']} | "
            f"{row['trades']} | {fmt(100*row['win'],1)} | {fmt(row['r'],2)} | "
            f"{fmt(row['r_trade'],4)} | {fmt(row['sharpe'])} | {row['verdict']} |"
        )
    nonheadline = [row for row in rows if not row["headline"]]
    kept_cells = sum(row["verdict"] == "KEEP" for row in nonheadline)
    headline_name = "Entry=20, exit=10, stop=2 ATR"
    kept_variants = sum(variant_keep.values()) - int(variant_keep.get(headline_name, False))
    variant_count = len(variant_keep) - 1
    lines.extend([
        "",
        f"There are {variant_count} non-headline parameter variants "
        f"(3×3×3 = 27 combinations including the headline). "
        f"{kept_variants}/{variant_count} non-headline variants have at least one KEEP; "
        f"{kept_cells}/{len(nonheadline)} non-headline pooled timeframe/exit cells are KEEP.",
        "The headline row is included as a reference, not optimized or replaced.",
    ])
    return "\n".join(lines), kept_variants, variant_count, kept_cells, len(nonheadline)


def volatility_section(res):
    lines = [
        "| Timeframe | Exit | Volatility bucket | Trades | Post-fee R | R/trade |",
        "|---|---|---|---:|---:|---:|",
    ]
    findings = []
    for interval in INTERVALS:
        for label in EXITS:
            grouped = {"lowvol": [], "highvol": [], "unknown": []}
            for trade in res["trades"][(interval,label)]:
                vol = (trade.regime or "unknown").rsplit("/", 1)[-1]
                if vol not in grouped:
                    vol = "unknown"
                grouped[vol].append(trade)
            means = {}
            for vol in ("lowvol", "highvol", "unknown"):
                trades = grouped[vol]
                values = np.array([trade.net_r for trade in trades])
                mean = float(values.mean()) if len(values) else float("nan")
                means[vol] = mean
                lines.append(
                    f"| {interval} | {label} | {vol} | {len(values)} | "
                    f"{fmt(values.sum(),2) if len(values) else 'n/a'} | {fmt(mean,4)} |"
                )
            if np.isfinite(means["lowvol"]) and np.isfinite(means["highvol"]):
                findings.append(
                    f"{interval}/{label}: high-vol {means['highvol']:+.4f}R/trade "
                    f"(n={len(grouped['highvol'])}) versus low-vol "
                    f"{means['lowvol']:+.4f}R/trade (n={len(grouped['lowvol'])}); "
                    f"difference high minus low {means['highvol']-means['lowvol']:+.4f}R/trade."
                )
            else:
                findings.append(
                    f"{interval}/{label}: insufficient classified trades to compare high- versus low-volatility cells."
                )
    lines.append("\nPlain findings (descriptive only): " + " ".join(findings))
    lines.append(
        "The spec makes no volatility-performance claim. The labels use the runner's "
        "pre-existing regime field and do not affect signals, entries, or exits."
    )
    return "\n".join(lines)


def verdict_section(res, summary):
    lines = [
        "| Timeframe | Exit | Trades >=30 | Expectancy >=0.10 | Sharpe >=0.70 | Recovery >=1.5 | Reward test | Discard conditions | Verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for interval in INTERVALS:
        for label in EXITS:
            m = res["pooled"][(interval,label)]
            if label == "forced-1:3":
                required = breakeven_win_rate(m["avg_fee_cost_r"]) + BAR.keep_win_margin
                reward = f"win {fmt(100*m['win_rate'],1)}% {'PASS' if m['win_rate'] >= required else 'FAIL'}; need {required:.1%}"
            else:
                reward = f"RR {fmt(m['rr_achieved'])} {'PASS' if m['rr_achieved'] >= BAR.keep_rr_native else 'FAIL'}; need 1.50"
            exp, sharpe, recovery = (
                m["expectancy_post_fee_r"], m["sharpe_post_fee"], m["r_recovery"]
            )
            discard = (
                f"exp<=0 {'yes' if exp <= 0 else 'no'}; "
                f"Sharpe<0.30 {'yes' if sharpe < BAR.discard_sharpe else 'no'}; "
                f"recovery<0.50 {'yes' if recovery < BAR.discard_r_recovery else 'no'}"
            )
            lines.append(
                f"| {interval} | {label} | {m['trades'] >= BAR.min_trades} ({m['trades']}) | "
                f"{exp >= BAR.keep_expectancy_r} ({exp:+.4f}) | "
                f"{sharpe >= BAR.keep_sharpe} ({fmt(sharpe)}) | "
                f"{recovery >= BAR.keep_r_recovery} ({fmt(recovery)}) | {reward} | "
                f"{discard} | {summary[(interval,label)]} |"
            )
    lines.append("\n" + describe())
    return "\n".join(lines)


def _cell_frame(headline_paths, interval, label):
    selected = [
        pd.read_csv(path) for path, _ in headline_paths
        if f"_{interval}_" in path.name
        and (("forced13" in path.name) == (label == "forced-1:3"))
    ]
    if not selected:
        return pd.DataFrame(columns=CSV_COLUMNS)
    frame = pd.concat(selected, ignore_index=True)
    frame["entry_dt"] = pd.to_datetime(frame["entry_time"], utc=True)
    frame["exit_dt"] = pd.to_datetime(frame["exit_time"], utc=True)
    frame["exit_year"] = frame["exit_dt"].dt.year
    return frame


def concentration_detail(res, headline_paths):
    eligible = {}
    for interval in INTERVALS:
        for label in EXITS:
            m = res["pooled"][(interval,label)]
            v, _ = verdict(m, label)
            if v == "KEEP" or m["expectancy_post_fee_r"] >= 0.10:
                frame = _cell_frame(headline_paths, interval, label)
                if len(frame) != m["trades"]:
                    raise RuntimeError(
                        f"Saved rows ({len(frame)}) do not match {interval}/{label} metrics ({m['trades']})."
                    )
                eligible[(interval,label)] = frame
    if not eligible:
        return "No headline cell is KEEP or has post-fee expectancy >= +0.10R; no qualifying concentration detail.", {}
    lines = [
        "Eligible cells are every headline KEEP or cell with post-fee expectancy >= +0.10R/trade. "
        "All detail below is computed from saved headline trade-list CSVs."
    ]
    for (interval,label), frame in eligible.items():
        best = frame.sort_values("R post-fee", ascending=False).head(5)
        lines.extend([
            "", f"### {interval} / {label}", "", "Best five completed trades by post-fee R:", "",
            "| Coin | Direction | Entry time (UTC) | Exit time (UTC) | Bars held | Entry price | Exit price | R post-fee |",
            "|---|---|---|---|---:|---:|---:|---:|",
        ])
        for _, trade in best.iterrows():
            lines.append(
                f"| {trade['coin']} | {trade['direction']} | {trade['entry_dt']:%Y-%m-%d %H:%M} | "
                f"{trade['exit_dt']:%Y-%m-%d %H:%M} | {int(trade['bars_held'])} | "
                f"{float(trade['entry_price']):.8f} | {float(trade['exit_price']):.8f} | "
                f"{float(trade['R post-fee']):+.4f} |"
            )
        lines.extend([
            "", "Calendar-year breakdown by exit timestamp (UTC):", "",
            "| Year | Pooled trades | Pooled R | Pooled R/trade | BTC n | BTC R | BTC R/trade | SOL n | SOL R | SOL R/trade | XRP n | XRP R | XRP R/trade |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for year, yearly in frame.groupby("exit_year", sort=True):
            pooled_r = float(yearly["R post-fee"].sum())
            bits = []
            for coin in COINS:
                sub = yearly[yearly["coin"] == coin]
                bits.extend([
                    str(len(sub)), f"{sub['R post-fee'].sum():+.4f}",
                    f"{sub['R post-fee'].mean():+.4f}" if len(sub) else "n/a",
                ])
            lines.append(
                f"| {int(year)} | {len(yearly)} | {pooled_r:+.4f} | "
                f"{pooled_r/len(yearly):+.4f} | " + " | ".join(bits) + " |"
            )
        remainder = frame.drop(best.index)
        lines.extend([
            "", "Results without the best five, overall and by direction:", "",
            "| Group | Trades | Post-fee R | R/trade |", "|---|---:|---:|---:|",
            (f"| All directions | {len(remainder)} | {remainder['R post-fee'].sum():+.4f} | {remainder['R post-fee'].mean():+.4f} |"
             if len(remainder) else "| All directions | 0 | 0.0000 | n/a |"),
        ])
        for direction in ("long", "short"):
            sub = remainder[remainder["direction"] == direction]
            lines.append(
                (f"| {direction} | {len(sub)} | {sub['R post-fee'].sum():+.4f} | {sub['R post-fee'].mean():+.4f} |"
                 if len(sub) else f"| {direction} | 0 | 0.0000 | n/a |")
            )
    return "\n".join(lines), eligible


def source_section(res, summary):
    outputs = []
    for interval in INTERVALS:
        for label in EXITS:
            m = res["pooled"][(interval,label)]
            outputs.append(
                f"{interval}/{label}: {m['expectancy_post_fee_r']:+.4f}R/trade post-fee "
                f"({summary[(interval,label)]})."
            )
    return (
        f"Spec source line, verbatim: {SOURCE_LINE}\n\n"
        "The spec makes no performance claim. These results test only its pinned "
        "close-breakout/opposite-channel interpretation and ATR stop; they are not "
        "attributed to Wilder beyond the source attribution in the spec. "
        + " ".join(outputs)
    )


def build_report(res, summary, cov, reconciliation, final_notes, sweep_rows,
                 variant_keep, all_paths, headline_paths, detail_text):
    audit = res["audit"]
    audit_rows = "\n".join(
        f"| {name} | {len(cols)} | {'PASS' if ok else 'FAIL'} | "
        f"{'none' if ok else '; '.join(problems[:3])} |"
        for name, (ok, cols, problems) in audit.items()
    )
    rec_rows = "\n".join(
        f"| {r['coin']} | {r['timeframe']} | {r['exit']} | {r['signals']} | "
        f"{r['taken']} | {r['blocked_open']} | {r['last_bar']} | {r['zero_risk']} | "
        f"{r['open_end']} | {r['other']} | {'PASS' if r['reconciles'] else 'FAIL'} |"
        for r in reconciliation
    )
    death_text, _shared = exit_death_section(res, make_spec())
    sweep_text, kept_variants, variant_count, kept_cells, cell_count = sensitivity_section(
        sweep_rows, variant_keep
    )
    audit_passes = sum(bool(value[0]) for value in audit.values())
    signal_total = sum(row["signals"] for row in reconciliation)
    bucket_total = sum(
        row["taken"] + row["blocked_open"] + row["last_bar"] + row["zero_risk"]
        + row["open_end"] + row["other"] for row in reconciliation
    )
    row_sum = 0
    for csv_path, expected in all_paths:
        actual = len(pd.read_csv(csv_path))
        if actual != expected:
            raise RuntimeError(f"Trade-list row count mismatch for {csv_path}: {actual} != {expected}.")
        row_sum += actual
    strategy_bytes = Path(s20r.__file__).read_bytes()
    runner_bytes = Path(__file__).read_bytes()
    strategy_hash = hashlib.sha256(strategy_bytes).hexdigest()
    runner_hash = hashlib.sha256(runner_bytes).hexdigest()
    result_summary = "; ".join(
        f"{interval}/{label}: {res['pooled'][(interval,label)]['trades']} trades, "
        f"{res['pooled'][(interval,label)]['expectancy_post_fee_r']:+.4f}R/trade, "
        f"Sharpe {fmt(res['pooled'][(interval,label)]['sharpe_post_fee'])}, "
        f"{summary[(interval,label)]}"
        for interval in INTERVALS for label in EXITS
    )
    result = "\n\n".join([
        "## 1. Rule and source\n\n"
        "**Departures from the spec: ATR smoothing is underspecified; this build uses standard Wilder smoothing, seeded with the simple average of the first 20 true ranges, then updated recursively.** "
        "Other execution conventions follow the requested engine path: closed-bar signals fill at next open; stop distance is frozen at signal and carried as `stop_frac`, scaling with fill/signal-close across entry gaps; stops win ties; gap-through stops fill at the open; unresolved open trades at data end are discarded; one position per coin/timeframe. Fees are 0.055% taker per side; funding is not modeled.\n\n"
        "Long when the closed-bar close is strictly above the prior entry-period high; short when strictly below the prior entry-period low. Current bar is excluded from each channel by shifting the completed rolling channel one bar. Native exit is a close strictly beyond the opposite prior exit-period channel, filled at next open. Initial stop is stop-multiple × Wilder ATR(20) from the signal bar; no native profit target. The forced comparison is 1R stop / 3R target, 30-bar limit, using the standard market-order simulation path.\n\n"
        f"Spec source sentence, verbatim: {SOURCE_LINE} The spec makes no performance claim.",
        "## 2. Parameters and declared interpretations\n\n"
        "- Headline: entry 20 bars, native exit 10 bars, Wilder ATR(20), initial stop 2×ATR; 250-bar warmup.\n"
        "- Wilder ATR seed: first ATR is the arithmetic mean of the first 20 true ranges (TR[0] is high-low because prior close is unavailable); each later value is `(previous ATR × 19 + current TR) / 20`.\n"
        "- Entry and exit channels use strict close comparisons against rolling high/low values shifted one bar; current bar excluded.\n"
        "- Stop fraction at signal is `stop_multiple × ATR(signal) / close(signal)` and is passed unchanged via `Signal.stop_frac`; engine resolves the stop using next-open fill price.\n"
        "- Coins BTCUSDT/SOLUSDT/XRPUSDT; 1H/4H/1D; coins pooled by timeframe. Funding is omitted.\n"
        "- Forced 1:3: stop 1R, target 3R, maximum 30 bars; same entry function and fixed signal-time risk distance as native.\n"
        "- Sweep is the independent Cartesian grid entry 10/20/55 × exit 5/10/20 × stop 1.5/2/2.5 ATR; headline included only as reference.",
        "## 3. Fresh lookahead-bias audit\n\n"
        f"Fresh cut-and-recompute lookahead audit passed {audit_passes}/{len(audit)} coin/timeframe datasets; "
        f"{sum(len(value[1]) for value in audit.values())} derived columns checked. Audit is on the headline strategy and completed before headline results.\n\n"
        "Channel inputs are shifted and ATR uses true ranges only through the signal bar. The audit checks recomputation on truncated data; execution uses next-open fills.\n\n"
        "| Dataset | Derived columns checked | Audit | Mismatches |\n|---|---:|---|---|\n" + audit_rows
        + "\n\nAll nine required local cache files were present; no data download was requested. Final-bar effects:\n\n"
        + "\n".join(final_notes),
        "## 4. Results and signal reconciliation\n\n"
        + result_table(res, summary)
        + "\n\nHistory is the tradeable window after 250 warmup bars. "
        + coverage.summary_line(cov, COINS, INTERVALS)
        + "\n\nEach generated valid signal is assigned once: taken and completed, blocked by an open position, last-bar signal with no next open, zero risk, accepted position still open and discarded at data end, or other accepted-but-unmatched.\n\n"
        "| Coin | Timeframe | Exit | Signals | Taken/completed | Blocked/open | Last bar | Zero risk | Open at end/discarded | Other | Reconciles? |\n"
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|\n" + rec_rows
        + f"\n\nReconciliation {'PASSES' if all(row['reconciles'] for row in reconciliation) else 'FAILS'}: {signal_total} signals, {bucket_total} assigned to exactly one category.",
        "## 5. Per-coin results\n\n" + per_coin_table(res)
        + "\n\n| Timeframe | Exit | Trades | R/trade post-fee | t-stat | Rough noise read |\n|---|---|---:|---:|---:|---|\n"
        + "\n".join(
            f"| {interval} | {label} | {stats['n']} | {fmt(stats['net_mean'],4)} | "
            f"{fmt(stats['t_net'])} | "
            f"{'positive beyond 2' if np.isfinite(stats['t_net']) and stats['t_net'] >= 2 else 'negative beyond -2' if np.isfinite(stats['t_net']) and stats['t_net'] <= -2 else 'inside/indeterminate'} |"
            for interval in INTERVALS for label in EXITS
            for stats in [context_checks.significance(res['trades'][(interval,label)])]
        )
        + "\n\nt is mean post-fee R divided by its standard error; it is a rough noise comparison, not proof of a durable edge.",
        "## 6. Concentration check (both exits)\n\n" + concentration_table(res)
        + "\n\nShares are shown only when total post-fee R is positive. Trades are ranked by post-fee R.",
        "## 7. Long/short breakdown (both exits)\n\n" + side_table(res),
        "## 8. Exit-death check\n\n" + death_text
        + "\n\n### 8a. Re-entry clustering after stop-outs (saved headline CSVs)\n\n" + reentry_section(headline_paths)
        + "\n\n### 8b. Exit-reason split and mean post-fee R (saved headline CSVs)\n\n" + reason_section(headline_paths),
        "## 9. Fees and funding\n\n"
        "Trading fees are included at 0.055% taker on entry and exit. Funding was not modeled; no funding-adjusted outcome is claimed.",
        "## 10. Parameter sensitivity sweep\n\n" + sweep_text,
        "## 11. Market-condition breakdown\n\n" + volatility_section(res),
        "## 12. Source comparison and discrepancies\n\n" + source_section(res, summary),
        "## 13. Fixed discard-bar verdict per cell\n\nThe fixed bar is applied after fees:\n\n```\n"
        + describe() + "\n```\n\n" + verdict_section(res, summary),
        "## 14. Bottom line (facts only)\n\n"
        + result_summary + "\n\n"
        + f"The parameter grid has {variant_count} non-headline variants; {kept_variants} variants have at least one KEEP. "
        + f"At the pooled timeframe/exit-cell level, {kept_cells}/{cell_count} non-headline cells are KEEP.",
        "## 14a. Concentration and stability detail\n\n" + detail_text,
        "## 15. Files created\n\n"
        "Dry run: no tracked files, engine, specs, strategy logs, or Opus files were modified; no commit or push was performed.\n\n"
        "| New source file | Lines | SHA-256 |\n|---|---:|---|\n"
        f"| src/s20r_atr_channel.py | {len(strategy_bytes.decode('utf-8').splitlines())} | {strategy_hash} |\n"
        f"| src/run_s20r.py | {len(runner_bytes.decode('utf-8').splitlines())} | {runner_hash} |\n\n"
        f"Trade-list CSV files: {len(all_paths)} (27 parameter combinations × 3 coins × 3 timeframes × 2 exits); total completed trade rows: {row_sum}. Every CSV row count matched its run result. Headline CSV count: {len(headline_paths)}.\n\n"
        f"Final report: {REPORT_PATH}.",
    ])
    return result + "\n"


def main():
    if REPORT_PATH.exists():
        raise FileExistsError(f"Refusing to overwrite requested report: {REPORT_PATH}")
    if COMPARE_PATH.exists():
        raise FileExistsError(f"Refusing to overwrite requested comparison: {COMPARE_PATH}")
    if TRADE_DIR.exists():
        raise FileExistsError(f"Refusing to overwrite existing trade-list directory: {TRADE_DIR}")
    missing = [
        runner.bd.DATA_DIR / f"{coin}_{interval}.parquet"
        for coin in COINS for interval in INTERVALS
        if not (runner.bd.DATA_DIR / f"{coin}_{interval}.parquet").is_file()
    ]
    if missing:
        raise FileNotFoundError(
            "Required local cache files are missing; refusing download fallback: "
            + ", ".join(str(path) for path in missing)
        )
    TRADE_DIR.mkdir(parents=True, exist_ok=False)
    spec = make_spec()
    headline = runner.run(spec, COINS, INTERVALS, audit=True)
    if len(headline["audit"]) != 9 or not all(v[0] for v in headline["audit"].values()):
        raise RuntimeError("Fresh headline lookahead audit did not pass all nine datasets.")
    reconciliation = reconcile(spec, headline)
    if len(reconciliation) != 18 or not all(row["reconciles"] for row in reconciliation):
        raise RuntimeError("Headline signal reconciliation failed for one or more cells.")
    sweep_rows, all_paths, variant_keep = build_sweep(headline)
    expected_rows = 27 * len(INTERVALS) * len(EXITS)
    expected_paths = 27 * len(COINS) * len(INTERVALS) * len(EXITS)
    if len(sweep_rows) != expected_rows:
        raise RuntimeError(f"Unexpected sweep row count: {len(sweep_rows)} != {expected_rows}.")
    if len(all_paths) != expected_paths:
        raise RuntimeError(f"Unexpected trade-list count: {len(all_paths)} != {expected_paths}.")
    headline_paths = [
        item for item in all_paths
        if "_e20_x10_s2_" in item[0].name
    ]
    if len(headline_paths) != 18:
        raise RuntimeError(f"Expected 18 headline CSV files; found {len(headline_paths)}.")
    cov = coverage.collect(COINS, INTERVALS, spec.warmup_for)
    final_notes = final_bar_notes(spec, headline)
    summary = {
        (interval, label): verdict(headline["pooled"][(interval,label)], label)[0]
        for interval in INTERVALS for label in EXITS
    }
    detail_text, _details = concentration_detail(headline, headline_paths)
    report = build_report(
        headline, summary, cov, reconciliation, final_notes, sweep_rows,
        variant_keep, all_paths, headline_paths, detail_text,
    )
    REPORT_PATH.write_text(report, encoding="utf-8", newline="\n")
    print(f"REPORT_WRITTEN={REPORT_PATH}")
    print(f"AUDITS={sum(v[0] for v in headline['audit'].values())}/{len(headline['audit'])}")
    print(f"RECONCILIATION={'PASS' if all(row['reconciles'] for row in reconciliation) else 'FAIL'}")
    print(f"TRADE_LISTS={len(all_paths)}")
    for interval in INTERVALS:
        for label in EXITS:
            m = headline["pooled"][(interval,label)]
            print(
                f"RESULT {interval} {label} trades={m['trades']} "
                f"R/trade={m['expectancy_post_fee_r']:+.6f} "
                f"Sharpe={fmt(m['sharpe_post_fee'])} verdict={summary[(interval,label)]}"
            )
    nonheadline = [row for row in sweep_rows if not row["headline"]]
    kept_count = sum(variant_keep.values()) - int(variant_keep.get("Entry=20, exit=10, stop=2 ATR", False))
    print(
        f"SWEEP_NONHEADLINE_VARIANTS={len(variant_keep)-1}; VARIANTS_WITH_KEEP={kept_count}; "
        f"NONHEADLINE_KEEP_CELLS={sum(row['verdict']=='KEEP' for row in nonheadline)}/{len(nonheadline)}"
    )
    print(f"REPORT_LINES={len(report.splitlines())}")
    print(f"REPORT_SHA256={hashlib.sha256(REPORT_PATH.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
