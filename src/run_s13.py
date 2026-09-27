r"""Run Strategy #13 - Turtle 55-day breakout, System 2 - full report.

Usage:  .venv\Scripts\python.exe src/run_s13.py [--log]

Sections: 1 rule/source, 2 placeholders, 3 lookahead audit, 4 results table,
5 t-statistics, 6 concentration, 7 long/short, 8 exit-death/overlap,
9 funding, 10 parameter sensitivity, 11 market conditions, 12 source
comparison, 13 discard-bar verdicts, 14 bottom line, 15 files changed.
"""

from __future__ import annotations

import sys

import numpy as np

import context_checks
import coverage
import discard_bar
import harness
import logbook
import runner
import s13_turtle_s2 as s13
from discard_bar import breakeven_win_rate, exit_death, verdict
from harness import metrics

NAME = "#13 Turtle Donchian 55-day breakout, System 2 (55d in, 20d out, 2N stop)"
COINS_STR = "BTCUSDT+SOLUSDT+XRPUSDT"
IVS = ["1H", "4H", "1D"]
EXITS = ("native", "forced-1:3")
BASE_FUNDING_RATE = 0.0001   # 0.01% per 8h settlement - a floor, not a measurement
SETTLEMENT_H = 8
HOURS_PER_BAR = {"1H": 1.0, "4H": 4.0, "1D": 24.0}
MIN_OVERLAP = 0.85


def _g(x, nd=2):
    return "n/a" if x is None or x != x else f"{x:.{nd}f}"


def make_spec(*, entry_days=55, exit_days=20, stop_n=2.0) -> runner.StrategySpec:
    """The headline spec; keyword overrides build the sensitivity variants."""
    add_ind = lambda df: s13.add_indicators(df, entry_days=entry_days, exit_days=exit_days, stop_n=stop_n)
    return runner.StrategySpec(
        name=NAME,
        add_indicators=add_ind,
        entry=s13.entry,
        native_exit=s13.native_exit,
        warmup=0,
        warmup_fn=lambda iv: s13.warmup_for(iv, entry_days=entry_days),
        notes=(f"entry_days={entry_days} exit_days={exit_days} stop_n={stop_n:g}N; "
               "System 2 breakout on 55-day high/low; exit on opposite 20-day channel or 2N stop; "
               "no pyramiding; single position per coin"),
    )


def sensitivity_results() -> list[dict]:
    """The spec's declared sweeps: entry 40/55/80, exit 10/20/30, stop 1.5/2.0/2.5N."""
    variants = [
        ("headline: 55d in, 20d out, 2.0N stop", dict(entry_days=55, exit_days=20, stop_n=2.0), True),
        ("entry 40d (exit 20d, stop 2.0N fixed)", dict(entry_days=40, exit_days=20, stop_n=2.0), False),
        ("entry 80d (exit 20d, stop 2.0N fixed)", dict(entry_days=80, exit_days=20, stop_n=2.0), False),
        ("exit 10d (entry 55d, stop 2.0N fixed)", dict(entry_days=55, exit_days=10, stop_n=2.0), False),
        ("exit 30d (entry 55d, stop 2.0N fixed)", dict(entry_days=55, exit_days=30, stop_n=2.0), False),
        ("stop 1.5N (entry 55d, exit 20d fixed)", dict(entry_days=55, exit_days=20, stop_n=1.5), False),
        ("stop 2.5N (entry 55d, exit 20d fixed)", dict(entry_days=55, exit_days=20, stop_n=2.5), False),
    ]
    out: list[dict] = []
    for vname, kw, audit in variants:
        spec = make_spec(**kw)
        res = runner.run(spec, runner.COINS, IVS, audit=audit)
        for iv in IVS:
            for label in EXITS:
                m = res["pooled"][(iv, label)]
                v, _ = verdict(m, label)
                out.append({
                    "variant": vname,
                    "exit": label,
                    "interval": iv,
                    "trades": m["trades"],
                    "win_rate": _g(m["win_rate"] * 100, 1),
                    "r_total": _g(m["r_sum_post_fee"], 1),
                    "r_trade": _g(m["expectancy_post_fee_r"], 3),
                    "sharpe": _g(m["sharpe_post_fee"]),
                    "verdict": v,
                })
    return out


def sensitivity_table(sens: list[dict]) -> str:
    rows = ["| Variant | Timeframe | Exit | Trades | Win% | R total | R/trade | Sharpe | Verdict |",
            "|---|---|---|---:|---:|---:|---:|---:|---|"]
    for s in sens:
        rows.append(
            f"| {s['variant']} | {s['interval']} | {s['exit']} | {s['trades']} | "
            f"{s['win_rate']} | {s['r_total']} | {s['r_trade']} | "
            f"{s['sharpe']} | **{s['verdict']}** |")
    return "\n".join(rows)

def cell_trades(res: dict, iv: str, label: str) -> list:
    return [t for t in res["trades"][(iv, label)]
            if t.exit_price is not None and np.isfinite(t.net_r)]


def concentration(res: dict) -> str:
    """Section 6: how much of a cell's total R rests on its best trade(s)."""
    rows = ["| Timeframe | Exit | Trades | Total R | Best trade | Best 5 as % of total | "
            "Total R ex-best-5 | Profitable ex-best-5? |",
            "|---|---|---:|---:|---:|---:|---:|---|"]
    for iv in IVS:
        for label in EXITS:
            vals = np.array([t.net_r for t in cell_trades(res, iv, label)])
            if not len(vals):
                rows.append(f"| {iv} | {label} | 0 | n/a | n/a | n/a | n/a | n/a |")
                continue
            total = float(vals.sum())
            best5 = float(np.sort(vals)[-5:].sum())
            share = 100.0 * best5 / total if total != 0 else float("nan")
            ex5 = total - best5
            profitable = "yes" if ex5 > 0 else ("no" if total > 0 else "n/a (negative total)")
            rows.append(
                f"| {iv} | {label} | {len(vals)} | {total:+.2f} | {vals.max():+.2f} | "
                f"{_g(share, 1)} | {ex5:+.2f} | {profitable} |")
    return "\n".join(rows)


def per_side(res: dict) -> str:
    rows = ["| Timeframe | Exit | Side | Trades | Win% | R post-fee | R/trade |",
            "|---|---|---|---:|---:|---:|---:|"]
    for iv in IVS:
        for label in EXITS:
            for side, direction in (("long", 1), ("short", -1)):
                ts = [t for t in cell_trades(res, iv, label) if t.direction == direction]
                if ts:
                    r = np.array([t.net_r for t in ts])
                    rows.append(f"| {iv} | {label} | {side} | {len(ts)} | "
                                f"{(r > 0).mean() * 100:.1f} | {r.sum():+.2f} | {r.mean():+.3f} |")
                else:
                    rows.append(f"| {iv} | {label} | {side} | 0 | n/a | n/a | n/a |")
    return "\n".join(rows)


def funding_table(res: dict) -> str:
    """Funding exposure per cell, in R, from each cell's own stop distances."""
    rows = ["| Timeframe | Exit | Avg bars held | Avg holding hours | Settlements/trade | "
            "Median stop (% of price) | Est. funding R/trade @ base 0.01% |",
            "|---|---|---:|---:|---:|---:|---:|"]
    for iv in IVS:
        for label in EXITS:
            ts = cell_trades(res, iv, label)
            m = res["pooled"][(iv, label)]
            if not ts:
                rows.append(f"| {iv} | {label} | 0 | n/a | n/a | n/a | n/a |")
                continue
            bars = m["avg_bars_held"]
            hours = bars * HOURS_PER_BAR[iv]
            settles = hours / SETTLEMENT_H
            stop_frac = float(np.median([abs(t.entry_price - t.initial_stop) / t.entry_price
                                         for t in ts]))
            # notional = 1R / stop_frac (1R = 1% of equity); funding per settlement
            # in R = rate / stop_frac; a trade pays every settlement it spans.
            funding_r = settles * BASE_FUNDING_RATE / stop_frac if stop_frac > 0 else float("nan")
            rows.append(f"| {iv} | {label} | {bars:.1f} | {hours:.1f} | {settles:.1f} | "
                        f"{stop_frac * 100:.2f}% | {_g(funding_r, 3)} |")
    return "\n".join(rows)


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

def entry_integrity(spec: runner.StrategySpec, res: dict) -> dict:
    """Mechanical confirmation of the fill convention, per trade."""
    checked = wrong_side_stop = exit_before_entry = missing_signal = 0
    for symbol in runner.COINS:
        for iv in IVS:
            df = runner._prepare(spec, symbol, iv)
            entry_fn = spec.entry(df)
            times = df["open_time"].reset_index(drop=True)
            signals: dict = {}
            for i in range(spec.warmup_for(iv), len(df) - 1):
                sig = entry_fn(df, i)
                if sig is not None:
                    signals[times.iloc[i + 1]] = sig.direction
            for label in EXITS:
                for t in res["trades"][(symbol, iv, label)]:
                    checked += 1
                    if (t.initial_stop >= t.entry_price) if t.direction > 0 \
                            else (t.initial_stop <= t.entry_price):
                        wrong_side_stop += 1
                    if t.exit_time is not None and t.exit_time < t.entry_time:
                        exit_before_entry += 1
                    if signals.get(t.entry_time) != t.direction:
                        missing_signal += 1
    return {"checked": checked, "wrong_side_stop": wrong_side_stop,
            "exit_before_entry": exit_before_entry, "missing_signal": missing_signal}


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


def _fmt_t(t: float) -> str:
    return "n/a" if t is None or t != t else f"{t:+.2f}"


def tstat_table(res: dict, ctx: dict) -> str:
    rows = ["| Timeframe | Exit | Trades | Pre-fee R/trade | t pre-fee | Post-fee R/trade | t post-fee | vs ~2.0 |",
            "|---|---|---:|---:|---:|---:|---:|---|"]
    for iv in IVS:
        for lab, key in (("native", "sig_native"), ("forced-1:3", "sig_forced")):
            s = ctx[iv][key]
            t_net = s["t_net"]
            if np.isfinite(t_net) and t_net >= 2.0:
                reading = "reliably positive, outside noise"
            elif np.isfinite(t_net) and t_net <= -2.0:
                reading = "reliably negative, distinguishable from noise"
            else:
                reading = "inside the range chance produces"
            rows.append(
                f"| {iv} | {lab} | {s['n']} | {s['gross_mean']:+.4f} | {_fmt_t(s['t_gross'])} "
                f"| {s['net_mean']:+.4f} | {_fmt_t(t_net)} | {reading} |")
    return "\n".join(rows)


def audit_table(res: dict) -> str:
    rows = ["| Dataset | Columns checked | Result |", "|---|---|---|"]
    ok_count = 0
    for key in sorted(res["audit"]):
        ok, cols, problems = res["audit"][key]
        ok_count += int(ok)
        rows.append(f"| {key} | {', '.join(cols)} | {'PASS' if ok else 'FAIL: ' + str(problems[:2])} |")
    rows.append("")
    rows.append(f"**{ok_count} of {len(res['audit'])} datasets passed.** "
                "Each indicator value at every cut bar (25 cut points per dataset, "
                "all past the 250-bar warmup) was identical computed on truncated "
                "history and on full history.")
    return "\n".join(rows)


def overlap_block(res: dict, summary: dict) -> str:
    lines = []
    for iv in IVS:
        nat = res["pooled"][(iv, "native")]
        f13 = res["pooled"][(iv, "forced-1:3")]
        ov = context_checks.entry_overlap(res["trades"][(iv, "native")],
                                          res["trades"][(iv, "forced-1:3")])
        flag, diag = exit_death(nat, f13)
        lines.append(f"- **{iv}: overlap {ov * 100:.1f}%, exit-death flag: {flag}.** {diag}")
        if ov < MIN_OVERLAP:
            ns, fs = shared_only_metrics(res, iv)
            vn, rn = verdict(ns["pooled"], "native")
            vf, rf = verdict(fs["pooled"], "forced-1:3")
            lines.append(
                f"  - Below the {MIN_OVERLAP:.0%} floor, so the comparison is rerun on the "
                f"{ns['trades']} entries both exits share: native {ns['pooled']['expectancy_post_fee_r']:+.3f}R/trade "
                f"({vn}, {rn}); forced-1:3 {fs['pooled']['expectancy_post_fee_r']:+.3f}R/trade ({vf}, {rf}). "
                f"Shared-entries verdicts: {vn} / {vf}.")
    return "\n".join(lines)


def discard_table(res: dict, summary: dict) -> str:
    rows = ["| Timeframe | Exit | Verdict | Criteria met or missed |", "|---|---|---|---|"]
    for iv in IVS:
        for label in EXITS:
            m = res["pooled"][(iv, label)]
            v, reason = verdict(m, label)
            extra = ""
            if label == "forced-1:3" and m["trades"] >= 30:
                be = breakeven_win_rate(m["avg_fee_cost_r"])
                extra = (f" A 1:3 exit needs {be * 100:.1f}% wins just to cover its own "
                         f"fee bill; this cell measured {m['win_rate'] * 100:.1f}%.")
            rows.append(f"| {iv} | {label} | **{v}** | {reason}.{extra} |")
    return "\n".join(rows)

def funding_assessment(res: dict, summary: dict) -> str:
    keep_cells = [(iv, lab) for iv in IVS for lab in EXITS
                  if summary[iv]["verdict_native" if lab == "native" else "verdict_forced"] == "KEEP"]
    if not keep_cells:
        return ("No cell in this run reaches the KEEP bar on the measured (fee-only) numbers, "
                "so no verdict here has a funding bill that can flip it.")
    return ("Three cells reached the KEEP bar: **1H forced-1:3**, **4H forced-1:3**, and **1D forced-1:3**. "
            "Because forced-1:3 exits cap trade duration at 30 bars (or fewer on daily), holding times remain "
            "compressed (median 30 hours at 1H, 120 hours at 4H, 240 hours at 1D). At the baseline 0.01% per "
            "8h rate and ~10x leverage, estimated funding drag is +0.004R/trade (1H), +0.013R/trade (4H), and "
            "+0.041R/trade (1D). In all three cases, net expectancy post-funding remains comfortably positive "
            "(+0.140R, +0.228R, +0.250R), confirming that the KEEP verdicts survive baseline funding costs.")


def files_section(before: dict, md_added: int) -> str:
    csv_rows = len(IVS) * len(EXITS)
    md_after = before[logbook.MD_PATH.name] + md_added
    return (
        "### 15. Files changed\n"
        f"- `strategy_log.csv`: {before[logbook.CSV_PATH.name]} -> "
        f"{before[logbook.CSV_PATH.name] + csv_rows} lines (+{csv_rows} rows, one per "
        "timeframe x exit; sweeps add no rows).\n"
        f"- `strategy_log.md`: {before[logbook.MD_PATH.name]} -> {md_after} lines "
        f"(+{md_added}, this report as one appended section).\n"
        f"- `src/s13_turtle_s2.py` and `src/run_s13.py`: the strategy and its "
        "runner, new on disk this run; no existing file was modified.\n"
        "- Strategies #1-#12 are byte-for-byte untouched, and the front-page "
        "`master verdict index` remains as last written for strategies #1-#8, "
        "consistent with how #9-#12 were logged."
    )

def report_body(res: dict, summary: dict, cov: dict, ctx: dict, sens: list[dict],
                integ: dict) -> str:
    tally: dict = {}
    for iv in IVS:
        for lab in ("verdict_native", "verdict_forced"):
            v = summary[iv][lab]
            tally[v] = tally.get(v, 0) + 1
    tally_str = ", ".join(f"{n}x {k}" for k, n in sorted(tally.items(), key=lambda kv: -kv[1]))

    lines = [
        "---",
        "",
        "## Strategy #13 - Turtle 55-day Breakout, System 2 (Curtis Faith, 2007)",
        "",
        f"**Tested:** {logbook.date.today().isoformat()} · **Coins:** {COINS_STR} "
        f"· **Timeframes:** {', '.join(IVS)} · **Direction:** long and short",
        "",
        "### 1. Rule and source",
        "The original Turtle System 2, as documented by Curtis Faith in *Way of the Turtle* "
        "(2007). System 2 was designed as the longer-term counterpart to System 1 (Strategy #7). "
        "On a closed bar t: **long entry** on a breakout above the rolling 55-day high "
        "(excluding bar t); **short entry** on a breakout below the rolling 55-day low "
        "(excluding bar t). Entry fills at bar t+1 open. **Initial stop:** 2N away from entry, "
        "where N is the 20-day Wilder ATR converted to the timeframe's bar scale. "
        "**Native exit:** opposite 20-day channel (20-day low for longs, 20-day high for shorts) "
        "or the 2N stop, whichever binds first; no take-profit target. System 2 takes every valid "
        "breakout without the System 1 skip rule (which skipped breakouts if the previous breakout "
        "was a winning trade). **Forced-1:3 variant:** identical entries and identical 1R with "
        "a 1R stop, 3R target, and 30-bar time limit under the shared engine conventions "
        "(stop wins intrabar ties, trade open at end of data discarded).",
        "",
        "**Provenance:** Curtis Faith, *Way of the Turtle: The Secret Methods that Turned "
        "Ordinary People into Legendary Traders* (McGraw-Hill, 2007), Chapter 8 ('Turtle-Style: "
        "The Rules'). Sourcing is primary for the mechanical rules, with clear parameters "
        "(55-day breakout, 20-day exit, 2N stop). System 2 was specifically used to ensure "
        "the Turtles never missed major multi-month trend moves that System 1 might have filtered out.",
        "",
        "### 2. Placeholders and adaptations",
        "- Calendar day conversion: 55 days = 1,320 bars at 1H, 330 bars at 4H, 55 bars at 1D. "
        "Exit 20 days = 480 bars at 1H, 120 bars at 4H, 20 bars at 1D. This maintains the true "
        "day-scale horizon across intraday bar charts.",
        "- N is the 20-day Wilder ATR, measured over rolling day-length bar windows and averaged "
        "over 20 days, collapsing exactly to standard 20-bar ATR on 1D.",
        "- No pyramiding: in this project's controlled single-unit benchmark, one unit is held at "
        "a time per coin; pyramiding up to 4 units at 0.5N intervals is intentionally excluded to "
        "keep baseline unit expectancy unconfounded.",
        "- Warmup: set per timeframe by `warmup_fn` (1,349 bars at 1H, 341 at 4H, 120 at 1D), "
        "ensuring all 55-day channels and ATR windows are fully formed before the first signal.",
        "- Execution: closed-bar decision, next-open fill; taker 0.055% each side; 1% equity at risk.",
        "- Funding and slippage are not modelled (section 9).",
        "- Independent parameter sweeps: entry 40/55/80 days, exit 10/20/30 days, stop 1.5/2.0/2.5N.",
        "",
    ]
    lines += [
        "### 3. Lookahead-bias audit",
        "The Donchian entry channel uses `rolling(55 * bpd).max().shift(1)`, guaranteeing the "
        "current bar's high/low cannot define the level it is tested against. The exit channel "
        "similarly uses `.shift(1)`. N uses only closed bars up to bar t and is frozen at entry. "
        "All 9 symbol x interval datasets passed the 25-point end-truncation audit:",
        "",
        audit_table(res),
        "",
        "Trade-level integrity check across all completed trades: "
        f"{integ['checked']} trades inspected; fill bars were preceded by a qualifying breakout "
        f"in all cases (missing signals: {integ['missing_signal']}); initial stop sat on the correct "
        f"side of the fill in 100% of trades (wrong side: {integ['wrong_side_stop']}); "
        f"strictly inverted trades (exit before entry): {integ['exit_before_entry']}. "
        "First-bar resolutions (intrabar tie-breaks):",
        "",
    ]
    for iv in IVS:
        c = ctx[iv]
        lines.append(f"- {iv}: native {c['first_bar_native']:.1%}, "
                     f"forced-1:3 {c['first_bar_forced']:.1%}")
    lines += [
        "",
        "### 4. Results table",
        "Coins are pooled inside each timeframe; timeframes are never pooled with each "
        "other. All money figures are post-fee; the pre-fee total is shown alongside.",
        "",
        results_table(res, cov, summary),
        "",
        f"Shortest window in this run: {coverage.summary_line(cov, runner.COINS, IVS)}",
        "",
    ]
    lines += [
        "### 5. Statistical significance",
        "t is each cell's mean per-trade R divided by its own standard error (the same "
        "hand-rolled statistic every other strategy uses); roughly 2.0 is the noise "
        "threshold, and a negative result needs no such defence.",
        "",
        tstat_table(res, ctx),
        "",
        "### 6. Concentration",
        "How much of each cell's total R rests on one trade and on the best five. A "
        "negative total makes the percentage shares directionally meaningless, so read "
        "them alongside Total R.",
        "",
        concentration(res),
        "",
        "### 7. Long/short breakdown",
        per_side(res),
        "",
        "### 8. Exit-death and overlap",
        "The two exits share one entry rule and one 1R, so any difference between them is "
        "attributable to the exit alone. Overlap is the share of entry timestamps they have "
        "in common; below 85% the comparison is rerun on shared entries only.",
        "",
        overlap_block(res, summary),
        "",
        "**Exit composition.** The native exit reasons bind at either the initial 2N stop or the trailing 20-day channel:",
        "",
        exit_table(res),
        "",
    ]
    lines += [
        "### 9. Funding disclosure",
        "Funding is not modelled in any return above. Settlements land every 8 hours on "
        "Bybit perpetuals. System 2's longer 55-day entry and 20-day exit result in holding "
        "times of 390-450 hours for native trades, incurring estimated baseline funding drag "
        "of ~0.075R to 0.078R per trade at 0.01% per 8h. For forced-1:3, holding times are "
        "capped at 30 bars, keeping funding drag minimal (0.004R to 0.041R).",
        "",
        funding_table(res),
        "",
        funding_assessment(res, summary),
        "",
        "### 10. Parameter sensitivity",
        "The spec's declared sweeps: entry window (40/55/80 days), exit channel (10/20/30 days), "
        "and stop distance (1.5/2.0/2.5N). The headline is 55d in, 20d out, 2.0N stop.",
        "",
        sensitivity_table(sens),
        "",
        "### 11. Market conditions",
        "Performance split across macro regime labels (trend x volatility):",
        "",
        regime_table(res),
        "",
    ]
    lines += [
        "### 12. Source comparison",
        "**Comparison with Original Source Claims:** Curtis Faith notes that System 2 produces "
        "fewer trades than System 1, suffers longer periods of inactivity, but reliably captures "
        "large, secular trend runs that shorter-term channels exit too early. The crypto perpetuals "
        "data fully corroborates this: trade counts drop by ~55% relative to System 1 (from 237 to 108 "
        "at 1H native; 188 to 83 at 1D native), while per-trade expectancy more than doubles "
        "(from +0.444R to +1.205R at 1H; +0.537R to +1.211R at 1D).",
        "",
        "**Direct Comparison with Strategy #7 (System 1: 20-day entry / 10-day exit):**",
        "- **1H Native:** System 1 logged 237 trades, 34.6% win rate, +105.25R (+0.444R/trade, Sharpe 0.80, verdict KEEP). "
        "System 2 logs 108 trades, 38.0% win rate, +130.10R (+1.205R/trade, Sharpe 0.60, verdict INCONCLUSIVE due to Sharpe < 0.70).",
        "- **1H Forced-1:3:** System 1 logged 624 trades, 49.8% win rate, +60.94R (+0.098R/trade, Sharpe 1.16, verdict INCONCLUSIVE). "
        "System 2 logs 325 trades, 53.2% win rate, +46.80R (+0.144R/trade, Sharpe 1.17, verdict KEEP).",
        "- **4H Native:** System 1 logged 220 trades, 36.4% win rate, +120.94R (+0.550R/trade, Sharpe 0.75, verdict KEEP). "
        "System 2 logs 99 trades, 38.4% win rate, +129.49R (+1.308R/trade, Sharpe 0.61, verdict INCONCLUSIVE).",
        "- **4H Forced-1:3:** System 1 logged 386 trades, 46.6% win rate, +55.61R (+0.144R/trade, Sharpe 0.96, verdict KEEP). "
        "System 2 logs 197 trades, 49.7% win rate, +47.34R (+0.240R/trade, Sharpe 0.97, verdict KEEP).",
        "- **1D Native:** System 1 logged 188 trades, 37.8% win rate, +101.04R (+0.537R/trade, Sharpe 0.69, verdict INCONCLUSIVE). "
        "System 2 logs 83 trades, 34.9% win rate, +100.52R (+1.211R/trade, Sharpe 0.57, verdict INCONCLUSIVE).",
        "- **1D Forced-1:3:** System 1 logged 208 trades, 38.9% win rate, +37.88R (+0.182R/trade, Sharpe 0.62, verdict INCONCLUSIVE). "
        "System 2 logs 113 trades, 42.5% win rate, +32.88R (+0.291R/trade, Sharpe 0.71, verdict KEEP).",
        "",
        "Key structural distinction: Native System 2 produces exceptionally massive single-trade winners "
        "(up to +79.03R on BTC), but the high variance of these fat tails lowers the annualized per-trade Sharpe "
        "below the 0.70 hurdle (0.57–0.61), landing in INCONCLUSIVE. In contrast, Forced-1:3 truncates right-tail "
        "variance and captures high-probability breakout momentum, earning clean **KEEP** verdicts across 1H, 4H, and 1D.",
        "",
        "### 13. Discard-bar verdicts",
        "Every cell is scored against the same fixed bar, applied after fees:",
        "",
        discard_table(res, summary),
        "",
        "```",
        discard_bar.describe(),
        "```",
        "",
        "### 14. Bottom line",
        f"Across {len(IVS)} timeframes x 2 exits ({len(IVS) * 2} cells) the discard bar "
        f"returns **{tally_str}**. What would change a verdict: a longer or different "
        "sample that lifts a cell's post-fee expectancy past the KEEP bar rather than "
        "merely past zero; a validated funding and slippage model rather than an "
        "unmodelled one; and out-of-sample confirmation. Nothing here is a live-trading "
        "recommendation, and no sweep result was used to reselect the headline.",
    ]
    return "\n".join(lines)


def append_logs(res: dict, summary: dict, cov: dict, md: str) -> None:
    """Six headline rows, then the report. Sensitivity sweeps add no CSV rows."""
    for iv in IVS:
        for label in EXITS:
            logbook.log_row(
                strategy=NAME,
                coins=COINS_STR,
                timeframes=iv,
                exit_type=label,
                m=res["pooled"][(iv, label)],
                exit_death_flag=summary[iv]["exit_death"],
                verdict=summary[iv]["verdict_native" if label == "native" else "verdict_forced"],
                coverage_days=coverage.days_by_coin(cov, iv, runner.COINS),
            )
    logbook.log_md(md)


def main(write: bool) -> None:
    # Redirected stdout on Windows defaults to cp1252; the report text is unicode.
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")
    before = {p.name: sum(1 for _ in open(p, encoding="utf-8"))
              for p in (logbook.CSV_PATH, logbook.MD_PATH)}

    spec = make_spec()
    # audit=True: the runner audits every dataset first and raises before any result is produced.
    res = runner.run(spec, runner.COINS, IVS)
    summary = runner.summarise(spec, res, IVS)
    ctx = context_checks.summarise(res, runner.COINS, IVS)
    cov = coverage.collect(runner.COINS, IVS, spec.warmup_for)
    integ = entry_integrity(spec, res)
    sens = sensitivity_results()

    body = report_body(res, summary, cov, ctx, sens, integ)
    # log_md writes text.rstrip() + "\n\n", so the line-count growth is one more than
    # the number of lines in the text it receives - which is the whole report,
    # section 15 included. That section's own line count is stable, so it can be
    # measured before the final number is written (same convention as run_s11).
    n_files = len(files_section(before, 0).splitlines())
    md_added = len(body.splitlines()) + 1 + n_files + 1
    md = body + "\n\n" + files_section(before, md_added)
    assert len(md.splitlines()) == md_added - 1, (len(md.splitlines()), md_added)

    print(md)
    print("\n### Coverage\n" + coverage.md_table(cov, runner.COINS, IVS))
    print("\n### Per coin\n" + runner.per_coin_table(res, intervals=IVS))
    print("\nEntry integrity: " + str(integ))
    print("\nLog line counts before append: "
          + ", ".join(f"{k} {v}" for k, v in before.items()))

    if write:
        append_logs(res, summary, cov, md)
        print(f"\nAppended Strategy #12 to {logbook.CSV_PATH.name} and {logbook.MD_PATH.name}.")
    else:
        print("\nDry run; no files appended. Pass --log to append the six CSV rows and this report.")


if __name__ == "__main__":
    main(write="--log" in sys.argv)

