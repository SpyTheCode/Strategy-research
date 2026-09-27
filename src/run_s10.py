"""Execute Strategy #10 exactly as specified in specs/s10_rsi2.md (final).

Both exit variants share one entry definition and one 1R distance. The
headline uses the resolved 2% stop with 10/90 entry thresholds; the stop and
entry-threshold sweeps are independent variants and never replace it.
"""

from __future__ import annotations

import sys

import numpy as np

import context_checks
import coverage
import logbook
import runner
import s10_rsi2 as s10
from discard_bar import breakeven_win_rate, describe, exit_death, verdict
from harness import Trade, metrics

NAME = "RSI(2) trend-filtered mean reversion (SMA200; long/short)"
COINS_STR = "+".join(runner.COINS)
IVS = runner.INTERVALS
EXITS = ("native", "forced-1:3")
STOP_SWEEP = (0.01, 0.02, 0.03)
ENTRY_SWEEP = ((5.0, 95.0), (10.0, 90.0), (15.0, 85.0))
# Funding is unmodelled in the returns; a settlement lands every 8 hours.
HOURS_PER_BAR = {"1H": 1.0, "4H": 4.0, "1D": 24.0}
SETTLEMENT_HOURS = 8.0
# Funding is unmodelled in the returns. This assumed base rate is an estimate, not
# a measured rate: 0.01% per 8-hour settlement is a mid-range figure for this venue.
BASE_FUNDING_RATE_PCT = 0.0001
# With 1% of equity risked against a 2% stop, position size is 50% of equity, so one
# settlement costs rate x 50 in risk units (1R = 1% of equity).
POSITION_MULTIPLE_R = 1.0 / s10.STOP_FRAC


def make_spec(stop_frac: float = s10.STOP_FRAC,
              oversold: float = s10.OVERSOLD,
              overbought: float = s10.OVERBOUGHT) -> runner.StrategySpec:
    """One spec. A sweep varies exactly one parameter and keeps everything else."""
    return runner.StrategySpec(
        name=f"{NAME} stop={stop_frac:.1%} entry={oversold:g}/{overbought:g}",
        add_indicators=s10.add_indicators,
        entry=lambda df: s10.entry(df, oversold, overbought, stop_frac),
        native_exit=s10.native_exit,
        warmup=s10.WARMUP,
        native_time_limit=None,
    )


def _g(x, nd: int = 2) -> str:
    return "n/a" if x is None or not np.isfinite(x) else f"{x:.{nd}f}"


def _days_line(cov: dict, iv: str) -> str:
    return " / ".join(f"{c.replace('USDT', '')} {cov[(iv, c)]['days']:.0f}d"
                      for c in runner.COINS if (iv, c) in cov)


def headline_table(res: dict, summary: dict, cov: dict) -> str:
    rows = [
        "| Timeframe | Exit | Trades | Days/coin | Win% | RR | R pre-fee | R post-fee | R/trade | Sharpe | Max DD % | Max DD R | Verdict |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for iv in IVS:
        for label, vkey in (("native", "verdict_native"), ("forced-1:3", "verdict_forced")):
            m = summary[iv][label]
            rows.append(
                f"| {iv} | {label} | {m['trades']} | {_days_line(cov, iv)} | {_g(m['win_rate'] * 100, 1)} | "
                f"{_g(m['rr_achieved'])} | {_g(m['r_sum_pre_fee'], 1)} | {_g(m['r_sum_post_fee'], 1)} | "
                f"{_g(m['expectancy_post_fee_r'], 3)} | {_g(m['sharpe_post_fee'])} | "
                f"{_g(m['max_drawdown_pct'], 1)} | {_g(m['max_drawdown_r'], 1)} | **{summary[iv][vkey]}** |"
            )
    return "\n".join(rows)


def audit_md(res: dict) -> str:
    keys = sorted(res["audit"])
    rows = ["| Dataset | Columns checked | Result |", "|---|---|---|"]
    passed = sum(res["audit"][k][0] for k in keys)
    for k in keys:
        ok, cols, problems = res["audit"][k]
        note = "PASS" if ok else f"FAIL: {'; '.join(problems[:2])}"
        rows.append(f"| {k} | {', '.join(cols)} | {note} |")
    rows.append("")
    rows.append(f"**{passed} of {len(keys)} datasets passed.** Each indicator value at every cut "
                "bar was identical computed on truncated history and on full history.")
    return "\n".join(rows)


def _side_stats(trades: list[Trade]) -> tuple[int, str, str, str]:
    ts = [t for t in trades if t.exit_price is not None and np.isfinite(t.net_r)]
    n = len(ts)
    if not n:
        return 0, "n/a", "n/a", "n/a"
    net = np.array([t.net_r for t in ts])
    bars = float(np.mean([t.bars_held for t in ts]))
    return n, f"{np.mean(net > 0) * 100:.1f}", f"{net.sum():.2f}", f"{net.mean():+.3f} ({bars:.1f} bars)"


def per_side(res: dict) -> str:
    rows = ["| Timeframe | Exit | Side | Trades | Win% | R post-fee | R/trade, avg bars |",
            "|---|---|---|---:|---:|---:|---|"]
    for iv in IVS:
        for label in EXITS:
            trades = res["trades"][(iv, label)]
            for side, direction in (("long", 1), ("short", -1)):
                n, wr, tot, per = _side_stats([t for t in trades if t.direction == direction])
                rows.append(f"| {iv} | {label} | {side} | {n} | {wr} | {tot} | {per} |")
    return "\n".join(rows)


def concentration(res: dict) -> str:
    rows = ["| Timeframe | Exit | Trades | Total R | Best trade | Best 5 trades | Best 5 as % of total |",
            "|---|---|---:|---:|---:|---:|---:|"]
    for iv in IVS:
        for label in EXITS:
            vals = np.array([t.net_r for t in res["trades"][(iv, label)]
                             if t.exit_price is not None and np.isfinite(t.net_r)])
            if not len(vals):
                rows.append(f"| {iv} | {label} | 0 | n/a | n/a | n/a | n/a |")
                continue
            total = float(vals.sum())
            best5 = float(np.sort(vals)[-5:].sum())
            share = 100.0 * best5 / total if total != 0 else float("nan")
            rows.append(f"| {iv} | {label} | {len(vals)} | {total:.2f} | {vals.max():+.2f} | "
                        f"{best5:+.2f} | {_g(share, 1)} |")
    return "\n".join(rows)


def regime_table(res: dict) -> str:
    rows = ["| Timeframe | Exit | Regime | Trades | Net R | R/trade |", "|---|---|---|---:|---:|---:|"]
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


def funding_table(res: dict) -> str:
    rows = ["| Timeframe | Exit | Avg bars held | Avg holding hours | Est. settlements/trade | Est. funding R/trade @ 0.01%/8h |",
            "|---|---|---:|---:|---:|---:|"]
    for iv in IVS:
        for label in EXITS:
            m = res["pooled"][(iv, label)]
            hours = m["avg_bars_held"] * HOURS_PER_BAR[iv]
            settles = hours / SETTLEMENT_HOURS
            # 1% risk against a 2% stop sizes the position at half of equity, so
            # one 0.01% settlement costs 0.01% x 50 = 0.005R.
            rows.append(f"| {iv} | {label} | {_g(m['avg_bars_held'], 1)} | {_g(hours, 1)} | "
                        f"{_g(settles, 2)} | {_g(settles * BASE_FUNDING_RATE_PCT * POSITION_MULTIPLE_R, 3)} |")
    return "\n".join(rows)


def significance_table(ctx: dict) -> str:
    rows = ["| Timeframe | Exit | Trades | Pre-fee R/trade | t pre-fee | Post-fee R/trade | t post-fee | vs 2.0 |",
            "|---|---|---:|---:|---:|---:|---:|---|"]
    for iv in IVS:
        for label, key in (("native", "sig_native"), ("forced-1:3", "sig_forced")):
            s = ctx[iv][key]
            t = s["t_net"]
            if not np.isfinite(t):
                vs = "no spread to measure"
            elif t >= 2.0:
                vs = "beyond the noise threshold"
            elif t <= -2.0:
                vs = "reliably negative, distinguishable from noise"
            else:
                vs = "inside the range chance produces"
            rows.append(f"| {iv} | {label} | {s['n']} | {s['gross_mean']:+.4f} | "
                        f"{_g(s['t_gross'])} | {s['net_mean']:+.4f} | {_g(t)} | {vs} |")
    return "\n".join(rows)

def overlap_block(res: dict, summary: dict) -> str:
    """Per timeframe: do the two exits trade the same entries, and does the exit decide it?"""
    lines = []
    for iv in IVS:
        nat = res["trades"][(iv, "native")]
        f13 = res["trades"][(iv, "forced-1:3")]
        ov = context_checks.entry_overlap(nat, f13)
        lines.append(f"**{iv}.** The two variants share **{ov:.1%}** of their entry timestamps. "
                     f"Exit-death: **{summary[iv]['exit_death']}** - {summary[iv]['exit_death_diag']}")
        if ov < context_checks.MIN_OVERLAP:
            keys = ({(t.direction, t.entry_time) for t in nat}
                    & {(t.direction, t.entry_time) for t in f13})
            sn = [t for t in nat if (t.direction, t.entry_time) in keys]
            sf = [t for t in f13 if (t.direction, t.entry_time) in keys]
            mn, mf = metrics(sn, interval=iv), metrics(sf, interval=iv)
            flag, _ = exit_death(mn, mf)
            lines.append(
                f"  That is below the {context_checks.MIN_OVERLAP:.0%} floor, so the exit comparison "
                f"is rerun on the {len(keys)} entry timestamps both variants took: native "
                f"{mn['expectancy_post_fee_r']:+.3f}R/trade over {len(sn)} completed trades vs "
                f"forced 1:3 {mf['expectancy_post_fee_r']:+.3f}R/trade over {len(sf)}. "
                f"Exit-death on that shared subset: **{flag}**."
            )
    return "\n\n".join(lines)


def sensitivity_results() -> dict:
    """Each variant is a fresh run over every coin, timeframe and exit."""
    out: dict[str, dict] = {}
    for stop in STOP_SWEEP:
        out[f"stop {stop:.0%}"] = runner.run(make_spec(stop_frac=stop),
                                             intervals=IVS, audit=False)
    for low, high in ENTRY_SWEEP:
        out[f"entry {low:g}/{high:g}"] = runner.run(make_spec(oversold=low, overbought=high),
                                                    intervals=IVS, audit=False)
    return out


def sensitivity_table(sens: dict) -> str:
    rows = ["| Variant | Timeframe | Exit | Trades | Win% | R post-fee | R/trade | Sharpe | Verdict |",
            "|---|---|---|---:|---:|---:|---:|---:|---|"]
    for variant, res in sens.items():
        for iv in IVS:
            for label in EXITS:
                m = res["pooled"][(iv, label)]
                v, _ = verdict(m, label)
                rows.append(f"| {variant} | {iv} | {label} | {m['trades']} | "
                            f"{_g(m['win_rate'] * 100, 1)} | {_g(m['r_sum_post_fee'], 1)} | "
                            f"{_g(m['expectancy_post_fee_r'], 3)} | {_g(m['sharpe_post_fee'])} | {v} |")
    return "\n".join(rows)


def discard_table(res: dict, summary: dict) -> str:
    rows = ["| Timeframe | Exit | Verdict | Criteria met or missed |", "|---|---|---|---|"]
    for iv in IVS:
        for label, vkey, rkey in (("native", "verdict_native", "reason_native"),
                                  ("forced-1:3", "verdict_forced", "reason_forced")):
            extra = ""
            if label == "forced-1:3":
                be = summary[iv]["breakeven_wr_forced"]
                wr = res["pooled"][(iv, label)]["win_rate"] * 100
                extra = (f" A 1:3 exit needs {be * 100:.1f}% wins just to cover its own fee bill; "
                         f"this cell measured {wr:.1f}%.")
            rows.append(f"| {iv} | {label} | **{summary[iv][vkey]}** | {summary[iv][rkey]}.{extra}")
    return "\n".join(rows)


def report_body(res: dict, summary: dict, cov: dict, ctx: dict, sens: dict) -> str:
    counts: dict[str, int] = {}
    for iv in IVS:
        for label, vkey in (("native", "verdict_native"), ("forced-1:3", "verdict_forced")):
            counts[summary[iv][vkey]] = counts.get(summary[iv][vkey], 0) + 1
    tally = ", ".join(f"{n}x {v}" for v, n in sorted(counts.items()))
    coins = sorted({c for _, c in cov})
    pre_pos = sum(1 for iv in IVS for lab in EXITS
                  if summary[iv][lab]["r_sum_pre_fee"] > 0)
    any_positive = any(summary[iv][lab]["r_sum_post_fee"] > 0 for iv in IVS for lab in EXITS)
    if pre_pos:
        pre = (f"{pre_pos} of {len(IVS) * len(EXITS)} cells are profitable before fees, so the "
               "entry signal does carry a measurable mean-reversion tendency - but after 0.055% "
               "per side against a 2% stop it does not survive as an executable edge on this "
               "universe.")
    else:
        pre = ("No cell is profitable even before fees, so on this universe the entry signal "
               "carries no exploitable mean-reversion tendency at these thresholds.")
    lines = [
        "## Strategy #10 - RSI(2) trend-filtered mean reversion",
        "",
        f"**Tested:** {logbook.date.today().isoformat()} - **Coins:** {COINS_STR} - "
        f"**Timeframes:** {', '.join(IVS)} - **Fees:** Bybit taker 0.055% per side - "
        "**Risk:** 1% of starting equity per trade, not compounded",
        "",
        "### 1. Rule and source",
        "On a closed bar t: **long** if close[t] > SMA200[t] and RSI(2)[t] < 10; **short** if "
        "close[t] < SMA200[t] and RSI(2)[t] > 90. Comparisons are strict, so equality is neither. "
        "Entry fills at bar t+1 open and the fixed 2% initial stop is measured from that actual "
        "fill (long entry x 0.98, short x 1.02), which defines 1R. **Native exit:** close a long "
        "once RSI(2) on a completed bar is strictly above 70 and a short once it is strictly below "
        "30, filled at the next open; the stop stays armed throughout, and there is no reversal on "
        "the exit bar - the next position needs its own later qualifying signal. No take-profit, "
        "no pyramiding, at most one position per coin per timeframe. **Forced-1:3 variant:** "
        "identical entries and identical 1R with a 1R stop, 3R target and 30-bar limit, under the "
        "shared engine conventions (the stop wins intrabar ties, a bar that gaps through the stop "
        "fills at the open, and a trade still open at the end of the data is discarded rather than "
        "marked to the last close).",
        "",
        "**Provenance:** the RSI(2) short-term mean-reversion family associated with Larry Connors, "
        "*Short Term Trading Strategies That Work* (2008), and Larry Williams, *Long-Term Secrets "
        "to Short-Term Trading* (1999). Connors' commonly cited pullback is long-only and exits on "
        "a 5-day SMA, so the short mirror, the 70/30 RSI exits and the fixed 2% stop are this "
        "test's declared adaptations and are not attributed to that source as canonical. No source "
        "performance claim is assumed or reproduced.",
        "",
        "### 2. Placeholders and adaptations",
        "- RSI(2): Wilder recursive smoothing (alpha = 1/2, `adjust=False`), needing two "
        "close-changes before a value exists; average loss of zero with positive average gain reads "
        "100, and both zero reads 50.",
        "- Trend filter: a contemporaneous, unshifted 200-bar close SMA, requiring all 200 closes.",
        "- Thresholds: entry 10/90, native exit 70/30, every comparison strict.",
        "- Initial stop: fixed 2.0% from the actual next-open fill; no trailing and no "
        "recalculation. A project risk convention, not a source parameter.",
        "- Execution: closed-bar decision and next-open fill; taker 0.055% each side; 1% of "
        "starting equity risked per trade, not compounded.",
        "- One position per coin per timeframe; no pyramiding; both long and short are traded.",
        "- Warmup is 201 bars on every timeframe, applied identically to the headline and to every "
        "sweep.",
        "- The forced 30-bar limit is the project's shared unvalidated convention, not an RSI "
        "source parameter.",
        "- Independent sweeps, each a fresh run that never replaces the headline: stop 1%/2%/3%, "
        "and entry pair 5/95, 10/90, 15/85 with the 70/30 exit thresholds held fixed.",
        "",
        "### 3. Lookahead audit",
        audit_md(res),
        "",
        "### 4. Results table",
        "Coins are pooled inside each timeframe; timeframes are never pooled with each other. All "
        "money figures are post-fee.",
        "",
        headline_table(res, summary, cov),
        "",
        coverage.summary_line(cov, coins, IVS),
        "",
        "### 5. Statistical significance",
        "t is each cell's mean per-trade R divided by its own standard error; roughly 2.0 is the "
        "noise threshold, and a negative result needs no such defence.",
        "",
        significance_table(ctx),
        "",
        "### 6. Concentration",
        "How much of each cell's total R rests on one trade and on the best five. A negative total "
        "makes the percentage shares directionally meaningless, so read them alongside Total R.",
        "",
        concentration(res),
        "",
        "### 7. Long/short breakdown",
        per_side(res),
        "",
        "### 8. Exit-death and overlap",
        "The two exits share one entry rule and one 1R, so any difference between them is "
        "attributable to the exit alone. Overlap is the share of entry timestamps they have in "
        "common; below 85% the comparison is rerun on shared entries only.",
        "",
        overlap_block(res, summary),
        "",
        "**Exit composition.**",
        "",
        exit_table(res),
        "",
        "### 9. Funding",
        "Funding is not modelled in any return above. Settlements land every 8 hours on this "
        "venue, so holding time is the cost exposure:",
        "",
        funding_table(res),
        "",
        f"The base rate used for that estimate is **{BASE_FUNDING_RATE_PCT * 100:.3f}% per 8-hour "
        "settlement**, an assumed mid-range figure for this venue rather than a rate measured "
        f"from the data. Position size is {POSITION_MULTIPLE_R:.0f}% of equity because 1% is "
        "risked against a 2% stop, which is what converts a percentage settlement into risk "
        "units.",
        "",
        "KEEP survival assessment: "
        + ("some cells are already profitable after fees, so funding is the difference between a "
           "marginal edge and none at all - it would erode any cell that cleared the discard bar "
           "on fees alone. " if any_positive else
           "no cell is profitable after fees even before any funding cost, so funding cannot "
           "rescue a verdict here - it can only make a losing cell lose faster. ")
        + "Funding is unmodelled, so no verdict in this report is a claim that an edge survives "
        "carry costs, and this strategy holds shorts as well as longs, whose true cost is not "
        "captured by the fee column alone.",
        "",
        "### 10. Parameter sensitivity",
        "Every declared variant, favourable or not. The headline is stop 2% / entry 10/90; nothing "
        "here selects or replaces it.",
        "",
        sensitivity_table(sens),
        "",
        "### 11. Market conditions",
        "Each cell split by the project's regime convention (trend/volatility, labelled from "
        "already-closed bars and used for reporting only, never for decisions).",
        "",
        regime_table(res),
        "",
        "### 12. Source comparison",
        "The approved specification supplies no source performance numbers to reproduce, so there "
        "is no claimed return, win rate or Sharpe to check these results against. The measured "
        "numbers are those in section 4, and the honest statement is that no source comparison is "
        "available for this rule as tested.",
        "",
        "### 13. Discard-bar verdicts",
        "Every cell is scored against the same fixed bar, applied after fees:",
        "",
        discard_table(res, summary),
        "",
        "```",
        describe(),
        "```",
        "",
        f"### 14. Bottom line",
        f"Across {len(IVS)} timeframes x 2 exits ({len(IVS) * 2} cells) the discard bar returns "
        f"**{tally}**. {pre} What would change a verdict: a longer or different "
        "sample that lifts a cell's post-fee expectancy past the KEEP bar rather than merely past "
        "zero; a validated funding and slippage model rather than an unmodelled one; and "
        "out-of-sample confirmation. Nothing here is a live-trading recommendation, and no sweep "
        "result was used to reselect the headline.",
    ]
    return "\n".join(lines)

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
        "- `src/s10_rsi2.py` and `src/run_s10.py`: the strategy and its runner, already on disk.\n"
        "- Nothing is deleted and no earlier strategy's entry is rewritten; both logs are "
        "append-only."
    )


def append_logs(res: dict, summary: dict, cov: dict, md: str) -> None:
    """Six headline rows, then the report. Sensitivity runs add no CSV rows."""
    for iv in IVS:
        for label, vkey in (("native", "verdict_native"), ("forced-1:3", "verdict_forced")):
            logbook.log_row(
                strategy=f"#10 RSI(2) SMA200 trend filter",
                coins=COINS_STR,
                timeframes=iv,
                exit_type=label,
                m=res["pooled"][(iv, label)],
                exit_death_flag=summary[iv]["exit_death"],
                verdict=summary[iv][vkey],
                coverage_days=coverage.days_by_coin(cov, iv, runner.COINS),
            )
    logbook.log_md(md)


def main(write: bool) -> None:
    before = {p.name: sum(1 for _ in open(p, encoding="utf-8"))
              for p in (logbook.CSV_PATH, logbook.MD_PATH)}

    # audit=True: the runner audits every dataset first and raises before any result is produced.
    spec = make_spec()
    res = runner.run(spec, intervals=IVS)
    summary = runner.summarise(spec, res, intervals=IVS)
    ctx = context_checks.summarise(res, runner.COINS, IVS, stop_pct=s10.STOP_FRAC * 100)
    cov = coverage.collect(runner.COINS, IVS, spec.warmup_for)
    sens = sensitivity_results()

    body = report_body(res, summary, cov, ctx, sens)
    # log_md writes text.rstrip() + "\n\n", so the line-count growth is one more than
    # the number of lines in the text it receives - which is the whole report,
    # section 15 included. That section's own line count is stable, so it can be
    # measured before the final number is written.
    n_files = len(files_section(before, 0).splitlines())
    md_added = len(body.splitlines()) + 1 + n_files + 1
    md = body + "\n\n" + files_section(before, md_added)
    assert len(md.splitlines()) == md_added - 1

    print(md)
    print("\n### Coverage\n" + coverage.md_table(cov, runner.COINS, IVS))
    print("\n### Per coin\n" + runner.per_coin_table(res, intervals=IVS))
    print("\nLog line counts before append: "
          + ", ".join(f"{k} {v}" for k, v in before.items()))

    if write:
        append_logs(res, summary, cov, md)
        print(f"\nAppended Strategy #10 to {logbook.CSV_PATH.name} and {logbook.MD_PATH.name}.")
    else:
        print("\nDry run; no files appended. Pass --log to append the six CSV rows and this report.")


if __name__ == "__main__":
    main(write="--log" in sys.argv)


