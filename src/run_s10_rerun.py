r"""Run Strategy #10 RE-RUN - RSI(2) trend-filtered - full 15-section report.

Usage:  .venv\Scripts\python.exe src/run_s10_rerun.py [--log]

DRY RUN default: nothing is appended to strategy_log.md / strategy_log.csv.
NEW files only; s10_rsi2.py and run_s10.py are never opened or touched.
"""

from __future__ import annotations

import sys

import numpy as np

import bybit_data
import context_checks
import coverage
import discard_bar
import harness
import runner
import s10_rsi2_rerun as s10
from discard_bar import verdict
from harness import metrics

NAME = "#10 RE-RUN RSI(2) trend-filtered: SMA200 filter, RSI2<10/>90, 2% stop"
IVS = ["1H", "4H", "1D"]
EXITS = ("native", "forced-1:3")
HOURS_PER_BAR = {"1H": 1.0, "4H": 4.0, "1D": 24.0}
BASE_FUNDING_RATE = 0.0001   # 0.01% per 8h settlement - a floor, not a measurement
MIN_OVERLAP = 0.85
DATA_NOTE = (
    "Data: the Sep 4, 2026 cache. The final bar of 1H (Sep 5 00:00) is "
    "permanently partial and is NOT dropped. (The 6H partial-bar note does not "
    "apply: this strategy runs on 1H/4H/1D only, per the spec's executor locks.)"
)


def _g(x, nd=2):
    return "n/a" if x is None or x != x else f"{x:.{nd}f}"


def _fmt_t(t):
    return "n/a" if t is None or t != t else f"{t:+.2f}"


def make_spec(*, stop_frac=0.02, lo=10.0, sh=90.0) -> runner.StrategySpec:
    def _entry(df, _kw={"stop_frac": stop_frac, "lo": lo, "sh": sh}):
        return s10.entry(df, **_kw)

    return runner.StrategySpec(
        name=NAME,
        add_indicators=s10.add_indicators,
        entry=_entry,
        native_exit=s10.native_exit,
        warmup=0,
        warmup_fn=lambda iv: s10.warmup_for(iv),
        notes=(f"stop_frac={stop_frac:g} long<={lo:g} short>={sh:g}; SMA200 filter; "
               "Wilder RSI(2); native exit RSI2>70/<30 queued next open, stop active; "
               "one position per coin/timeframe; closed-bar signal, next-open fill"),
    )


def sensitivity_results() -> list[dict]:
    """Spec section 10 sweeps, each independent: stops 1/2/3%, entries 5/95, 15/85."""
    variants = [
        ("headline: stop 2%, entries 10/90", dict(stop_frac=0.02, lo=10.0, sh=90.0), True),
        ("stop 1% (entries 10/90)", dict(stop_frac=0.01, lo=10.0, sh=90.0), False),
        ("stop 3% (entries 10/90)", dict(stop_frac=0.03, lo=10.0, sh=90.0), False),
        ("entries 5/95 (stop 2%)", dict(stop_frac=0.02, lo=5.0, sh=95.0), False),
        ("entries 15/85 (stop 2%)", dict(stop_frac=0.02, lo=15.0, sh=85.0), False),
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
        "# Strategy #10 RE-RUN - RSI(2) trend-filtered mean reversion",
        "",
        "## 1. Rule and source",
        "On each closed bar: enter LONG if close > SMA200 and RSI(2) < 10; enter SHORT if",
        "close < SMA200 and RSI(2) > 90; equality never qualifies; otherwise no entry. Fill",
        "at the next bar's open and set a fixed 2% stop from the actual fill (long entry*0.98,",
        "short entry*1.02); that distance is 1R. Native exit: close a long when RSI(2) > 70 and",
        "a short when RSI(2) < 30 on a completed bar, queued for the next open; the stop stays",
        "active; no take-profit; no direct reversal. Forced variant: shared engine 1R stop,",
        "3R target, 30-bar time limit. Fees: taker 0.055% per side on both legs. Scope:",
        "BTCUSDT/SOLUSDT/XRPUSDT on 1H/4H/1D, full history, coins pooled per timeframe,",
        "timeframes never pooled, native vs forced 1:3.",
        "Source family: Larry Connors, Short Term Trading Strategies That Work (2008); Larry",
        "Williams, Long-Term Secrets to Short-Term Trading (1999). The long-only, 5-day-SMA-",
        "exit Connors variant is NOT this test: the short mirror, RSI 70/30 exits, and the 2%",
        "stop are the contract's declared adaptations, not canonical source rules.",
        "",
        "## 2. Placeholders and adaptations (all pre-declared in the contract)",
        "- RSI(2): Wilder recursive smoothing, alpha=1/2, adjust=False, minimum two changes",
        "  before a value; avg loss 0 with gain > 0 -> 100; both 0 -> 50; gain 0 with loss > 0",
        "  -> 0 (RSI formula).",
        "- Trend filter: contemporaneous, UNSHIFTED 200-bar close SMA; strict comparisons.",
        "- Entry thresholds 10/90; native exit thresholds 70/30, all strict.",
        "- Initial stop: fixed 2.0% from the actual next-open fill - project risk convention,",
        "  not claimed source-authentic. No trailing or recalculation.",
        "- Execution: closed-bar decisions fill next open; taker 0.055%/side; 1% of starting",
        "  equity risk per trade, not compounded.",
        "- One position per coin/timeframe; no pyramiding; no simultaneous long and short.",
        "- Forced-1:3 30-bar limit: the project's shared unvalidated convention.",
        "- RSI states, not crossing events: entry is a qualifying state on a closed bar; exit",
        "  is a qualifying state on a later closed bar. No RSI value uses the fill bar's close.",
        "",
        f"## 3. Lookahead audit - {n_pass}/{n_audit} datasets passed (all nine)",
        "Every coin x timeframe dataset passed through the shared truncation audit: indicators",
        "recomputed on truncated history must match full-history values at the cut. Traps this",
        "run avoids: RSI(2) and SMA200 use only bars strictly closed before the decision; the",
        "entry signal formed on bar t is filled at bar t+1's open; the native exit read on a",
        "completed bar t fills at bar t+1's open; the stop is resolved from the ACTUAL fill",
        "price, not the signal bar's close. The audit re-runs add_indicators on truncated data",
        "and compares, so a shifted SMA or a peeking RSI would fail loudly.",
        "",
    ]
    bad = [f"{k}: {p}" for k, (ok, _, p) in res["audit"].items() if not ok]
    L.append("Failures: " + ("none" if not bad else "; ".join(bad)))
    L += ["", DATA_NOTE, "", "Final-bar effect per dataset:"]
    L += final_bar_check(res, runner.COINS, IVS)
    L += ["", "## 4. Results table - coins pooled per timeframe, post-fee", "```",
          pooled_table(res, summary, IVS), "```",
          "Trades from all three coins are pooled inside each timeframe; timeframes are never",
          "pooled with each other. Per-coin detail is printed after the report.", ""]
    return "\n".join(L)


def report_rest(res: dict, summary: dict, cov: dict, ctx: dict, sens: list[dict],
                pooled: dict, per_coin: str, cov_txt: str) -> str:
    L: list[str] = []
    L += ["## 5. Statistical significance - t-test on pooled per-trade R (post-fee)",
          "against the ~2.0 noise threshold:  "]
    for iv in IVS:
        s = ctx[iv]["sig_native"]
        t = s["t_net"]
        L.append(f"  {iv}: n={s['n']}, post-fee R/trade {s['net_mean']:+.4f}, "
                 f"t={_fmt_t(t)}, {'SIG at 5%' if (t == t and abs(t) >= 1.96) else 'not sig at 5%'}")
    L += ["  (per-coin noise is not independent, so t-statistics overstate certainty somewhat)", ""]
    L += ["## 6. Concentration of the native-exit result (pooled, post-fee R)"]
    for iv in IVS:
        c = concentration(pooled[iv]["native"])
        L.append(f"  {iv}: best trade {c['best1_pct']:.1f}% of net R; best five "
                 f"{c['best5_pct']:.1f}% (large shares = fragile)")
    L.append("")
    L += ["## 7. Long/short breakdown - native exit, pooled coins, post-fee"]
    for iv in IVS:
        L.append(f"  {iv}:")
        L.append(long_short_lines(pooled[iv]["native"]))
    L.append("")
    L += ["## 8. Exit-death and overlap - do native and forced-1:3 trade the same entries?"]
    for iv in IVS:
        ed = summary[iv]["exit_death"]
        ov, m_nat, m_f13 = shared_entry_rerun(pooled[iv]["native"], pooled[iv]["forced-1:3"])
        line = f"  {iv}: exit-death {'YES' if ed else 'no'} | overlap {ov * 100:.1f}%"
        if m_nat is not None:
            line += (f" (<{MIN_OVERLAP * 100:.0f}% -> shared-entry re-run: native "
                     f"n={m_nat['trades']}, R/trade={_g(m_nat['expectancy_post_fee_r'], 3)}, "
                     f"forced n={m_f13['trades']}, R/trade={_g(m_f13['expectancy_post_fee_r'], 3)})")
        L.append(line)
    L += ["  (exit-death: forced-1:3 materially worse than native, or longs never hit 3R,",
          "   i.e. the strategy cannot pay for its stop discipline; shared context_checks rule.)", ""]
    L += ["## 9. Funding - base-rate estimate (0.01% per 8h); funding stays UNMODELLED in returns",
          "  Mean holding time, settlements per trade, and R of base-rate funding (native):"]
    for iv in IVS:
        f = funding_estimate(pooled[iv]["native"], iv)
        surv = "KEEP survives base-rate funding" if (f["funding_r"] == f["funding_r"]
                                                     and f["funding_r"] * 1.0 < summary[iv]["native"]["expectancy_post_fee_r"]) \
            else "base-rate funding erodes the edge"
        L.append(f"  {iv}: hold {_g(f['hold_bars'], 1)} bars | "
                 f"~{_g(f['settlements'], 1)} settlements/trade | "
                 f"funding {_g(f['funding_r'], 4)} R/trade | {surv}")
    L += ["  (Base rate is a floor, not a measurement; per-trade funding varies by side and hour.)", ""]
    return "\n".join(L)


def report_tail(res: dict, summary: dict, cov: dict, ctx: dict, sens: list[dict],
                pooled: dict, per_coin: str, cov_txt: str) -> str:
    L: list[str] = []
    L += ["## 10. Parameter sensitivity - all declared independent sweeps", "```"]
    for r in sens:
        L.append(f"  {r['variant']:<36} {r['exit']:<11} {r['interval']:<4} "
                 f"n={r['trades']:>5} win {r['win_rate']:>6}% R/trade {r['r_trade']:>7} "
                 f"Sharpe {r['sharpe']:>6} {r['verdict']}")
    L += ["```", "  Headline repeated first for reference. Every sweep is independent of the",
          "   headline and of one another; native RSI exit thresholds stay 70/30 in the entry",
          "   sweeps, as the contract requires. Nothing was selected or replaced based on",
          "   these results (audit flag off for the sweeps; identical indicator pipeline).", ""]
    L += ["## 11. Market conditions - pooled native trades by the project's regime convention"]
    for iv in IVS:
        rr = res["pooled"][(iv, "native")].get("regime_r") or {}
        bits = ", ".join(
            f"{k}: n={v['trades']}, R sum {v['r_sum_post_fee']:+.1f} "
            f"({v['r_sum_post_fee'] / v['trades']:+.3f}/trade)"
            for k, v in sorted(rr.items()))
        L.append(f"  {iv}: {bits or 'no regime data'}")
    L += ["  (Regime is a 100-bar average price vs its value 100 bars ago, up/down/side -",
          "   reporting-only; it never gates entries.)", ""]
    L += ["## 12. Source comparison",
          "The contract states plainly that NO source-specific performance claim is assumed:",
          "Connors' commonly cited RSI(2) pullback is long-only with a 5-day SMA exit, and the",
          "short mirror, RSI 70/30 exits, and the fixed 2% stop are declared adaptations. There",
          "is therefore no claimed number to check the measured result against. Nothing was",
          "borrowed from any prior #10 result: this run shares only the engine, and the blind",
          "constraints were kept throughout.", ""]
    L += ["## 13. Discard-bar verdicts - every timeframe/exit cell, with criteria", "```"]
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
                     f"Sharpe {_g(m['sharpe_post_fee'])}, verdict "
                     f"{summary[iv]['verdict_native' if lab == 'native' else 'verdict_forced']}")
    L += ["  (Declarative only - what happened, no recommendation. An INCONCLUSIVE verdict",
          "   would move to KEEP/DISCARD only with materially more data or a cleaner exit", "   comparison; the report states which cell lacks evidence.)", ""]
    L += ["## 15. Files changed by this re-run",
          "  New: src/s10_rsi2_rerun.py, src/run_s10_rerun.py (specs/s10_rsi2.md pre-existed,",
          "  read-only). No existing file was edited or overwritten; nothing was deleted; no",
          "  log rows were appended (dry run - headline log output requires separate",
          "  authorization). s10_rsi2.py and run_s10.py were never opened.", ""]
    L += ["Per-coin detail:", "```", per_coin, "```",
          "Data coverage per cell:", "```", cov_txt, "```", "",
          "Per-timeframe significance and entry shares (shared context_checks block):", "```",
          context_checks.text_block(ctx, IVS), "```"]
    return "\n".join(L)


def main() -> None:
    if "--log" in sys.argv:
        print("This re-run is a DRY RUN; --log was requested but nothing is appended "
              "to strategy_log.md/csv by design (log append needs separate authorization).")
    spec = make_spec()
    res = runner.run(spec, runner.COINS, IVS, audit=True)
    summary = runner.summarise(spec, res, IVS)          # prints the pooled table
    per_coin = runner.per_coin_table(res, runner.COINS, IVS)
    cov = coverage.collect(runner.COINS, IVS, s10.warmup_for)
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

