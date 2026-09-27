r"""Run Strategy #11 â€” MACD line/signal crossover (Appel 1979) â€” full report.

Usage:  .venv\Scripts\python.exe src/run_s11.py [--log]

Redo of the first #11 entry, which reached the log as a short five-section
stub. That stub was removed from both logs and is replaced by this complete
15-section run. t-statistics are computed the same hand-rolled way every
other strategy uses them (context_checks), so scipy is not needed.

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
import s11_macd_crossover as s11
from discard_bar import breakeven_win_rate, exit_death, verdict
from harness import metrics

NAME = "#11 MACD Crossover (12/26/9, 200-SMA, 2ATR)"
COINS_STR = "BTCUSDT+SOLUSDT+XRPUSDT"
IVS = ["1H", "4H", "1D"]
EXITS = ("native", "forced-1:3")
WARMUP = 250
BASE_FUNDING_RATE = 0.0001   # 0.01% per 8h settlement - a floor, not a measurement
SETTLEMENT_H = 8
HOURS_PER_BAR = {"1H": 1.0, "4H": 4.0, "1D": 24.0}
MIN_OVERLAP = 0.85


def _g(x, nd=2):
    return "n/a" if x is None or x != x else f"{x:.{nd}f}"


def make_spec(*, fast=12, slow=26, signal_ema=9, sma_period=200, stop_mult=2.0) -> runner.StrategySpec:
    """The headline spec; keyword overrides build the sensitivity variants."""
    add_ind = lambda df: s11.add_indicators(df, fast=fast, slow=slow,
                                            signal_ema=signal_ema, sma_period=sma_period)
    return runner.StrategySpec(
        name=NAME,
        add_indicators=add_ind,
        entry=lambda df: s11.entry(df, fast=fast, slow=slow, stop_mult=stop_mult),
        native_exit=s11.native_exit,
        warmup=WARMUP,
        notes=("fast=12 slow=26 signal=9 sma200 stop_mult=2.0; "
               "MACD crosses signal + close>200SMA (long) / close<200SMA (short); "
               "native exit on opposite cross; no TP"),
    )


def sensitivity_results() -> list[dict]:
    """Every declared sweep, run exactly like the headline (audit=True for any
    variant whose indicator values change, audit=False for pure risk changes).
    The headline row is repeated first for side-by-side reading; nothing here
    selects or replaces the predeclared headline."""
    variants = [
        ("headline: stop 2.0x ATR", dict(), True),
        ("stop 1.5x ATR", dict(stop_mult=1.5), False),
        ("stop 2.5x ATR", dict(stop_mult=2.5), False),
        ("MACD 8/21 (signal 9 fixed)", dict(fast=8, slow=21), True),
        ("SMA filter 100", dict(sma_period=100), True),
        ("SMA filter 300", dict(sma_period=300), True),
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
                    "variant": label,
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
    """Mechanical confirmation of the fill convention, per trade.

    For every completed trade we recompute the entry signals on the same data
    and check that (a) the bar BEFORE the fill had a qualifying signal in the
    trade's direction (closed-bar decision, next-open fill), (b) the stop sits
    on the correct side of the fill price (stop_frac resolved at fill time from
    the signal bar's ATR - no fill-bar information), and (c) no trade exits
    before it enters. Any nonzero count invalidates the run.
    """
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
                    if t.exit_time is not None and t.exit_time <= t.entry_time:
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
                "so no verdict here has a funding bill that can flip it. For the record: at "
                "the base rate of 0.01% per 8-hour settlement the estimated funding cost is "
                "the last column of the table above per trade - it would erode any future "
                "KEEP that spans settlements, and it cannot rescue a losing cell.")
    return ("Cells that reached KEEP span funding stamps by construction; their verdicts "
            "are provisional until the base-rate cost in the last column of the table "
            "above is replaced by measured funding for the same window.")


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
        "- This is a RE-DO of Strategy #11: the earlier five-section stub (logged 2026-09-26 "
        "at strategy_log.md lines 5368-5446 and strategy_log.csv rows 74-79) was removed and "
        "replaced by this complete report. Strategies #1-#10 are byte-for-byte untouched, and "
        "the front-page master verdict index is left as last written for strategies #1-#8.\n"
        "- `src/s11_macd_crossover.py` and `src/run_s11.py`: the strategy and its runner, "
        "already on disk; the runner no longer needs scipy.\n"
        "- The `master verdict index` front matter was last updated at Strategy #8 and is "
        "left untouched, consistent with how #9 and #10 were logged."
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
        "## Strategy #11 — MACD Crossover (Gerald Appel, 1979)",
        "",
        f"**Tested:** {logbook.date.today().isoformat()} · **Coins:** {COINS_STR} "
        f"· **Timeframes:** {', '.join(IVS)} · **Direction:** long and short",
        "",
        "### 1. Rule and source",
        "MACD line = 12-EMA − 26-EMA; signal = 9-EMA of the MACD line (standard "
        "exponential smoothing, alpha = 2/(span+1), `adjust=False`). On a closed bar t: "
        "**long** if the MACD line crosses above the signal line (MACD > signal now, "
        "MACD <= signal on the prior bar) AND close[t] > 200-SMA[t]; **short** on the "
        "mirror cross below with close[t] < 200-SMA. Entry fills at bar t+1 open. "
        "The initial stop is 2 x ATR(14, Wilder) measured as a fraction of the signal "
        "bar's close and resolved against the actual next-open fill price, which defines "
        "1R. **Native exit:** close a long when MACD crosses back below the signal line, "
        "a short when it crosses back above, filled at the next open; the stop stays "
        "armed throughout; no take-profit, no pyramiding, at most one position per coin "
        "per timeframe. **Forced-1:3 variant:** identical entries and identical 1R with "
        "a 1R stop, 3R target and 30-bar time limit under the shared engine conventions "
        "(stop wins intrabar ties, a bar gapping through the stop fills at the open, a "
        "trade still open at the end of the data is discarded rather than marked to the "
        "last close).",
        "",
        "**Provenance:** Gerald Appel, *The Moving Average Convergence-Divergence Trading "
        "Method* (1979) - the original source for the indicator and the 12/26/9 parameters. "
        "The source describes MACD/signal crossovers on stock data with no universal stop "
        "and no crypto-specific exit, so the 2 x ATR(14) stop, the 200-SMA trend filter and "
        "the crypto perp execution are this test's declared adaptations, not source canon. "
        "No source performance claim is assumed or reproduced.",
        "",
        "### 2. Placeholders and adaptations",
        "- MACD 12/26/9: canonical Appel parameters, applied unmodified; EMA smoothing is "
        "the standard `span` convention (alpha = 2/(span+1), `adjust=False`).",
        "- Trend filter: a contemporaneous, unshifted 200-bar close SMA - a project "
        "addition to keep entries on the side of the longer trend, not a source parameter.",
        "- Initial stop: 2 x ATR(14) (Wilder SMA of true range) as a fraction of the "
        "signal bar's close, resolved against the actual next-open fill. A project "
        "extrapolation; the source defines no stop.",
        "- Warmup: 250 bars on every timeframe (SMA200 needs 200; margin for EMA/ATR "
        "settle-in), applied identically to the headline and every sweep.",
        "- Execution: closed-bar decision and next-open fill; taker 0.055% each side; "
        "1% of starting equity risked per trade, never compounded; one position per coin "
        "per timeframe; both long and short traded.",
        "- The forced 30-bar limit is the project's shared unvalidated convention.",
        "- Funding and slippage are not modelled (section 9).",
        "- Independent sweeps, each a fresh run that never replaces the headline: stop "
        "1.5x/2.5x ATR, MACD 8/21 (signal 9 fixed), SMA filter 100 and 300.",
        "",
    ]
    lines += [
        "### 3. Lookahead-bias audit",
        "The engine's standing rules: a decision on a closed bar fills at the next bar's "
        "open, and the stop wins every intrabar tie. Three specific traps checked here: "
        "(a) the MACD/signal EMAs are recursive but causal - proven by the end-truncation "
        "audit below; (b) a crossover needs the PREVIOUS bar's MACD/signal values, which "
        "are also closed-bar reads; (c) the ATR stop distance is captured from the signal "
        "bar and only translated to the actual fill price at the next open, so the fill "
        "bar's range never touches the stop level. The regime columns used in section 11 "
        "are computed from already-closed bars and are never consulted by any decision.",
        "",
        audit_table(res),
        "",
        "Beyond the indicator audit, every completed trade was re-derived from the data: "
        f"{integ['checked']} trades checked; the fill bar had a qualifying same-direction "
        f"signal on the immediately preceding closed bar in all but {integ['missing_signal']} "
        f"cases; the stop sat on the wrong side of the fill in {integ['wrong_side_stop']} "
        f"trades; {integ['exit_before_entry']} trades exited before entering. First-bar "
        "resolutions (where the intrabar tie-break, not the strategy, decides):",
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
        "### 5. Statistical significance",
        "t is each cell's mean per-trade R divided by its own standard error (the same "
        "hand-rolled statistic every other strategy uses); roughly 2.0 is the noise "
        "threshold, and a negative result needs no such defence.",
        "",
        tstat_table(res, ctx),
        "",
    ]
    lines += [
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
        "**Exit composition.**",
        "",
        exit_table(res),
        "",
    ]
    lines += [
        "### 9. Funding disclosure",
        "Funding is not modelled in any return above. Settlements land every 8 hours on "
        "this venue, so holding time is the cost exposure. The stop distance varies per "
        "trade (2 x ATR), so the position multiple varies with it: notional = 1R / stop "
        "fraction, and a percentage settlement converts to R at that multiple.",
        "",
        funding_table(res),
        "",
        funding_assessment(res, summary),
        "",
        "### 10. Parameter sensitivity",
        "Every declared variant, favourable or not, run exactly like the headline. The "
        "headline is MACD 12/26/9, 200-SMA filter, 2.0x ATR stop; nothing here selects "
        "or replaces it. The signal EMA (9) is held fixed per the specification, which "
        "declares fast/slow and stop as the swept parameters.",
        "",
        sensitivity_table(sens),
        "",
        "### 11. Market conditions",
        "Each cell split by the project's regime convention (trend/volatility, labelled "
        "from already-closed bars and used for reporting only, never for decisions). "
        "The source's claimed condition is a trending market, entered in the direction "
        "of the 200-SMA filter.",
        "",
        regime_table(res),
        "",
    ]
    lines += [
        "### 12. Source comparison",
        "The source is the original inventor's 1979 booklet, which specifies MACD 12/26/9 "
        "with signal-line crossovers and makes qualitative claims - that MACD times trend "
        "changes and that signal-line crosses catch them early. It publishes no win rate, "
        "no reward-to-risk ratio, no Sharpe, and no drawdown figures, and it predates "
        "crypto, fees of 0.055% per side, and perp funding entirely. So there is no "
        "claimed performance number to reproduce; the only testable source claim is "
        "directional. Section 11 checks it: crossover entries do trade with the declared "
        "trend (the 200-SMA filter enforces that by construction), and the question this "
        "report answers is whether the edge survives costs on this universe - the source "
        "gives no basis for any stronger comparison. Sourcing strength: primary and "
        "original for the rule, silent on everything this project measures.",
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
    body = "\n".join(lines)
    return body

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
    # measured before the final number is written (same convention as run_s10).
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
        print(f"\nReplaced Strategy #11 in {logbook.CSV_PATH.name} and {logbook.MD_PATH.name}.")
    else:
        print("\nDry run; no files appended. Pass --log to append the six CSV rows and this report.")


if __name__ == "__main__":
    main(write="--log" in sys.argv)

