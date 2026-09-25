"""Run Strategy #2 - Dual Momentum (Bybit perps), and log it.

Usage:  .venv\\Scripts\\python.exe src\\run_s02.py [--log]
"""

from __future__ import annotations

import sys

import numpy as np

import bybit_data as bd
import context_checks
import lookahead_check
import logbook
import runner
import s02_dual_momentum as s02
from discard_bar import verdict

NAME = "Dual Momentum (absolute leg + BTC switch)"
COINS_STR = "BTCUSDT+SOLUSDT+XRPUSDT"
SENS_LOOKBACKS = [8, 14, 30]      # the source's long-leg N is undisclosed


def make_spec(mom_days: int) -> runner.StrategySpec:
    return runner.StrategySpec(
        name=f"{NAME} lookback={mom_days}d",
        add_indicators=lambda df: s02.add_indicators(df, mom_days),
        entry=s02.entry,
        native_exit=s02.native_exit,
        warmup=0,                                  # replaced by warmup_fn
        warmup_fn=lambda iv: s02.warmup_for(iv, mom_days),
        native_time_limit=None,                    # the source has no time barrier
        raw_extra=s02.RAW_EXTRA,
        prepare_extra=s02.inject_btc,
    )


def show_audit(symbol: str = "SOLUSDT", interval: str = "1D") -> bool:
    """Print the lookahead proof on one dataset so it is visible, not asserted.

    Deliberately run on a coin that is NOT Bitcoin, so the cross-coin Bitcoin
    switch is part of what gets tested rather than a column that happens to
    equal the coin's own close.
    """
    df = bd.drop_forming_bar(bd.load(symbol, interval), interval)
    df = s02.inject_btc(df, symbol, interval)
    keep = lookahead_check.RAW | s02.RAW_EXTRA
    raw = df[[c for c in df.columns if c in keep]].copy()
    return lookahead_check.report(
        f"{NAME} on {symbol} {interval}", raw, s02.add_indicators,
        first_cut=max(300, s02.warmup_for(interval) + 50),
    )


def leg_split(trades) -> dict:
    """Long leg vs short leg, separately.

    The source credits its SHORT leg with 75% of profits, while the academic
    paper it cites for authority concludes the opposite. Since the Bitcoin
    switch only lets the book trade while Bitcoin is ABOVE its 30-day average,
    it is worth measuring how often the short leg is even allowed to fire.
    """
    out = {}
    for name, d in [("long", 1), ("short", -1)]:
        sel = [t for t in trades if t.direction == d and np.isfinite(t.net_r)]
        out[name] = {
            "trades": len(sel),
            "r_post_fee": float(sum(t.net_r for t in sel)),
            "win_rate": float(sum(1 for t in sel if t.net_r > 0) / len(sel)) if sel else float("nan"),
        }
    return out


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
        legs = leg_split(res["trades"][(interval, label)])
        lines.append(
            f"    legs: long {legs['long']['trades']} trades {legs['long']['r_post_fee']:+.1f}R, "
            f"short {legs['short']['trades']} trades {legs['short']['r_post_fee']:+.1f}R"
        )
    return "\n".join(lines)


def _hold_days(res: dict, interval: str, label: str) -> float:
    """Average hold converted to days, so the three timeframes are comparable."""
    bpd = {"1H": 24, "4H": 6, "1D": 1}[interval]
    return res["pooled"][(interval, label)]["avg_bars_held"] / bpd


def main(write: bool) -> None:
    print("=" * 78)
    print(f"STRATEGY #2 - {NAME}")
    print("=" * 78)

    if not show_audit():
        raise SystemExit("Lookahead audit failed - no results will be produced.")

    spec = make_spec(s02.MOM_LOOKBACK_DAYS)
    res = runner.run(spec)
    n_pass = sum(1 for ok, _, _ in res["audit"].values() if ok)
    print(f"\nLookahead audit re-run on all 9 datasets: {n_pass}/9 PASS")

    summary = runner.summarise(spec, res)

    print("\nAverage hold in DAYS (the source reports about 13 days)")
    for interval in runner.INTERVALS:
        print(f"  {interval}: native {_hold_days(res, interval, 'native'):5.1f} days, "
              f"forced-1:3 {_hold_days(res, interval, 'forced-1:3'):5.1f} days")

    ctx = context_checks.summarise(res, runner.COINS, runner.INTERVALS)
    print("\nWas this a fair test? (noise level, intrabar ambiguity, entry overlap)")
    print(context_checks.text_block(ctx, runner.INTERVALS))

    print("\nMeasured 1R, as a % of price (the source discloses no stop at all)")
    for interval in runner.INTERVALS:
        bits = []
        for symbol in runner.COINS:
            df = runner._prepare(spec, symbol, interval)
            bits.append(f"{symbol} {df['stop_frac'].median() * 100:.2f}%")
        print(f"  {interval}: " + ", ".join(bits))

    print("\nExit composition, legs, and market conditions")
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

    # --- momentum-lookback sensitivity -------------------------------------
    print("\nLookback sensitivity - the source states its 8-day SHORT window and its")
    print("30-day Bitcoin average, but never the long leg's N. This sweeps it.")
    print(f"{'N days':>7} {'tf':>4} {'exit':<11} {'trades':>7} {'win%':>6} "
          f"{'R post':>8} {'R/trade':>8} {'Sharpe':>7}  verdict")
    sens: dict = {}
    for nd in SENS_LOOKBACKS:
        sres = res if nd == s02.MOM_LOOKBACK_DAYS else runner.run(make_spec(nd), audit=False)
        sens[nd] = sres
        for interval in runner.INTERVALS:
            for label in ["native", "forced-1:3"]:
                m = sres["pooled"][(interval, label)]
                v, _ = verdict(m, label)

                def g(x, ndp=2):
                    return "n/a" if x != x else f"{x:.{ndp}f}"
                print(f"{nd:>7} {interval:>4} {label:<11} {m['trades']:>7} "
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


def _g(x, nd: int = 2) -> str:
    return "n/a" if x is None or x != x else f"{x:.{nd}f}"


def _md_table(summary: dict) -> str:
    head = ("| Timeframe | Exit | Trades | Win% | RR | R (pre-fee) | R (post-fee) "
            "| R/trade | Sharpe | Max DD % | Max DD (R) | R-recovery | Verdict |")
    rows = [head, "|" + "---|" * 13]
    for interval in runner.INTERVALS:
        s = summary[interval]
        for label, vkey in [("native", "verdict_native"), ("forced-1:3", "verdict_forced")]:
            m = s[label]
            rows.append(
                f"| {interval} | {label} | {m['trades']} | {_g(m['win_rate'] * 100, 1)} "
                f"| {_g(m['rr_achieved'])} | {_g(m['r_sum_pre_fee'], 1)} "
                f"| {_g(m['r_sum_post_fee'], 1)} | {_g(m['expectancy_post_fee_r'], 3)} "
                f"| {_g(m['sharpe_post_fee'])} | {_g(m['max_drawdown_pct'], 1)} "
                f"| {_g(m['max_drawdown_r'], 1)} | {_g(m['r_recovery'])} | **{s[vkey]}** |"
            )
    return "\n".join(rows)


def _md_legs(res: dict) -> str:
    rows = ["| Timeframe | Exit | Long trades | Long R | Long win% | Short trades "
            "| Short R | Short win% |", "|" + "---|" * 8]
    for interval in runner.INTERVALS:
        for label in ["native", "forced-1:3"]:
            g = leg_split(res["trades"][(interval, label)])
            rows.append(
                f"| {interval} | {label} | {g['long']['trades']} "
                f"| {g['long']['r_post_fee']:+.1f} | {_g(g['long']['win_rate'] * 100, 1)} "
                f"| {g['short']['trades']} | {g['short']['r_post_fee']:+.1f} "
                f"| {_g(g['short']['win_rate'] * 100, 1)} |"
            )
    return "\n".join(rows)


def _md_sens(sens: dict) -> str:
    rows = ["| Long-leg N | Timeframe | Exit | Trades | Win% | R (post-fee) | R/trade "
            "| Sharpe | Verdict |", "|" + "---|" * 9]
    for nd, sres in sens.items():
        for interval in runner.INTERVALS:
            for label in ["native", "forced-1:3"]:
                m = sres["pooled"][(interval, label)]
                v, _ = verdict(m, label)
                rows.append(
                    f"| {nd} days | {interval} | {label} | {m['trades']} "
                    f"| {_g(m['win_rate'] * 100, 1)} | {_g(m['r_sum_post_fee'], 1)} "
                    f"| {_g(m['expectancy_post_fee_r'], 3)} | {_g(m['sharpe_post_fee'])} "
                    f"| {v} |"
                )
    return "\n".join(rows)


def _md_risk(res: dict) -> tuple[str, float, float, float]:
    """Measured 1R against a typical candle, per coin and timeframe.

    Strategy #1's biggest weakness was a stop narrower than one candle, which
    meant the pessimistic intrabar tie-break decided most trades. This checks
    the same thing here instead of assuming the wider stop fixed it.

    Returns the markdown table, the WORST (smallest) candle multiple in it, and
    the smallest and largest measured 1R, so the write-up quotes measured
    numbers rather than hand-typed ones.
    """
    rows = ["| Timeframe | Coin | Measured 1R (% of price) | Typical candle (%) "
            "| 1R as a multiple of one candle |", "|" + "---|" * 5]
    worst, r_lo, r_hi = float("inf"), float("inf"), 0.0
    for interval in runner.INTERVALS:
        for symbol in runner.COINS:
            df = runner._prepare(make_spec(s02.MOM_LOOKBACK_DAYS), symbol, interval)
            r_pct = float(df["stop_frac"].median() * 100)
            candle = context_checks.median_candle_range_pct(symbol, interval)
            mult = r_pct / candle
            worst, r_lo, r_hi = min(worst, mult), min(r_lo, r_pct), max(r_hi, r_pct)
            rows.append(f"| {interval} | {symbol} | {r_pct:.2f}% | {candle:.2f}% "
                        f"| {mult:.1f}x |")
    return "\n".join(rows), worst, r_lo, r_hi




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
        + (f" — average hold {summary[i][lab]['avg_bars_held']:.1f} bars "
           f"({_hold_days(res, i, lab):.1f} days), fees cost "
           f"{summary[i][lab]['avg_fee_cost_r']:.3f}R per trade, best conditions "
           f"{summary[i][lab]['best_regime']}, worst {summary[i][lab]['worst_regime']}"
           if summary[i][lab]["trades"] else "")
        for i in runner.INTERVALS for lab in ["native", "forced-1:3"]
    )

    fair = context_checks.text_block(ctx, runner.INTERVALS)

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

    overlap_lo = min(ctx[i]["overlap"] for i in runner.INTERVALS)
    overlap_hi = max(ctx[i]["overlap"] for i in runner.INTERVALS)
    tmax = max(ctx[i][k]["t_gross"] for i in runner.INTERVALS
               for k in ["sig_native", "sig_forced"])
    legs = {i: leg_split(res["trades"][(i, "native")]) for i in runner.INTERVALS}
    risk_table, risk_worst, r_lo, r_hi = _md_risk(res)

    # Funding is NOT modelled anywhere in this project. The line below is an
    # illustration built on Bybit's own baseline rate (the value the rate sits at
    # when longs and shorts are balanced), purely to show whether the omission is
    # big enough to matter. It is not a measurement of what funding actually was.
    base_rate = 0.0001
    fund_rows = "\n".join(
        f"| {i} | {summary[i]['native']['avg_bars_held'] * hours[i] / 8:.0f} "
        f"| {summary[i]['native']['avg_bars_held'] * hours[i] / 8 * base_rate * 100:.2f}% "
        f"| {summary[i]['native']['avg_bars_held'] * hours[i] / 8 * base_rate * 100 / r_hi:.3f}"
        f"–{summary[i]['native']['avg_bars_held'] * hours[i] / 8 * base_rate * 100 / r_lo:.3f}R "
        f"| {summary[i]['native']['expectancy_post_fee_r']:+.3f}R |"
        for i in runner.INTERVALS
    )
    mix1h = summary["1H"]["forced-1:3"]["exit_reason_mix"]
    n_sens_keep = sum(
        1 for sres in sens.values() for i in runner.INTERVALS
        for lab in ["native", "forced-1:3"]
        if verdict(sres["pooled"][(i, lab)], lab)[0] == "KEEP"
    )
    per_coin_keep = [
        f"{s} {i} {lab}" for s in runner.COINS for i in runner.INTERVALS
        for lab in ["native", "forced-1:3"]
        if verdict(res["per_cell"][(s, i, lab)], lab)[0] == "KEEP"
    ]

    text = f"""---

## Strategy #2 — Dual Momentum (Bybit perps), absolute leg + Bitcoin switch

**Tested:** {logbook.date.today().isoformat()} · **Coins:** BTCUSDT, SOLUSDT, XRPUSDT
(Bybit USDT perpetuals) · **Timeframes:** 1H, 4H, 1D · **Direction:** long and short ·
**Source's own cadence:** weekly re-rank pinned to Monday, average hold about 13 days

**Source:** [+117% in 4 Years: Dual Momentum on Crypto Futures](https://backtestsnotsignals.substack.com/p/117-in-4-years-dual-momentum-on-crypto)
· sourcing rated **strong** (full performance figures, method described in prose,
author states his own caveats).

### The rules, in plain English

This is a momentum system with a master switch, not a chart-pattern system.

1. **Rank and go long.** Take the trailing N-day return of every coin in the
   universe, **deliberately ignoring the most recent bar**, and buy the strongest
   names. The skipped bar matters: the author reports that without it the whole
   edge disappears.
2. **Go short outright weakness.** Any coin whose plain 8-day return is negative
   is sold short.
3. **The Bitcoin switch sits on top of everything.** If Bitcoin closes below its
   30-day moving average, the entire book is flattened — longs and shorts alike —
   and no new trade is opened.

Getting out, the source's way: there is **no stop and no target**. Positions are
re-examined once a week, on Monday, and held otherwise. A position closes when the
weekly re-check no longer likes it, or when the Bitcoin switch turns off. Average
hold is about 13 days. Risk is handled by position size — smaller size in wilder
coins — and by the switch cutting exposure to zero.

Getting out, the forced way (this project's standard comparison): stop at 1R,
target at 3R, 30-bar time limit. Identical entries, identical 1R.

**What it suits:** a trending market, and specifically a Bitcoin uptrend. It is
built to switch itself off in Bitcoin bear markets rather than to profit from them.

### What could NOT be reproduced, and why that matters

Rule 1 is **cross-sectional** — it ranks twenty coins against each other and buys
the winners. This project trades three coins. Ranking three names is not a small
version of ranking twenty; it is a different rule, so **the ranking leg is not
reproduced at all.**

What **is** reproduced is the other half of "dual" momentum — the absolute test the
source applies on top of its ranking, with the same skipped bar and the same
Bitcoin switch: go long when this coin's own skip-adjusted trailing return is
positive, go short when its 8-day return is negative, stay flat whenever Bitcoin
is below its 30-day average. Everything below is labelled "absolute leg + Bitcoin
switch" for that reason. It is not a verdict on the source's full system.

### Parameters — what the source states, and what is a guess

| Parameter | Value used | Where it came from |
|---|---|---|
| Short-leg window | {s02.SHORT_LOOKBACK_DAYS} days | **stated by the source** |
| Bitcoin moving average | {s02.BTC_MA_DAYS} days | **stated by the source** |
| Skipped bar | {s02.SKIP_DAYS} bar | **stated by the source** |
| Re-rank day | Monday | **stated by the source** |
| Long-leg lookback N | {s02.MOM_LOOKBACK_DAYS} days | **placeholder** — the source never gives N. Swept at 8/14/30 below |
| Stop distance | {s02.ATR_STOP_MULT}x a {s02.ATR_DAYS}-day average daily range | **placeholder** — the source has no stop at all |
| Forced-1:3 time limit | {runner.FORCED_TIME_LIMIT} bars | project-wide **unvalidated placeholder** |

Two of those deserve calling out.

**The stop is mine, not the source's.** A stop had to exist because R is the
denominator of every number this project reports, and because an unstopped
perpetual short is unbounded risk nobody would actually trade. It is measured
against a **daily-equivalent** average range rather than the trading bar's range —
a 14-bar range on hourly candles would be a 14-hour stop on a 13-day trade, which
would stop out almost immediately and would measure the stop instead of the
strategy. The consequence is that 1R means the same real risk on all three
timeframes, so the three are comparable. It also happens to be a fair reading of
the source's own risk control: risking a fixed fraction of equity against a
volatility-scaled stop **is** inverse-volatility sizing.

The cost of that choice is visible in the exit mix below: a stop the source does
not have ended {summary['1H']['native']['exit_reason_mix'].get('stop', 0)} of
{summary['1H']['native']['trades']} native trades on 1H. That share of the native
result is attributable to my placeholder, not to the source's rule.

### How this test differs from the source

| | Source | This test |
|---|---|---|
| Universe | top 20 by market cap | 3 fixed coins |
| Selection | cross-sectional ranking | not reproduced — absolute momentum only |
| Timeframe | daily data, weekly decisions | 1H, 4H and 1D data, weekly decisions |
| Stop | none | volatility stop, as above |
| Costs | not stated | Bybit taker {0.00055:.5f} both legs, always applied |
| Funding | not stated | not modelled — see the funding section |

One structural point about the three timeframes. Because the decision day is pinned
to Monday, all three timeframes get the **same** number of decision points — 336
Monday-00:00 bars on 1H, 4H and 1D alike. So this is not three tests at three
different trade frequencies. It is one decision cadence, examined with three
different resolutions of stop and exit. That is why the trade counts below are
similar across timeframes instead of scaling with bar count.

### Lookahead check — run fresh on this strategy

Method: recompute every indicator on history that has been cut off at a given bar,
then compare the value at the cut against the value the same indicator shows when
the whole history is present. If future candles were leaking into a past decision,
the two numbers would differ.

Columns checked: {', '.join(cols)}.
Result: **{n_pass}/9 datasets PASS** at 25 cut points each, to a tolerance of
1e-12.

Three things were specifically dealt with on this strategy, because it is the first
one that reads data from a coin other than the one being traded:

- **Bitcoin's price is injected as raw data before any indicator is built**, so the
  audit truncates it at the same bar as everything else. Had Bitcoin's full history
  been loaded inside the indicator step instead, the audit would have ignored the
  cut and would have quietly stopped testing half the rule while still printing
  PASS. `btc_close` and `btc_on` appear in the checked-columns list above, which is
  the proof that the switch really was audited.
- **Bitcoin's bars are aligned onto the traded coin's timestamps by backward fill**,
  so a decision only ever sees the most recent Bitcoin bar that had already closed.
- **The audit's first cut was moved past the warm-up.** The default first cut sits
  at bar 300, which is inside this strategy's 816-bar hourly warm-up — every
  indicator would still be blank there, and comparing blank to blank would print a
  pass without having tested anything.

On top of that, the two protections that apply to every strategy here: a signal read
from a finished candle is filled at the **next** candle's open, and the momentum
windows are shifted twice on purpose — once for the source's skipped bar, once to
reach the start of the window — so no window ever includes the bar being decided on.

### Results — three coins pooled per timeframe, after fees

{_md_table(summary)}

Pre-fee is shown only so the size of the fee bill is visible. Every verdict is made
on the post-fee column.

### How the trades ended

{mixes}

### The long leg versus the short leg — the source's biggest claim, tested

The source credits its **short** leg with 75% of profits. The academic paper it
cites for authority concludes the **opposite**: that momentum profits come almost
entirely from the long leg while the short leg loses money. Those cannot both be
true, so the two legs were measured separately.

{_md_legs(res)}

**The paper wins and the source loses, on this data.** On the native exit the long
leg produced {legs['1H']['long']['r_post_fee']:+.1f}R on 1H,
{legs['4H']['long']['r_post_fee']:+.1f}R on 4H and
{legs['1D']['long']['r_post_fee']:+.1f}R on 1D. The short leg produced
{legs['1H']['short']['r_post_fee']:+.1f}R, {legs['4H']['short']['r_post_fee']:+.1f}R
and {legs['1D']['short']['r_post_fee']:+.1f}R. It is not merely smaller — it is
close to nothing on every timeframe, negative on 1H, and never more than
{max(legs[i]['short']['r_post_fee'] for i in runner.INTERVALS):+.0f}R against a long
leg that produced upwards of
{min(legs[i]['long']['r_post_fee'] for i in runner.INTERVALS):+.0f}R.

There is a mechanical reason, and it is worth understanding because it is a design
flaw in the rule rather than an accident of this data. **The Bitcoin switch only
permits trading while Bitcoin is above its 30-day average.** That is precisely when
altcoins tend to have positive momentum. So the short leg is only ever allowed to
fire in the narrow case of a coin falling *while Bitcoin is rising* — and it is
forbidden in exactly the conditions a short seller wants, because a Bitcoin
downtrend flattens the whole book. The switch and the short leg work against each
other by construction.

Trade counts show the same thing: {legs['1H']['long']['trades']} long trades against
{legs['1H']['short']['trades']} short on 1H. The book is roughly
{legs['1H']['long']['trades'] / max(legs['1H']['long']['trades'] + legs['1H']['short']['trades'], 1):.0%}
long by trade count. Whatever this strategy is, it is a long-biased trend follower
with a small short appendix, not a balanced long/short book.

### Exit-death check

{death}

**Read that flag with care on this strategy — the precondition for it is not met.**
The check is only clean when both variants trade the same entries, and here they
share just {overlap_lo:.0%}–{overlap_hi:.0%} of them, against the
{context_checks.MIN_OVERLAP:.0%} threshold this project requires. The cause is
structural rather than a bug: the native exit holds a position for
{min(_hold_days(res, i, 'native') for i in runner.INTERVALS):.0f}–{max(_hold_days(res, i, 'native') for i in runner.INTERVALS):.0f} days,
and an open position blocks the next weekly signal, so the native variant simply
gets fewer chances to enter ({summary['1H']['native']['trades']} trades on 1H against
{summary['1H']['forced-1:3']['trades']} for the forced version). The two variants are
therefore not the same entries with different exits; they are different trade sets.

What can still be said, because both readings point the same way: **this strategy's
result lives in its native exit, and forcing a 1:3 onto it takes the result away.**
Per trade, native earned {summary['1H']['native']['expectancy_post_fee_r']:+.3f}R on
1H against {summary['1H']['forced-1:3']['expectancy_post_fee_r']:+.3f}R forced,
{summary['4H']['native']['expectancy_post_fee_r']:+.3f}R against
{summary['4H']['forced-1:3']['expectancy_post_fee_r']:+.3f}R on 4H, and
{summary['1D']['native']['expectancy_post_fee_r']:+.3f}R against
{summary['1D']['forced-1:3']['expectancy_post_fee_r']:+.3f}R on 1D. The achieved
reward-to-risk collapses the same way, from about
{summary['1H']['native']['rr_achieved']:.1f}:1 native to
{summary['1H']['forced-1:3']['rr_achieved']:.1f}:1 forced on 1H.

**This is the opposite of the pattern that motivated this whole project.** A previous
postmortem on seven consecutive failed systems found the exit to be the culprit
seven times out of seven: indicator-reversal exits produced zero winners, while a
fixed take-profit on the identical entries produced zero losers. Strategy #2 inverts
that. Its condition-based exit — hold until the weekly re-check or the Bitcoin switch
says otherwise — is the part that works, and the fixed 3R target is what destroys it.
That is what a genuine trend-following payoff distribution looks like: a low win rate
of about {summary['1H']['native']['win_rate']:.0%} paying about
{summary['1H']['native']['rr_achieved']:.1f}:1, where capping the winners at 3R
removes the few outliers that fund everything else.

**One caveat that cuts against the forced variant's numbers rather than for them.**
On 1H the forced test barely tests 1:3 at all: of
{summary['1H']['forced-1:3']['trades']} trades, the 3R target was reached
{mix1h.get('target', 0)} times and the {runner.FORCED_TIME_LIMIT}-bar clock ended
{mix1h.get('time', 0)} of them. With 1R measured against a daily range, 1R is roughly
{r_lo:.0f}–{r_hi:.0f}% of price, so a 3R target sits {3 * r_lo:.0f}–{3 * r_hi:.0f}% away — unreachable inside
{runner.FORCED_TIME_LIMIT} hours. The 1H forced-1:3 row is therefore mostly measuring
"hold for 30 hours, then leave", not a 1:3 trade plan. The time limit stays fixed at
{runner.FORCED_TIME_LIMIT} bars because the ruler does not move between strategies,
but the 1H and 4H forced numbers should be read as a handicapped test rather than a
fair refutation. Only the 1D forced-1:3 column gives the target a realistic chance —
and there it hits {summary['1D']['forced-1:3']['exit_reason_mix'].get('target', 0)}
times out of {summary['1D']['forced-1:3']['trades']}.

### Where the money actually went

{fee_rows}

**Fees are not the story on this strategy, and that is itself a finding.** They cost
about {summary['1H']['native']['avg_fee_cost_r']:.3f}R per round trip, roughly a
hundredth of a risk unit, because 1R here is {r_lo:.0f}–{r_hi:.0f}% of price and a
{runner.TAKER_FEE_RATE * 100:.3f}% commission
is tiny against that. Contrast Strategy #1, where a 2% stop on hourly candles made
the commission bill the entire difference between flat and losing. A wide stop makes
a strategy fee-insensitive; a tight stop makes fees decisive.

### Was this a fair test?

```
{fair}
```

{risk_table}

Four things to read out of those blocks:

- **The positive results are not statistically distinguishable from luck.** The
  largest t-statistic anywhere in this test is {tmax:+.2f}, and roughly 2 is the bare
  minimum before an average is worth taking seriously. The native exit's
  {summary['1H']['native']['r_sum_post_fee']:+.0f}R on 1H looks impressive as a total,
  but it comes from {summary['1H']['native']['trades']} trades with a spread of
  {ctx['1H']['sig_native']['gross_std']:.1f}R per trade. A handful of large winners
  produced most of it. That is normal for trend following and it is also exactly the
  shape that cannot be told apart from chance at this sample size.
- **The intrabar ambiguity problem from Strategy #1 is gone.** At most
  {max(ctx[i]['first_bar_forced'] for i in runner.INTERVALS):.0%}
  of forced trades resolved inside their first candle, versus a majority on Strategy
  #1's 1D test. 1R is {risk_worst:.1f}x wider than a typical candle at its worst in the
  table above, so the pessimistic stop-wins tie-break almost never had to be applied.
  The daily-equivalent stop did its job.
- **The two exit variants do not trade the same entries** ({overlap_lo:.0%}–{overlap_hi:.0%}
  overlap against a {context_checks.MIN_OVERLAP:.0%} requirement), for the structural
  reason given above. This weakens the exit-death comparison and is the single largest
  methodological weakness in this entry.
- **The sample is thin in a way trade count hides.** {summary['1D']['native']['trades']}
  trades sounds adequate, but they come from 336 Monday decision points across three
  coins over about five years, and the three coins are heavily correlated. The
  effective number of independent bets is far smaller than the trade count suggests.

### Per-coin breakdown — the pooled number is mostly Bitcoin

```
{runner.per_coin_table(res)}
```

Of the {summary['1H']['native']['r_sum_post_fee']:+.0f}R the pooled 1H native test
produced, {res['per_cell'][('BTCUSDT', '1H', 'native')]['r_sum_post_fee']:+.0f}R came
from Bitcoin alone, on {res['per_cell'][('BTCUSDT', '1H', 'native')]['trades']} trades.
XRP's 1D native cell is an outright DISCARD. Every negative post-fee cell in the whole
per-coin table belongs to SOL or XRP. This is a Bitcoin-uptrend strategy that was
applied to two altcoins, not a rule that worked on three coins independently.

{("**One per-coin cell scores KEEP: " + ", ".join(per_coin_keep) + ".** It is reported "
  "because nothing gets hidden, and it is explicitly *not* being treated as a KEEP. "
  "It is one cell out of 18 per-coin cells; at that count, one cell clearing the bar "
  "is what noise alone produces. The pooled verdict for that timeframe and exit is "
  "the one that counts, and it is not a KEEP. Picking the single best cell out of 18 "
  "is the selection error this project exists to avoid.")
 if per_coin_keep else "No per-coin cell reaches KEEP."}

### Verdicts — each exit variant scored separately

{verdicts}

Not one cell reaches KEEP at the pooled level. The native exit lands
**INCONCLUSIVE on all three timeframes** for the same reason each time: it makes
money in total but its risk-adjusted return falls short of the bar, and the
per-trade average cannot be separated from noise. The forced 1:3 is a DISCARD on 1H
and INCONCLUSIVE on 4H and 1D.

### Lookback sensitivity (secondary evidence, not the headline)

The source never discloses the long leg's N. This sweeps it at 8, 14 and 30 days.
Read it as a check on whether the verdict above is an artefact of a guessed number,
not as an optimisation — nothing here is tuned or selected.

{_md_sens(sens)}

**{n_sens_keep} of the 18 cells above reach KEEP.** The native exit stays positive at
every value of N on every timeframe, which is a genuine robustness result — the
finding does not depend on my guess. But it is positive-and-INCONCLUSIVE at every
value of N too, so no choice of N rescues it. Shortening N to 8 days roughly doubles
the trade count ({sens[8]['pooled'][('1H', 'native')]['trades']} against
{sens[30]['pooled'][('1H', 'native')]['trades']} on 1H) and cuts the total roughly in
half, which is what you would expect if the longer lookback is selecting stronger
trends rather than merely trading more.

### Bottom line

**INCONCLUSIVE on the native exit across all three timeframes; DISCARD on 1H forced
1:3 and INCONCLUSIVE on 4H and 1D forced 1:3.** No KEEP, and no DISCARD of the
strategy as a whole.

What was actually learned, in order of confidence:

1. **The source's central claim about its short leg does not survive.** The long leg
   produced essentially all of the profit and the short leg produced roughly nothing.
   The academic paper the author cites against himself is the one this data agrees
   with. The Bitcoin switch and the short leg are structurally in conflict.
2. **The strategy's result depends on its native exit, not on a target.** This is the
   first strategy in the project where forcing a clean 1:3 makes things worse rather
   than better, and it is a textbook low-win-rate, high-payoff trend profile.
3. **The pooled result is largely Bitcoin's uptrend.** Both altcoins contributed
   little or negative after fees.
4. **Nothing here is statistically solid.** The best t-statistic is {tmax:+.2f}
   against a minimum of about 2.

Why INCONCLUSIVE rather than DISCARD: the results are positive, robust to the one
parameter that was swept, and short of the bar on risk-adjusted grounds rather than
on direction. Calling that a DISCARD would overstate what was tested — and the
biggest single component of the source's rule, the cross-sectional ranking, was never
tested at all.

**What would change this verdict:** running the real rule on a 20-coin universe with
genuine cross-sectional ranking. That is the same build Strategy #1's write-up flagged
— the runner cannot currently rank a universe — and it is now the second strategy
blocked on it. Worth noting that a wider universe should help this one specifically:
its problem is not a broken rule but too few independent bets, and ranking twenty
coins is how the source gets both more trades and better selection. Flagged as a
possible revisit, not scheduled.

### Funding cost — flagged, and this time the omission is NOT conservative

Bybit charges or pays funding on a perpetual every 8 hours. Measured average holds on
the native exit: {funding}. So every native trade spans roughly fifty funding windows,
which is far more exposure to funding than Strategy #1 had.

The direction matters here in a way it did not for Strategy #1. That strategy was
short only, and a short *receives* funding when the rate is positive, so the unknown
could have been a hidden credit. **This strategy is long-biased** — about
{legs['1H']['long']['trades'] / max(legs['1H']['long']['trades'] + legs['1H']['short']['trades'], 1):.0%}
of trades are longs — and a long *pays* funding when the rate is positive. Worse, the
Bitcoin switch only lets it trade while Bitcoin is above its 30-day average, which is
exactly the condition in which funding rates are usually positive. So the most likely
sign of the unmodelled cost is negative, and **this omission cannot be claimed to be
conservative.**

How much would it take to matter? The table below assumes Bybit's baseline rate of
{base_rate * 100:.2f}% per 8-hour window — **an assumption, not a measurement; this
project has not collected historical funding rates:**

| Timeframe | Funding windows per trade | Cost of notional at baseline | Cost in R (1R = {r_lo:.1f}–{r_hi:.1f}% of price) | Measured native edge |
|---|---|---|---|---|
{fund_rows}

At the baseline rate the effect is real but small against the native edge — a few
percent of it. It is not small against the forced-1:3 edge, where it would consume a
meaningful share of it. And the baseline is a floor rather than a typical value: in
strong bull markets, which is exactly when this strategy is long and fully exposed,
funding has run well above baseline for extended stretches.

Per the standing rule: no KEEP is being claimed, so nothing is blocked today. But this
is now on record as a strategy where funding must be measured before any KEEP could be
treated as real — and the native exit sits close enough to the bar that funding could
plausibly decide it.

### Also not modelled

Slippage and order-book depth. Two caveats belong to the source rather than to these
numbers: its universe is the 2026 top-20 applied backwards, which is survivorship bias
in its +117% headline (not in this entry — these three coins were fixed in advance and
all three still trade), and its stated in-sample and held-out windows overlap by a full
year, which undercuts its walk-forward claim.
"""
    # The whole write-up is built before anything is written, so a formatting
    # mistake cannot leave half a record in an append-only log.
    _csv_rows(summary)
    logbook.log_md(text)


if __name__ == "__main__":
    main("--log" in sys.argv)





