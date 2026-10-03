r"""Run Strategy #9 RE-RUN - NR7 (Bulkowski) - full 15-section report.

Usage:  .venv\Scripts\python.exe src/run_s09_rerun.py [--log]

DRY RUN default: nothing is appended to strategy_log.md / strategy_log.csv.
NEW files only; s09_nr7.py and run_s09.py are never opened or touched.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import bybit_data
import context_checks
import coverage
import discard_bar
import harness
import logbook
import runner
import s09_nr7_rerun as s9
from discard_bar import breakeven_win_rate, exit_death, verdict
from harness import metrics

NAME = "#9 RE-RUN NR7 (Bulkowski): stop orders at NR7 high/low, REST_BARS=1, offset 0"
COINS_STR = "BTCUSDT+SOLUSDT+XRPUSDT"
IVS = ["1H", "4H", "6H", "1D"]
EXITS = ("native", "forced-1:3")
HOURS_PER_BAR = {"1H": 1.0, "4H": 4.0, "6H": 6.0, "1D": 24.0}
BASE_FUNDING_RATE = 0.0001   # 0.01% per 8h settlement - a floor, not a measurement
MIN_OVERLAP = 0.85
DATA_NOTE = (
    "Data: the Sep 4, 2026 cache. The final bars of 1H (Sep 5 00:00) and 6H "
    "(Sep 5 12:00) are permanently partial and are NOT dropped. The 6H files "
    "are a later data vintage than the other timeframes."
)


def _g(x, nd=2):
    return "n/a" if x is None or x != x else f"{x:.{nd}f}"


def _fmt_t(t):
    return "n/a" if t is None or t != t else f"{t:+.2f}"


def make_spec(*, n=7, rest_bars=1, offset_mult=0.0) -> runner.StrategySpec:
    add_ind = lambda df: s9.add_indicators(df, n=n, rest_bars=rest_bars,
                                           offset_mult=offset_mult)
    return runner.StrategySpec(
        name=NAME,
        add_indicators=add_ind,
        entry=s9.no_entry,
        native_exit=s9.native_exit,
        warmup=0,
        warmup_fn=lambda iv: s9.warmup_for(iv),
        resting=True,
        notes=(f"n={n} rest_bars={rest_bars} offset_mult={offset_mult:g}; "
               "resting stops at NR7 high/low; stop = opposite pattern end; "
               "native = measure rule (1:1 at offset 0); one position; "
               "double-touch bars skipped by engine convention"),
    )


def sensitivity_results() -> list[dict]:
    """Spec section 10 sweeps, each independent: offset 0.1%, REST 2, REST 3, NR4."""
    variants = [
        ("headline: N=7, REST_BARS=1, offset 0", dict(n=7, rest_bars=1, offset_mult=0.0), True),
        ("offset 0.1% of bar D's range (REST 1, N 7)", dict(n=7, rest_bars=1, offset_mult=0.001), False),
        ("REST_BARS=2 (N 7, offset 0)", dict(n=7, rest_bars=2, offset_mult=0.0), False),
        ("REST_BARS=3 (N 7, offset 0)", dict(n=7, rest_bars=3, offset_mult=0.0), False),
        ("NR4 in place of NR7 (REST 1, offset 0)", dict(n=4, rest_bars=1, offset_mult=0.0), False),
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
                    "variant": vname, "exit": label, "interval": iv,
                    "trades": m["trades"],
                    "win_rate": _g(m["win_rate"] * 100, 1),
                    "r_total": _g(m["r_sum_post_fee"], 1),
                    "r_trade": _g(m["expectancy_post_fee_r"], 3),
                    "sharpe": _g(m["sharpe_post_fee"]),
                    "verdict": v,
                })
    return out


def concentration(trades: list) -> dict:
    """Share of total post-fee R contributed by the best trade / best five."""
    closed = [t for t in trades if t.exit_price is not None and np.isfinite(t.net_r)]
    if not closed:
        return {"best1_pct": float("nan"), "best5_pct": float("nan")}
    rs = sorted((t.net_r for t in closed), reverse=True)
    total = sum(rs)
    if total <= 0:
        return {"best1_pct": float("inf") if total == 0 else float("nan"),
                "best5_pct": float("inf") if total == 0 else float("nan")}
    return {"best1_pct": rs[0] / total * 100.0,
            "best5_pct": sum(rs[:5]) / total * 100.0}


def funding_estimate(trades: list, interval: str) -> dict:
    """Base-rate funding: 0.01% of notional per 8h held, measured in R."""
    hb = HOURS_PER_BAR[interval]
    rows = []
    for t in trades:
        if t.exit_price is None or not np.isfinite(t.risk_per_unit) or t.risk_per_unit <= 0:
            continue
        settlements = t.bars_held * hb / 8.0
        rows.append(settlements * BASE_FUNDING_RATE * t.entry_price / t.risk_per_unit)
    if not rows:
        return {"hold_bars": float("nan"), "settlements": float("nan"),
                "funding_r": float("nan")}
    return {"hold_bars": float(np.mean([t.bars_held for t in trades
                                        if t.exit_price is not None])),
            "settlements": float(np.mean(rows)) * 8.0 / (hb if hb else 8.0),
            "funding_r": float(np.mean(rows))}


def final_bar_check(res: dict, coins, intervals) -> list[str]:
    """Does each dataset's final bar appear as a trade's entry or exit time?"""
    lines = []
    for iv in intervals:
        for sym in coins:
            df = bybit_data.drop_forming_bar(bybit_data.load(sym, iv), iv)
            last = df.index[-1]
            touched = []
            for label in EXITS:
                for t in res["trades"][(sym, iv, label)]:
                    if t.entry_time == last or t.exit_time == last:
                        touched.append(label)
                        break
            lines.append(f"  {sym} {iv}: last bar {last} "
                         f"({'touches: ' + ', '.join(touched) if touched else 'changes no trade'})")
    return lines

def long_short_lines(trades: list) -> str:
    out = []
    for d, lab in [(1, "long"), (-1, "short")]:
        ts = [t for t in trades if t.direction == d and t.exit_price is not None]
        if not ts:
            out.append(f"  {lab:<6} 0 trades")
            continue
        net = np.array([t.net_r for t in ts])
        out.append(f"  {lab:<6} {len(ts):>5} trades | win {float((net > 0).mean()) * 100:5.1f}% "
                   f"| R sum {net.sum():+8.1f} | R/trade {net.mean():+.3f}")
    return "\n".join(out)


def shared_entry_rerun(nat: list, f13: list):
    """Entry overlap; if below 85%, metrics recomputed on the shared entries only."""
    sa = {(t.direction, t.entry_time) for t in nat}
    sb = {(t.direction, t.entry_time) for t in f13}
    union = sa | sb
    ov = float(len(sa & sb) / len(union)) if union else float("nan")
    if not (ov == ov) or ov >= MIN_OVERLAP:
        return ov, None, None
    shared = sa & sb
    nat2 = [t for t in nat if (t.direction, t.entry_time) in shared]
    f132 = [t for t in f13 if (t.direction, t.entry_time) in shared]
    return ov, metrics(nat2, interval=""), metrics(f132, interval="")


def pooled_table(res: dict, summary: dict, intervals) -> str:
    lines = [runner.HEAD, "-" * len(runner.HEAD)]
    for iv in intervals:
        for label in EXITS:
            m = res["pooled"][(iv, label)]
            v = summary[iv]["verdict_native" if label == "native" else "verdict_forced"]
            lines.append(runner._line(iv, label, m, v))
    return "\n".join(lines)


def report_body(res: dict, summary: dict, cov: dict, ctx: dict, sens: list[dict]) -> str:
    L: list[str] = []
    n_audit = len(res["audit"])
    n_pass = sum(1 for ok, _, _ in res["audit"].values() if ok)

    L += [
        "# Strategy #9 RE-RUN - NR7 (Bulkowski)",
        "",
        "## 1. Rule and source",
        "Source: Thomas Bulkowski, \"NR7\", thepatternsite.com (Encyclopedia of Chart Patterns).",
        "Setup: bar D is an NR7 when its range (high - low, NOT true range) is strictly smaller",
        "than the range of each of the six bars before it; ties do not qualify. Entry: resting",
        "stop orders through bar D+1 only (REST_BARS=1) - buy stop at bar D's high, sell stop at",
        "bar D's low; first touch is the trade. Stop: the opposite end of the pattern; that",
        "distance is 1R. Native exit: the measure rule - target = pattern height beyond bar D's",
        "high (long) / low (short); at offset 0 that is exactly 1R, a symmetric 1:1. Forced",
        "variant: same stop, 3R target, 30-bar time limit. Fees: taker 0.055% per side on both",
        "legs. Scope: BTCUSDT/SOLUSDT/XRPUSDT on 1H/4H/6H/1D, full history, coins pooled per",
        "timeframe, timeframes never pooled, native vs forced 1:3.",
        "",
        "## 2. Placeholders and adaptations (all pre-declared)",
        "- Trigger offset = 0 in the headline (sensitivity: 0.1% of bar D's range).",
        "- REST_BARS = 1 in the headline (sensitivities: 2 and 3).",
        "- N = 7 in the headline (sensitivity: NR4). Strict '<' against all prior six ranges.",
        "- 30-bar forced-1:3 time limit: the project's shared unvalidated convention, not a",
        "  Bulkowski parameter.",
        "- Double-touch rule: the spec asks for a 1R loss when bar D+1 touches BOTH ends,",
        "  direction attributed to the trigger nearer the open. The shared resting engine",
        "  cannot express that without code changes (its convention is to skip a bar that",
        "  touches both triggers and count it in stats['ambiguous']); per the blind rules no",
        "  engine changes were built. The engine convention was used instead: double-touch",
        "  bars produce NO trade, and the per-timeframe ambiguous counts are disclosed in",
        "  section 3. This affects only the long/short split and trade counts, and it is the",
        "  one place this re-run departs from the spec text.",
        "- Gap-through-entry convention: the engine's existing one - a stop order that gaps",
        "  through fills at the WORSE of the trigger price and the bar's open, and 1R is the",
        "  actual entry-to-stop distance.",
        "- Position handling: the engine's existing convention - one position at a time, no",
        "  re-entry inside a session, no reversal; a trade still open at data end is",
        "  discarded, not marked to close.",
        "",
        f"## 3. Lookahead audit - {n_pass}/{n_audit} datasets passed",
        "Every dataset was audited by the shared truncation audit: indicators recomputed on",
        "truncated history must match full-history values at the cut. Entry logic coverage:",
        "the buy/sell triggers are bar D's high/low (plus offset), computed from bars that",
        "closed strictly before the session; the engine then tests those triggers against",
        "bar D+1's own high/low - the first bar the orders could legally touch. No decision",
        "uses bar D+1's data to fill a bar D+1 order.",
        "",
    ]
    bad = [f"{k}: {p}" for k, (ok, _, p) in res["audit"].items() if not ok]
    L.append("Failures: " + ("none" if not bad else "; ".join(bad)))
    L += ["", DATA_NOTE, "", "Final-bar effect per dataset:"]
    L += final_bar_check(res, runner.COINS, IVS)
    amb = {iv: {label: sum(res["fills"][(s, iv, label)].get("ambiguous", 0)
                           for s in runner.COINS) for label in EXITS} for iv in IVS}
    L += ["", "Double-touch (both triggers touched inside the order's session), pooled coins:",
          "  " + " | ".join(f"{iv}: native {amb[iv]['native']}, forced-1:3 {amb[iv]['forced-1:3']}"
                            for iv in IVS)]
    L += ["", "## 4. Results table - coins pooled per timeframe, post-fee", "```",
          pooled_table(res, summary, IVS), "```",
          "Trades from all three coins are pooled inside each timeframe; timeframes are never",
          "pooled with each other. Per-coin detail is printed after the report.", ""]
    return "\n".join(L)

def report_rest(res: dict, summary: dict, cov: dict, ctx: dict, sens: list[dict],
                pooled: dict, per_coin: str, cov_txt: str) -> str:
    L: list[str] = []
    L += ["## 5. Significance - t-test on pooled per-trade R (post-fee), per timeframe"]
    for iv in IVS:
        s = ctx[iv]["sig_native"]
        t = s["t_net"]
        L.append(f"  {iv}: n={s['n']}, post-fee R/trade {s['net_mean']:+.4f}, "
                 f"t={_fmt_t(t)}, {'SIG at 5%' if (t == t and abs(t) >= 1.96) else 'not sig at 5%'}")
    L += ["  (n and t from the shared context_checks significance test; per-coin noise is not", "   independent, so t-statistics overstate certainty somewhat.)", ""]
    L += ["## 6. Concentration of the native-exit result (pooled, post-fee R)"]
    for iv in IVS:
        c = concentration(pooled[iv]["native"])
        L.append(f"  {iv}: best trade {c['best1_pct']:.1f}% of net R; best five "
                 f"{c['best5_pct']:.1f}% (large shares = fragile)")
    L.append("")
    L += ["## 7. Long/short split - native exit, pooled coins, post-fee"]
    for iv in IVS:
        L.append(f"  {iv}:")
        L.append(long_short_lines(pooled[iv]["native"]))
    L.append("")
    L += ["## 8. Exit-overlap - do native and forced-1:3 trade the same entries?",
          "Native-vs-forced entry overlap (union base), pooled per timeframe:"]
    for iv in IVS:
        ov, m_nat, m_f13 = shared_entry_rerun(pooled[iv]["native"], pooled[iv]["forced-1:3"])
        line = (f"  {iv}: overlap {ov * 100:.1f}%")
        if m_nat is not None:
            line += (f" (<{MIN_OVERLAP * 100:.0f}% -> shared-entry re-run: native "
                     f"n={m_nat['trades']}, R/trade={_g(m_nat['expectancy_post_fee_r'], 3)}, "
                     f"forced n={m_f13['trades']}, R/trade={_g(m_f13['expectancy_post_fee_r'], 3)})")
        L.append(line)
    L.append("")
    L += ["## 9. Funding cost at the base rate (0.01% per 8h, estimate - Bybit rates vary)",
          "  Mean holding time, settlements, and R of base-rate funding per trade (native):"]
    for iv in IVS:
        f = funding_estimate(pooled[iv]["native"], iv)
        L.append(f"  {iv}: hold {_g(f['hold_bars'], 1)} bars | "
                 f"funding {_g(f['funding_r'], 4)} R/trade")
    L += ["  (Base rate is a floor, not a measurement; per-trade funding varies by side and hour.)", ""]
    return "\n".join(L)


def report_tail(res: dict, summary: dict, cov: dict, ctx: dict, sens: list[dict],
                pooled: dict, per_coin: str, cov_txt: str) -> str:
    L: list[str] = []
    L += ["## 10. Sensitivities (section-10 sweeps only - never the headline)", "```"]
    for r in sens:
        L.append(f"  {r['variant']:<44} {r['exit']:<11} {r['interval']:<4} "
                 f"n={r['trades']:>5} win {r['win_rate']:>6}% R/trade {r['r_trade']:>7} "
                 f"Sharpe {r['sharpe']:>6} {r['verdict']}")
    L += ["```", "  Headline repeated first for reference; sweep runs reuse the audited indicator", "   pipeline with only the swept parameter changed (audit flag off for speed).", ""]
    L += ["  Note on the REST_BARS=2/3 rows: they are expected to match the headline exactly,",
          "  and not because of a plumbing fault. A session whose only bar D+1 touches",
          "  neither trigger sits strictly inside bar D's range, so bar D+1 is itself NR7 and",
          "  bar D+2 opens a fresh session whose triggers replace the old session's - the",
          "  engine's one-session state machine never grants the old session its extended",
          "  bar (verified: REST=2/3 put ZERO entries on extended bars; only the session",
          "  bookkeeping shifts, e.g. BTCUSDT 1H armed=9668 buckets 9336 under REST=2).",
          "  Measuring a longer order lifetime would need overlapping-session support in the",
          "  shared engine, which the spec's STEP 0 forbids; rows are reported as-engine-is."]
    L += ["## 11. Market conditions - pooled native trades by regime label"]
    for iv in IVS:
        rr = res["pooled"][(iv, "native")].get("regime_r") or {}
        bits = ", ".join(
            f"{k}: n={v['trades']}, R sum {v['r_sum_post_fee']:+.1f} "
            f"({v['r_sum_post_fee'] / v['trades']:+.3f}/trade)"
            for k, v in sorted(rr.items()))
        L.append(f"  {iv}: {bits or 'no regime data'}")
    L += ["  (Regime is a 100-bar average price vs 100-bar-ago average, up/down/side -", "   reporting-only, it does not gate entries.)", ""]
    L += ["## 12. Comparison with the source's own claims",
          "Bulkowski's NR7 page presents the pattern with the measure rule but, as used here,",
          "the source makes no numeric performance claim that this re-run can check - no",
          "average return, win rate, or hold time is claimed for NR7 in the text this re-run",
          "is based on. The measure rule itself is implemented as specified. Nothing was",
          "borrowed from any prior #9 result: this run shares only the engine with the rest",
          "of the project, and the blind constraints were kept throughout.", ""]
    L += ["## 13. Discard-bar verdict, cell by cell", "```"]
    for sym in runner.COINS:
        for iv in IVS:
            for label in EXITS:
                m = res["per_cell"][(sym, iv, label)]
                v, why = verdict(m, label)
                L.append(f"  {sym} {iv} {label:<11} {v:<12} {why}")
    L += ["```", ""]
    L += ["## 14. Bottom line"]
    for iv in IVS:
        for lab in ("native", "forced-1:3"):
            m = summary[iv][lab]
            L.append(f"  {iv} {lab:<11}: {m['trades']} trades, win {_g(m['win_rate'] * 100, 1)}%, "
                     f"{m['expectancy_post_fee_r']:+.3f} R/trade post-fee, "
                     f"Sharpe {_g(m['sharpe_post_fee'])}, verdict {summary[iv]['verdict_native' if lab == 'native' else 'verdict_forced']}")
    L += ["  (Declarative only - what happened, no recommendation.)", ""]
    L += ["## 15. Files changed by this re-run",
          "  New: src/s09_nr7_rerun.py, src/run_s09_rerun.py, specs/s09_nr7_rerun.md.",
          "  No existing file was opened for results, edited, or overwritten; no log entries",
          "  were appended (dry run). s09_nr7.py and run_s09.py were never opened.", ""]
    L += ["Per-coin detail:", "```", per_coin, "```",
          "Data coverage per cell:", "```", cov_txt, "```", "",
          "Per-timeframe significance and entry shares (shared context_checks block):", "```",
          context_checks.text_block(ctx, IVS), "```"]
    return "\n".join(L)


def main() -> None:
    if "--log" in sys.argv:
        print("This re-run is a DRY RUN; --log was requested but nothing is appended "
              "to strategy_log.md/csv by design.")
    spec = make_spec()
    res = runner.run(spec, runner.COINS, IVS, audit=True)
    summary = runner.summarise(spec, res, IVS)          # prints the pooled table
    per_coin = runner.per_coin_table(res, runner.COINS, IVS)
    cov = coverage.collect(runner.COINS, IVS, s9.warmup_for)
    cov_txt = coverage.md_table(cov, runner.COINS, IVS)
    ctx = context_checks.summarise(res, runner.COINS, IVS)
    pooled = {iv: {"native": res["trades"][(iv, "native")],
                   "forced-1:3": res["trades"][(iv, "forced-1:3")]} for iv in IVS}
    sens = sensitivity_results()
    print()
    print(report_body(res, summary, cov, ctx, sens))
    print(report_rest(res, summary, cov, ctx, sens, pooled, per_coin, cov_txt))
    print(report_tail(res, summary, cov, ctx, sens, pooled, per_coin, cov_txt))


if __name__ == "__main__":
    main()


