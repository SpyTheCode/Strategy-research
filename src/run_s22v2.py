from __future__ import annotations

import hashlib
import itertools
from pathlib import Path

import numpy as np
import pandas as pd

import lookahead_check
import runner
import s22v2_supertrend as s22v2
from discard_bar import BAR, breakeven_win_rate
from harness import (
    TAKER_FEE_RATE,
    Trade,
    forced_13_exit,
    metrics,
    simulate,
)

NAME = "#22 Supertrend (7, 3), independent build"
COINS = ("BTCUSDT", "SOLUSDT", "XRPUSDT")
INTERVALS = ("1H", "4H", "1D")
EXITS = ("native", "forced-1:3")
ATR_PERIODS = (7, 10, 14)
MULTIPLIERS = (2.0, 3.0, 4.0)
FORCED_LIMIT = 30
ROOT = Path(__file__).resolve().parent.parent
TRADE_DIR = ROOT / "trade_lists" / "s22v2"
REPORT_PATH = Path(r"C:\Users\MarketCoder\Desktop\s22v2_report.txt")
COMPARE_PATH = Path(r"C:\Users\MarketCoder\Desktop\s22v2_compare.txt")
HOURS_PER_BAR = {"1H": 1.0, "4H": 4.0, "1D": 24.0}
CSV_COLUMNS = [
    "coin", "timeframe", "exit_variant", "direction", "entry_time",
    "entry_price", "exit_time", "exit_price", "exit_reason", "bars_held",
    "initial_stop", "R pre-fee", "R post-fee", "regime",
]
SOURCE_LINE = (
    "**Source:** Olivier Seban's Supertrend indicator (commonly attributed to Seban; "
    "canonical implementation varies). Test trend-following: long when close crosses "
    "above the active final upper band; short when close crosses below active final "
    "lower band. Native reverse on direction flip. No independent TP; initial stop "
    "is active Supertrend line."
)


def fmt(value, digits: int = 3) -> str:
    try:
        if value is None or not np.isfinite(value):
            return "n/a"
    except (TypeError, ValueError):
        return "n/a"
    return f"{value:+.{digits}f}" if value < 0 else f"{value:.{digits}f}"


def fixed_verdict(m: dict, exit_name: str) -> tuple[str, str]:
    if m["trades"] < BAR.min_trades:
        return "INCONCLUSIVE", f"under {BAR.min_trades} trades"
    exp = m["expectancy_post_fee_r"]
    sharpe = m["sharpe_post_fee"]
    total = m["r_sum_post_fee"]
    drawdown = m["max_drawdown_r"]
    recovery = m["r_recovery"]
    discard = (
        exp <= 0.0
        or sharpe < 0.30
        or total < 0.5 * drawdown
    )
    if discard:
        reasons = []
        if exp <= 0.0:
            reasons.append("expectancy <= 0")
        if sharpe < 0.30:
            reasons.append("Sharpe < 0.30")
        if total < 0.5 * drawdown:
            reasons.append("total R < 0.5x max DD R")
        return "DISCARD", ", ".join(reasons)
    if exit_name == "native":
        reward_ok = (
            np.isfinite(m["rr_achieved"])
            and m["rr_achieved"] >= BAR.keep_rr_native
        )
        reward_text = (
            f"RR {fmt(m['rr_achieved'])} >= {BAR.keep_rr_native:.2f}"
        )
    else:
        required_win = (
            breakeven_win_rate(m["avg_fee_cost_r"]) + BAR.keep_win_margin
        )
        reward_ok = m["win_rate"] >= required_win
        reward_text = (
            f"win {m['win_rate']:.1%} >= {required_win:.1%}"
        )
    keep = (
        exp >= BAR.keep_expectancy_r
        and sharpe >= BAR.keep_sharpe
        and recovery >= BAR.keep_r_recovery
        and reward_ok
    )
    if keep:
        return "KEEP", reward_text + " PASS"
    return "INCONCLUSIVE", reward_text + " or KEEP thresholds not met"


def make_spec(period: int, multiplier: float):
    return runner.StrategySpec(
        name=f"{NAME} [ATR={period}, multiplier={multiplier:g}]",
        add_indicators=lambda df: s22v2.add_indicators(
            df, period=period, multiplier=multiplier
        ),
        entry=s22v2.entry,
        native_exit=s22v2.native_exit,
        warmup=s22v2.WARMUP,
        native_time_limit=None,
    )


def synthetic_gate() -> str:
    rising = np.linspace(100.0, 300.0, 200, endpoint=False)
    falling = np.linspace(300.0, 100.0, 200)
    close = np.concatenate((rising, falling))
    frame = pd.DataFrame({
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
    })
    _, upper, lower, direction = s22v2._supertrend(
        frame, period=7, multiplier=3.0, initial_direction=-1
    )
    start = 6
    changes = np.flatnonzero(
        (direction[1:] != direction[:-1]) & (direction[1:] != 0)
    ) + 1
    changes = changes[changes > start]
    flips_up = [int(i) for i in changes if direction[i] == 1]
    flips_down = [int(i) for i in changes if direction[i] == -1]
    up_leg = slice(start, 200)
    down_leg = slice(200, 400)
    up_ok = bool(np.all(lower[up_leg] < close[up_leg]))
    down_ok = bool(np.all(upper[down_leg] > close[down_leg]))
    if len(flips_up) != 1 or len(flips_down) != 1 or not up_ok or not down_ok:
        raise RuntimeError(
            "Synthetic Supertrend gate failed: "
            f"up flips={flips_up}, down flips={flips_down}, "
            f"up line below={up_ok}, down line above={down_ok}."
        )
    return (
        "RAN: 400-bar synthetic test (200 rising, 200 falling); "
        f"UP flip={flips_up[0]}, DOWN flip={flips_down[0]}; "
        f"line below all up-leg closes={up_ok}; "
        f"line above all down-leg closes={down_ok}. "
        "Synthetic test state was seeded DOWN solely to exercise both flip "
        "directions; production remains initialized UP."
    )


def signal_gate(frames: dict) -> tuple[list[str], dict]:
    lines = []
    signal_info = {}
    for interval in ("1D", "4H", "1H"):
        df = frames[("BTCUSDT", interval)]
        direction = df["s22v2_direction"].to_numpy(dtype=int)
        changes = np.flatnonzero(
            (direction[1:] != direction[:-1])
            & (direction[1:] != 0)
            & (direction[:-1] != 0)
        ) + 1
        gaps = np.diff(changes)
        median_gap = float(np.median(gaps)) if len(gaps) else float("nan")
        lines.append(
            f"BTCUSDT {interval}: {len(changes)} trend flips; "
            f"median bars between flips={fmt(median_gap, 1)}."
        )
        entry_fn = s22v2.entry(df)
        found = 0
        for i in range(s22v2.WARMUP, len(df) - 1):
            signal = entry_fn(df, i)
            if signal is None:
                continue
            entry_open = float(df["open"].iloc[i + 1])
            stop = float(signal.stop_price)
            correct = stop < entry_open if signal.direction > 0 else stop > entry_open
            side = "long" if signal.direction > 0 else "short"
            lines.append(
                f"BTCUSDT {interval} first signal {found + 1}: {side}; "
                f"signal close={float(df['close'].iloc[i]):.8f}; "
                f"entry-bar open={entry_open:.8f}; stop={stop:.8f}; "
                f"correct-side={'YES' if correct else 'NO'}."
            )
            if not correct:
                raise RuntimeError(
                    f"Signal sanity gate failed: BTCUSDT {interval} {side} "
                    f"stop {stop} is not on the correct side of entry {entry_open}."
                )
            signal_info[(interval, found)] = {
                "side": side,
                "signal_close": float(df["close"].iloc[i]),
                "entry_open": entry_open,
                "stop": stop,
                "direction": signal.direction,
                "signal_time": pd.Timestamp(df["open_time"].iloc[i]),
                "entry_time": pd.Timestamp(df["open_time"].iloc[i + 1]),
            }
            found += 1
            if found == 5:
                break
        if found < 5:
            raise RuntimeError(
                f"Signal sanity gate found only {found} BTCUSDT {interval} "
                "signals; five are required."
            )
    return lines, signal_info


def audit_all(frames: dict) -> dict:
    spec = make_spec(7, 3.0)
    audit = {}
    keep = lookahead_check.RAW | spec.raw_extra
    for coin in COINS:
        for interval in INTERVALS:
            frame = frames[(coin, interval)]
            raw = frame.drop(columns=[c for c in frame.columns if c not in keep])
            ok, cols, problems = lookahead_check.audit(
                raw, spec.add_indicators,
                first_cut=max(300, spec.warmup_for(interval) + 50),
            )
            audit[f"{coin} {interval}"] = (ok, cols, problems)
            if not ok:
                raise RuntimeError(
                    f"Fresh lookahead audit FAILED for {coin} {interval}: "
                    f"{problems[:3]}"
                )
    return audit


def evaluate(frames: dict, period: int, multiplier: float) -> dict:
    per_cell = {}
    trades_by_cell = {}
    pooled = {}
    pooled_trades = {}
    for interval in INTERVALS:
        portfolio = {label: [] for label in EXITS}
        for coin in COINS:
            df = s22v2.add_indicators(
                frames[(coin, interval)], period=period, multiplier=multiplier
            )
            entry_fn = s22v2.entry(df)
            native_fn = s22v2.native_exit(df)
            for label in EXITS:
                exit_fn = native_fn if label == "native" else forced_13_exit
                limit = None if label == "native" else FORCED_LIMIT
                trades = simulate(
                    df, entry_fn, exit_fn, warmup=s22v2.WARMUP,
                    time_limit_bars=limit,
                    entry_fee_rate=TAKER_FEE_RATE,
                    exit_fee_rate=TAKER_FEE_RATE,
                )
                trades_by_cell[(coin, interval, label)] = trades
                per_cell[(coin, interval, label)] = metrics(
                    trades, interval=interval
                )
                portfolio[label].extend(trades)
        for label, trades in portfolio.items():
            pooled_trades[(interval, label)] = sorted(
                trades, key=lambda trade: trade.entry_time
            )
            pooled[(interval, label)] = metrics(trades, interval=interval)
    return {
        "per_cell": per_cell,
        "trades": trades_by_cell,
        "pooled": pooled,
        "pooled_trades": pooled_trades,
    }


def trade_rows(trades: list[Trade], coin: str, interval: str, label: str):
    return [{
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
    } for trade in sorted(trades, key=lambda item: item.entry_time)]


def save_variant(result: dict, period: int, multiplier: float) -> list[tuple[Path, int]]:
    outputs = []
    tag_mult = f"{multiplier:g}".replace(".", "p")
    for coin in COINS:
        for interval in INTERVALS:
            for label in EXITS:
                rows = trade_rows(
                    result["trades"][(coin, interval, label)],
                    coin, interval, label,
                )
                suffix = "forced13" if label == "forced-1:3" else "native"
                path = TRADE_DIR / (
                    f"s22v2_a{period}_m{tag_mult}_{coin}_{interval}_{suffix}.csv"
                )
                pd.DataFrame(rows, columns=CSV_COLUMNS).to_csv(
                    path, index=False, encoding="utf-8", lineterminator="\n"
                )
                outputs.append((path, len(rows)))
    return outputs


def reconcile_one(
    df: pd.DataFrame,
    label: str,
    completed_trades: list[Trade],
) -> dict:
    entry_fn = s22v2.entry(df)
    exit_fn = s22v2.native_exit(df) if label == "native" else forced_13_exit
    times = pd.DatetimeIndex(df["open_time"])
    completed_keys = {
        (trade.direction, pd.Timestamp(trade.entry_time))
        for trade in completed_trades
    }
    pending_entry = None
    pending_key = None
    pending_exit_reason = None
    position = None
    accepted = set()
    mirror_closed = set()
    dispositions = {}
    counts = {
        "signals": 0,
        "taken": 0,
        "blocked_open": 0,
        "last_bar": 0,
        "zero_risk": 0,
        "open_end": 0,
        "other": 0,
    }
    limit = None if label == "native" else FORCED_LIMIT

    def classify(key, bucket):
        if key is not None:
            dispositions[key] = bucket

    for i in range(s22v2.WARMUP, len(df)):
        row = df.iloc[i]
        if position is not None and pending_exit_reason is not None:
            mirror_closed.add((position.direction, pd.Timestamp(position.entry_time)))
            position = None
            pending_exit_reason = None
        if position is None and pending_entry is not None:
            fill = float(row["open"])
            stop = pending_entry.resolve_stop(fill)
            if stop == fill:
                counts["zero_risk"] += 1
                classify(pending_key, "zero-risk")
            else:
                position = Trade(
                    direction=pending_entry.direction,
                    entry_time=times[i],
                    entry_price=fill,
                    initial_stop=stop,
                )
                accepted.add((position.direction, pd.Timestamp(position.entry_time)))
                classify(pending_key, "accepted")
            pending_entry = None
            pending_key = None
        if position is not None:
            plan = exit_fn(df, i, position)
            stop_hit = plan.stop_level is not None and (
                row["low"] <= plan.stop_level if position.direction > 0
                else row["high"] >= plan.stop_level
            )
            target_hit = plan.target_level is not None and (
                row["high"] >= plan.target_level if position.direction > 0
                else row["low"] <= plan.target_level
            )
            if stop_hit or target_hit:
                mirror_closed.add(
                    (position.direction, pd.Timestamp(position.entry_time))
                )
                position = None
            else:
                position.bars_held += 1
                if limit is not None and position.bars_held >= limit:
                    pending_exit_reason = "time"
                elif plan.close_exit:
                    pending_exit_reason = plan.reason or "signal"

        signal = entry_fn(df, i)
        if signal is None:
            continue
        counts["signals"] += 1
        if i + 1 >= len(df):
            counts["last_bar"] += 1
        elif pending_entry is None and (
            position is None or pending_exit_reason is not None
        ):
            pending_entry = signal
            pending_key = (signal.direction, pd.Timestamp(times[i + 1]))
        else:
            counts["blocked_open"] += 1
            key = (signal.direction, pd.Timestamp(times[i + 1]))
            classify(key, "blocked-while-open")

    open_keys = (
        {(position.direction, pd.Timestamp(position.entry_time))}
        if position is not None else set()
    )
    counts["taken"] = len(accepted & completed_keys)
    counts["open_end"] = len(accepted & open_keys)
    counts["other"] = len(accepted - completed_keys - open_keys)
    for key in accepted & completed_keys:
        classify(key, "taken")
    for key in accepted & open_keys:
        classify(key, "open-at-end/discarded")
    for key in accepted - completed_keys - open_keys:
        classify(key, "accepted-but-unmatched")
    bucket_total = sum(counts[key] for key in (
        "taken", "blocked_open", "last_bar", "zero_risk", "open_end", "other"
    ))
    counts["reconciles"] = (
        bucket_total == counts["signals"] and completed_keys == mirror_closed
    )
    counts["dispositions"] = dispositions
    if not counts["reconciles"]:
        raise RuntimeError(
            f"Signal reconciliation failed for {label}: {counts}."
        )
    return counts


def reconciliation(frames: dict, result: dict) -> list[dict]:
    rows = []
    for coin in COINS:
        for interval in INTERVALS:
            df = s22v2.add_indicators(
                frames[(coin, interval)], period=7, multiplier=3.0
            )
            for label in EXITS:
                counts = reconcile_one(
                    df, label, result["trades"][(coin, interval, label)]
                )
                rows.append({
                    "coin": coin,
                    "timeframe": interval,
                    "exit": label,
                    **counts,
                })
    return rows


def check_native_holding(result: dict, frames: dict) -> list[str]:
    problems = []
    for interval in INTERVALS:
        pooled = result["pooled"][(interval, "native")]
        trades = result["pooled_trades"][(interval, "native")]
        if pooled["trades"] < 100:
            problems.append(
                f"{interval} native pooled trades={pooled['trades']} (<100)"
            )
        for coin in COINS:
            data_length = len(frames[(coin, interval)])
            long_trades = result["trades"][(coin, interval, "native")]
            for trade in long_trades:
                if trade.bars_held > 0.10 * data_length:
                    problems.append(
                        f"{coin} {interval} native held {trade.bars_held} bars "
                        f"(dataset {data_length}, over 10%)"
                    )
        if interval == "1H" and pooled["avg_bars_held"] > 200:
            problems.append(
                f"1H native average hold={pooled['avg_bars_held']:.2f} (>200)"
            )
        if trades:
            median = float(np.median([trade.bars_held for trade in trades]))
            maximum = max(trade.bars_held for trade in trades)
            print(
                f"RAN: native {interval} holding gate: "
                f"trades={pooled['trades']}, average={pooled['avg_bars_held']:.2f}, "
                f"median={median:.1f}, maximum={maximum} bars."
            )
        else:
            print(f"RAN: native {interval} holding gate: no completed trades.")
    if problems:
        expected_exception = [
            "SOLUSDT 1D native held 195 bars (dataset 1787, over 10%)"
        ]
        if problems != expected_exception:
            raise RuntimeError(
                "Native holding gate failed outside the user-approved exception; "
                "debug required: " + "; ".join(problems)
            )
        trade = max(
            result["trades"][("SOLUSDT", "1D", "native")],
            key=lambda item: item.bars_held,
        )
        if (
            trade.bars_held != 195
            or pd.Timestamp(trade.entry_time) != pd.Timestamp("2023-10-01T00:00:00Z")
            or pd.Timestamp(trade.exit_time) != pd.Timestamp("2024-04-13T00:00:00Z")
            or trade.exit_reason != "opposite-supertrend-flip"
        ):
            raise RuntimeError(
                "The previously debugged SOLUSDT 1D exception changed; "
                "stop and investigate before reporting."
            )
        print(
            "RAN: debugged the sole 10% holding exception. It is a valid SOLUSDT "
            "1D long from 2023-10-01 to the next-open exit on 2024-04-13, held "
            "195/1787 bars; the 2024-04-12 close flipped the Supertrend to DOWN. "
            "No code defect was found. No artificial time cap was added; "
            "proceeding with the user's authorization to document this exception."
        )
    return problems


def pooled_table(result: dict, verdicts: dict) -> str:
    lines = [
        "| Timeframe | Exit | Trades | Win% | RR | R pre-fee | R post-fee | R/trade | Sharpe | Max DD % | Max DD R | R-recovery | Fee cost/trade | Verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for interval in INTERVALS:
        for label in EXITS:
            m = result["pooled"][(interval, label)]
            verdict, _ = fixed_verdict(m, label)
            verdicts[(interval, label)] = verdict
            lines.append(
                f"| {interval} | {label} | {m['trades']} | "
                f"{fmt(100*m['win_rate'],1)} | {fmt(m['rr_achieved'])} | "
                f"{fmt(m['r_sum_pre_fee'])} | {fmt(m['r_sum_post_fee'])} | "
                f"{fmt(m['expectancy_post_fee_r'])} | {fmt(m['sharpe_post_fee'])} | "
                f"{fmt(m['max_drawdown_pct'])} | {fmt(m['max_drawdown_r'])} | "
                f"{fmt(m['r_recovery'])} | {fmt(m['avg_fee_cost_r'])} | "
                f"{verdict} |"
            )
    return "\n".join(lines)


def per_coin_table(result: dict) -> str:
    lines = [
        "| Coin | Timeframe | Exit | Trades | Win% | RR | R pre-fee | R post-fee | R/trade | Sharpe | Max DD % | Max DD R | R-recovery | Fee cost/trade | Verdict |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for coin in COINS:
        for interval in INTERVALS:
            for label in EXITS:
                m = result["per_cell"][(coin, interval, label)]
                verdict, _ = fixed_verdict(m, label)
                lines.append(
                    f"| {coin} | {interval} | {label} | {m['trades']} | "
                    f"{fmt(100*m['win_rate'],1)} | {fmt(m['rr_achieved'])} | "
                    f"{fmt(m['r_sum_pre_fee'])} | {fmt(m['r_sum_post_fee'])} | "
                    f"{fmt(m['expectancy_post_fee_r'])} | "
                    f"{fmt(m['sharpe_post_fee'])} | "
                    f"{fmt(m['max_drawdown_pct'])} | {fmt(m['max_drawdown_r'])} | "
                    f"{fmt(m['r_recovery'])} | {fmt(m['avg_fee_cost_r'])} | "
                    f"{verdict} |"
                )
    return "\n".join(lines)


def reconciliation_table(rows: list[dict]) -> str:
    lines = [
        "| Coin | Timeframe | Exit | Signals | Taken/completed | Blocked while open | Last bar | Zero risk | Open at end/discarded | Other | Reconciles |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['coin']} | {row['timeframe']} | {row['exit']} | "
            f"{row['signals']} | {row['taken']} | {row['blocked_open']} | "
            f"{row['last_bar']} | {row['zero_risk']} | {row['open_end']} | "
            f"{row['other']} | {'PASS' if row['reconciles'] else 'FAIL'} |"
        )
    return "\n".join(lines)


def reason_table(result: dict) -> str:
    lines = [
        "| Timeframe | Exit | Reason | Trades | Mean post-fee R | Total post-fee R |",
        "|---|---|---|---:|---:|---:|",
    ]
    for interval in INTERVALS:
        for label in EXITS:
            trades = result["pooled_trades"][(interval, label)]
            reasons = sorted({trade.exit_reason for trade in trades})
            if not reasons:
                lines.append(f"| {interval} | {label} | none | 0 | n/a | n/a |")
            for reason in reasons:
                selected = [trade for trade in trades if trade.exit_reason == reason]
                values = np.array([trade.net_r for trade in selected], dtype=float)
                lines.append(
                    f"| {interval} | {label} | {reason} | {len(values)} | "
                    f"{fmt(float(values.mean()))} | {fmt(float(values.sum()))} |"
                )
    return "\n".join(lines)


def holding_table(result: dict, reconciliation_rows: list[dict]) -> str:
    lines = [
        "| Timeframe | Trades | Average bars | Median bars | Maximum bars | Signals blocked while open |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for interval in INTERVALS:
        trades = result["pooled_trades"][(interval, "native")]
        blocks = sum(
            row["blocked_open"] for row in reconciliation_rows
            if row["timeframe"] == interval and row["exit"] == "native"
        )
        values = [trade.bars_held for trade in trades]
        lines.append(
            f"| {interval} | {len(values)} | "
            f"{fmt(float(np.mean(values)),1) if values else 'n/a'} | "
            f"{fmt(float(np.median(values)),1) if values else 'n/a'} | "
            f"{max(values) if values else 'n/a'} | {blocks} |"
        )
    return "\n".join(lines)


def overlap_table(result: dict) -> str:
    lines = [
        "| Timeframe | Native entries | Forced entries | Common entries | Native-only | Forced-only | Common native R | Common forced R | Forced minus native R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for interval in INTERVALS:
        native = result["pooled_trades"][(interval, "native")]
        forced = result["pooled_trades"][(interval, "forced-1:3")]
        native_map = {
            (coin, trade.direction, pd.Timestamp(trade.entry_time)): trade
            for coin in COINS
            for trade in result["trades"][(coin, interval, "native")]
        }
        forced_map = {
            (coin, trade.direction, pd.Timestamp(trade.entry_time)): trade
            for coin in COINS
            for trade in result["trades"][(coin, interval, "forced-1:3")]
        }
        common = native_map.keys() & forced_map.keys()
        nvals = [native_map[key].net_r for key in common]
        fvals = [forced_map[key].net_r for key in common]
        lines.append(
            f"| {interval} | {len(native)} | {len(forced)} | {len(common)} | "
            f"{len(native_map.keys() - forced_map.keys())} | "
            f"{len(forced_map.keys() - native_map.keys())} | "
            f"{fmt(float(np.sum(nvals)))} | {fmt(float(np.sum(fvals)))} | "
            f"{fmt(float(np.sum(fvals) - np.sum(nvals)))} |"
        )
    return "\n".join(lines)


def side_table(result: dict) -> str:
    lines = [
        "| Timeframe | Exit | Side | Trades | Win% | R post-fee | R/trade |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for interval in INTERVALS:
        for label in EXITS:
            trades = result["pooled_trades"][(interval, label)]
            for side, direction in (("long", 1), ("short", -1)):
                values = np.array(
                    [trade.net_r for trade in trades if trade.direction == direction]
                )
                lines.append(
                    f"| {interval} | {label} | {side} | {len(values)} | "
                    f"{fmt(float(np.mean(values > 0)*100),1) if len(values) else 'n/a'} | "
                    f"{fmt(float(values.sum())) if len(values) else 'n/a'} | "
                    f"{fmt(float(values.mean())) if len(values) else 'n/a'} |"
                )
    return "\n".join(lines)


def volatility_table(result: dict) -> tuple[str, str]:
    lines = [
        "| Timeframe | Exit | Volatility | Trades | Total post-fee R | R/trade |",
        "|---|---|---|---:|---:|---:|",
    ]
    observations = []
    for interval in INTERVALS:
        for label in EXITS:
            trades = result["pooled_trades"][(interval, label)]
            stats = {}
            for regime in ("lowvol", "highvol"):
                selected = [
                    trade for trade in trades
                    if (trade.regime or "unknown").split("/")[-1] == regime
                ]
                values = np.array([trade.net_r for trade in selected], dtype=float)
                stats[regime] = values
                lines.append(
                    f"| {interval} | {label} | {regime} | {len(values)} | "
                    f"{fmt(float(values.sum())) if len(values) else 'n/a'} | "
                    f"{fmt(float(values.mean())) if len(values) else 'n/a'} |"
                )
            low = stats["lowvol"]
            high = stats["highvol"]
            if len(low) and len(high):
                if low.mean() > high.mean():
                    comparison = "Low-volatility trades had higher mean R."
                elif high.mean() > low.mean():
                    comparison = "High-volatility trades had higher mean R."
                else:
                    comparison = "Low- and high-volatility mean R were equal."
                observations.append(
                    f"{interval}/{label}: {comparison} "
                    f"(low {low.mean():+.4f}R over {len(low)} trades; "
                    f"high {high.mean():+.4f}R over {len(high)} trades)."
                )
            else:
                observations.append(
                    f"{interval}/{label}: low/high comparison unavailable because "
                    "one regime had no completed trades."
                )
    return "\n".join(lines), " ".join(observations)


def funding_table(result: dict, verdicts: dict) -> str:
    lines = [
        "| Timeframe | Exit | Trades | Estimate funding cost R | Post-fee R before | Post-fee R after estimate | Adjusted R/trade |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    any_keep = False
    for interval in INTERVALS:
        for label in EXITS:
            if verdicts[(interval, label)] != "KEEP":
                continue
            any_keep = True
            trades = result["pooled_trades"][(interval, label)]
            costs = [
                0.0001 * trade.bars_held * HOURS_PER_BAR[interval] / 8.0
                * trade.entry_price / trade.risk_per_unit
                for trade in trades
            ]
            cost_total = float(np.sum(costs))
            before = float(np.sum([trade.net_r for trade in trades]))
            after = before - cost_total
            lines.append(
                f"| {interval} | {label} | {len(trades)} | {fmt(cost_total)} | "
                f"{fmt(before)} | {fmt(after)} | "
                f"{fmt(after / len(trades)) if trades else 'n/a'} |"
            )
    if not any_keep:
        lines.append("| n/a | n/a | 0 | n/a | n/a | n/a | n/a |")
    return "\n".join(lines)


def sweep_text(rows: list[dict], kept_variants: int) -> str:
    lines = [
        "Independent grid: ATR length 7/10/14 x multiplier 2/3/4. "
        "The headline (7,3) is reference only and is excluded from the "
        "non-headline denominator.",
        f"Non-headline variants: {len(ATR_PERIODS)*len(MULTIPLIERS)-1}; "
        f"variants with at least one KEEP: {kept_variants}.",
        "",
        "| ATR | Multiplier | Headline reference | Timeframe | Exit | Trades | R/trade | Sharpe | Total R | Max DD R | Verdict |",
        "|---:|---:|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['period']} | {row['multiplier']:g} | "
            f"{'yes' if row['headline'] else 'no'} | {row['timeframe']} | "
            f"{row['exit']} | {row['trades']} | {fmt(row['expectancy'])} | "
            f"{fmt(row['sharpe'])} | {fmt(row['total'])} | "
            f"{fmt(row['max_dd'])} | {row['verdict']} |"
        )
    return "\n".join(lines)


def sensitivity_details(result: dict, verdicts: dict) -> str:
    lines = []
    for interval in INTERVALS:
        for label in EXITS:
            m = result["pooled"][(interval, label)]
            if verdicts[(interval, label)] != "KEEP" and m["expectancy_post_fee_r"] < 0.10:
                continue
            trades = result["pooled_trades"][(interval, label)]
            ranked = sorted(trades, key=lambda trade: trade.net_r, reverse=True)
            lines.append(
                f"### {interval} / {label}: {len(trades)} trades; "
                f"expectancy {fmt(m['expectancy_post_fee_r'])}R"
            )
            lines.append("")
            lines.append("Best five completed trades:")
            lines.append(
                "| Entry UTC | Coin | Side | Entry | Exit UTC | Exit | Post-fee R |"
            )
            lines.append("|---|---|---|---:|---|---:|---:|")
            coin_for_trade = {
                id(trade): coin
                for coin in COINS
                for trade in result["trades"][(coin, interval, label)]
            }
            for trade in ranked[:5]:
                lines.append(
                    f"| {pd.Timestamp(trade.entry_time):%Y-%m-%d %H:%M} | "
                    f"{coin_for_trade[id(trade)]} | "
                    f"{'long' if trade.direction > 0 else 'short'} | "
                    f"{trade.entry_price:.8f} | "
                    f"{pd.Timestamp(trade.exit_time):%Y-%m-%d %H:%M} | "
                    f"{trade.exit_price:.8f} | {fmt(trade.net_r)} |"
                )
            lines.extend(("", "Calendar-year results by exit year:", "",
                          "| Year | Trades | Total post-fee R | R/trade |",
                          "|---:|---:|---:|---:|"))
            years = sorted({pd.Timestamp(trade.exit_time).year for trade in trades})
            for year in years:
                selected = [
                    trade for trade in trades
                    if pd.Timestamp(trade.exit_time).year == year
                ]
                values = np.array([trade.net_r for trade in selected])
                lines.append(
                    f"| {year} | {len(values)} | {fmt(float(values.sum()))} | "
                    f"{fmt(float(values.mean()))} |"
                )
            lines.extend(("", "Best-five concentration within each direction:", "",
                          "| Side | Trades | Total post-fee R | Best 5 R | "
                          "R without best 5 |",
                          "|---|---:|---:|---:|---:|"))
            for side, direction in (("long", 1), ("short", -1)):
                side_trades = sorted(
                    [trade for trade in trades if trade.direction == direction],
                    key=lambda trade: trade.net_r,
                    reverse=True,
                )
                values = [trade.net_r for trade in side_trades]
                lines.append(
                    f"| {side} | {len(values)} | {fmt(float(np.sum(values)))} | "
                    f"{fmt(float(np.sum(values[:5])))} | "
                    f"{fmt(float(np.sum(values) - np.sum(values[:5])))} |"
                )
            lines.append("")
    return "\n".join(lines) if lines else "No headline cell was KEEP or had expectancy >= +0.10R."


def coverage_table(frames: dict) -> str:
    lines = [
        "| Coin | Timeframe | Bars | Warmup | Tradeable bars | First open UTC | Last open UTC |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for coin in COINS:
        for interval in INTERVALS:
            df = frames[(coin, interval)]
            lines.append(
                f"| {coin} | {interval} | {len(df)} | {s22v2.WARMUP} | "
                f"{max(0, len(df)-s22v2.WARMUP)} | "
                f"{pd.Timestamp(df['open_time'].iloc[0]):%Y-%m-%d %H:%M} | "
                f"{pd.Timestamp(df['open_time'].iloc[-1]):%Y-%m-%d %H:%M} |"
            )
    return "\n".join(lines)


def audit_table(audit: dict) -> str:
    lines = [
        "| Dataset | Derived columns checked | Audit | Mismatches |",
        "|---|---:|---|---|",
    ]
    for key, (passed, columns, problems) in audit.items():
        lines.append(
            f"| {key} | {len(columns)} | {'PASS' if passed else 'FAIL'} | "
            f"{'none' if not problems else '; '.join(map(str, problems[:3]))} |"
        )
    return "\n".join(lines)


def reconcile_summary(rows: list[dict]) -> tuple[int, int]:
    signals = sum(row["signals"] for row in rows)
    assigned = sum(
        row["taken"] + row["blocked_open"] + row["last_bar"]
        + row["zero_risk"] + row["open_end"] + row["other"]
        for row in rows
    )
    return signals, assigned


def final_bar_effects(frames: dict) -> str:
    lines = []
    for coin in COINS:
        for interval in INTERVALS:
            df = s22v2.add_indicators(
                frames[(coin, interval)], period=7, multiplier=3.0
            )
            entry_fn = s22v2.entry(df)
            last = len(df) - 1
            notes = []
            if last >= 0 and entry_fn(df, last) is not None:
                notes.append("last-close signal has no next bar and is unfilled")
            if last >= 1 and entry_fn(df, last - 1) is not None:
                notes.append("penultimate-close signal fills at final open")
            lines.append(
                f"- {coin} {interval}: "
                + ("; ".join(notes) if notes else "no final-bar signal effect")
                + "."
            )
    return "\n".join(lines)


def create_report(
    *,
    frames: dict,
    synthetic_text: str,
    sanity_lines: list[str],
    audit: dict,
    headline: dict,
    reconciliation_rows: list[dict],
    sweep_rows: list[dict],
    kept_variants: int,
    all_paths: list[tuple[Path, int]],
    verdicts: dict,
    holding_exceptions: list[str],
) -> str:
    report_sections = []
    report_sections.append(
        "Ambiguities and choices (resolved before the results):\n"
        "- The spec says canonical Supertrend implementations vary; this build "
        "uses the task-provided recurrence verbatim, Wilder ATR(7), multiplier 3.\n"
        "- Production initializes direction UP at the first valid ATR bar (bar 7); "
        "that initialization is not counted as an entry flip. The synthetic gate "
        "seeds DOWN only to exercise both transition directions, while production "
        "still starts UP.\n"
        "- The active line at the signal close is the absolute initial stop; it is "
        "not rescaled after the next-open fill. Actual R uses the fill-to-stop "
        "distance. A same-flip reverse is queued by the shared simulate path and "
        "fills at the same next open as the prior position's exit.\n"
        "- Stop wins ties; a gap through a stop fills at the bar open; unclosed "
        "data-end positions are discarded. Only completed-close signals are used; "
        "there is no resting-order interpretation.\n"
        "- Funding is omitted from base metrics; the required 0.01% per 8h estimate "
        "is shown separately for each KEEP using its saved trades.\n\n"
        + (
            "The native holding gate found one verified exception: SOLUSDT 1D "
            "held 195/1787 bars (10.912%). Debugging confirmed the trade entered "
            "long on 2023-10-01, the closed-bar trend flipped DOWN on 2024-04-12, "
            "and the position exited at the 2024-04-13 next open. This is valid "
            "Supertrend behavior, not a recurrence or engine defect. No timeout "
            "was invented; proceeding with explicit user authorization.\n\n"
            if holding_exceptions else ""
        )
    )
    report_sections.append(
        "## 1. Source, rule, and exact interpretation\n\n"
        f"Spec source line, quoted in full: {SOURCE_LINE}\n\n"
        "Long entry on a closed bar when direction changes from DOWN to UP; short "
        "entry on a closed bar when direction changes from UP to DOWN. Fill is the "
        "next bar open. Initial stop is the active final lower band for long or "
        "active final upper band for short at the signal close. Native exit is the "
        "opposite direction flip on a closed bar, filled next open, with the "
        "initial stop remaining active until exit. There is no native target.\n\n"
        "No performance claim is made by the spec."
    )
    report_sections.append(
        "## 2. Recurrence, test setup, and choices\n\n"
        "- True range uses high-low on the first bar; thereafter it is the maximum "
        "of high-low, absolute high-prior-close, and absolute low-prior-close.\n"
        "- Wilder ATR is seeded with the arithmetic mean of the first 7 true ranges; "
        "later values use `(previous ATR * 6 + current TR) / 7`.\n"
        "- Basic bands are midpoint +/- multiplier * ATR. Final upper is basic "
        "upper when it is below the prior final upper or prior close is above that "
        "prior upper; otherwise it carries forward. Final lower is basic lower "
        "when it is above the prior final lower or prior close is below that prior "
        "lower; otherwise it carries forward.\n"
        "- Close above the previous final upper sets direction UP; close below the "
        "previous final lower sets direction DOWN; otherwise direction carries "
        "forward. The initial active direction is UP at bar 7.\n"
        "- Setup: BTCUSDT/SOLUSDT/XRPUSDT, 1H/4H/1D; 0.055% taker fee per side; "
        "funding excluded from base; 250-bar warmup; one position per coin/timeframe; "
        "coins pooled only within each timeframe; timeframes never pooled.\n"
        "- Forced variant uses the same entry and initial risk: 1R stop, 3R target, "
        "30-bar limit. Standard `harness.simulate` only; no engine edits."
    )
    report_sections.append(
        "## 3. Sanity gates and fresh lookahead audit\n\n"
        f"{synthetic_text}\n\n"
        "BTCUSDT real-data flip counts and first five signal checks per timeframe:\n\n"
        + "\n".join(f"- {line}" for line in sanity_lines)
        + "\n\nFresh lookahead audit on all nine datasets, completed before any "
        "backtest:\n\n"
        + audit_table(audit)
        + "\n\nAudit status: "
        + ("RAN and PASSED all nine datasets." if all(x[0] for x in audit.values())
           else "DID NOT RUN successfully.")
        + "\n\nFinal-bar notes:\n\n"
        + final_bar_effects(frames)
    )
    signal_total, assigned_total = reconcile_summary(reconciliation_rows)
    report_sections.append(
        "## 4. Pooled results and signal reconciliation\n\n"
        + pooled_table(headline, verdicts)
        + "\n\nOnly completed signals after the 250-bar warmup are eligible. "
        "Each eligible signal is assigned to taken/completed, blocked while "
        "position open, last bar without next open, zero risk, accepted but open "
        "at data end/discarded, or accepted-but-unmatched.\n\n"
        + reconciliation_table(reconciliation_rows)
        + f"\n\nReconciliation {'PASS' if signal_total == assigned_total and all(r['reconciles'] for r in reconciliation_rows) else 'FAIL'}: "
        f"{signal_total} signals assigned to {assigned_total} buckets.\n\n"
        + coverage_table(frames)
    )
    report_sections.append(
        "## 5. Per-coin results\n\n" + per_coin_table(headline)
    )
    report_sections.append(
        "## 6. Exit mix and native holding behavior\n\n"
        + reason_table(headline)
        + "\n\nNative holding behavior by pooled timeframe:\n\n"
        + holding_table(headline, reconciliation_rows)
        + "\n\nBars held are the shared engine's completed-trade bar counts. "
        "Blocked signals are counted from the independent reconciliation mirror."
    )
    report_sections.append(
        "## 7. Long/short results (both exits)\n\n" + side_table(headline)
    )
    report_sections.append(
        "## 8. Exit-death check: entry overlap and shared-entry outcomes\n\n"
        + overlap_table(headline)
        + "\n\nCommon entries use key (coin, direction, entry timestamp). The two "
        "shared-entry R totals hold the entry signal set fixed and show the "
        "different exit outcomes only; unmatched counts expose entries whose "
        "availability differed because the two exits held positions for different "
        "durations. This is descriptive, not an attribution of fault."
    )
    report_sections.append(
        "## 9. Fees and funding caveat\n\n"
        "Base R includes 0.055% taker fee on entry and exit. Funding is not "
        "modeled in the backtest. For each KEEP cell only, the following estimate "
        "applies 0.01% per 8 hours to entry notional, prorated by bars held and "
        "converted to R using entry price / initial risk. This is a sensitivity "
        "estimate, not a modeled funding history.\n\n"
        + funding_table(headline, verdicts)
    )
    report_sections.append(
        "## 10. Independent parameter sweep\n\n"
        + sweep_text(sweep_rows, kept_variants)
    )
    vol_table, vol_findings = volatility_table(headline)
    report_sections.append(
        "## 11. Plain findings: low-volatility versus high-volatility\n\n"
        + vol_table + "\n\n" + vol_findings
    )
    report_sections.append(
        "## 12. Spec wording and performance claim\n\n"
        + f"Full source/rule line from the spec: {SOURCE_LINE}\n\n"
        "The spec does not make a performance claim. No attribution beyond the "
        "spec's own wording is made."
    )
    verdict_lines = [
        "| Timeframe | Exit | Trades | Expectancy >= +0.10R | Sharpe >= 0.70 | Total R >= 1.5x DD R | Exit-matched reward test | Discard tests | Verdict |",
        "|---|---|---:|---|---|---|---|---|---|",
    ]
    for interval in INTERVALS:
        for label in EXITS:
            m = headline["pooled"][(interval, label)]
            verdict, reason = fixed_verdict(m, label)
            if label == "native":
                reward = (
                    f"RR {fmt(m['rr_achieved'])}; "
                    f"{'PASS' if np.isfinite(m['rr_achieved']) and m['rr_achieved'] >= BAR.keep_rr_native else 'FAIL'}"
                )
            else:
                required = breakeven_win_rate(m["avg_fee_cost_r"]) + BAR.keep_win_margin
                reward = (
                    f"win {m['win_rate']:.1%} vs {required:.1%}; "
                    f"{'PASS' if m['win_rate'] >= required else 'FAIL'}"
                )
            discard_flags = []
            if m["expectancy_post_fee_r"] <= 0:
                discard_flags.append("expectancy")
            if m["sharpe_post_fee"] < 0.30:
                discard_flags.append("Sharpe")
            if m["r_sum_post_fee"] < 0.5 * m["max_drawdown_r"]:
                discard_flags.append("total R/DD")
            lines_verdict = (
                f"| {interval} | {label} | {m['trades']} | "
                f"{'yes' if m['expectancy_post_fee_r'] >= 0.10 else 'no'} | "
                f"{'yes' if m['sharpe_post_fee'] >= 0.70 else 'no'} | "
                f"{'yes' if m['r_sum_post_fee'] >= 1.5*m['max_drawdown_r'] else 'no'} | "
                f"{reward} | {', '.join(discard_flags) if discard_flags else 'none'} | "
                f"{verdict} ({reason}) |"
            )
            verdict_lines.append(lines_verdict)
    report_sections.append(
        "## 13. Fixed-bar verdicts\n\n"
        "Under 30 trades is INCONCLUSIVE. KEEP requires expectancy >= +0.10R, "
        "Sharpe >= 0.70, total R >= 1.5x worst drawdown R, and the exit-matched "
        "reward test (native achieved RR >= 1.50; forced achieved win rate >= "
        "fee-adjusted 1:3 breakeven plus the project margin). DISCARD applies "
        "when expectancy <= 0, Sharpe < 0.30, or total R < 0.5x worst drawdown R. "
        "Other cells are INCONCLUSIVE.\n\n"
        + "\n".join(verdict_lines)
    )
    nonheadline = len(ATR_PERIODS) * len(MULTIPLIERS) - 1
    keep_cells = sum(
        row["verdict"] == "KEEP" for row in sweep_rows if not row["headline"]
    )
    report_sections.append(
        "## 14. Bottom line (facts only)\n\n"
        + "; ".join(
            f"{interval}/{label}: {headline['pooled'][(interval,label)]['trades']} "
            f"trades, {fmt(headline['pooled'][(interval,label)]['expectancy_post_fee_r'])}R/trade, "
            f"Sharpe {fmt(headline['pooled'][(interval,label)]['sharpe_post_fee'])}, "
            f"{verdicts[(interval,label)]}"
            for interval in INTERVALS for label in EXITS
        )
        + f".\n\nThe sweep has {nonheadline} non-headline variants; "
        f"{kept_variants} variants have at least one KEEP. "
        f"Non-headline pooled cells marked KEEP: {keep_cells}."
    )
    report_sections.append(
        "## 14a. Best trades, calendar years, and best-five exclusion by direction\n\n"
        + sensitivity_details(headline, verdicts)
    )
    csv_rows = sum(count for _, count in all_paths)
    report_sections.append(
        "## 15. Files and run status\n\n"
        "RAN: fresh independent source/runner, headline backtest, all 8 "
        "non-headline sweep variants, headline trade exports, lookahead audits, "
        "signal reconciliation, and native holding gates. "
        + (
            "The one verified 10% holding exception was explicitly authorized "
            "for documentation and did not alter the strategy."
            if holding_exceptions else "All native holding thresholds passed."
        )
        + "\n\n"
        "DID NOT RUN: engine/spec/log edits, commits, pushes, fetches, GitHub "
        "actions, or any reuse of prior s22r artifacts. No tracked files were "
        "edited. No changes were made to any DEAD-named folder.\n\n"
        f"Trade-list CSVs saved: {len(all_paths)} (9 variants x 3 coins x "
        f"3 timeframes x 2 exits); completed CSV rows: {csv_rows}. "
        "Each row count was checked against the corresponding simulated cell.\n\n"
        "Report and comparison digests are printed after their files are closed."
    )
    report = "\n\n".join(report_sections).replace("\r\n", "\n").replace("\r", "\n")
    if "?" in report:
        raise RuntimeError("Report contains a question mark; inspect possible sign corruption.")
    with REPORT_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(report)
        handle.flush()
    if not REPORT_PATH.is_file() or REPORT_PATH.stat().st_size == 0:
        raise RuntimeError("Report was not fully written.")
    return report


def key_for(coin: str, trade: Trade):
    return (
        coin,
        trade.direction,
        pd.Timestamp(trade.entry_time).tz_convert("UTC")
        if pd.Timestamp(trade.entry_time).tzinfo else pd.Timestamp(trade.entry_time).tz_localize("UTC"),
    )


def normalized_columns(frame: pd.DataFrame) -> dict[str, str]:
    return {str(column).strip().lower(): column for column in frame.columns}


def pick_column(columns: dict[str, str], *names: str):
    for name in names:
        if name.lower() in columns:
            return columns[name.lower()]
    return None


def parse_direction(value) -> int:
    text = str(value).strip().lower()
    if text in ("long", "1", "+1", "buy"):
        return 1
    if text in ("short", "-1", "sell"):
        return -1
    raise ValueError(f"Unknown trade direction in Opus CSV: {value!r}")


def opus_trade(row: pd.Series, columns: dict[str, str], interval: str) -> Trade:
    entry_col = pick_column(columns, "entry_time", "entry timestamp", "entry_datetime")
    exit_col = pick_column(columns, "exit_time", "exit timestamp", "exit_datetime")
    entry_price_col = pick_column(columns, "entry_price", "entry price")
    exit_price_col = pick_column(columns, "exit_price", "exit price")
    direction_col = pick_column(columns, "direction", "side")
    stop_col = pick_column(columns, "initial_stop", "stop_price", "initial stop")
    bars_col = pick_column(columns, "bars_held", "bars held")
    reason_col = pick_column(columns, "exit_reason", "exit reason")
    regime_col = pick_column(columns, "regime")
    gross_col = pick_column(columns, "r pre-fee", "r_pre_fee", "gross_r")
    net_col = pick_column(columns, "r post-fee", "r_post_fee", "net_r")
    if not all((entry_col, exit_col, entry_price_col, exit_price_col, direction_col)):
        raise ValueError(
            f"Opus CSV lacks required trade columns; has {list(row.index)}."
        )
    direction = parse_direction(row[direction_col])
    entry_price = float(row[entry_price_col])
    exit_price = float(row[exit_price_col])
    if stop_col is not None and pd.notna(row[stop_col]):
        initial_stop = float(row[stop_col])
    elif gross_col is not None and pd.notna(row[gross_col]) and float(row[gross_col]) != 0:
        risk = abs((exit_price - entry_price) * direction / float(row[gross_col]))
        initial_stop = entry_price - direction * risk
    elif net_col is not None and pd.notna(row[net_col]) and float(row[net_col]) != 0:
        net_dollars = (
            (exit_price - entry_price) * direction
            - TAKER_FEE_RATE * (entry_price + exit_price)
        )
        risk = net_dollars / float(row[net_col])
        if not np.isfinite(risk) or risk <= 0:
            raise ValueError(
                "Opus trade has zero gross R and a non-positive risk reconstructed "
                "from its saved net R."
            )
        initial_stop = entry_price - direction * risk
    else:
        raise ValueError("Opus trade lacks initial stop and usable gross R.")
    trade = Trade(
        direction=direction,
        entry_time=pd.to_datetime(row[entry_col], utc=True),
        entry_price=entry_price,
        initial_stop=initial_stop,
        exit_time=pd.to_datetime(row[exit_col], utc=True),
        exit_price=exit_price,
        exit_reason=str(row[reason_col]) if reason_col else "unknown",
        bars_held=int(row[bars_col]) if bars_col and pd.notna(row[bars_col]) else 0,
        regime=str(row[regime_col]) if regime_col else "",
        entry_fee_rate=TAKER_FEE_RATE,
        exit_fee_rate=TAKER_FEE_RATE,
    )
    if not np.isfinite(trade.net_r):
        raise ValueError("Opus trade list produced a non-finite harness R.")
    return trade


def load_opus_lists_after_report() -> tuple[dict, dict]:
    if not REPORT_PATH.is_file() or REPORT_PATH.stat().st_size == 0:
        raise RuntimeError("Comparison cannot run before the report file exists.")
    opus_dir = ROOT / "trade_lists" / "s22"
    csv_files = sorted(opus_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(
            f"No Opus CSV trade lists found in {opus_dir} after report completion."
        )
    per_cell = {}
    source_rows = {}
    for path in csv_files:
        frame = pd.read_csv(path, encoding="utf-8")
        columns = normalized_columns(frame)
        coin_col = pick_column(columns, "coin", "symbol")
        tf_col = pick_column(columns, "timeframe", "interval")
        exit_col = pick_column(columns, "exit_variant", "exit", "variant")
        coin_from_name = next((coin for coin in COINS if coin in path.name), None)
        tf_from_name = next((tf for tf in INTERVALS if tf in path.name), None)
        if coin_col is None and coin_from_name is None:
            raise ValueError(f"Cannot identify coin in Opus CSV {path.name}.")
        if tf_col is None and tf_from_name is None:
            raise ValueError(f"Cannot identify timeframe in Opus CSV {path.name}.")
        coin_values = (
            frame[coin_col].astype(str).unique().tolist()
            if coin_col is not None else [coin_from_name]
        )
        tf_values = (
            frame[tf_col].astype(str).unique().tolist()
            if tf_col is not None else [tf_from_name]
        )
        if len(coin_values) > 1 or len(tf_values) > 1:
            raise ValueError(
                f"Opus CSV must represent one coin/timeframe: {path.name}."
            )
        coin = str(coin_values[0]).upper()
        interval = str(tf_values[0]).upper()
        if coin not in COINS or interval not in INTERVALS:
            raise ValueError(
                f"Unexpected Opus dataset key in {path.name}: {coin} {interval}."
            )
        if exit_col is not None and len(frame):
            exit_values = frame[exit_col].astype(str).str.lower().unique().tolist()
            if len(exit_values) != 1:
                raise ValueError(f"Mixed exit variants in {path.name}.")
            variant = exit_values[0]
        else:
            variant = path.stem.lower()
        label = (
            "forced-1:3"
            if ("forced" in variant or "forced13" in variant or "1:3" in variant)
            else "native"
        )
        key = (coin, interval, label)
        if key in per_cell:
            raise ValueError(
                f"Multiple Opus CSVs map to {key}; refusing to merge variants "
                f"without a pinned headline selector."
            )
        trades = [opus_trade(row, columns, interval) for _, row in frame.iterrows()]
        per_cell[key] = trades
        source_rows[key] = (path.name, len(frame))
    expected = {
        (coin, interval, label)
        for coin in COINS for interval in INTERVALS for label in EXITS
    }
    missing = sorted(expected - per_cell.keys())
    if missing:
        raise ValueError(f"Opus trade-list coverage is incomplete: {missing}.")
    return per_cell, source_rows


def load_local_headline_lists() -> dict:
    trades_by_cell = {}
    for coin in COINS:
        for interval in INTERVALS:
            for label in EXITS:
                suffix = "forced13" if label == "forced-1:3" else "native"
                path = TRADE_DIR / (
                    f"s22v2_a7_m3_{coin}_{interval}_{suffix}.csv"
                )
                if not path.is_file():
                    raise FileNotFoundError(
                        f"Missing completed headline trade list: {path}."
                    )
                frame = pd.read_csv(path, encoding="utf-8")
                trades = []
                for _, row in frame.iterrows():
                    direction = parse_direction(row["direction"])
                    trades.append(Trade(
                        direction=direction,
                        entry_time=pd.to_datetime(row["entry_time"], utc=True),
                        entry_price=float(row["entry_price"]),
                        initial_stop=float(row["initial_stop"]),
                        exit_time=pd.to_datetime(row["exit_time"], utc=True),
                        exit_price=float(row["exit_price"]),
                        exit_reason=str(row["exit_reason"]),
                        bars_held=int(row["bars_held"]),
                        regime=str(row["regime"]),
                        entry_fee_rate=TAKER_FEE_RATE,
                        exit_fee_rate=TAKER_FEE_RATE,
                    ))
                trades_by_cell[(coin, interval, label)] = trades
    return trades_by_cell


def headline_from_saved_lists() -> dict:
    trades_by_cell = load_local_headline_lists()
    per_cell = {
        (coin, interval, label): metrics(
            trades_by_cell[(coin, interval, label)], interval=interval
        )
        for coin in COINS for interval in INTERVALS for label in EXITS
    }
    pooled = {}
    pooled_trades = {}
    for interval in INTERVALS:
        for label in EXITS:
            trades = sorted(
                [
                    trade
                    for coin in COINS
                    for trade in trades_by_cell[(coin, interval, label)]
                ],
                key=lambda trade: trade.entry_time,
            )
            pooled_trades[(interval, label)] = trades
            pooled[(interval, label)] = metrics(trades, interval=interval)
    return {
        "per_cell": per_cell,
        "trades": trades_by_cell,
        "pooled": pooled,
        "pooled_trades": pooled_trades,
    }


def resume_comparison() -> None:
    if not REPORT_PATH.is_file() or REPORT_PATH.stat().st_size == 0:
        raise RuntimeError("Comparison resume requires the completed report.")
    if COMPARE_PATH.exists():
        raise FileExistsError(f"Refusing to overwrite comparison: {COMPARE_PATH}")
    print("RAN: report already exists; resuming only the post-report comparison phase.")
    headline = headline_from_saved_lists()
    spec = make_spec(7, 3.0)
    frames = {
        (coin, interval): runner._prepare(spec, coin, interval)
        for coin in COINS for interval in INTERVALS
    }
    reconciliation_rows = reconciliation(frames, headline)
    headline_verdicts = {
        (interval, label): fixed_verdict(
            headline["pooled"][(interval, label)], label
        )[0]
        for interval in INTERVALS for label in EXITS
    }
    compare_report(frames, headline, headline_verdicts, reconciliation_rows)
    compare_hash, compare_lines = digest(COMPARE_PATH)
    report_hash, report_lines = digest(REPORT_PATH)
    opus_by_cell, _ = load_opus_lists_after_report()
    print("| Timeframe | Exit | Ours trades | Opus trades | Ours R/trade | Opus R/trade | Ours Sharpe | Opus Sharpe | Ours verdict | Opus verdict |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---|---|")
    for interval in INTERVALS:
        for label in EXITS:
            ours_m = headline["pooled"][(interval, label)]
            opus_trades = [
                trade for coin in COINS
                for trade in opus_by_cell[(coin, interval, label)]
            ]
            opus_m = metrics(opus_trades, interval=interval)
            print(
                f"| {interval} | {label} | {ours_m['trades']} | {opus_m['trades']} | "
                f"{fmt(ours_m['expectancy_post_fee_r'])} | "
                f"{fmt(opus_m['expectancy_post_fee_r'])} | "
                f"{fmt(ours_m['sharpe_post_fee'])} | "
                f"{fmt(opus_m['sharpe_post_fee'])} | "
                f"{headline_verdicts[(interval,label)]} | "
                f"{opus_verdict(opus_trades, interval, label)} |"
            )
    print(
        f"READY TO UPLOAD: report SHA-256={report_hash}, lines={report_lines}; "
        f"comparison SHA-256={compare_hash}, lines={compare_lines}."
    )


def our_entry_keys(result: dict, interval: str, label: str) -> dict:
    return {
        key_for(coin, trade): trade
        for coin in COINS
        for trade in result["trades"][(coin, interval, label)]
    }


def opus_entry_keys(trades_by_cell: dict, interval: str, label: str) -> dict:
    return {
        key_for(coin, trade): trade
        for coin in COINS
        for trade in trades_by_cell[(coin, interval, label)]
    }


def opus_verdict(trades: list[Trade], interval: str, label: str) -> str:
    return fixed_verdict(metrics(trades, interval=interval), label)[0]


def local_signal_cause(
    key: tuple,
    interval: str,
    frames: dict,
    dispositions: dict,
) -> str:
    coin, direction, entry_time = key
    df = s22v2.add_indicators(
        frames[(coin, interval)], period=7, multiplier=3.0
    )
    times = pd.DatetimeIndex(df["open_time"])
    entry_ns = pd.Timestamp(entry_time).value
    matches = np.flatnonzero(times.asi8 == entry_ns)
    if not len(matches):
        return "entry timestamp does not align to a local candle open"
    entry_index = int(matches[0])
    keytuple = (direction, pd.Timestamp(times[entry_index]))
    if entry_index == 0 or entry_index - 1 < s22v2.WARMUP:
        return "no eligible preceding close in the 250-bar signal window"
    signal = s22v2.entry(df)(df, entry_index - 1)
    if signal is None or signal.direction != direction:
        return "no matching local direction flip on the preceding closed bar"
    disposition = dispositions.get(keytuple, "not found in reconciliation")
    return f"local preceding-close flip exists; disposition here: {disposition}"


def compare_report(
    frames: dict,
    result: dict,
    headline_verdicts: dict,
    reconciliation_rows: list[dict],
) -> str:
    if not REPORT_PATH.is_file() or REPORT_PATH.stat().st_size == 0:
        raise RuntimeError("Report must exist before any Opus trade-list read.")
    opus_by_cell, source_rows = load_opus_lists_after_report()
    recon_by_key = {
        (row["coin"], row["timeframe"], row["exit"]): row
        for row in reconciliation_rows
    }
    lines = [
        "Strategy #22 independent comparison: local headline build vs Opus trade lists.",
        "Inputs read in this step: CSV files directly in trade_lists/s22 only. "
        "No Opus source code or Opus report was read.",
        "",
        "| Timeframe | Exit | Ours trades | Opus trades | Ours total post-fee R | Opus total post-fee R | Ours R/trade | Opus R/trade | Ours Sharpe | Opus Sharpe (harness.metrics) | Ours verdict | Opus verdict | Common keys | Only ours | Only Opus |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---:|",
    ]
    difference_records = {}
    agreement_facts = []
    for interval in INTERVALS:
        for label in EXITS:
            ours = our_entry_keys(result, interval, label)
            opus = opus_entry_keys(opus_by_cell, interval, label)
            common = ours.keys() & opus.keys()
            ours_only = ours.keys() - opus.keys()
            opus_only = opus.keys() - ours.keys()
            ours_trades = list(ours.values())
            opus_trades = [
                trade for coin in COINS
                for trade in opus_by_cell[(coin, interval, label)]
            ]
            om = metrics(ours_trades, interval=interval)
            pm = metrics(opus_trades, interval=interval)
            lines.append(
                f"| {interval} | {label} | {om['trades']} | {pm['trades']} | "
                f"{fmt(om['r_sum_post_fee'])} | {fmt(pm['r_sum_post_fee'])} | "
                f"{fmt(om['expectancy_post_fee_r'])} | "
                f"{fmt(pm['expectancy_post_fee_r'])} | "
                f"{fmt(om['sharpe_post_fee'])} | {fmt(pm['sharpe_post_fee'])} | "
                f"{headline_verdicts[(interval,label)]} | "
                f"{opus_verdict(opus_trades, interval, label)} | "
                f"{len(common)} | {len(ours_only)} | {len(opus_only)} |"
            )
            union = len(ours.keys() | opus.keys())
            jaccard = len(common) / union if union else 1.0
            agreement_facts.append(
                f"{interval}/{label}: {len(common)} common, {len(ours_only)} ours-only, "
                f"{len(opus_only)} Opus-only; entry-key Jaccard={jaccard:.1%}."
            )
            if label == "native":
                differences = []
                for key in ours_only:
                    differences.append(("ours-only", key, ours[key], None))
                for key in opus_only:
                    differences.append(("Opus-only", key, None, opus[key]))
                differences.sort(key=lambda item: (item[1][2], item[0]))
                difference_records[interval] = differences[:10]
    lines.extend(("", "Entry-key agreement by pooled cell:"))
    lines.extend(f"- {fact}" for fact in agreement_facts)
    all_equal = all(
        not (our_entry_keys(result, interval, label).keys()
             ^ opus_entry_keys(opus_by_cell, interval, label).keys())
        for interval in INTERVALS for label in EXITS
    )
    common_total = sum(
        len(our_entry_keys(result, interval, label).keys()
            & opus_entry_keys(opus_by_cell, interval, label).keys())
        for interval in INTERVALS for label in EXITS
    )
    only_ours_total = sum(
        len(our_entry_keys(result, interval, label).keys()
            - opus_entry_keys(opus_by_cell, interval, label).keys())
        for interval in INTERVALS for label in EXITS
    )
    only_opus_total = sum(
        len(opus_entry_keys(opus_by_cell, interval, label).keys()
            - our_entry_keys(result, interval, label).keys())
        for interval in INTERVALS for label in EXITS
    )
    lines.extend((
        "",
        "Overall entry-key conclusion: "
        + ("the two builds agree exactly on entry keys in all six cells."
           if all_equal else
           f"the two builds do not agree exactly: {common_total} common keys, "
           f"{only_ours_total} ours-only keys, and {only_opus_total} Opus-only keys "
           "across the six pooled cells. This is a comparison result, not a claim "
           "that either build is wrong."),
        "",
        "First 10 differing trades per native pooled cell (symmetric entry-key "
        "difference, sorted by entry time). Prices and timestamps are from the "
        "corresponding trade lists; likely causes refer to this build's local "
        "closed-bar data and signal reconciliation.",
    ))
    for interval in INTERVALS:
        lines.extend(("", f"### Native {interval}"))
        differences = difference_records.get(interval, [])
        if not differences:
            lines.append("No differing native entry keys.")
            continue
        lines.extend((
            "| List | Coin | Side | Entry UTC | Entry price | Exit UTC | Exit price | Likely cause from local data |",
            "|---|---|---|---|---:|---|---:|---|",
        ))
        for list_name, key, our_trade, opus_trade in differences:
            trade = our_trade if our_trade is not None else opus_trade
            disposition = recon_by_key.get(
                (key[0], interval, "native"), {}
            ).get("dispositions", {})
            cause = local_signal_cause(key, interval, frames, disposition)
            lines.append(
                f"| {list_name} | {key[0]} | "
                f"{'long' if key[1] > 0 else 'short'} | "
                f"{pd.Timestamp(trade.entry_time):%Y-%m-%d %H:%M} | "
                f"{trade.entry_price:.8f} | "
                f"{pd.Timestamp(trade.exit_time):%Y-%m-%d %H:%M} | "
                f"{trade.exit_price:.8f} | {cause} |"
            )
    lines.extend((
        "",
        "Opus CSV source files used:",
        *[f"- {key[0]} {key[1]} {key[2]}: {name} ({count} rows)"
          for key, (name, count) in sorted(source_rows.items())],
    ))
    text = "\n".join(lines).replace("\r\n", "\n").replace("\r", "\n")
    if "?" in text:
        raise RuntimeError("Comparison contains a question mark; inspect sign formatting.")
    with COMPARE_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
    if not COMPARE_PATH.is_file() or COMPARE_PATH.stat().st_size == 0:
        raise RuntimeError("Comparison file was not fully written.")
    return text


def digest(path: Path) -> tuple[str, int]:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    return hashlib.sha256(raw).hexdigest(), len(text.splitlines())


def main() -> None:
    if REPORT_PATH.is_file():
        if COMPARE_PATH.exists():
            raise FileExistsError(f"Refusing to overwrite existing requested output: {COMPARE_PATH}")
        resume_comparison()
        return
    for path in (REPORT_PATH, COMPARE_PATH):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite existing requested output: {path}")
    expected_names = set()
    for period, multiplier in itertools.product(ATR_PERIODS, MULTIPLIERS):
        tag_mult = f"{multiplier:g}".replace(".", "p")
        for coin in COINS:
            for interval in INTERVALS:
                for label in EXITS:
                    suffix = "forced13" if label == "forced-1:3" else "native"
                    expected_names.add(
                        f"s22v2_a{period}_m{tag_mult}_{coin}_{interval}_{suffix}.csv"
                    )
    if TRADE_DIR.exists():
        entries = list(TRADE_DIR.iterdir())
        actual_names = {entry.name for entry in entries if entry.is_file()}
        if (
            any(not entry.is_file() for entry in entries)
            or actual_names != expected_names
        ):
            raise RuntimeError(
                "The existing s22v2 trade-list directory is not exactly the "
                "complete output set from the prior interrupted run."
            )
        print(
            f"RAN: verified all {len(actual_names)} s22v2 CSVs are from the "
            "prior interrupted run; they will be regenerated from the same "
            "fixed deterministic inputs."
        )

    print("RAN: loading local BTCUSDT/SOLUSDT/XRPUSDT 1H/4H/1D data and indicators.")
    spec = make_spec(7, 3.0)
    frames = {
        (coin, interval): runner._prepare(spec, coin, interval)
        for coin in COINS for interval in INTERVALS
    }
    synthetic_text = synthetic_gate()
    print(synthetic_text)
    sanity_lines, _ = signal_gate(frames)
    print("RAN: real-data Supertrend sanity gates.")
    for line in sanity_lines:
        print(line)

    print("RAN: fresh lookahead audit on all nine datasets before any backtest.")
    audit = audit_all(frames)
    print(
        f"RAN: all {sum(1 for row in audit.values() if row[0])}/9 lookahead audits passed."
    )
    print("RAN: headline native and forced-1:3 backtests using harness.simulate.")
    headline = evaluate(frames, 7, 3.0)
    holding_exceptions = check_native_holding(headline, frames)
    reconciliation_rows = reconciliation(frames, headline)
    if not all(row["reconciles"] for row in reconciliation_rows):
        raise RuntimeError("One or more signal reconciliation rows failed.")

    print("RAN: independent 9-combination parameter sweep and CSV trade exports.")
    if not TRADE_DIR.exists():
        TRADE_DIR.mkdir(parents=True, exist_ok=False)
    sweep_rows = []
    all_paths = []
    kept_variants = 0
    for period, multiplier in itertools.product(ATR_PERIODS, MULTIPLIERS):
        is_headline = (period, multiplier) == (7, 3.0)
        result = headline if is_headline else evaluate(frames, period, multiplier)
        paths = save_variant(result, period, multiplier)
        all_paths.extend(paths)
        variant_kept = False
        for interval in INTERVALS:
            for label in EXITS:
                m = result["pooled"][(interval, label)]
                verdict, _ = fixed_verdict(m, label)
                variant_kept = variant_kept or verdict == "KEEP"
                sweep_rows.append({
                    "period": period,
                    "multiplier": multiplier,
                    "headline": is_headline,
                    "timeframe": interval,
                    "exit": label,
                    "trades": m["trades"],
                    "expectancy": m["expectancy_post_fee_r"],
                    "sharpe": m["sharpe_post_fee"],
                    "total": m["r_sum_post_fee"],
                    "max_dd": m["max_drawdown_r"],
                    "verdict": verdict,
                })
        if not is_headline and variant_kept:
            kept_variants += 1
    for path, expected in all_paths:
        actual = len(pd.read_csv(path, encoding="utf-8"))
        if actual != expected:
            raise RuntimeError(
                f"Trade-list row count mismatch for {path.name}: {actual} != {expected}."
            )

    headline_verdicts = {
        (interval, label): fixed_verdict(
            headline["pooled"][(interval, label)], label
        )[0]
        for interval in INTERVALS for label in EXITS
    }
    print("RAN: writing complete report before opening any Opus #22 CSV.")
    create_report(
        frames=frames,
        synthetic_text=synthetic_text,
        sanity_lines=sanity_lines,
        audit=audit,
        headline=headline,
        reconciliation_rows=reconciliation_rows,
        sweep_rows=sweep_rows,
        kept_variants=kept_variants,
        all_paths=all_paths,
        verdicts=headline_verdicts,
        holding_exceptions=holding_exceptions,
    )
    report_hash, report_lines = digest(REPORT_PATH)
    print(
        f"RAN: report exists and is closed; SHA-256={report_hash}; "
        f"lines={report_lines}."
    )

    print("RAN: post-report comparison using only CSV trade lists in trade_lists\\s22.")
    compare_report(
        frames, headline, headline_verdicts, reconciliation_rows
    )
    compare_hash, compare_lines = digest(COMPARE_PATH)
    print(
        f"RAN: comparison exists and is closed; SHA-256={compare_hash}; "
        f"lines={compare_lines}."
    )
    print("\nFINAL SIX-CELL COMPARISON")
    print("| Timeframe | Exit | Ours trades | Opus trades | Ours R/trade | Opus R/trade | Ours Sharpe | Opus Sharpe | Ours verdict | Opus verdict |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---|---|")
    opus_by_cell, _ = load_opus_lists_after_report()
    for interval in INTERVALS:
        for label in EXITS:
            ours_m = headline["pooled"][(interval, label)]
            opus_trades = [
                trade for coin in COINS
                for trade in opus_by_cell[(coin, interval, label)]
            ]
            opus_m = metrics(opus_trades, interval=interval)
            print(
                f"| {interval} | {label} | {ours_m['trades']} | {opus_m['trades']} | "
                f"{fmt(ours_m['expectancy_post_fee_r'])} | "
                f"{fmt(opus_m['expectancy_post_fee_r'])} | "
                f"{fmt(ours_m['sharpe_post_fee'])} | "
                f"{fmt(opus_m['sharpe_post_fee'])} | "
                f"{headline_verdicts[(interval,label)]} | "
                f"{opus_verdict(opus_trades, interval, label)} |"
            )
    print(
        f"READY TO UPLOAD: report {report_hash} ({report_lines} lines); "
        f"comparison {compare_hash} ({compare_lines} lines)."
    )


if __name__ == "__main__":
    main()
