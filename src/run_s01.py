"""Run Strategy #1 - Bollinger Band Reversion (short only), and log it.

Usage:  .venv\\Scripts\\python.exe src\\run_s01.py
"""

from __future__ import annotations

import sys

import bybit_data as bd
import context_checks
import lookahead_check
import logbook
import runner
import s01_bb_reversion as s01
from discard_bar import verdict

NAME = "BB Reversion (short-only)"
COINS_STR = "BTCUSDT+SOLUSDT+XRPUSDT"


def make_spec(stop_frac: float) -> runner.StrategySpec:
    return runner.StrategySpec(
        name=f"{NAME} stop={stop_frac:.1%}",
        add_indicators=s01.add_indicators,
        entry=lambda df: s01.entry(df, stop_frac),
        native_exit=s01.native_exit,
        warmup=s01.WARMUP,
        native_time_limit=None,          # the source describes no time barrier
    )


def show_audit(symbol: str = "BTCUSDT", interval: str = "4H") -> bool:
    """Print the lookahead proof on one dataset so it is visible, not just asserted."""
    df = bd.drop_forming_bar(bd.load(symbol, interval), interval)
    raw = df[[c for c in df.columns if c in lookahead_check.RAW]].copy()
    return lookahead_check.report(f"{NAME} on {symbol} {interval}", raw, s01.add_indicators)


def detail(res: dict, interval: str) -> str:
    lines = []
    for label in ["native", "forced-1:3"]:
        m = res["pooled"][(interval, label)]
        mix = ", ".join(f"{k} {v}" for k, v in sorted(m["exit_reason_mix"].items())) or "none"
        lines.append(
            f"  {interval} {label:<11} exits: {mix} | avg hold {m['avg_bars_held']:.1f} bars "
            f"| fees {m['avg_fee_cost_r']:.3f}R/trade | best {m['best_regime']} "
            f"| worst {m['worst_regime']}"
        )
    return "\n".join(lines)


def main(write: bool) -> None:
    print("=" * 78)
    print(f"STRATEGY #1 - {NAME}")
    print("=" * 78)

    if not show_audit():
        raise SystemExit("Lookahead audit failed - no results will be produced.")

    spec = make_spec(s01.STOP_FRAC)
    res = runner.run(spec)
    n_pass = sum(1 for ok, _, _ in res["audit"].values() if ok)
    print(f"\nLookahead audit re-run on all 9 datasets: {n_pass}/9 PASS")

    summary = runner.summarise(spec, res)

    ctx = context_checks.summarise(res, runner.COINS, runner.INTERVALS,
                                   stop_pct=s01.STOP_FRAC * 100)
    print("\nWas this a fair test? (noise level, intrabar ambiguity, entry overlap)")
    print(context_checks.text_block(ctx, runner.INTERVALS, stop_pct=s01.STOP_FRAC * 100))

    print("\nExit composition and market conditions")
    for interval in runner.INTERVALS:
        print(detail(res, interval))

    print("\nExit-death check (same entries, same 1R, only the exit differs)")
    for interval in runner.INTERVALS:
        s = summary[interval]
        print(f"  {interval}: exit-death = {s['exit_death'].upper()}")
        print(f"      {s['exit_death_diag']}")

    print("\nVerdicts, applied to each exit variant separately")
    for interval in runner.INTERVALS:
        s = summary[interval]
        print(f"  {interval} native      {s['verdict_native']}: {s['reason_native']}")
        print(f"  {interval} forced-1:3  {s['verdict_forced']}: {s['reason_forced']}"
              f"  [own fee breakeven {s['breakeven_wr_forced']:.1%}]")

    print("\nPer-coin breakdown (not pooled)")
    print(runner.per_coin_table(res))

    # --- stop-size sensitivity ---------------------------------------------
    print("\nStop-size sensitivity - the source withheld its stop %, and the stop")
    print("IS 1R, so it scales every number reported above.")
    print(f"{'stop%':>6} {'tf':>4} {'exit':<11} {'trades':>7} {'win%':>6} "
          f"{'R post':>8} {'R/trade':>8} {'Sharpe':>7}  verdict")
    sens: dict = {}
    for sf in [0.01, 0.02, 0.03]:
        sres = res if sf == s01.STOP_FRAC else runner.run(make_spec(sf), audit=False)
        sens[sf] = sres
        for interval in runner.INTERVALS:
            for label in ["native", "forced-1:3"]:
                m = sres["pooled"][(interval, label)]
                v, _ = verdict(m, label)

                def g(x, nd=2):
                    return "n/a" if x != x else f"{x:.{nd}f}"
                print(f"{sf:>6.1%} {interval:>4} {label:<11} {m['trades']:>7} "
                      f"{g(m['win_rate'] * 100, 1):>6} {g(m['r_sum_post_fee'], 1):>8} "
                      f"{g(m['expectancy_post_fee_r'], 3):>8} "
                      f"{g(m['sharpe_post_fee']):>7}  {v}")

    if write:
        write_logs(res, summary, sens, ctx)
        print("\nBoth logs updated: strategy_log.csv and strategy_log.md")
    else:
        print("\n(dry run - nothing written to the logs; pass --log to record it)")


def _csv_rows(summary: dict) -> None:
    for interval in runner.INTERVALS:
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


def _md_table(summary: dict) -> str:
    head = ("| Timeframe | Exit | Trades | Win% | RR | R (pre-fee) | R (post-fee) "
            "| R/trade | Sharpe | Max DD % | Max DD (R) | R-recovery | Verdict |")
    sep = "|" + "---|" * 13
    rows = [head, sep]
    for interval in runner.INTERVALS:
        s = summary[interval]
        for label, vkey in [("native", "verdict_native"), ("forced-1:3", "verdict_forced")]:
            m = s[label]

            def g(x, nd=2):
                return "n/a" if x is None or x != x else f"{x:.{nd}f}"
            rows.append(
                f"| {interval} | {label} | {m['trades']} | {g(m['win_rate'] * 100, 1)} "
                f"| {g(m['rr_achieved'])} | {g(m['r_sum_pre_fee'], 1)} "
                f"| {g(m['r_sum_post_fee'], 1)} | {g(m['expectancy_post_fee_r'], 3)} "
                f"| {g(m['sharpe_post_fee'])} | {g(m['max_drawdown_pct'], 1)} "
                f"| {g(m['max_drawdown_r'], 1)} | {g(m['r_recovery'])} | **{s[vkey]}** |"
            )
    return "\n".join(rows)


def _md_sens(sens: dict) -> str:
    rows = ["| Stop % | Timeframe | Exit | Trades | Win% | R (post-fee) | R/trade | Sharpe |",
            "|" + "---|" * 8]
    for sf, sres in sens.items():
        for interval in runner.INTERVALS:
            for label in ["native", "forced-1:3"]:
                m = sres["pooled"][(interval, label)]

                def g(x, nd=2):
                    return "n/a" if x != x else f"{x:.{nd}f}"
                rows.append(
                    f"| {sf:.0%} | {interval} | {label} | {m['trades']} "
                    f"| {g(m['win_rate'] * 100, 1)} | {g(m['r_sum_post_fee'], 1)} "
                    f"| {g(m['expectancy_post_fee_r'], 3)} | {g(m['sharpe_post_fee'])} |"
                )
    return "\n".join(rows)


def write_logs(res: dict, summary: dict, sens: dict, ctx: dict) -> None:
    n_pass = sum(1 for ok, _, _ in res["audit"].values() if ok)
    cols = sorted({c for _, cl, _ in res["audit"].values() for c in cl})

    death = "\n".join(
        f"- **{i}: exit-death = {summary[i]['exit_death'].upper()}.** "
        f"{summary[i]['exit_death_diag']}"
        for i in runner.INTERVALS
    )
    verdicts = "\n".join(
        f"- **{i} / native exit — {summary[i]['verdict_native']}.** {summary[i]['reason_native']}\n"
        f"- **{i} / forced 1:3 — {summary[i]['verdict_forced']}.** {summary[i]['reason_forced']} "
        f"(its own fee-derived breakeven win rate is {summary[i]['breakeven_wr_forced']:.1%})"
        for i in runner.INTERVALS
    )
    mixes = "\n".join(
        f"- {i} {lab}: " + (", ".join(
            f"{k} {v}" for k, v in sorted(summary[i][lab]["exit_reason_mix"].items())) or "no trades")
        + (f" — average hold {summary[i][lab]['avg_bars_held']:.1f} bars, fees cost "
           f"{summary[i][lab]['avg_fee_cost_r']:.3f}R per trade, best conditions "
           f"{summary[i][lab]['best_regime']}, worst {summary[i][lab]['worst_regime']}"
           if summary[i][lab]["trades"] else "")
        for i in runner.INTERVALS for lab in ["native", "forced-1:3"]
    )

    fair = context_checks.text_block(ctx, runner.INTERVALS, stop_pct=s01.STOP_FRAC * 100)

    hours = {"1H": 1, "4H": 4, "1D": 24}
    funding = "; ".join(
        f"{i} holds {summary[i]['native']['avg_bars_held']:.1f} bars "
        f"= {summary[i]['native']['avg_bars_held'] * hours[i]:.0f} hours "
        f"= about {summary[i]['native']['avg_bars_held'] * hours[i] / 8:.0f} funding windows"
        for i in runner.INTERVALS
    )

    fee_rows = "\n".join(
        ["| Timeframe | Exit | Trades | Before fees | Fee bill | After fees |",
         "|---|---|---|---|---|---|"]
        + [f"| {i} | {lab} | {summary[i][lab]['trades']} "
           f"| {summary[i][lab]['r_sum_pre_fee']:+.1f}R "
           f"| {summary[i][lab]['avg_fee_cost_r'] * summary[i][lab]['trades']:.1f}R "
           f"| {summary[i][lab]['r_sum_post_fee']:+.1f}R |"
           for i in runner.INTERVALS for lab in ["native", "forced-1:3"]]
    )
    best = summary["1H"]["forced-1:3"]
    overlap_lo = min(ctx[i]["overlap"] for i in runner.INTERVALS)
    tmax = max(ctx[i][k]["t_gross"] for i in runner.INTERVALS
               for k in ["sig_native", "sig_forced"])

    text = f"""---

## Strategy #1 — Bollinger Band Reversion (short only)

**Tested:** {logbook.date.today().isoformat()} · **Coins:** BTCUSDT, SOLUSDT, XRPUSDT
(Bybit USDT perpetuals) · **Timeframes:** 1H, 4H, 1D · **Direction:** short only ·
**Source's own timeframe:** 4H

### The rules, in plain English

Only ever sell short, and only when the market is already falling. Three things
must line up on a candle that has finished forming:

1. the faster moving average sits below the slower one, so the trend is down;
2. that candle is the **first** one to close above the upper Bollinger band — a
   stretched bounce inside a downtrend, not the tenth candle of a rally. The
   source stresses this: without the "first" condition a strong rally fires entry
   after entry and every one of them stops out;
3. volume on that candle is above its own recent average, so the push is real
   rather than a thin wick.

The trade is then sold short at the **next** candle's open.

Getting out, the source's way: take profit when a candle closes at or below the
**lower** Bollinger band — the full swing from one edge of the range to the other.
Stop loss is a fixed percentage above the entry price. There is no time limit.

Getting out, the forced way (this project's standard comparison): stop at 1R,
target at 3R, and a 30-bar time limit. Identical entries, identical 1R.

### Parameters — every one is a placeholder

The source describes the logic in public but keeps the numbers behind a paywall.
Nothing below was taken from the source; all of it is a stated assumption.

| Parameter | Value used | Where it came from |
|---|---|---|
| Bollinger period | {s01.BB_PERIOD} | Bollinger's own canonical default |
| Bollinger std-dev multiplier | {s01.BB_STD} | Bollinger's own canonical default |
| Fast EMA | {s01.EMA_SHORT} | **Placeholder** — source undisclosed |
| Slow EMA | {s01.EMA_MEDIUM} | **Placeholder** — source undisclosed |
| Volume SMA length | {s01.VOL_SMA} | **Placeholder** — source undisclosed |
| Stop loss | {s01.STOP_FRAC:.0%} from the fill price | **Placeholder** — source undisclosed |
| Warm-up bars skipped | {s01.WARMUP} | enough for the slowest indicator to settle |
| Forced-1:3 time limit | 30 bars | project-wide **unvalidated placeholder** |

The stop percentage is the dangerous one. The stop **is** 1R, and 1R is the
denominator of every number in this report, so guessing it wrong rescales
everything. A sensitivity table is included below for that reason.

### How this test differs from the source

| | Source | This test |
|---|---|---|
| Universe | top 30 by market cap, rebuilt monthly (72 pairs appear) | 3 fixed coins |
| Timeframe | 4H only | 1H, 4H, 1D |
| Leverage | 1.5x fixed | irrelevant — R-multiples are scale-invariant |
| Costs | not stated | Bybit taker {0.00055:.5f} both legs, always applied |

The universe gap is the big one. A rule that fires rarely per coin becomes a
usable system across 72 coins and a starved one across 3. Fewer trades also means
less diversification, so the pooled equity curve here is bumpier than the
source's by construction. The source's reported ~25% win rate and ~3.5:1 payoff
come from that wide universe and cannot be expected to reproduce on three coins.

### Lookahead check — run fresh on this strategy

Method: recompute every indicator on history that has been cut off at a given
bar, then compare the value at the cut against the value the same indicator shows
when the whole history is present. If future candles were leaking into a past
decision, the two numbers would differ.

Columns checked: {', '.join(cols)}.
Result: **{n_pass}/9 datasets PASS** at 25 cut points each, to a tolerance of
1e-12. Every indicator value at the cut was identical with and without the future
bars present.

Two structural protections back that up: a signal read from a finished candle is
filled at the **next** candle's open, never at the closing price it was measured
on; and the percentage stop is measured from the actual fill price, not from the
signal candle's close (self-test #9 proves this on hand-built candles).

### Results — three coins pooled per timeframe, after fees

{_md_table(summary)}

Pre-fee is shown only so the size of the fee bill is visible. Every verdict is
made on the post-fee column.

### How the trades ended

{mixes}

### Exit-death check

Same entry rule, same 1R distance, only the exit rules differ — so a gap between
the two rows of a timeframe is caused by the exit alone. Entry overlap between the
two variants is {overlap_lo:.0%} at worst (an open position blocks the next signal,
so the realised sets are not quite identical), which is high enough for the
comparison to be fair.

{death}

**The answer here is no, on all three timeframes — and that is worth stating
plainly, because it is the opposite of what this project usually finds.** A
previous postmortem on seven consecutive failed systems found the exit to be the
culprit seven times out of seven: indicator-reversal exits produced **zero**
winners in that set, while a fixed take-profit on the identical entries produced
**zero** losers. That is why every strategy here is run twice and the two verdicts
are never collapsed into one.

This strategy does not fit that pattern. Forcing a clean 1:3 onto these entries
does help — it lifts 1H from {summary['1H']['native']['expectancy_post_fee_r']:+.3f}R
to {best['expectancy_post_fee_r']:+.3f}R per trade and 4H from
{summary['4H']['native']['expectancy_post_fee_r']:+.3f}R to
{summary['4H']['forced-1:3']['expectancy_post_fee_r']:+.3f}R — but it never gets
the sign to flip, and on 1D it makes things worse. When neither exit can rescue a
set of entries, the entries are what is wrong. There is nothing here for a better
exit to save.

### Where the money actually went

{fee_rows}

The single most important line in this whole report is 1H forced-1:3: it earns
**{best['r_sum_pre_fee']:+.1f}R before costs and {best['r_sum_post_fee']:+.1f}R
after them.** The commission bill on {best['trades']} trades is
{best['avg_fee_cost_r'] * best['trades']:.0f}R, and that is the entire difference
between a flat line and a losing one. A 2% stop on an hourly chart makes 1R small,
so a fixed percentage fee eats {best['avg_fee_cost_r']:.1%} of a risk unit every
round trip. This is exactly why the project rule is that post-fee is the only
number that counts.

### Was this a fair test?

```
{fair}
```

Three things to read out of that block:

- **Nothing here is distinguishable from luck, even before costs.** The largest
  t-statistic across all six runs is {tmax:+.2f}; roughly 2 is the bare minimum
  before an average is worth taking seriously. So this is not "a small edge
  destroyed by fees" — the pre-fee edge cannot be shown to exist either.
- **The 1D test is not really a test of the strategy.** A typical daily candle
  moves {ctx['1D']['stop_vs_candle']['BTCUSDT'][0]:.1f}% on BTC,
  {ctx['1D']['stop_vs_candle']['SOLUSDT'][0]:.1f}% on SOL and
  {ctx['1D']['stop_vs_candle']['XRPUSDT'][0]:.1f}% on XRP, while the stop is only
  2% away and the 3R target only 6% away. Both barriers sit inside one candle, so
  {ctx['1D']['first_bar_forced']:.0%} of forced-1:3 trades resolved on their first
  bar, where plain candle data cannot say which barrier was touched first. The
  engine always resolves that against us. The 1D verdict below is what the fixed
  bar returns, but it is measuring the tie-break rule as much as the strategy.
- **4H is borderline for the same reason** on SOL, whose typical 4H candle is
  {ctx['4H']['stop_vs_candle']['SOLUSDT'][0]:.2f}% against a 2% stop. 1H is the
  only timeframe where 1R is comfortably wider than a single candle, and 1H is
  therefore the cleanest of the three results.

### Verdicts — each exit variant scored separately

{verdicts}

### Stop-size sensitivity (secondary evidence, not the headline)

The source withheld its stop percentage. This shows what happens at 1%, 2% and
3%. Read it as a check on whether the verdict above is an artefact of a guessed
number, not as an optimisation — nothing here is tuned or selected.

{_md_sens(sens)}

Every one of the 18 cells above is a DISCARD. Widening the stop to 3% raises the
win rate (1H forced-1:3 goes from {sens[0.02]['pooled'][('1H', 'forced-1:3')]['win_rate']:.1%}
to {sens[0.03]['pooled'][('1H', 'forced-1:3')]['win_rate']:.1%}) because a wider stop
is harder to hit, and it does turn 1H forced-1:3 barely positive at
{sens[0.03]['pooled'][('1H', 'forced-1:3')]['r_sum_post_fee']:+.1f}R total — still a
DISCARD on Sharpe and on drawdown recovery. Tightening it to 1% makes everything
worse. The verdict is not an artefact of the guessed stop size.

### Bottom line

The strategy is a **DISCARD on all three timeframes and on both exit variants**,
and the reason is the entry, not the exit. Both exits were tried, neither works,
and the pre-fee edge cannot be distinguished from chance in the first place.

Two honest caveats attached to that:

1. The parameters are guesses. The source's real EMA lengths, volume period,
   Bollinger settings and stop percentage are paywalled. The stop was probed at
   three values and the answer did not change, but the other four were not.
2. The universe is wrong. The source trades 30 coins rebuilt monthly; this is
   three coins. That is the difference between a rule that fires often enough to
   diversify and one that does not.

**What would change this verdict:** running the same rules across a 30-coin
universe rebuilt monthly, which is the one difference from the source that is both
large and testable. That is a build, not a tweak — it needs cross-sectional data
handling the current runner does not have. Flagged as a possible revisit, not
scheduled.

### Funding cost — flagged, and it does apply here

Bybit charges or pays funding on a perpetual every 8 hours. Measured average holds
on this strategy: {funding}. Every timeframe here is therefore a multi-window hold
and the standing funding flag applies to all three, not just the slow ones.

One nuance specific to this strategy: it is **short only**, and a short position
*receives* funding when the rate is positive and pays it when negative. Funding is
therefore not automatically a hidden cost here — it could be a hidden credit. This
project has not measured historical funding rates, so the direction is unknown and
**this omission cannot be claimed to be conservative.**

It does not change anything today: every cell on every timeframe is a DISCARD by a
wide margin, and no KEEP is being claimed. But per the standing rule, if a
short-only or multi-day strategy later comes close to a KEEP, funding must be
resolved before that KEEP is treated as real.

### Also not modelled

Slippage, order-book depth, and whether the 3R target or the lower-band exit was
genuinely fillable at the printed price. Those would all make the numbers worse.
Funding, as above, could go either way.
"""
    # The whole write-up is built before anything is written, so a formatting
    # mistake cannot leave half a record in an append-only log.
    _csv_rows(summary)
    logbook.log_md(text)


if __name__ == "__main__":
    main("--log" in sys.argv)
