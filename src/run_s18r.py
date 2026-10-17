from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

import runner
import s18r_failed_break as s18r
from discard_bar import BAR, describe, exit_death, verdict
from harness import Signal, Trade, forced_13_exit, metrics

NAME = "#18 Donchian failed-break reversion (independent build)"
COINS = ["BTCUSDT", "SOLUSDT", "XRPUSDT"]
INTERVALS = ["1H", "4H", "1D"]
EXITS = ("native", "forced-1:3")
HOURS_PER_BAR = {"1H": 1.0, "4H": 4.0, "1D": 24.0}
FORCED_LIMIT = 30
ROOT = Path(__file__).resolve().parent.parent
TRADE_DIR = ROOT / "trade_lists" / "s18r"
OPUS_TRADE_DIR = ROOT / "trade_lists" / "s18"
REPORT_PATH = Path(r"C:\Users\MarketCoder\Desktop\s18r_report.txt")
OPUS_REPORT_PATH = ROOT / "s18_report_final.txt"
COMPARE_PATH = Path(r"C:\Users\MarketCoder\Desktop\s18r_compare.txt")
SOURCE_LINE = (
    "**Source:** Richard Donchian, channel trading methodology as described in "
    "*Futures: An Investor's Guide to Trading Financial Futures* (1981); the "
    "failed-break reversion is this spec's explicit adaptation, not claimed as "
    "his canonical system. Enter short when close breaks above prior 20-bar high "
    "then closes back inside within 3 bars; long mirror below prior low and close "
    "back inside. Native exit at channel midpoint; no TP. Stop 1\u00d720-bar channel "
    "width beyond fill, placeholder."
)
CSV_COLUMNS = [
    "coin", "timeframe", "exit_variant", "direction", "entry_time",
    "entry_price", "exit_time", "exit_price", "exit_reason", "bars_held",
    "initial_stop", "R pre-fee", "R post-fee", "regime",
]


def fmt(value, digits=2):
    if value is None:
        return "n/a"
    try:
        if not np.isfinite(value):
            return "n/a"
    except (TypeError, ValueError):
        return "n/a"
    return f"{value:.{digits}f}"


def stop_tag(value):
    return f"{value:g}".replace(".", "p")


def make_spec(channel=20, window=3, stop_width=1.0):
    return runner.StrategySpec(
        name=f"{NAME} [channel={channel}, failure={window}, stop={stop_width:g}x width]",
        add_indicators=lambda df: s18r.add_indicators(
            df, channel_period=channel, failure_window=window, stop_width=stop_width
        ),
        entry=s18r.entry,
        native_exit=s18r.native_exit,
        warmup=s18r.WARMUP,
        native_time_limit=None,
    )


def variant_name(channel, window, stop_width):
    return f"channel={channel}, failure={window}, stop={stop_width:g}x width"


def write_variant_lists(result, channel, window, stop_width):
    paths = []
    prefix = f"s18r_c{channel}_w{window}_s{stop_tag(stop_width)}"
    for coin in COINS:
        for interval in INTERVALS:
            for label in EXITS:
                trades = sorted(result["trades"][(coin, interval, label)], key=lambda t: t.entry_time)
                rows = [{
                    "coin": coin, "timeframe": interval, "exit_variant": label,
                    "direction": "long" if trade.direction > 0 else "short",
                    "entry_time": pd.Timestamp(trade.entry_time).strftime("%Y-%m-%d %H:%M:%S%z"),
                    "entry_price": trade.entry_price,
                    "exit_time": pd.Timestamp(trade.exit_time).strftime("%Y-%m-%d %H:%M:%S%z"),
                    "exit_price": trade.exit_price, "exit_reason": trade.exit_reason,
                    "bars_held": trade.bars_held, "initial_stop": trade.initial_stop,
                    "R pre-fee": trade.gross_r, "R post-fee": trade.net_r, "regime": trade.regime,
                } for trade in trades]
                path = TRADE_DIR / f"{prefix}_{coin}_{interval}_{label.replace(':', '')}.csv"
                if path.exists():
                    raise FileExistsError(f"Refusing to overwrite trade list: {path}")
                pd.DataFrame(rows, columns=CSV_COLUMNS).to_csv(
                    path, index=False, encoding="utf-8", lineterminator="\n"
                )
                paths.append((path, len(rows), channel, window, stop_width, coin, interval, label))
    return paths


def _sim_reconcile(df, label, entry_fn, exit_fn, completed_trades):
    times = df["open_time"].reset_index(drop=True)
    closed_keys = {(t.direction, pd.Timestamp(t.entry_time)) for t in completed_trades}
    signals = [entry_fn(df, i) for i in range(len(df))]
    pending_entry = None
    pending_signal_key = None
    pending_exit_reason = None
    position = None
    accepted, completed_mirror, blocked_keys, open_end_keys = set(), set(), set(), set()
    counts = {"signals": 0, "taken": 0, "blocked_open": 0, "signal_while_open": 0,
              "last_bar": 0, "zero_risk": 0, "open_end": 0, "other": 0}
    time_limit = FORCED_LIMIT if label == "forced-1:3" else None
    for i in range(s18r.WARMUP, len(df)):
        row = df.iloc[i]
        if position is not None and pending_exit_reason is not None:
            completed_mirror.add((position.direction, pd.Timestamp(position.entry_time)))
            position, pending_exit_reason = None, None
        if position is None and pending_entry is not None:
            fill = float(row["open"])
            stop = pending_entry.resolve_stop(fill)
            if stop != fill:
                position = Trade(
                    direction=pending_entry.direction, entry_time=pd.Timestamp(times.iloc[i]),
                    entry_price=fill, initial_stop=stop, regime=str(row.get("regime", "")),
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
                row["low"] <= plan.stop_level if position.direction > 0 else row["high"] >= plan.stop_level
            )
            hit_target = plan.target_level is not None and (
                row["high"] >= plan.target_level if position.direction > 0 else row["low"] <= plan.target_level
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
        key = (signal.direction, pd.Timestamp(times.iloc[i + 1])) if i + 1 < len(df) else None
        if position is not None:
            counts["signal_while_open"] += 1
        if i + 1 >= len(df):
            counts["last_bar"] += 1
        elif signal.stop_frac is not None and signal.stop_frac <= 0:
            counts["zero_risk"] += 1
        elif pending_entry is None and (position is None or pending_exit_reason is not None):
            pending_entry, pending_signal_key = signal, key
        else:
            counts["blocked_open"] += 1
            if key is not None:
                blocked_keys.add(key)
    if position is not None:
        open_end_keys.add((position.direction, pd.Timestamp(position.entry_time)))
    counts["taken"] = len(accepted & closed_keys)
    counts["open_end"] = len(accepted & open_end_keys)
    counts["other"] = len(accepted - closed_keys - open_end_keys)
    assigned = sum(counts[k] for k in ("taken", "blocked_open", "last_bar", "zero_risk", "open_end", "other"))
    return {**counts, "reconciles": assigned == counts["signals"] and closed_keys == completed_mirror,
            "blocked_keys": blocked_keys}


def reconcile(spec, result):
    rows = []
    for coin in COINS:
        for interval in INTERVALS:
            df = runner._prepare(spec, coin, interval)
            entry_fn = spec.entry(df)
            for label in EXITS:
                exit_fn = spec.native_exit(df) if label == "native" else forced_13_exit
                counts = _sim_reconcile(df, label, entry_fn, exit_fn, result["trades"][(coin, interval, label)])
                counts["blocked_keys"] = {(coin, d, ts) for d, ts in counts["blocked_keys"]}
                rows.append({"coin": coin, "timeframe": interval, "exit": label, **counts})
    return rows

def result_table(result, summary):
    lines = [
        "| Timeframe | Exit | Trades | Win% | RR | R pre-fee | R post-fee | R/trade | Sharpe | Max DD % | Max DD R | R-recovery | Fee cost/trade | Verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for interval in INTERVALS:
        for label in EXITS:
            m = result["pooled"][(interval, label)]
            lines.append(
                f"| {interval} | {label} | {m['trades']} | {fmt(100*m['win_rate'],1)} | "
                f"{fmt(m['rr_achieved'])} | {fmt(m['r_sum_pre_fee'],2)} | "
                f"{fmt(m['r_sum_post_fee'],2)} | {fmt(m['expectancy_post_fee_r'],4)} | "
                f"{fmt(m['sharpe_post_fee'])} | {fmt(m['max_drawdown_pct'],2)} | "
                f"{fmt(m['max_drawdown_r'],2)} | {fmt(m['r_recovery'])} | "
                f"{fmt(m['avg_fee_cost_r'],4)} | **{summary[(interval,label)]}** |"
            )
    return "\n".join(lines)


def per_coin_table(result):
    lines = ["| Coin | Timeframe | Exit | Trades | Win% | R post-fee | R/trade | Sharpe | Fixed-bar verdict |",
             "|---|---|---|---:|---:|---:|---:|---:|---|"]
    for coin in COINS:
        for interval in INTERVALS:
            for label in EXITS:
                m = result["per_cell"][(coin, interval, label)]
                v, _ = verdict(m, label)
                lines.append(f"| {coin} | {interval} | {label} | {m['trades']} | {fmt(100*m['win_rate'],1)} | "
                             f"{fmt(m['r_sum_post_fee'],2)} | {fmt(m['expectancy_post_fee_r'],4)} | "
                             f"{fmt(m['sharpe_post_fee'])} | {v} |")
    return "\n".join(lines)


def side_table(result):
    lines = ["| Timeframe | Exit | Side | Trades | Win% | R post-fee | R/trade |", "|---|---|---|---:|---:|---:|---:|"]
    for interval in INTERVALS:
        for label in EXITS:
            trades = result["trades"][(interval, label)]
            for side, direction in (("long", 1), ("short", -1)):
                values = np.array([t.net_r for t in trades if t.direction == direction], dtype=float)
                lines.append(f"| {interval} | {label} | {side} | {len(values)} | "
                             f"{fmt(100*np.mean(values > 0),1) if len(values) else 'n/a'} | "
                             f"{fmt(values.sum(),2) if len(values) else 'n/a'} | "
                             f"{fmt(values.mean(),4) if len(values) else 'n/a'} |")
    return "\n".join(lines)


def concentration_table(result):
    lines = ["| Timeframe | Exit | Trades | Best trade R | Best 5 R | R without best 5 |", "|---|---|---:|---:|---:|---:|"]
    for interval in INTERVALS:
        for label in EXITS:
            values = np.array([t.net_r for t in result["trades"][(interval,label)] if np.isfinite(t.net_r)])
            ordered = np.sort(values)[::-1]
            lines.append(f"| {interval} | {label} | {len(values)} | {fmt(ordered[0],3) if len(values) else 'n/a'} | "
                         f"{fmt(ordered[:5].sum(),3) if len(values) else 'n/a'} | "
                         f"{fmt(values.sum()-ordered[:5].sum(),3) if len(values) else 'n/a'} |")
    return "\n".join(lines)


def native_holding_section(result, reconciliation):
    lines = ["| Timeframe | Avg bars | Median bars | Max bars | Exit reason | Trades | Mean post-fee R | Blocked: position open | Signals fired while open |",
             "|---|---:|---:|---:|---|---:|---:|---:|---:|"]
    for interval in INTERVALS:
        trades = result["trades"][(interval,"native")]
        groups = {"midpoint": [], "stop": [], "other": []}
        for trade in trades:
            groups[trade.exit_reason if trade.exit_reason in ("midpoint", "stop") else "other"].append(trade.net_r)
        held = [trade.bars_held for trade in trades]
        cells = [row for row in reconciliation if row["timeframe"] == interval and row["exit"] == "native"]
        blocked = sum(row["blocked_open"] for row in cells)
        while_open = sum(row["signal_while_open"] for row in cells)
        for reason in ("midpoint", "stop", "other"):
            values = groups[reason]
            lines.append(f"| {interval} | {fmt(np.mean(held),2) if held else 'n/a'} | "
                         f"{fmt(np.median(held),2) if held else 'n/a'} | {max(held) if held else 'n/a'} | "
                         f"{reason} | {len(values)} | {fmt(np.mean(values),4) if values else 'n/a'} | {blocked} | {while_open} |")
    return "\n".join(lines)


def reason_section(result):
    lines = ["| Timeframe | Exit | Exit reason | Trades | Mean post-fee R |", "|---|---|---|---:|---:|"]
    for interval in INTERVALS:
        for label in EXITS:
            grouped = {}
            for trade in result["trades"][(interval,label)]:
                grouped.setdefault(trade.exit_reason or "other", []).append(trade.net_r)
            for reason, values in sorted(grouped.items()):
                lines.append(f"| {interval} | {label} | {reason} | {len(values)} | {fmt(np.mean(values),4)} |")
    return "\n".join(lines)


def final_bar_notes(prepared, result, spec):
    lines = []
    for coin in COINS:
        for interval in INTERVALS:
            df = prepared[(coin,interval)]
            entry_fn = spec.entry(df)
            final_time = pd.Timestamp(df["open_time"].iloc[-1])
            effects = []
            if len(df) > 1 and entry_fn(df,len(df)-2) is not None:
                effects.append("penultimate-bar signal fills at final open")
            entries = sum(pd.Timestamp(t.entry_time) == final_time for name in EXITS for t in result["trades"][(coin,interval,name)])
            exits = sum(pd.Timestamp(t.exit_time) == final_time for name in EXITS for t in result["trades"][(coin,interval,name)])
            if entries: effects.append(f"{entries} completed entry stamps at final open")
            if exits: effects.append(f"{exits} exits stamped at final bar")
            if entry_fn(df,len(df)-1) is not None: effects.append("final-close signal has no next bar and is unfilled")
            lines.append(f"- {coin} {interval}: final bar opens {final_time:%Y-%m-%d %H:%M} UTC; " +
                         ("; ".join(effects) if effects else "no final-bar signal or completed trade entry/exit is affected") + ".")
    return "\n".join(lines)


def sweep_text(sweep_results):
    lines = ["| Variant | Changed factor | Timeframe | Exit | Trades | Win% | Post-fee total R | R/trade | Sharpe | Verdict |",
             "|---|---|---|---|---:|---:|---:|---:|---:|---|"]
    for name, factor, result, is_headline in sweep_results:
        suffix = " (headline reference)" if is_headline else ""
        for interval in INTERVALS:
            for label in EXITS:
                m = result["pooled"][(interval,label)]
                v, _ = verdict(m,label)
                lines.append(f"| {name}{suffix} | {factor} | {interval} | {label} | {m['trades']} | "
                             f"{fmt(100*m['win_rate'],1)} | {fmt(m['r_sum_post_fee'],2)} | "
                             f"{fmt(m['expectancy_post_fee_r'],4)} | {fmt(m['sharpe_post_fee'])} | {v} |")
    return "\n".join(lines)


def market_context(result):
    lines = ["| Timeframe | Exit | Volatility | Trades | Post-fee total R | R/trade |", "|---|---|---|---:|---:|---:|"]
    for interval in INTERVALS:
        for label in EXITS:
            buckets = {"lowvol": [], "highvol": [], "unknown": []}
            for trade in result["trades"][(interval,label)]:
                vol = (trade.regime or "unknown").rsplit("/",1)[-1]
                buckets.setdefault(vol if vol in buckets else "unknown", []).append(trade.net_r)
            for bucket, values in buckets.items():
                arr = np.array(values,dtype=float)
                lines.append(f"| {interval} | {label} | {bucket} | {len(arr)} | {fmt(arr.sum(),2) if len(arr) else 'n/a'} | {fmt(arr.mean(),4) if len(arr) else 'n/a'} |")
    return "\n".join(lines) + "\n\nRegime labels are descriptive and do not affect decisions."


def fixed_verdict_section(result, summary):
    lines = ["| Timeframe | Exit | Trades >=30 | Expectancy >=0.10 | Sharpe >=0.70 | Recovery >=1.5 | Reward test | Discard conditions | Verdict |",
             "|---|---|---|---|---|---|---|---|---|"]
    for interval in INTERVALS:
        for label in EXITS:
            m = result["pooled"][(interval,label)]
            if label == "forced-1:3":
                required = (1.0 + m["avg_fee_cost_r"]) / 4.0 + BAR.keep_win_margin
                reward = f"win {fmt(100*m['win_rate'],1)}% {'PASS' if m['win_rate'] >= required else 'FAIL'}; need {required:.1%}"
            else:
                reward = f"RR {fmt(m['rr_achieved'])} {'PASS' if m['rr_achieved'] >= BAR.keep_rr_native else 'FAIL'}; need 1.50"
            exp, sharpe, recovery = m["expectancy_post_fee_r"], m["sharpe_post_fee"], m["r_recovery"]
            discard = f"exp<=0 {'yes' if exp <= 0 else 'no'}; Sharpe<0.30 {'yes' if sharpe < BAR.discard_sharpe else 'no'}; recovery<0.50 {'yes' if recovery < BAR.discard_r_recovery else 'no'}"
            lines.append(f"| {interval} | {label} | {m['trades'] >= BAR.min_trades} ({m['trades']}) | "
                         f"{exp >= BAR.keep_expectancy_r} ({fmt(exp,4)}) | {sharpe >= BAR.keep_sharpe} ({fmt(sharpe)}) | "
                         f"{recovery >= BAR.keep_r_recovery} ({fmt(recovery)}) | {reward} | {discard} | {summary[(interval,label)]} |")
    return "\n".join(lines)

def exit_death_rows(result):
    lines = []
    for interval in INTERVALS:
        native = result["pooled"][(interval,"native")]
        forced = result["pooled"][(interval,"forced-1:3")]
        native_keys = {(coin,t.direction,pd.Timestamp(t.entry_time)) for coin in COINS for t in result["trades"][(coin,interval,"native")]}
        forced_keys = {(coin,t.direction,pd.Timestamp(t.entry_time)) for coin in COINS for t in result["trades"][(coin,interval,"forced-1:3")]}
        union = native_keys | forced_keys
        overlap = 100*len(native_keys & forced_keys)/len(union) if union else float("nan")
        dead, _ = exit_death(native,forced)
        lines.append(f"| {interval} | {native['trades']} | {forced['trades']} | {fmt(overlap,1)}% | "
                     f"{fmt(native['expectancy_post_fee_r'],4)} | {fmt(forced['expectancy_post_fee_r'],4)} | {'yes' if dead else 'no'} |")
    return lines


def variant_configs():
    return [
        (10,3,1.0,variant_name(10,3,1.0),"channel",False),
        (55,3,1.0,variant_name(55,3,1.0),"channel",False),
        (20,1,1.0,variant_name(20,1,1.0),"failure window",False),
        (20,5,1.0,variant_name(20,5,1.0),"failure window",False),
        (20,3,0.5,variant_name(20,3,0.5),"stop width",False),
        (20,3,1.5,variant_name(20,3,1.5),"stop width",False),
    ]


def report_text(result, summary, audit, coverage_rows, reconciliation, prepared,
                headline_paths, sweep_results, source_hash, runner_hash, all_paths):
    audit_rows = [f"| {name} | {len(cols)} | {'PASS' if ok else 'FAIL'} | {len(problems)} | "
                  f"{', '.join(map(str,problems[:3])) if problems else 'none'} |"
                  for name,(ok,cols,problems) in audit.items()]
    rec_lines = [f"| {r['coin']} | {r['timeframe']} | {r['exit']} | {r['signals']} | {r['taken']} | "
                 f"{r['blocked_open']} | {r['last_bar']} | {r['zero_risk']} | {r['open_end']} | {r['other']} | "
                 f"{'PASS' if r['reconciles'] else 'FAIL'} |" for r in reconciliation]
    signal_total = sum(r["signals"] for r in reconciliation)
    assigned = sum(r[k] for r in reconciliation for k in ("taken","blocked_open","last_bar","zero_risk","open_end","other"))
    coverage = "| Coin | Timeframe | Bars | Warmup bars | History days after warmup |\n|---|---|---:|---:|---:|\n" + "\n".join(
        f"| {coin} | {interval} | {bars} | {s18r.WARMUP} | {days:.1f} |" for coin,interval,bars,days in coverage_rows)
    result_rows = "\n".join(result_table(result,summary).splitlines()[2:])
    summary = "; ".join(f"{interval}/{label}: {result['pooled'][(interval,label)]['trades']} trades, "
                         f"{result['pooled'][(interval,label)]['expectancy_post_fee_r']:+.4f}R/trade, "
                         f"Sharpe {fmt(result['pooled'][(interval,label)]['sharpe_post_fee'])}, {summary[(interval,label)]}"
                         for interval in INTERVALS for label in EXITS)
    headline_rows = sum(item[1] for item in headline_paths)
    count_nonheadline = len({item[0] for item in sweep_results if not item[3]})
    template = f'''## 1. Rule and source

Ambiguities and choices, listed before the results:
- Failure-window count: the breakout close is bar 0; only the next 3 completed closes (bars 1 through 3) can fail. A re-entry on the third subsequent bar is valid.
- Breakout/re-entry boundary: breakout is a strict close beyond the prior channel; back inside means the close is inclusively between that completed bar's prior-channel low and high.
- Channel during the episode: upper/lower bounds and width are recomputed each completed bar from the preceding N bars, excluding the current bar; the breakout's original channel is not frozen.
- Second breakout while waiting: one contiguous outside-close episode can produce at most one failure event. The window is not reset by another outside close, and an opposite-side close does not replace the stored direction. After expiry, the episode remains latched until a close returns inside, preventing repeated events from a continuing outside run.
- Stop reference: width is measured on the failure/re-entry signal bar, multiplied by the stop-width parameter, and frozen as a fraction of that signal close. `Signal.stop_frac` applies that fraction to the next-open fill, so price distance scales across an entry gap; the stop is fill-relative, not an absolute signal-close price.
- Midpoint: arithmetic mean of the current prior-channel high and low, recomputed each completed bar. A close reaching/passing it queues a market exit for the next open. The spec does not say limit; this uses standard close-signal `simulate`, not a resting-order path.
- Fixed setup: BTCUSDT/SOLUSDT/XRPUSDT, 1H/4H/1D, 0.055% taker fee per side, funding omitted, closed-bar signal/next-open fill, stop wins ties, gap-through stop fills at open, open positions at data end discarded, one position per coin/timeframe, coins pooled by timeframe. Forced 1:3 uses 1R stop, 3R target and 30-bar limit.

Spec source line, verbatim: \n\n{SOURCE_LINE} The failed-break rule is the spec's adaptation, not Donchian's canonical system. The spec makes no performance claim.

## 2. Parameters and state machine

Headline: 20-bar channel, 3 subsequent-bar failure window, 1.0x channel-width stop, 250-bar warmup; no native profit target. A close above the upper channel arms a short failure; a close below the lower channel arms a long failure. A valid return inside within the window emits one signal for that episode. The native midpoint trigger is close-based and fills next open; stop is intrabar.

Sweep varies each parameter independently around the headline (not a Cartesian grid): channel 10/20/55; failure window 1/3/5; stop width 0.5/1/1.5. The headline is a reference and excluded from the denominator: 6 unique non-headline variants.

## 3. Fresh lookahead audit, coverage, and final-bar impact

Fresh headline cut-and-recompute audit: {sum(bool(v[0]) for v in audit.values())}/{len(audit)} datasets passed; {sum(len(v[1]) for v in audit.values())} derived columns checked.

| Dataset | Derived columns checked | Audit | Mismatches | Problems |
|---|---:|---|---:|---|
{chr(10).join(audit_rows)}

Rolling extrema exclude the current bar, and the breakout/failure state machine processes completed bars strictly forward.

{coverage}

Final-bar effects:
{chr(10).join(final_bar_notes(prepared,result,make_spec()).splitlines())}

## 4. Results and signal reconciliation

| Timeframe | Exit | Trades | Win% | RR | R pre-fee | R post-fee | R/trade | Sharpe | Max DD % | Max DD R | R-recovery | Fee cost/trade | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
{result_rows}

Every generated valid signal is assigned once: taken and completed, blocked by an open position, final-bar/no-next-open, zero-risk, accepted but open at end/discarded, or other.

| Coin | Timeframe | Exit | Signals | Taken/completed | Blocked/open | Last bar | Zero risk | Open at end/discarded | Other | Reconciles? |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(rec_lines)}

Reconciliation {'PASSES' if all(r['reconciles'] for r in reconciliation) and signal_total == assigned else 'FAILS'}: {signal_total} signals, {assigned} assignments. Headline files: {len(headline_paths)} CSVs, {headline_rows} completed rows.

## 5. Per-coin results and sampling context

{per_coin_table(result)}

Mean post-fee R / standard error, descriptive only:

| Timeframe | Exit | Trades | t-stat | Rough noise read |
|---|---|---:|---:|---|
{chr(10).join(tstat_rows(result))}

## 6. Concentration check

{concentration_table(result)}

## 7. Long/short breakdown

{side_table(result)}

## 8. Exit-death and reason checks

| Timeframe | Native trades | Forced trades | Entry-key overlap | Native R/trade | Forced R/trade | Exit-death? |
|---|---:|---:|---:|---:|---:|---|
{chr(10).join(exit_death_rows(result))}

Entry-key overlap is the shared share of the union of completed (coin, direction, entry-time) keys.

### 8a. Exit-reason split and mean post-fee R

{reason_section(result)}

### 8b. Signal/entry behavior

Blocked events are reconciled per coin/timeframe in section 4. The one-position constraint is independent for every coin and timeframe; no cross-coin lock is applied.

### 8c. Native-exit holding behavior

{native_holding_section(result,reconciliation)}

Average/median/maximum use completed native trades' engine `bars_held`. Signals fired while open counts each valid native entry event evaluated while a position remained active, whether or not a pending next-open exit allowed a reversal.

## 9. Fees and funding

Fees are included at 0.055% taker on entry and exit. Funding was not modeled; no funding-adjusted outcome is claimed.

## 10. Parameter sensitivity sweep

{sweep_text(sweep_results)}

Six non-headline variants were tested independently; the headline reference is included and excluded from the denominator. No Cartesian sweep was added.

## 11. Market-condition breakdown

{market_context(result)}

Regime labels are descriptive only and do not affect signal, entry, or exit decisions.

## 12. Source comparison and discrepancies

The source note identifies this failed-break rule as an explicit adaptation, not a canonical Donchian system. No source-system performance claim is made. Execution choices not pinned by the spec are disclosed in section 1. Opus source code was not read.

## 13. Fixed discard-bar verdict per cell

The shared project fixed bar is applied after fees:

```text
{describe()}
```

{fixed_verdict_section(result, { (interval,label): verdict(result['pooled'][(interval,label)],label)[0] for interval in INTERVALS for label in EXITS })}

## 14. Bottom line (facts only)

{summary}

## 14a. Concentration and parameter stability detail

The headline is a reference, not an optimized replacement. Each of the three factors was varied independently with other headline settings held constant. Section 6 reports best-trade/top-five concentration and residual R. Non-headline parameter variants in this report: {count_nonheadline}.

## 15. Files created

Dry run: no tracked files, engine, specs, strategy logs, or Opus files were modified; no commit or push was performed. Independent source files and CSVs are new outputs only.

| File | Lines | SHA-256 |
|---|---:|---|
| src/s18r_failed_break.py | {len(Path(s18r.__file__).read_text(encoding='utf-8').splitlines())} | {source_hash} |
| src/run_s18r.py | {len(Path(__file__).read_text(encoding='utf-8').splitlines())} | {runner_hash} |

Trade-list CSVs under `trade_lists/s18r/`: {len(all_paths)} files across headline plus six independent sweep variants; total completed rows: {sum(item[1] for item in all_paths)}. Headline rows: {headline_rows}.\n'''
    return template


def tstat_rows(result):
    lines = []
    for interval in INTERVALS:
        for label in EXITS:
            values = np.array([t.net_r for t in result["trades"][(interval,label)]],dtype=float)
            stat = float(values.mean()/(values.std(ddof=1)/math.sqrt(len(values)))) if len(values)>1 and values.std(ddof=1)>0 else float("nan")
            read = "positive beyond 2" if stat >= 2 else "negative beyond -2" if stat <= -2 else "inside/indeterminate"
            lines.append(f"| {interval} | {label} | {len(values)} | {fmt(stat,2)} | {read} |")
    return lines

def find_col(frame, candidates):
    available = {str(col).strip().lower().replace("_"," "): col for col in frame.columns}
    for candidate in candidates:
        name = candidate.lower().replace("_"," ")
        if name in available:
            return available[name]
    return None


def direction_value(value):
    text = str(value).strip().lower()
    if text in ("1", "+1", "long", "buy"):
        return 1
    if text in ("-1", "short", "sell"):
        return -1
    raise ValueError(f"Unrecognized trade direction {value!r}.")


def as_utc(value):
    return pd.Timestamp(pd.to_datetime(value,utc=True))


def opus_headline_file(path):
    name = path.name.lower()
    tests = (
        (r"(?:^|[_-])(?:c|ch|channel|entry)[_-]?10(?:[_\-.]|$)",False),
        (r"(?:^|[_-])(?:c|ch|channel|entry)[_-]?55(?:[_\-.]|$)",False),
        (r"(?:^|[_-])(?:w|window|fail)[_-]?1(?:[_\-.]|$)",False),
        (r"(?:^|[_-])(?:w|window|fail)[_-]?5(?:[_\-.]|$)",False),
        (r"(?:^|[_-])(?:s|stop)[_-]?0[._-]?5(?:[_\-.]|$)",False),
        (r"(?:^|[_-])(?:s|stop)[_-]?1[._-]?5(?:[_\-.]|$)",False),
        (r"(?:^|[_-])(?:c|ch|channel|entry)[_-]?20(?:[_\-.]|$)",True),
        (r"(?:^|[_-])(?:w|window|fail)[_-]?3(?:[_\-.]|$)",True),
        (r"(?:^|[_-])(?:s|stop)[_-]?1(?:[_\-.]|$)",True),
    )
    found = [(re.search(pattern,name), expected) for pattern,expected in tests]
    recognized = [expected for match,expected in found if match]
    return not recognized or all(recognized)


def opus_trade_data(trade_dir):
    if not trade_dir.is_dir():
        raise FileNotFoundError(f"Required Opus trade-list directory is missing: {trade_dir}")
    files = sorted(p for p in trade_dir.rglob("*.csv") if opus_headline_file(p))
    if not files:
        raise FileNotFoundError(f"No headline Opus trade-list CSVs found under {trade_dir}")
    trades = {(tf,label):{} for tf in INTERVALS for label in EXITS}
    for path in files:
        frame = pd.read_csv(path,encoding="utf-8")
        if frame.empty:
            continue
        coin_col = find_col(frame,["coin","symbol","market"])
        tf_col = find_col(frame,["timeframe","interval"])
        exit_col = find_col(frame,["exit_variant","exit","exit type"])
        direction_col = find_col(frame,["direction","side"])
        entry_time_col = find_col(frame,["entry_time","entry timestamp","entry_time_utc"])
        entry_price_col = find_col(frame,["entry_price","entry price"])
        exit_time_col = find_col(frame,["exit_time","exit timestamp","exit_time_utc"])
        exit_price_col = find_col(frame,["exit_price","exit price"])
        net_r_col = find_col(frame,["R post-fee","R post fee","net_r","post_fee_r"])
        if direction_col is None or entry_time_col is None:
            raise ValueError(f"Required entry-key columns are absent from {path.name}.")
        filename = path.name.upper()
        for _,row in frame.iterrows():
            timeframe = str(row[tf_col]).upper() if tf_col else next((tf for tf in INTERVALS if tf in filename),"")
            if timeframe not in INTERVALS:
                continue
            if exit_col:
                exit_text = str(row[exit_col]).lower().replace("_","-")
                label = "forced-1:3" if "forced" in exit_text or "1:3" in exit_text or exit_text == "13" else "native"
            else:
                label = "forced-1:3" if "FORCED" in filename or "FORCED13" in filename else "native"
            coin = str(row[coin_col]).upper() if coin_col else next((c for c in COINS if c in filename),"")
            if coin not in COINS:
                continue
            direction = direction_value(row[direction_col])
            entry_time = as_utc(row[entry_time_col])
            key = (coin,direction,entry_time)
            trades[(timeframe,label)][key] = {
                "coin":coin,"direction":direction,"entry_time":entry_time,
                "entry_price":float(row[entry_price_col]) if entry_price_col and pd.notna(row[entry_price_col]) else float("nan"),
                "exit_time":as_utc(row[exit_time_col]) if exit_time_col and pd.notna(row[exit_time_col]) else pd.NaT,
                "exit_price":float(row[exit_price_col]) if exit_price_col and pd.notna(row[exit_price_col]) else float("nan"),
                "net_r":float(row[net_r_col]) if net_r_col and pd.notna(row[net_r_col]) else float("nan"),
                "source_file":path.name,
            }
    return trades,[p.name for p in files]


def parse_float(value):
    value = str(value).replace(",","").replace("%","").strip().replace("+","")
    try:
        return float(value)
    except ValueError:
        return None


def opus_report_summary(path):
    text = path.read_text(encoding="utf-8")
    output = {}
    headers = []
    for raw in text.splitlines():
        if not raw.lstrip().startswith("|"):
            continue
        cells = [cell.strip().replace("**","") for cell in raw.strip().strip("|").split("|")]
        if cells and cells[0].lower() in ("timeframe","interval"):
            headers = [re.sub(r"[^a-z0-9]+", " ", cell.lower()).strip() for cell in cells]
            continue
        if len(cells) < 3 or cells[0] not in INTERVALS or cells[1] not in EXITS:
            continue
        try:
            count = int(cells[2].replace(",",""))
        except ValueError:
            continue
        def idx(names):
            normalized = {re.sub(r"[^a-z0-9]+", " ", name.lower()).strip() for name in names}
            return next((i for i,h in enumerate(headers) if h in normalized),None)
        count_i = idx({"trades","n"})
        total_i = idx({"r post fee","post fee total r","total r post fee"})
        sharpe_i = idx({"sharpe","sharpe post fee"})
        verdict_i = idx({"verdict","fixed bar verdict"})
        if total_i is None or sharpe_i is None or verdict_i is None:
            continue
        output[(cells[0],cells[1])] = {
            "trades":int(cells[count_i]) if count_i is not None and count_i<len(cells) else count,
            "total_r":parse_float(cells[total_i]) if total_i is not None and total_i<len(cells) else None,
            "sharpe":parse_float(cells[sharpe_i]) if sharpe_i is not None and sharpe_i<len(cells) else None,
            "verdict":cells[verdict_i].strip("* ") if verdict_i is not None and verdict_i<len(cells) else "n/a",
        }
    return output


def signal_diagnostic(prepared, key, timeframe, blocked_keys):
    coin,direction,entry_time = key
    df = prepared[(coin,timeframe)]
    opens = pd.to_datetime(df["open_time"],utc=True)
    matches = np.flatnonzero((opens == entry_time).to_numpy())
    if key in blocked_keys:
        return "Matching signal was blocked because this coin/timeframe already held a position."
    if not len(matches):
        return "Entry time is not an exact open in our data; likely source-data boundary or timestamp convention."
    signal_i = int(matches[0])-1
    if signal_i < 0:
        return "No preceding completed signal bar exists in our data."
    actual = int(df["s18_signal_direction"].iloc[signal_i])
    close = float(df["close"].iloc[signal_i])
    upper = float(df["s18_channel_high"].iloc[signal_i])
    lower = float(df["s18_channel_low"].iloc[signal_i])
    context = f"signal-bar close={close:.8g}, prior channel=[{lower:.8g},{upper:.8g}]"
    if actual == direction:
        reason = "our completed entry was triggered by this close and filled next open; its absence in Opus is consistent with different open-position/exit timing"
    elif actual:
        reason = f"our state emitted {'long' if actual>0 else 'short'}, suggesting boundary/episode-state interpretation"
    else:
        reason = "our state emitted no event, suggesting window/event-reset or input timestamp/data interpretation"
    return f"{context}; {reason}."

def comparison_text(ours, opus_metrics, opus_trades, rec_rows, prepared, opus_report, opus_files):
    lines = [
        "# Strategy #18 independent-build comparison", "",
        "Opus source code was not read. Entry keys are (coin, direction, entry timestamp UTC). Ours use the independent headline lists; Opus uses only its final report and trade-list CSVs.", "",
        "| Timeframe | Exit | Ours trades | Ours total post-fee R | Ours R/trade | Ours Sharpe | Opus trades | Opus total post-fee R | Opus R/trade | Opus Sharpe | Ours verdict | Opus verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    blocked_keys = {(coin,direction,ts) for row in rec_rows if row["exit"]=="native" for coin,direction,ts in row["blocked_keys"]}
    ours_by_cell = {}
    for timeframe in INTERVALS:
        for label in EXITS:
            cell_trades = [(coin,t) for coin in COINS for t in ours["trades"][(coin,timeframe,label)]]
            cell_values = np.array([t.net_r for _,t in cell_trades],dtype=float)
            our_metrics = metrics([t for _,t in cell_trades],interval=timeframe)
            ours_map = {
                (coin,t.direction,as_utc(t.entry_time)):{
                    "coin":coin,"direction":t.direction,"entry_time":as_utc(t.entry_time),
                    "entry_price":t.entry_price,"exit_time":as_utc(t.exit_time),
                    "exit_price":t.exit_price,"net_r":t.net_r,
                } for coin,t in cell_trades
            }
            ours_by_cell[(timeframe,label)] = ours_map
            opus_map = opus_trades[(timeframe,label)]
            opus_row = opus_metrics.get((timeframe,label),{})
            opus_values = np.array([r["net_r"] for r in opus_map.values() if np.isfinite(r["net_r"])],dtype=float)
            opus_total = opus_row.get("total_r")
            opus_count = opus_row.get("trades",len(opus_map))
            if len(opus_values) and len(opus_values) == opus_count:
                opus_total = float(opus_values.sum())
            elif opus_total is None and len(opus_values):
                opus_total = float(opus_values.sum())
            opus_expectancy = opus_total / opus_count if opus_total is not None and opus_count else (float(opus_values.mean()) if len(opus_values) else None)
            ours_verdict,_ = verdict(our_metrics,label)
            lines.append(f"| {timeframe} | {label} | {len(ours_map)} | {fmt(cell_values.sum(),3)} | "
                         f"{fmt(our_metrics['expectancy_post_fee_r'],5)} | {fmt(our_metrics['sharpe_post_fee'],3)} | "
                         f"{opus_count} | {fmt(opus_total,3)} | {fmt(opus_expectancy,5)} | "
                         f"{fmt(opus_row.get('sharpe'),3)} | {ours_verdict} | {opus_row.get('verdict','n/a')} |")
            common = set(ours_map)&set(opus_map)
            only_ours = set(ours_map)-set(opus_map)
            only_opus = set(opus_map)-set(ours_map)
            lines.extend(["",f"### {timeframe} {label}: entry-key reconciliation", "",
                          f"Common: {len(common)}; only ours: {len(only_ours)}; only Opus: {len(only_opus)}.", "",
                          "| Key source | Coin | Direction | Entry timestamp UTC | Entry price |",
                          "|---|---|---|---|---:|"])
            for source_name,keys,mapping in (("common",common,ours_map),("ours only",only_ours,ours_map),("Opus only",only_opus,opus_map)):
                for key in sorted(keys,key=lambda k:(k[2],k[0],k[1])):
                    rec = mapping[key]
                    lines.append(f"| {source_name} | {key[0]} | {'long' if key[1]>0 else 'short'} | "
                                 f"{key[2].strftime('%Y-%m-%d %H:%M:%S UTC')} | {fmt(rec['entry_price'],8)} |")
    for timeframe in INTERVALS:
        label="native"
        our_map=ours_by_cell[(timeframe,label)]
        op_map=opus_trades[(timeframe,label)]
        differing=[("ours only",k,our_map[k]) for k in set(our_map)-set(op_map)]
        differing += [("Opus only",k,op_map[k]) for k in set(op_map)-set(our_map)]
        differing.sort(key=lambda row:(row[1][2],row[1][0],row[1][1],row[0]))
        lines.extend(["",f"### {timeframe} native: first 10 differing trades", "",
                      "| Source | Coin | Direction | Entry timestamp UTC | Entry price | Exit timestamp UTC | Exit price | Likely cause from our data |",
                      "|---|---|---|---|---:|---|---:|---|"])
        if not differing:
            lines.append("| ? | ? | ? | No differing entry keys | ? | ? | ? | All headline keys match. |")
        for source_name,key,record in differing[:10]:
            cause=signal_diagnostic(prepared,key,timeframe,blocked_keys)
            exit_time=record["exit_time"]
            exit_text=exit_time.strftime("%Y-%m-%d %H:%M:%S UTC") if pd.notna(exit_time) else "n/a"
            lines.append(f"| {source_name} | {key[0]} | {'long' if key[1]>0 else 'short'} | "
                         f"{key[2].strftime('%Y-%m-%d %H:%M:%S UTC')} | {fmt(record['entry_price'],8)} | "
                         f"{exit_text} | {fmt(record['exit_price'],8)} | {cause} |")
    lines.extend(["","## Inputs and limitations","",
                  f"Opus report: `{opus_report}`; selected Opus CSVs: {len(opus_files)}.",
                  "Opus metrics are taken from report tables where available; trade totals are derived from the CSVs if the report has no parseable cell.",
                  "Differing-trade causes are hypotheses grounded in our loaded bars/state and do not establish Opus implementation behavior."])
    return "\n".join(lines)+"\n"


def write_comparison(ours, rec_rows, prepared):
    if not REPORT_PATH.is_file():
        raise FileNotFoundError("Independent report must be fully written before comparison inputs are opened.")
    opus_metrics=opus_report_summary(OPUS_REPORT_PATH)
    opus_trades,opus_files=opus_trade_data(OPUS_TRADE_DIR)
    text=comparison_text(ours,opus_metrics,opus_trades,rec_rows,prepared,OPUS_REPORT_PATH,opus_files)
    with COMPARE_PATH.open("w",encoding="utf-8",newline="\n") as stream:
        stream.write(text)
    return text


def variant_csv_path(channel, window, stop_width, coin, interval, label):
    prefix = f"s18r_c{channel}_w{window}_s{stop_tag(stop_width)}"
    return TRADE_DIR / f"{prefix}_{coin}_{interval}_{label.replace(':', '')}.csv"


def load_variant_result(channel, window, stop_width):
    result = {"per_cell": {}, "pooled": {}, "trades": {}}
    for coin in COINS:
        for interval in INTERVALS:
            for label in EXITS:
                path = variant_csv_path(channel, window, stop_width, coin, interval, label)
                if not path.is_file():
                    raise FileNotFoundError(f"Expected independent trade list is missing: {path}")
                frame = pd.read_csv(path, encoding="utf-8")
                trades = []
                for _, row in frame.iterrows():
                    trades.append(Trade(
                        direction=direction_value(row["direction"]),
                        entry_time=as_utc(row["entry_time"]),
                        entry_price=float(row["entry_price"]),
                        initial_stop=float(row["initial_stop"]),
                        exit_time=as_utc(row["exit_time"]),
                        exit_price=float(row["exit_price"]),
                        exit_reason=str(row["exit_reason"]),
                        bars_held=int(row["bars_held"]),
                        regime=str(row["regime"]) if pd.notna(row["regime"]) else "",
                    ))
                result["trades"][(coin, interval, label)] = trades
                result["per_cell"][(coin, interval, label)] = metrics(trades, interval=interval)
    for interval in INTERVALS:
        for label in EXITS:
            pooled = [trade for coin in COINS for trade in result["trades"][(coin, interval, label)]]
            result["trades"][(interval, label)] = pooled
            result["pooled"][(interval, label)] = metrics(pooled, interval=interval)
    return result


def main():
    if REPORT_PATH.is_file():
        headline = load_variant_result(20, 3, 1.0)
        spec = make_spec()
        prepared = {(coin, interval): runner._prepare(spec, coin, interval)
                    for coin in COINS for interval in INTERVALS}
        reconciliation = reconcile(spec, headline)
        comparison = write_comparison(headline, reconciliation, prepared)
        digest = hashlib.sha256(COMPARE_PATH.read_bytes()).hexdigest()
        print(f"RAN: comparison finalized after report write; lines={len(comparison.splitlines())}; SHA-256={digest}")
        return
    TRADE_DIR.mkdir(parents=True, exist_ok=True)
    configs = [(20, 3, 1.0, variant_name(20, 3, 1.0), "reference", True)] + variant_configs()
    expected_paths = [variant_csv_path(c, w, s, coin, tf, label)
                      for c, w, s, _, _, _ in configs
                      for coin in COINS for tf in INTERVALS for label in EXITS]
    existing_count = sum(path.exists() for path in expected_paths)
    if existing_count not in (0, len(expected_paths)):
        raise FileExistsError(f"Incomplete independent trade-list set: {existing_count}/{len(expected_paths)} expected files exist.")
    reuse_trade_lists = existing_count == len(expected_paths)
    if REPORT_PATH.exists() or COMPARE_PATH.exists():
        raise FileExistsError("Refusing to overwrite an existing Desktop s18r output.")

    headline_spec = make_spec()
    headline = runner.run(headline_spec, COINS, INTERVALS, audit=True)
    if len(headline["audit"]) != 9 or not all(value[0] for value in headline["audit"].values()):
        raise RuntimeError("Fresh headline lookahead audit did not pass all nine datasets.")
    prepared = {(coin, interval): runner._prepare(headline_spec, coin, interval)
                for coin in COINS for interval in INTERVALS}
    coverage_rows = []
    for coin in COINS:
        for interval in INTERVALS:
            bars = len(prepared[(coin, interval)])
            days = max(0, bars - s18r.WARMUP) * HOURS_PER_BAR[interval] / 24.0
            coverage_rows.append((coin, interval, bars, days))
    reconciliation = reconcile(headline_spec, headline)
    if not all(row["reconciles"] for row in reconciliation):
        raise RuntimeError("Headline signal reconciliation failed; report was not written.")

    if reuse_trade_lists:
        all_paths = []
        for channel, window, stop_width, _, _, _ in configs:
            for coin in COINS:
                for interval in INTERVALS:
                    for label in EXITS:
                        path = variant_csv_path(channel, window, stop_width, coin, interval, label)
                        count = len(pd.read_csv(path, encoding="utf-8"))
                        all_paths.append((path, count, channel, window, stop_width, coin, interval, label))
    else:
        all_paths = write_variant_lists(headline, 20, 3, 1.0)

    sweep_results = [(variant_name(20, 3, 1.0), "reference", headline, True)]
    for channel, window, stop_width, name, factor, is_headline in variant_configs():
        if reuse_trade_lists:
            result = load_variant_result(channel, window, stop_width)
        else:
            result = runner.run(make_spec(channel, window, stop_width), COINS, INTERVALS, audit=False)
            all_paths.extend(write_variant_lists(result, channel, window, stop_width))
        sweep_results.append((name, factor, result, is_headline))

    headline_paths = [item for item in all_paths if item[2:5] == (20, 3, 1.0)]
    source_hash = hashlib.sha256(Path(s18r.__file__).read_bytes()).hexdigest()
    runner_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    summary = {(tf, label): verdict(headline["pooled"][(tf, label)], label)[0]
               for tf in INTERVALS for label in EXITS}
    report = report_text(headline, summary, headline["audit"], coverage_rows, reconciliation,
                         prepared, headline_paths, sweep_results, source_hash, runner_hash, all_paths)
    with REPORT_PATH.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(report)

    comparison = write_comparison(headline, reconciliation, prepared)
    report_bytes = REPORT_PATH.read_bytes()
    comparison_bytes = COMPARE_PATH.read_bytes()
    print(f"RAN: fresh lookahead audits={sum(bool(v[0]) for v in headline['audit'].values())}/9; reconciliation={sum(r['signals'] for r in reconciliation)} signals.")
    for interval in INTERVALS:
        for label in EXITS:
            m = headline["pooled"][(interval, label)]
            print(f"RAN: {interval} {label}: trades={m['trades']}; R/trade={m['expectancy_post_fee_r']:+.6f}; "
                  f"Sharpe={fmt(m['sharpe_post_fee'], 4)}; verdict={summary[(interval, label)]}")
    print("RAN: native holding behavior reported for all 3 timeframes.")
    print(f"RAN: report={REPORT_PATH}; lines={len(report_bytes.splitlines())}; SHA-256={hashlib.sha256(report_bytes).hexdigest()}")
    print(f"RAN: comparison={COMPARE_PATH}; lines={len(comparison_bytes.splitlines())}; SHA-256={hashlib.sha256(comparison_bytes).hexdigest()}")
    print(f"RAN: trade-list CSVs={len(all_paths)}; completed rows={sum(item[1] for item in all_paths)}; no tracked files/logs changed.")


if __name__=="__main__":
    main()

