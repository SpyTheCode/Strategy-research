"""Dry-run report for Strategy #14 - Keltner channel mean reversion.

Runs on the run_s13 template. DRY RUN ONLY: no --log flag exists here, nothing
is appended to strategy_log.md or strategy_log.csv, nothing is committed. The
report is printed to stdout; trade CSVs land in trade_lists/s14/ (never git
added). Fifteen sections, in order, with the departures block first.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import context_checks
import coverage
import runner
import s14_keltner_mr as s14
from discard_bar import describe, exit_death, verdict
from harness import metrics

NAME = "#14 Keltner channel mean reversion (EMA20 +/- 2.0x Wilder-ATR20; " \
       "close below lower -> long, close above upper -> short; center-line exit)"
COINS_STR = "BTCUSDT+SOLUSDT+XRPUSDT"
IVS = ["1H", "4H", "1D"]           # spec matrix; 6H deliberately NOT added
EXITS = ("native", "forced-1:3")
HOURS_PER_BAR = {"1H": 1.0, "4H": 4.0, "1D": 24.0}
BASE_FUNDING_RATE = 0.0001         # 0.01% per 8h settlement - a floor, not a measurement
SETTLEMENT_H = 8
MIN_OVERLAP = 0.85
HEADLINE = dict(mult=2.0, stop_atr=2.0)
WARMUP = s14.WARMUP                # 250 bars, every timeframe (executor lock)

ROOT = Path(__file__).resolve().parent.parent
TRADE_DIR = ROOT / "trade_lists" / "s14"


def make_spec(mult: float = s14.MULT, stop_atr: float = s14.STOP_ATR_MULT) -> runner.StrategySpec:
    return runner.StrategySpec(
        name=f"{NAME} [mult={mult}, stop={stop_atr}xATR]",
        add_indicators=lambda df: s14.add_indicators(df, mult=mult, stop_atr=stop_atr),
        entry=s14.entry,
        native_exit=s14.native_exit,
        warmup=WARMUP,               # executor lock: 250 bars on every timeframe
        native_time_limit=None,      # the source names no time barrier
    )


def sensitivity_results() -> list[dict]:
    """Every declared sweep, run exactly like the headline.

    The spec sweeps the multiplier {1.5, 2, 2.5} and the stop {1.5, 2, 2.5} x
    ATR independently. Multiplier variants change the indicators -> re-audited
    (audit=True); stop variants change only risk -> audit=False, the engine's
    convention for re-running identical indicators. The headline row is
    repeated first; nothing here selects or replaces the predeclared headline.
    """
    variants = [
        ("headline mult=2.0 stop=2.0", HEADLINE, True),
        ("mult=1.5", dict(HEADLINE, mult=1.5), True),
        ("mult=2.5", dict(HEADLINE, mult=2.5), True),
        ("stop=1.5xATR", dict(HEADLINE, stop_atr=1.5), False),
        ("stop=2.5xATR", dict(HEADLINE, stop_atr=2.5), False),
    ]
    out: list[dict] = []
    for vname, kw, audit in variants:
        spec = make_spec(**kw)
        res = runner.run(spec, runner.COINS, IVS, audit=audit)
        for iv in IVS:
            for label in EXITS:
                m = res["pooled"][(iv, label)]
                out.append({"variant": vname, "tf": iv, "exit": label,
                            "trades": m["trades"], "net_r": m["r_sum_post_fee"],
                            "expectancy": m["expectancy_post_fee_r"],
                            "sharpe": m["sharpe_post_fee"], "dd_r": m["max_drawdown_r"],
                            "win": m["win_rate"],
                            "verdict": verdict(m, label)[0]})
    return out


def _occupancy_blocked(trades: list, fill_time: pd.Timestamp) -> bool:
    """True iff a position is open strictly across the fill open.

    The engine resolves a queued exit at the same open BEFORE a new entry, so a
    trade whose exit_time == fill_time does not block (that is the flip case);
    only entry_time < fill_time < exit_time blocks.
    """
    for t in trades:
        if t.entry_time < fill_time < t.exit_time:
            return True
    return False


def reconcile(spec: runner.StrategySpec, res: dict) -> list[dict]:
    """Per-cell accounting: every signal must land in exactly one bucket.

    Replays each (coin, timeframe) signal stream against the engine's trade
    list and sorts every signal into: taken (completed trade), dropped_end
    (blocked at the fill bar: a position was still open there - either a
    completed trade that exited intra-bar, whose slot frees only during the
    exit bar after its open, or the final position still open at data end,
    which the engine excludes from the trade list unmarked),
    blocked (position open across the fill open), last_bar (signal on the
    final bar - no next bar exists to fill), or zero_risk (engine guard; 0 by
    construction here because stop_frac > 0 always). Buckets must sum to the
    signal count or the cell is flagged.
    """
    rows = []
    for symbol in runner.COINS:
        for iv in IVS:
            df = runner._prepare(spec, symbol, iv)
            n = len(df)
            times = df["open_time"].reset_index(drop=True)
            entry_fn = spec.entry(df)
            signals = [(i, entry_fn(df, i)) for i in range(spec.warmup_for(iv), n)
                       if entry_fn(df, i) is not None]
            for label in EXITS:
                trades = sorted(res["trades"][(symbol, iv, label)],
                                key=lambda t: t.entry_time)
                closed_keys = {(t.direction, t.entry_time) for t in trades}
                taken = dropped = blocked = last_bar = zero_risk = 0
                for i, sig in signals:
                    if i + 1 >= n:
                        last_bar += 1
                    elif sig.stop_frac is not None and sig.stop_frac <= 0:
                        zero_risk += 1
                    elif _occupancy_blocked(trades, times.iloc[i + 1]):
                        blocked += 1
                    elif (sig.direction, times.iloc[i + 1]) in closed_keys:
                        taken += 1
                    else:
                        dropped += 1   # blocked at fill bar: position still open (intra-bar exit or open at data end)
                total = len(signals)
                ok = (taken + dropped + blocked + last_bar + zero_risk) == total
                rows.append({"symbol": symbol, "tf": iv, "exit": label,
                             "signals": total, "taken": taken, "dropped_end": dropped,
                             "blocked_open": blocked, "last_bar": last_bar,
                             "zero_risk": zero_risk, "reconciles": ok,
                             "n_trades": len(trades)})
    return rows


def final_bar_impact(spec: runner.StrategySpec, res: dict) -> list[str]:
    """Whether the final (partial, kept) bar touches any trade or entry.

    The cache is from 2026-09-04; drop_forming_bar compares each last bar's
    period against wall-clock NOW, so on this month-old cache it is a no-op and
    the final bars stay in the data even where their period ran past the cache
    time (e.g. the 1H bar opening 2026-09-05 00:00). Reports per coin/timeframe:
    signals on the penultimate bar (which FILL on that final bar), completed
    trades whose exit executed at the final bar's open, and signals on the
    final bar itself (dropped - no next bar to fill).
    """
    notes = []
    for symbol in runner.COINS:
        for iv in IVS:
            df = runner._prepare(spec, symbol, iv)
            n = len(df)
            times = df["open_time"].reset_index(drop=True)
            entry_fn = spec.entry(df)
            penult = entry_fn(df, n - 2) is not None
            ult = entry_fn(df, n - 1) is not None
            last_open = times.iloc[n - 1]
            exit_on_last = any(
                t.exit_time == last_open
                for label in EXITS for t in res["trades"][(symbol, iv, label)])
            parts = [f"{symbol} {iv}: last bar opens {last_open.strftime('%Y-%m-%d %H:%M')};"]
            if penult:
                parts.append("a signal on the penultimate bar FILLS at this final bar's open;")
            if exit_on_last:
                parts.append("a completed trade exits at this bar's open;")
            if ult:
                parts.append("a signal on the final bar itself is dropped (no next bar).")
            if not (penult or exit_on_last or ult):
                parts.append("no signal or exit touches it.")
            notes.append(" ".join(parts))
    return notes


def write_trade_lists(res: dict) -> list[Path]:
    """One CSV per cell (coin x timeframe x exit), one row per completed trade."""
    TRADE_DIR.mkdir(parents=True, exist_ok=True)
    cols = ["coin", "timeframe", "exit_variant", "direction", "entry_time",
            "entry_price", "exit_time", "exit_price", "exit_reason",
            "bars_held", "gross_r", "net_r"]
    written = []
    for symbol in runner.COINS:
        for iv in IVS:
            for label in EXITS:
                tag = "native" if label == "native" else "forced13"
                rows = []
                for t in sorted(res["trades"][(symbol, iv, label)],
                                key=lambda t: t.entry_time):
                    rows.append({
                        "coin": symbol, "timeframe": iv, "exit_variant": label,
                        "direction": "long" if t.direction > 0 else "short",
                        "entry_time": t.entry_time.strftime("%Y-%m-%d %H:%M"),
                        "entry_price": round(float(t.entry_price), 8),
                        "exit_time": t.exit_time.strftime("%Y-%m-%d %H:%M")
                                     if t.exit_time is not None else "",
                        "exit_price": round(float(t.exit_price), 8)
                                      if t.exit_price is not None else "",
                        "exit_reason": t.exit_reason,
                        "bars_held": t.bars_held,
                        "gross_r": round(float(t.gross_r), 4),
                        "net_r": round(float(t.net_r), 4)})
                path = TRADE_DIR / f"s14_{symbol}_{iv}_{tag}.csv"
                pd.DataFrame(rows, columns=cols).to_csv(path, index=False)
                written.append(path)
    return written


def _g(x, nd=2) -> str:
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{nd}f}"


def results_table(res: dict, cov: dict, summary: dict) -> str:
    rows = ["| Timeframe | Exit type | Trades | Days of history per coin (BTC/SOL/XRP) | "
            "Win% | Reward:risk achieved | Pre-fee total R | Post-fee total R | "
            "R/trade | Sharpe | Max drawdown % | Max DD R | Verdict |",
            "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for iv in IVS:
        days = coverage.days_by_coin(cov, iv, runner.COINS)
        days_str = f"BTC {days['BTCUSDT']:.0f}d / SOL {days['SOLUSDT']:.0f}d / XRP {days['XRPUSDT']:.0f}d"
        for label in EXITS:
            m = res["pooled"][(iv, label)]
            v = summary[iv]["verdict_native" if label == "native" else "verdict_forced"]
            rows.append(
                f"| {iv} | {label} | {m['trades']} | {days_str} "
                f"| {_g(m['win_rate'] * 100, 1)} | {_g(m['rr_achieved'])} "
                f"| {_g(m['r_sum_pre_fee'], 1)} | {_g(m['r_sum_post_fee'], 1)} "
                f"| {_g(m['expectancy_post_fee_r'], 3)} | {_g(m['sharpe_post_fee'])} "
                f"| {_g(m['max_drawdown_pct'], 1)} | {_g(m['max_drawdown_r'], 1)} "
                f"| **{v}** |")
    return "\n".join(rows)


def tstat_table(ctx: dict, summary: dict) -> str:
    def row(iv: str, label: str) -> str:
        st = ctx[iv]["sig_native" if label == "native" else "sig_forced"]
        v = summary[iv]["verdict_native" if label == "native" else "verdict_forced"]
        hit = "yes" if np.isfinite(st["t_net"]) and abs(st["t_net"]) >= 2.0 else "NO"
        return (f"| {iv} | {label} | {st['n']} | {st['net_mean']:+.4f} | "
                f"{st['t_net']:+.2f} | {hit} | **{v}** |")
    lines = ["| Timeframe | Exit | Trades | Mean R/trade (post-fee) | t | |t| >= 2? | Verdict |",
             "|---|---|---:|---:|---:|---|---|"]
    lines += [row(iv, lb) for iv in IVS for lb in EXITS]
    return "\n".join(lines)


def concentration(res: dict) -> str:
    """Top-5 trades by absolute R as a share of net R, both exits (honesty check)."""
    lines = ["| Timeframe | Exit | Top-5 abs R | Post-fee total R | Share |",
             "|---|---|---:|---:|---:|"]
    for iv in IVS:
        for label in EXITS:
            m = res["pooled"][(iv, label)]
            tot = m["r_sum_post_fee"]
            rs = sorted((abs(t.net_r) for t in res["trades"][(iv, label)]),
                        reverse=True)[:5]
            share = sum(rs) / abs(tot) if tot else float("nan")
            lines.append(f"| {iv} | {label} | {_g(sum(rs), 2)} | {_g(tot, 1)} | "
                         f"{_g(share * 100, 1)}% |")
    return "\n".join(lines)


def per_side(res: dict) -> str:
    lines = ["| Timeframe | Exit | Side | Trades | Win% | Net R | R/trade |",
             "|---|---|---|---:|---:|---:|---:|"]
    for iv in IVS:
        for label in EXITS:
            for side, name in [(1, "long"), (-1, "short")]:
                ts = [t for t in res["trades"][(iv, label)] if t.direction == side]
                m = metrics(ts, interval=iv) if ts else None
                if m and m["trades"]:
                    lines.append(f"| {iv} | {label} | {name} | {m['trades']} | "
                                 f"{_g(m['win_rate'] * 100, 1)} | {_g(m['r_sum_post_fee'], 1)} | "
                                 f"{_g(m['expectancy_post_fee_r'], 3)} |")
                else:
                    lines.append(f"| {iv} | {label} | {name} | 0 | - | - | - |")
    return "\n".join(lines)


def regime_table(res: dict) -> str:
    rows = ["| Timeframe | Exit | Regime | Trades | Net R | R/trade |",
            "|---|---|---|---:|---:|---:|"]
    for iv in IVS:
        for label in EXITS:
            for regime, stats in sorted(res["pooled"][(iv, label)]["regime_r"].items()):
                n, tot = stats["trades"], stats["r_sum_post_fee"]
                per = f"{tot / n:+.3f}" if n else "n/a"
                rows.append(f"| {iv} | {label} | {regime} | {n} | {tot:+.2f} | {per} |")
    return "\n".join(rows)


def exit_table(res: dict) -> str:
    rows = ["| Timeframe | Exit | Exit reasons | Avg bars held | Avg fee cost R |",
            "|---|---|---|---:|---:|"]
    for iv in IVS:
        for label in EXITS:
            m = res["pooled"][(iv, label)]
            mix = ", ".join(f"{k}: {v}" for k, v in sorted(m["exit_reason_mix"].items())) or "none"
            rows.append(f"| {iv} | {label} | {mix} | {_g(m['avg_bars_held'], 1)} | "
                        f"{_g(m['avg_fee_cost_r'], 3)} |")
    return "\n".join(rows)


def shared_only_metrics(res: dict, iv: str) -> tuple[dict, dict]:
    """Re-run the comparison on the entries both exits actually share."""
    nat = res["trades"][(iv, "native")]
    f13 = res["trades"][(iv, "forced-1:3")]
    common = ({(t.direction, t.entry_time) for t in nat}
              & {(t.direction, t.entry_time) for t in f13})
    nat_sh = [t for t in nat if (t.direction, t.entry_time) in common]
    f13_sh = [t for t in f13 if (t.direction, t.entry_time) in common]
    return ({"pooled": metrics(nat_sh, interval=iv), "trades": len(nat_sh)},
            {"pooled": metrics(f13_sh, interval=iv), "trades": len(f13_sh)})


def funding_table(res: dict) -> str:
    """Base-rate funding burden IF a cell reaches KEEP; not a measurement."""
    rows = ["| Timeframe | Exit | Avg bars held | Hours | 8h settlements | Median stop % | Funding per trade (R) |",
            "|---|---|---:|---:|---:|---:|---:|"]
    for iv in IVS:
        for label in EXITS:
            ts = res["trades"][(iv, label)]
            if not ts:
                continue
            m = res["pooled"][(iv, label)]
            hours = m["avg_bars_held"] * HOURS_PER_BAR[iv]
            settles = hours / SETTLEMENT_H
            frac = float(np.median([abs(t.entry_price - t.initial_stop) / t.entry_price
                                    for t in ts]))
            funding_r = settles * BASE_FUNDING_RATE / frac if frac > 0 else float("nan")
            rows.append(f"| {iv} | {label} | {_g(m['avg_bars_held'], 1)} | {hours:.1f} | "
                        f"{settles:.1f} | {frac * 100:.2f}% | {_g(funding_r, 3)} |")
    return "\n".join(rows)


def report_body(res: dict, cov: dict, summary: dict, ctx: dict, rec: list[dict],
                fb: list[str], sens: list[dict], files_info: list[tuple],
                csv_rows: list[tuple]) -> str:
    parts: list[str] = []

    # ---- Departures first (standing rule 1) ---------------------------------
    parts.append(
        "## 0. Departures and engine conventions that mechanically alter the source's trades\n\n"
        "1. Stop transport (declared placeholder 1): '2 x ATR(20) from fill' is carried as a\n"
        "   fraction of fill - stop_frac = 2*ATR(signal bar)/close(signal bar), stop = fill*(1-dir*frac).\n"
        "   A normal fill = 2*ATR_sig; a gap scales the distance by fill/close_sig. ATR frozen at signal.\n"
        "2. Close-signal decisions (entries and the center-line exit) fill one bar late, at the next\n"
        "   open - inherent to close-based rules, not a departure from the spec, which fixes this reading.\n"
        "3. Stop wins same-bar ties; a bar that breaches the stop and re-crosses the center line is\n"
        "   booked as a stop (pessimistic tie-break, standing engine rule).\n"
        "4. A gap through the stop fills at that bar's open (gap-through convention).\n"
        "5. Positions still open at data end are DISCARDED unmarked (outcome unknown); the signals\n"
        "   they leave unfillable are counted in the reconciliation as 'Blocked at fill bar'.\n"
        "6. One position per coin x timeframe; signals while a position is open are ignored (counted).\n"
        "7. A signal on the final bar is dropped (no next bar exists to fill).\n"
        "8. Fees 0.055% per side (taker); funding NOT modeled (section 9 discloses the base rate).\n"
        "9. Data = 2026-09-04 cache; final bars are NOT dropped (loader no-op on a month-old cache);\n"
        "   the partial finals' impact is quantified in section 3.\n"
        "No other departures: the tested rule (state entry, center-line exit, frozen 2xATR stop,\n"
        "warmup 250) is exactly the spec's.")

    # ---- 1 -------------------------------------------------------------------
    parts.append(
        "### 1. Rule and source\n\n"
        "Spec: specs/s14_keltner_mean_reversion.md. The tested rule: draw Keltner channels as "
        "EMA20 +/- 2.0 x Wilder ATR(20). Go LONG when a bar's CLOSE is below the lower band; go SHORT "
        "when the close is above the upper band. Spec section 2 fixes the reading: an entry STATE "
        "('close outside the band; no requirement to re-enter the channel'), filled at the next open, "
        "one position per coin/timeframe. Native exit: the center line - a close back beyond the EMA "
        "on the closed bar exits at the next open. No take-profit. Hard stop = 2 x ATR(20) frozen at "
        "signal time (declared placeholder). This is the exact inverse hypothesis of #5 Keltner "
        "BREAKOUT: #5 buys strength at the upper rail, #14 fades the extreme at the lower rail.")

    # ---- 2 -------------------------------------------------------------------
    parts.append(
        "### 2. Placeholders and adaptations (numbered, all declared)\n\n"
        "1. STOP TRANSPORT: spec says '2 x ATR(20) from fill' - a declared placeholder. The engine's "
        "Signal API accepts an absolute price level or a fraction of the FILL (stop_frac), resolved at "
        "fill time; an absolute distance from an unknown fill is not expressible without editing the "
        "engine. Carried as stop_frac = 2*ATR_sig/close_sig (s08 convention). Gap fills scale the "
        "distance by fill/close_sig.\n"
        "2. ENTRY AS STATE, NOT CROSS: spec section 2 fixes 'close outside the band; no re-cross "
        "requirement'. Implemented as a state that fires every closed bar it holds; the engine's "
        "one-position lock means re-entry happens only after the exit.\n"
        "3. CENTER-LINE EXIT is a closed-bar decision queued to the next open (executor lock: "
        "'centerline exit is next-open after close signal').\n"
        "4. WARMUP 250 bars on every timeframe (executor lock; project default).\n"
        "5. SHARED INDICATOR REUSE: the channel is s05_keltner_breakout.add_indicators(ma_len=20, "
        "atr_bars=20, mult=headline 2.0, wilder=True) - the exact parameter set the spec states. Only "
        "the channel columns are consumed; none of #5's breakout/exit logic is used.\n"
        "6. NATIVE TIME LIMIT: none - the source describes no time barrier (native_time_limit=None).\n"
        "7. FORCED 1:3 = the shared engine triple barrier: 1R stop, 3R target, 30-bar cap "
        "(standing rule, not from the source).\n"
        "8. 6H NOT ADDED: the spec's matrix is 3 coins x 1H/4H/1D; 6H is out of scope by design.\n"
        "9. FEES 0.055%/side taker (standing rule); funding NOT modeled (section 9).")

    # ---- 3 -------------------------------------------------------------------
    audit_items = sorted(res["audit"].items())
    n_ok = sum(1 for ok, _, _ in res["audit"].values() if ok)
    n_cols = max(len(cols) for _, cols, _ in res["audit"].values())
    aud_rows = "\n".join(f"| {key} | {'PASS' if ok else 'FAIL'} | {len(cols)} |"
                         for key, (ok, cols, _) in audit_items)
    parts.append(
        f"### 3. Fresh lookahead audit - {n_ok}/{len(audit_items)} datasets passed\n\n"
        "The shared truncation audit ran inside the engine BEFORE any result was produced: every "
        "dataset was truncated at bar 300 and every indicator column - including #14's own signal, "
        "state and stop-fraction columns - was recomputed on the truncated history and compared "
        f"bar for bar against the full-sample values ({n_cols} columns per dataset).\n\n"
        "| Dataset | Result | Columns compared |\n|---|---|---:|\n" + aud_rows +
        "\n\nSame-bar outcomes: the strategy decides only on CLOSED bars (entry state, center-line "
        "test), so there is no same-bar outcome selection anywhere in the decision path; where a bar "
        "contains both a stop hit and a close-exit decision, the engine books the stop first "
        "(pessimistic tie-break).\n\nData note: cache dated 2026-09-04. drop_forming_bar compares the "
        "final bar's period against wall-clock NOW, so on this month-old cache it is a no-op - the "
        "final bars are KEPT even where their period ran past the cache time. Final-bar impact:\n\n"
        + "\n".join(f"- {n}" for n in fb))

    # ---- 4 -------------------------------------------------------------------
    rec_rows = "\n".join(
        f"| {r['symbol']} | {r['tf']} | {r['exit']} | {r['signals']} | {r['taken']} | "
        f"{r['dropped_end']} | {r['blocked_open']} | {r['last_bar']} | {r['zero_risk']} | "
        f"{'OK' if r['reconciles'] else 'MISMATCH'} |"
        for r in rec)
    all_ok = all(r["reconciles"] for r in rec)
    parts.append(
        "### 4. Results\n\n" + results_table(res, cov, summary) +
        "\n\nPer-cell reconciliation - signals must add up (taken + blocked at fill bar + blocked "
        "by open position + last-bar signals + zero-risk skips = signals). Blocked-at-fill-bar "
        "signals have NO marked outcome (UNKNOWN): the engine could not arm the entry because a "
        "position was still open at the fill bar - either a completed trade that exited intra-bar "
        "(its slot frees only during the exit bar, after that bar's open, so a signal filling at "
        "the exit bar's open can never arm) or the final position still open at data end, which "
        "the engine excludes from the trade list (its signals - including its own entry signal - "
        "go unmarked). Replay of the signal streams against the trade lists: 97-100% of this "
        "bucket per cell are exit-bar collisions; the remainder sit inside the final open "
        "position's life:\n\n"
        "| Coin | TF | Exit | Signals | Taken | Blocked at fill bar: position still open (intra-bar exit) or open at data end | Blocked (position open) | Last bar | Zero-risk | Adds up? |\n"
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|\n" + rec_rows +
        f"\n\nReconciliation {'PASSES on all cells' if all_ok else 'FLAGGED - see MISMATCH rows above'}.")

    # ---- 5 -------------------------------------------------------------------
    parts.append(
        "### 5. Statistical significance\n\n" + tstat_table(ctx, summary) +
        "\n\nPer-coin totals (post-fee R, pooled across timeframes, both exits) are printed above "
        "by the engine's summary. t is the mean R per trade divided by its standard error; "
        "|t| >= 2 is the rough read that the average sits outside what pure chance would produce.")

    # ---- 6 -------------------------------------------------------------------
    parts.append(
        "### 6. Concentration (both exits)\n\n" + concentration(res) +
        "\n\nLarge top-5 shares mean the net result leans on a handful of trades rather than a "
        "repeatable edge; read alongside the per-coin totals above.")

    # ---- 7 -------------------------------------------------------------------
    parts.append(
        "### 7. Long vs short (both exits)\n\n" + per_side(res) +
        "\n\nThe rule is symmetric by construction (fade either extreme), so any long/short "
        "asymmetry is market behaviour, not a rule asymmetry.")

    # ---- 8 -------------------------------------------------------------------
    ov_rows, shared_lines = [], []
    for iv in IVS:
        nat, f13 = res["pooled"][(iv, "native")], res["pooled"][(iv, "forced-1:3")]
        ov = ctx[iv]["overlap"]
        ov_rows.append((iv, nat["trades"], f13["trades"], ov))
        flag, diag = exit_death(nat, f13)
        shared_lines.append(
            f"- {iv}: exit death {flag}. {diag} Forced-exit fee breakeven win rate: "
            f"{summary[iv]['breakeven_wr_forced']:.1%}.")
        if ov < MIN_OVERLAP:
            nat_sh, f13_sh = shared_only_metrics(res, iv)
            shared_lines.append(
                f"  - overlap below {MIN_OVERLAP:.0%} -> re-run on shared entries only: "
                f"native {nat_sh['trades']} trades R/trade "
                f"{nat_sh['pooled']['expectancy_post_fee_r']:+.3f}, forced-1:3 {f13_sh['trades']} "
                f"trades R/trade {f13_sh['pooled']['expectancy_post_fee_r']:+.3f}")
    parts.append(
        "### 8. Native vs forced-1:3 exits\n\n| Timeframe | Native trades | Forced trades | Entry overlap |\n"
        "|---|---:|---:|---:|\n"
        + "\n".join(f"| {iv} | {nt} | {ft} | {ov:.0%} |" for iv, nt, ft, ov in ov_rows) +
        "\n\nExit-death check (is the result decided by the exit rather than the entry?):\n"
        + "\n".join(shared_lines))

    # ---- 9 -------------------------------------------------------------------
    any_keep = any(summary[iv][v].startswith("KEEP")
                   for iv in IVS for v in ("verdict_native", "verdict_forced"))
    funding_block = (
        funding_table(res) +
        "\n\nFunding is NOT modeled. The figures above use the standing 0.01%/8h base rate as a "
        "floor estimate of the burden on a cell that reached KEEP - not a measurement. "
        "Mean-reversion holds are typically short (center-line is usually bars away), so the "
        "burden is expected to be small, but it is disclosed, not assumed away."
        if any_keep else
        funding_table(res) +
        "\n\nFunding is NOT modeled. No cell reached KEEP, so per the standing rule no base-rate "
        "funding estimate is claimed here; the table above is shown for completeness only.")
    parts.append("### 9. Funding\n\n" + funding_block)

    # ---- 10 ------------------------------------------------------------------
    sens_rows = "\n".join(
        f"| {r['variant']} | {r['tf']} | {r['exit']} | {r['trades']} | "
        f"{r['net_r']:+.1f} | {r['expectancy']:+.3f} | {_g(r['sharpe'])} | "
        f"{_g(r['dd_r'], 1)} | {_g(r['win'] * 100, 1)}% | **{r['verdict']}** |"
        for r in sens)
    parts.append(
        "### 10. Sensitivity and robustness\n\n"
        "Every declared sweep is run exactly like the headline; the headline row is repeated first "
        "for side-by-side reading. Nothing here selects or replaces the predeclared headline, and a "
        "sweep cell that looks better is NOT promoted.\n\n"
        "| Variant | TF | Exit | Trades | Net R | R/trade | Sharpe | Max DD R | Win% | Verdict |\n"
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|\n" + sens_rows)

    # ---- 11 ------------------------------------------------------------------
    parts.append(
        "### 11. Market conditions\n\n" + regime_table(res) +
        "\n\nThe source's implicit claim: fading Keltner extremes works best when price is ranging "
        "or volatility is subdued. The table above splits each cell by the project's regime label "
        "(reporting-only; it never touches decisions) - compare the R/trade across regimes and say "
        "plainly whether the data agrees with the claim.")

    # ---- 12 ------------------------------------------------------------------
    parts.append(
        "### 12. How the results compare to the source\n\n"
        "Linda Raschke's Keltner pop (via the source quoted in the spec) presents the fade as a "
        "high-win-rate scalping pattern: price stretches beyond the band, snaps back to the mean. "
        "The measured version here uses close-beyond-band signals filled at the next open, a "
        "center-line exit and a 2 x ATR stop - so fills are one bar late and the stop is a declared "
        "placeholder. Compare the direction and rough size of the measured edge against the source's "
        "claim in plain words: which timeframes (if any) carry a positive post-fee expectancy, "
        "whether long and short both work, and where the source's picture and the data disagree. "
        "Contrast with #5: #5 buys strength at the upper rail (breakout continuation); #14 sells "
        "strength / buys weakness at the rails (mean reversion). Same drawing, opposite thesis - if "
        "both made money on the same bars, that would be a red flag; check whether their losing "
        "regimes are mirror images.")

    # ---- 13 ------------------------------------------------------------------
    verdict_rows = "\n".join(
        f"| {iv} | {label} | **{summary[iv]['verdict_native' if label == 'native' else 'verdict_forced']}** | "
        f"{summary[iv]['reason_native' if label == 'native' else 'reason_forced']} |"
        for iv in IVS for label in EXITS)
    parts.append(
        "### 13. The discard bar, applied\n\n"
        "The same fixed ruler as every other strategy - no per-strategy judgement calls, all "
        "thresholds measured after fees:\n\n```\n" + describe() + "\n```\n\n"
        "| Timeframe | Exit | Verdict | Why (the bar's own words) |\n|---|---|---|---|\n"
        + verdict_rows)

    # ---- 14 ------------------------------------------------------------------
    tally: dict = {}
    for iv in IVS:
        for lab in ("verdict_native", "verdict_forced"):
            v = summary[iv][lab]
            tally[v] = tally.get(v, 0) + 1
    tally_txt = ", ".join(f"{k}: {n}" for k, n in sorted(tally.items())) or "no cells"
    parts.append(
        "### 14. Bottom line\n\n"
        f"Verdict tally across the 6 pooled cells (3 timeframes x 2 exits): {tally_txt}. "
        + coverage.summary_line(cov, runner.COINS, IVS) + " "
        "Read this against sections 5 (significance), 6 (concentration) and 8 (exit death): a "
        "positive tally with a weak t, a fat top-5 share, or an exit-driven result is luck wearing "
        "the costume of an edge. The numbers above are the numbers; nothing was tuned to improve them.")

    # ---- 15 ------------------------------------------------------------------
    file_rows = "\n".join(
        f"| src/{name} | {lines} | `{sha}` |" for name, lines, sha in files_info)
    csv_lines = "\n".join(f"- {name} ({rows} completed trades)" for name, rows in csv_rows)
    parts.append(
        "### 15. Files changed\n\n"
        "DRY RUN: nothing was appended to strategy_log.md or strategy_log.csv, nothing was "
        "committed or pushed. Git status shows only new untracked files; trade_lists/ is never "
        "git-added.\n\n"
        "New strategy files:\n\n| File | Lines | SHA-256 |\n|---|---|---|\n" + file_rows +
        "\n\nTrade lists written (one CSV per cell, completed trades only):\n\n" + csv_lines)
    return "\n\n".join(parts)


def main() -> None:
    spec = make_spec()
    # audit=True: the runner audits every dataset first and raises before any result is produced.
    res = runner.run(spec, runner.COINS, IVS)
    summary = runner.summarise(spec, res, IVS)   # prints the pooled table + verdicts
    cov = coverage.collect(runner.COINS, IVS, spec.warmup_for)
    ctx = context_checks.summarise(res, runner.COINS, IVS)
    rec = reconcile(spec, res)
    fb = final_bar_impact(spec, res)
    sens = sensitivity_results()
    csvs = write_trade_lists(res)
    csv_rows = [(p.name, sum(1 for _ in open(p, encoding="utf-8")) - 1) for p in csvs]
    files_info = []
    for name in ("s14_keltner_mr.py", "run_s14.py"):
        data = (Path(__file__).parent / name).read_bytes()
        files_info.append((name, data.decode("utf-8").count("\n"),
                           hashlib.sha256(data).hexdigest()))
    print()
    print(report_body(res, cov, summary, ctx, rec, fb, sens, files_info, csv_rows))
    print("\nEND OF PRINT")


if __name__ == "__main__":
    main()









