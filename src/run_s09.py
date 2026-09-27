"""Run Strategy #9 - Bulkowski's Narrow Range 7 (NR7), and log it.

Usage:  .venv\\Scripts\\python.exe src\\run_s09.py [--log]

Mirrors run_s04.py, because NR7 needs the same resting-order execution path
Crabel's breakout needed: the two stops sit in the market at prices fixed
before the bar, and fill intrabar.
"""

from __future__ import annotations

import sys

import numpy as np

import bybit_data as bd
import context_checks
import coverage
import lookahead_check
import logbook
import runner
import s09_nr7 as s09
from discard_bar import BAR, breakeven_win_rate, exit_death, verdict
from harness import add_regime_columns, forced_13_exit, metrics, simulate_resting

NAME = "Bulkowski Narrow Range 7 (smallest high-low range of 7 bars, breakout of that bar)"
COINS_STR = "BTCUSDT+SOLUSDT+XRPUSDT"

# Four timeframes, read as one test at four bar sizes: the rule is always
# "smallest range of the last 7 bars, trade the next bar's breakout", and only
# the bar that carries the definition changes. 1H is the headline for the same
# reason as Strategy #4 - it resolves the entry bar most finely.
IVS = ["1H", "4H", "6H", "1D"]
HEADLINE_TF = "1H"

# The source's own crypto result, for a like-for-like comparison. Stated on 38
# cryptocurrencies with a height-based target; see write_logs for the table.
PAPER_WIN_UPTREND = 48
PAPER_WIN_DOWNTREND = 42
PAPER_GAIN = 13
PAPER_LOSS = -7


def make_spec(lookback: int = s09.LOOKBACK,
              offset_mult: float = s09.OFFSET_MULT,
              rest_bars: int = s09.REST_BARS) -> runner.StrategySpec:
    bits = [f"N={lookback}"]
    if offset_mult != s09.OFFSET_MULT:
        bits.append(f"offset={offset_mult:g}x range")
    if rest_bars != s09.REST_BARS:
        bits.append(f"orders rest {rest_bars} bars")
    return runner.StrategySpec(
        name=f"{NAME} [{' '.join(bits)}]",
        add_indicators=lambda df: s09.add_indicators(df, lookback, offset_mult, rest_bars),
        entry=s09.no_entry,            # never consulted: this spec is resting=True
        native_exit=s09.native_exit,
        warmup=0,                      # replaced by warmup_fn
        warmup_fn=lambda interval: max((lookback + 2) *
                                      {"1H": 24, "4H": 6, "6H": 4, "1D": 1}[interval],
                                      120),
        native_time_limit=None,        # the measure rule is the exit, nothing else
        resting=True,
    )


def show_audit(symbol: str = "BTCUSDT", interval: str = HEADLINE_TF) -> bool:
    """Print the lookahead proof on one dataset so it is visible, not asserted."""
    df = bd.drop_forming_bar(bd.load(symbol, interval), interval)
    raw = df[[c for c in df.columns if c in lookahead_check.RAW]].copy()
    return lookahead_check.report(
        f"{NAME} on {symbol} {interval}", raw, s09.add_indicators,
        first_cut=max(300, s09.warmup_for(interval) + 50),
    )


def fills(res: dict, interval: str, label: str) -> dict:
    """Session accounting for one timeframe, summed over the three coins."""
    keys = ["sessions_armed", "traded", "ambiguous", "blocked", "no_touch"]
    out = {k: 0 for k in keys}
    for symbol in runner.COINS:
        f = res["fills"].get((symbol, interval, label), {})
        for k in keys:
            out[k] += int(f.get(k, 0))
    return out


def leg_split(trades) -> dict:
    """Long leg vs short leg, separately. NR7 is symmetric by construction."""
    out = {}
    for side, d in [("long", 1), ("short", -1)]:
        sel = [t for t in trades if t.direction == d and np.isfinite(t.net_r)]
        r = np.array([t.net_r for t in sel]) if sel else np.array([])
        out[side] = {
            "trades": len(sel),
            "r_post_fee": float(r.sum()) if len(r) else float("nan"),
            "win_rate": float((r > 0).mean()) if len(r) else float("nan"),
        }
    return out


def risk_pct(symbol: str, interval: str) -> float:
    """Median 1R - the narrow bar's own range - as a percentage of price.

    This is the number that explains the whole result: the risk unit is the
    SMALLEST range of the last seven bars by definition, so it is smaller than
    a typical candle by construction. Measuring it against the fee is the point
    of the geometry section in the write-up.
    """
    df = s09.add_indicators(bd.drop_forming_bar(bd.load(symbol, interval), interval))
    r = (df["risk_unit"] / df["close"]).dropna()
    return float(r.median() * 100.0) if len(r) else float("nan")


def nr7_pct(symbol: str, interval: str, lookback: int = s09.LOOKBACK) -> float:
    """How often the pattern actually fires, as a share of all bars."""
    df = s09.add_indicators(bd.drop_forming_bar(bd.load(symbol, interval), interval),
                            lookback=lookback)
    return float(df["is_nr7"].mean() * 100.0)


def main(write: bool) -> None:
    print(f"Strategy #9 - {NAME}")
    print("=" * 78)
    if not show_audit():
        print("LOOKAHEAD AUDIT FAILED - refusing to produce any result.")
        return

    spec = make_spec()
    res = runner.run(spec, intervals=IVS)
    summary = runner.summarise(spec, res, intervals=IVS)

    print("\nSession accounting - orders placed / filled / missed (three coins pooled)")
    print(f"{'tf':<5} {'exit':<11} {'armed':>7} {'traded':>7} {'no touch':>9} "
          f"{'both sides':>11} {'blocked':>8}")
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            f = fills(res, interval, label)
            print(f"{interval:<5} {label:<11} {f['sessions_armed']:>7} {f['traded']:>7} "
                  f"{f['no_touch']:>9} {f['ambiguous']:>11} {f['blocked']:>8}")

    print("\nPer coin, per timeframe, per exit")
    print(runner.per_coin_table(res, intervals=IVS))

    r1_pct = float(np.median([risk_pct(s, HEADLINE_TF) for s in runner.COINS]))
    ctx = context_checks.summarise(res, runner.COINS, IVS, stop_pct=r1_pct)
    print("\nContext checks - is the test fair, and is the result distinguishable from luck")
    print(context_checks.text_block(ctx, IVS, stop_pct=r1_pct))

    cov = coverage.collect(runner.COINS, IVS, spec.warmup_for)
    print("\nCoverage - tradeable history after warmup")
    print(coverage.text_block(cov, runner.COINS, IVS))

    print("\nGeometry - 1R is the NARROWEST range of the last 7 bars, so it is smaller"
          " than a typical candle by construction.")
    print(f"{'coin':<9} {'1H 1R as % of price':>21} {'NR7 bars, 1H':>14} {'1D 1R as %':>12}")
    for symbol in runner.COINS:
        print(f"{symbol:<9} {risk_pct(symbol, '1H'):>19.3f}% "
              f"{nr7_pct(symbol, '1H'):>13.1f}% {risk_pct(symbol, '1D'):>11.3f}%")
    print(f"Round-trip taker fee is {2 * runner.TAKER_FEE_RATE * 100:.3f}% of price, "
          f"against a median 1R of {r1_pct:.3f}%.")

    # --- sensitivities ----------------------------------------------------------
    print("\nSensitivities on the headline timeframe only")
    sens: dict = {}
    for tag, kw in [
        ("N = 7 (traded)", {}),
        ("N = 4 (NR4, separately published)", {"lookback": 4}),
        ("N = 10", {"lookback": 10}),
        ("trigger offset = 0.1% of the bar's range", {"offset_mult": 0.001}),
        ("orders rest 2 bars", {"rest_bars": 2}),
        ("orders rest 3 bars", {"rest_bars": 3}),
    ]:
        sres = runner.run(make_spec(**kw), intervals=[HEADLINE_TF])
        sens[tag] = sres["pooled"]
        for label in ["native", "forced-1:3"]:
            m = sres["pooled"][(HEADLINE_TF, label)]
            v, _ = verdict(m, label)
            print(f"  {tag:<44} {label:<11} n={m['trades']:>5} "
                  f"R={m['r_sum_post_fee']:>7.1f} sh={m['sharpe_post_fee']:>6.2f} {v}")

    if write:
        write_logs(res, summary, sens, ctx, cov, r1_pct)
        print("\nBoth logs updated: strategy_log.csv and strategy_log.md")
    else:
        print("\nDry run - nothing written. Add --log to append to both logs.")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _csv_rows(summary: dict) -> None:
    for interval in IVS:
        s = summary[interval]
        for label, vkey in [("native", "verdict_native"), ("forced-1:3", "verdict_forced")]:
            logbook.log_row(
                strategy=NAME,
                coins=COINS_STR,
                timeframes=interval,
                exit_type=label,
                m=s[label],
                exit_death_flag=s["exit_death"],
                verdict=s[vkey],
            )


def _g(x, nd: int = 2) -> str:
    return "n/a" if x is None or x != x else f"{x:.{nd}f}"


def _md_table(summary: dict) -> str:
    head = ("| Timeframe | Exit | Trades | Win% | RR | R (pre-fee) | R (post-fee) "
            "| R/trade | Sharpe | Max DD % | Max DD (R) | R-recovery | Fee cost/trade | Verdict |")
    rows = [head, "|" + "---|" * 14]
    for interval in IVS:
        s = summary[interval]
        for label, vkey in [("native", "verdict_native"), ("forced-1:3", "verdict_forced")]:
            m = s[label]
            rows.append(
                f"| {interval} | {label} | {m['trades']} | {_g(m['win_rate'] * 100, 1)} "
                f"| {_g(m['rr_achieved'])} | {_g(m['r_sum_pre_fee'], 1)} "
                f"| {_g(m['r_sum_post_fee'], 1)} | {_g(m['expectancy_post_fee_r'], 3)} "
                f"| {_g(m['sharpe_post_fee'])} | {_g(m['max_drawdown_pct'], 1)} "
                f"| {_g(m['max_drawdown_r'], 1)} | {_g(m['r_recovery'])} "
                f"| {_g(m['avg_fee_cost_r'], 3)}R | **{s[vkey]}** |"
            )
    return "\n".join(rows)


def _md_fills(res: dict) -> str:
    rows = ["| Timeframe | Exit | Sessions with orders placed | Traded | Neither side reached "
            "| Both sides in one bar (skipped) | Blocked by an open trade |",
            "|" + "---|" * 7]
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            f = fills(res, interval, label)
            rows.append(
                f"| {interval} | {label} | {f['sessions_armed']} | {f['traded']} "
                f"| {f['no_touch']} | {f['ambiguous']} | {f['blocked']} |"
            )
    return "\n".join(rows)


def _md_legs(res: dict) -> str:
    rows = ["| Timeframe | Exit | Long trades | Long R | Long win% | Short trades "
            "| Short R | Short win% |", "|" + "---|" * 8]
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            g = leg_split(res["trades"][(interval, label)])
            rows.append(
                f"| {interval} | {label} | {g['long']['trades']} "
                f"| {g['long']['r_post_fee']:+.1f} | {_g(g['long']['win_rate'] * 100, 1)} "
                f"| {g['short']['trades']} | {g['short']['r_post_fee']:+.1f} "
                f"| {_g(g['short']['win_rate'] * 100, 1)} |"
            )
    return "\n".join(rows)


def _md_geom(r1_pct: float) -> str:
    rows = ["| Coin | 1R as % of price (1H) | NR7 bars as % of all bars (1H) "
            "| 1R as % of price (1D) |", "|" + "---|" * 4]
    for symbol in runner.COINS:
        rows.append(
            f"| {symbol} | {risk_pct(symbol, '1H'):.3f}% | {nr7_pct(symbol, '1H'):.1f}% "
            f"| {risk_pct(symbol, '1D'):.3f}% |"
        )
    rows.append(f"| Round-trip taker fee | {2 * runner.TAKER_FEE_RATE * 100:.3f}% of price "
                f"| | |")
    return "\n".join(rows)


def _md_sens(sens: dict) -> str:
    rows = [f"| Variant ({HEADLINE_TF}) | Exit | Trades | Win% | RR | R (post-fee) "
            "| R/trade | Sharpe | Fee cost/trade | Verdict |", "|" + "---|" * 10]
    for tag, pooled in sens.items():
        for label in ["native", "forced-1:3"]:
            m = pooled[(HEADLINE_TF, label)]
            v, _ = verdict(m, label)
            rows.append(
                f"| {tag} | {label} | {m['trades']} | {_g(m['win_rate'] * 100, 1)} "
                f"| {_g(m['rr_achieved'])} | {_g(m['r_sum_post_fee'], 1)} "
                f"| {_g(m['expectancy_post_fee_r'], 3)} | {_g(m['sharpe_post_fee'])} "
                f"| {_g(m['avg_fee_cost_r'], 3)}R | {v} |"
            )
    return "\n".join(rows)


def write_logs(res: dict, summary: dict, sens: dict, ctx: dict, cov: dict,
               r1_pct: float) -> None:
    """Append the CSV rows and the full markdown section for this strategy."""
    _csv_rows(summary)

    keeps = [i for i in IVS if summary[i]["exit_death"]]
    hn = summary[HEADLINE_TF]["native"]
    hf = summary[HEADLINE_TF]["forced-1:3"]
    fee_pct = 2 * runner.TAKER_FEE_RATE * 100
    t_gross = ctx[HEADLINE_TF]["sig_native"]["t_gross"]
    t_net = ctx[HEADLINE_TF]["sig_native"]["t_net"]
    t_gross_all = " / ".join(
        f"{i} {ctx[i]['sig_native']['t_gross']:+.2f}" for i in IVS
    )
    t_net_all = " / ".join(
        f"{i} {ctx[i]['sig_native']['t_net']:+.2f}" for i in IVS
    )

    parts: list[str] = []
    parts.append(f"""## Strategy #9 - Bulkowski's Narrow Range 7 (NR7)

### Source, and the rule exactly as written

Thomas Bulkowski, "NR7", *thepatternsite.com* (Encyclopedia of Chart Patterns). The setup and the
crypto-specific entry are short enough to quote in full:

* Setup: *"The most recent bar must have a smaller high-low price range than the prior six bars
  (seven bars, total)."* The range is **high - low**. He is explicit that it is not true range.
* Breakout: *"A breakout occurs when price closes above the top or below the bottom of the NR7."*
* Entry, for the cryptocurrency test: *"I placed a buy stop a penny above the top of the NR7 and a
  stop loss order a penny below the bottom of the pattern."*
* Exit, the measure rule: *"Measure the height of pattern and add it to the highest price in the
  pattern to get an upward target or subtract it from the lowest low in the pattern to get a
  downward price target."*

This is the next strategy in the lineage started by #4: Crabel names the "narrow range day" as the
conditioning framework for his opening-range breakout and defers its measurement to paywalled
chapters. Bulkowski's NR7 is the standard, fully-published form of that same idea, so it is what
gets tested here instead of a guess at what Crabel left out.

**The rule as tested:** bar D's high-low range is the smallest of the last seven. Before bar D+1
opens, a buy stop sits at bar D's high and a sell stop at bar D's low; whichever fires first is the
trade, and the other end of the pattern is the stop. The exit is the measure rule - the pattern's
own height projected from the entry - which is exactly 1R, making the native exit a symmetric 1:1.

### What is a PLACEHOLDER, never a guess at the source's intent

* **"A penny" above and below the trigger.** Meaningless on a six-figure bitcoin. The traded config
  puts the trigger exactly on bar D's high and low; the offset is run as a sensitivity at 0.1% of
  the bar's range rather than assumed. This is the only free parameter the rule contains.
* **How long unfilled orders rest.** The source says when the breakout is *recognised*, not when
  unexecuted orders are cancelled. The literal reading of *"price closes above the top"* is the
  following bar, so `REST_BARS = 1` is the headline and 2 / 3 bars are sensitivities.
* **N = 7**, because the source is "NR7". NR4 is a separately published pattern and is run as a
  sensitivity, not folded into the headline.

### What this test could NOT reproduce, and what that means

* **The venue and the asset class.** Bulkowski's own result is on 38 cryptocurrencies, but his
  stop-loss and measure-rule percentages come from an equities career. The structural difference
  matters more here than for any other strategy in this project, for the reason in the geometry
  section below.
* **A stop order that is actually resting.** Bybit charges taker fees on both legs of a stop order
  in this test. A maker rebate on the entry leg is the cheapest realistic change, and it is
  reported in the fee section rather than assumed away.
* **The trend conditioning of the source's own result.** He reports the win rate separately in
  uptrends and downtrends; the regime table below is the closest this project has, and it is
  labelled post-fee where his is not.""")

    parts.append(f"""### Lookahead bias: what was checked, freshly, for this strategy

The runner audits every coin/timeframe input before simulation by rebuilding indicators on truncated
history and comparing with the full-data values; this report also prints a separate BTCUSDT 1H audit.
The displayed audit checked 10 computed columns and passed. Four places needed real care:

* **IS_NR7** compares bar D against the six bars before it and is written ON bar D, so it is a
  closed-bar fact by construction.
* **The triggers and the risk unit** are the most recent narrow bar's own high, low and range,
  carried forward with `where(is_nr7).ffill().shift(1)` - bar *i* reads only bars at or before *i-1*.
* **The "session" is the armed window, not the clock.** NR7's orders rest for bars after a narrow
  bar, which can begin at any hour. The window is therefore derived from IS_NR7 alone, which is closed-
  bar data; it is not aligned to a UTC day.
* **The current bar's high and low** are used by the engine to FILL an order that was already
  sitting there at a pre-bar price, and are never used by the strategy to DECIDE anything. Six
  hand-built-candle tests in the shared resting-order test suite pin that behaviour down, including
  filling at the trigger, filling worse when a bar gaps through it, and refusing to guess when one
  bar covers both sides.""")


    parts.append(f"""### Results - three coins pooled per timeframe, every number post-fee

The four timeframes are one test at four bar sizes. The rule never changes: seven bars, smallest
range wins, trade the next bar's breakout. Only the bar that carries the definition changes.

{_md_table(summary)}

**Verdicts, per exit variant, never collapsed:**

* **Native (the source's own measure rule):** {' · '.join(f"{i} {summary[i]['verdict_native']} - {summary[i]['reason_native']}" for i in IVS)}
* **Forced 1:3:** {' · '.join(f"{i} {summary[i]['verdict_forced']} - {summary[i]['reason_forced']}" for i in IVS)}

Exit-death check (does the source's own exit beat a forced 1:3 on the same entries):
{' · '.join(f"{i}: {summary[i]['exit_death']} ({summary[i]['exit_death_diag']})" for i in IVS)}.
Rows that read yes: {', '.join(keeps) if keeps else 'none'}.

The two variants share {', '.join(f"{i} {ctx[i]['overlap']:.1%}" for i in IVS)} of their entries,
against the {context_checks.MIN_OVERLAP:.0%} minimum for "same entries, only the exit differs" to be
a fair claim. The overlap is short on the fine bars because the two exits hold for different lengths
(a 1:1 measure exit versus a 30-bar triple barrier), so while holding one blocks different armed
sessions for each. The disagreement is in the SIGN of the edge and is far larger than the overlap gap
can account for, which is the comparison the exit-death check exists to make.""")

    parts.append(f"""### Why the result is what it is: the pattern's own geometry

NR7 is the first strategy in this project whose risk unit is defined as the SMALLEST thing in the
window. Every other strategy measures 1R from a typical or an extreme candle - an ATR, a channel, a
day's range - so 1R is at least as big as a normal bar. Here 1R is required to be *narrower than six
of the last seven bars*. That is not a side effect of the construction; it is the construction.

{_md_geom(r1_pct)}

The round-trip taker fee is {fee_pct:.3f}% of price and the median risk unit is {r1_pct:.3f}% of
price, so fees cost roughly **{_g(hn['avg_fee_cost_r'], 2)}R per trade** at {HEADLINE_TF}. In this
 pooled sample the native 1H expectancy moves from {_g(ctx[HEADLINE_TF]['sig_native']['gross_mean'], 3)}R gross to
 {_g(ctx[HEADLINE_TF]['sig_native']['net_mean'], 3)}R post-fee. Fees materially reduce the edge, but do not erase it
in the pooled 1H mean; the negative BTC row and the weak aggregate Sharpe explain why the quality
verdict can still be DISCARD.

The same fee-to-risk mechanism documented in `discard_bar.py` applies: as 1R gets smaller relative to
the fixed percentage fee, fees consume more R per trade. This is an explanation for the timeframe
pattern, not by itself a complete causal account of the observed coin- and timeframe-level results.""")


    lg = leg_split(res["trades"][(HEADLINE_TF, "native")])
    parts.append(f"""### Concentration - is the edge in one leg or one coin?

NR7 is symmetric by construction: a buy stop above and a sell stop below the same bar. If the market
is genuinely choosing a direction out of consolidation, both legs should carry it.

{_md_legs(res)}

At {HEADLINE_TF}, {lg['long']['trades']} long and {lg['short']['trades']} short entries split roughly
evenly. The pooled result is not representative of every coin: the per-coin table above shows BTC's
native 1H row is negative while SOL and XRP are positive. Both legs and all coins therefore need to be
read separately; a pooled edge is not evidence of a uniform signal.

### Regime - does it work anywhere?

{chr(10).join(f"* **{k}:** {v['trades']} trades, {v['r_sum_post_fee']:+.1f}R post-fee" for k, v in hn['regime_r'].items()) if hn['regime_r'] else 'No regime labels populated.'}

Best regime: {hn['best_regime']}. Worst: {hn['worst_regime']}. The source's own result is conditioned
on trend direction ({PAPER_WIN_UPTREND}% win in an uptrend, {PAPER_WIN_DOWNTREND}% in a downtrend) and
is stated gross; these rows are post-fee, so they are not comparable column for column.

### Fees and funding: the binding constraint

Fee cost per trade is **{_g(hn['avg_fee_cost_r'], 3)}R** native and {_g(hf['avg_fee_cost_r'], 3)}R
forced at {HEADLINE_TF}, against a median 1R of {r1_pct:.3f}% of price. The breakeven win rate for the
forced 1:3 at that fee level is **{breakeven_win_rate(hf['avg_fee_cost_r']):.1%}**, and the measured
win rate is **{hf['win_rate']:.1%}** - the forced variant lands essentially on its own fee-breakeven
line, so judge the actual post-fee expectancy and verdict rather than inferring that costs consume
the whole signal. Forced 1:3 verdicts by timeframe: {'; '.join(f"{i} {summary[i]['verdict_forced']}" for i in IVS)}.

Pre-fee, the entry is doing something: the gross t-statistic is {t_gross:+.2f} at {HEADLINE_TF}
({t_gross_all} across timeframes). Post-fee it is {t_net:+.2f} ({t_net_all}). The 1H t-statistic
falls sharply after fees; on coarser bars the measured edge remains positive. Statistical evidence is
not by itself proof of a robust or transferable strategy.""")

    d_nat = summary[IVS[-1]]["native"]
    parts.append(f"""### Coverage, and the sensitivities

{coverage.md_table(cov, runner.COINS, IVS)} (warmup: {make_spec().warmup_for(HEADLINE_TF)} {HEADLINE_TF} bars, so
the 100-bar regime average is populated before any trade.)

Sensitivities, headline timeframe, both exits:

{_md_sens(sens)}

The table is the evidence for the sensitivities; each row uses its own warmup. NR4 and N=10 change
both the frequency and geometry of setups, and the offset changes which breakouts fill. These are
different rules, not independent confirmation of the N=7 headline. The rest-window variants are also
reported as-run. Resting orders for two or three bars produced the same aggregate metrics as one bar
in this run. The execution model tracks one active session state, so the unchanged results should not
be interpreted as evidence that order expiry never matters; the longer-rest variants are not
independent confirmation of the headline result.

### Bottom line

Measured native verdicts by timeframe: {'; '.join(f"{i} {summary[i]['verdict_native']}" for i in IVS)}.
Forced 1:3 verdicts: {'; '.join(f"{i} {summary[i]['verdict_forced']}" for i in IVS)}. At {HEADLINE_TF},
the native strategy records {_g(hn['r_sum_post_fee'], 1)}R post-fee over {hn['trades']} pooled trades
({hn['win_rate']:.1%} wins), while forced 1:3 records {_g(hf['r_sum_post_fee'], 1)}R over
{hf['trades']} trades ({hf['win_rate']:.1%} wins). The measured headline native expectancy is
{_g(hn['expectancy_post_fee_r'], 3)}R/trade; the verdict is based on the shared discard criteria,
not a blanket claim that all fees erase all edge.

### Interpretation and limits

Bulkowski reports underperformance against buy-and-hold in his own sample. This backtest does not
calculate a buy-and-hold comparison, so it cannot independently confirm that benchmark claim. Results
vary substantially by timeframe and coin: pooled native verdicts are
{' ; '.join(f"{i} {summary[i]['verdict_native']}" for i in IVS)}, and forced 1:3 verdicts are
{' ; '.join(f"{i} {summary[i]['verdict_forced']}" for i in IVS)} under this project's thresholds.
These labels are screening criteria, not proof of future profitability.

The narrow pattern range makes the fee-to-risk ratio relevant, but does not alone explain the
timeframe/coin differences. A maker-fee scenario or wider stop would be a different execution/risk
model and should be tested explicitly rather than assumed. Coarser bars have positive pooled results
in this sample, but need out-of-sample and execution-resolution checks before being treated as
evidence of a durable effect.""")

    logbook.log_md("\n\n".join(parts))


if __name__ == "__main__":
    main(write="--log" in sys.argv)
