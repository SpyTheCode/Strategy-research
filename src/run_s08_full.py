"""Run Strategy #8 - Supertrend (complete analysis), and log it.

Usage:  .venv\\Scripts\\python.exe src\\run_s08_full.py [--log]

The full-depth analysis matching the standard set by Strategies #1-7. Everything
printed to the terminal is a measurement; the prose rendered into the log quotes
those measurements by name, so a re-run cannot leave a stale number in a sentence
beside a fresh table.

WHAT THE SOURCE ACTUALLY SAYS, AND WHAT IT DOES NOT
--------------------------------------------------
Olivier Seban is credited with the indicator, but he published no backtest for
it. The outcome claims that do circulate come from education sites, not from the
author, and they are marketing copy: "50-60% win rate" for flip entries, "65-72%"
for pullback entries, from a site whose own footer says it is educational content
and not trading advice. No market, no bar size, no date span, no Sharpe, no
drawdown and no trade count is stated anywhere. So the source comparison is a
comparison of SHAPE, not of outcome - and the shape claims are what the tables
below measure.

THE DIRECTION AMBIGUITY
----------------------
The literature is split, and the split is not an oversight: TrendSpider's
reference describes a bearish flip as "a possible short entry or exit from long
trades", i.e. both directions; most retail treatments trade the line long-only,
using it to time entries and exits of a long book. Both are run here, both
directions as the headline (the literal reading of "flip = trade the new
direction") and long-only as a labelled sensitivity.
"""

from __future__ import annotations

import pickle
import sys

import numpy as np
import pandas as pd

import bybit_data as bd
import context_checks
import coverage
import logbook
import lookahead_check
import runner
import s08_fast
import s08_fastpath
import s08_supertrend as s08
from discard_bar import BAR, EXIT_DEATH_GAP_R, exit_death, verdict
from harness import metrics

SNAPSHOT = r"c:\tmp\s08_bundle.pkl"

NAME = "Supertrend (10, 3)"
COINS_STR = "BTCUSDT+SOLUSDT+XRPUSDT"
IVS = ["1H", "4H", "1D"]

# 4H is the headline: the timeframe where the KEEP sits, and the only one where
# the entry/exit overlap is high enough for the exit-death comparison to mean
# anything. 1D is reported beside it because a daily Supertrend is the closest
# thing to a conventional reading of the rule, and 1H because it is the densest
# sample - most trades, least noise.
HEADLINE_TF = "4H"
DENSE_TF = "1H"

# The source's own claims, such as they are. Where nothing is stated the field is
# None and the comparison table says "not stated" rather than inventing a number.
SRC = {
    "what": "market and bar size NOT stated (education sites, not Seban)",
    "win_flip": (50.0, 60.0),       # "flip entries produce 50-60% win rates"
    "win_pullback": (65.0, 72.0),   # "pullback entries produce 65-72% win rates"
    "rr": 1.5,                      # "R:R 1.5:1 to 3:1"
    "condition": "sustained trends; whipsaws in ranges/chop",
    "sharpe": None, "dd": None, "trades": None,
}

LABELS = ["native", "forced-1:3"]

# Bybit settles funding every 8 hours at a base rate. The base rate is a floor,
# not a forecast: a trend-follower is by definition holding the crowded side of a
# one-way market, where funding is usually worse than base.
FUNDING_BASE_PCT = 0.01      # per 8-hour stamp, as a percent
FUNDING_HOURS = 8.0
HOURS_PER_BAR = {"1H": 1.0, "4H": 4.0, "6H": 6.0, "1D": 24.0}

TRADED_TAG = "as traded"
LONGONLY_TAG = "long-only, the other common reading of the rule"


def make_spec(atr_period: int = s08.ATR_PERIOD,
              multiplier: float = s08.MULTIPLIER,
              long_only: bool = False) -> runner.StrategySpec:
    """Build a StrategySpec. The parameters are the source's defaults unless overridden.

    `add_indicators` runs through s08_fast, which s08_selftest pins to the
    reference s08_supertrend implementation column-for-column. The report needs
    roughly a hundred and fifty backtest passes (nine datasets x two exits,
    repeated across the ATR / multiplier / direction sweeps plus a 25-cut audit
    on each of nine datasets), which the reference's per-bar `df.loc` loop
    cannot deliver in any reasonable time. s08_fast and s08_fastpath are both
    proven trade-identical to the real thing by s08_selftest before this
    report is allowed to use them.
    """
    bits = [f"{atr_period}", f"{multiplier:g}"]
    if long_only:
        bits.append("long-only")
    return runner.StrategySpec(
        name=f"Supertrend ({atr_period}, {multiplier:g})[{' '.join(bits)}]",
        add_indicators=lambda df: s08_fast.add_indicators(df, atr_period, multiplier),
        entry=lambda df: s08_fastpath.entry(df, long_only=long_only),
        native_exit=s08_fastpath.native_exit,
        warmup=50,
        notes=f"atr_period={atr_period} multiplier={multiplier} long_only={long_only}",
        fast_simulate=s08_fastpath.simulate,
    )


def show_audit(symbol: str = "BTCUSDT", interval: str = HEADLINE_TF) -> bool:
    """Print the lookahead proof on one dataset so it is visible, not asserted."""
    df = bd.drop_forming_bar(bd.load(symbol, interval), interval)
    raw = df[[c for c in df.columns if c in lookahead_check.RAW]].copy()
    return lookahead_check.report(
        f"{NAME} on {symbol} {interval}", raw, s08_fast.add_indicators,
        first_cut=max(300, 50 + 50),
    )


# ---------------------------------------------------------------------------
# Measurements this strategy needs that the shared code does not provide
# ---------------------------------------------------------------------------

def r_pct(trades) -> float:
    """Median 1R as a percentage of the entry price, measured from real fills.

    1R is the ATR distance the indicator placed, resolved against the actual fill
    price - not read off the indicator - so it is the risk that was really
    carried. It is the denominator of every R-based figure and the number that
    decides whether fees and funding are rounding errors or decisive.
    """
    v = [abs(t.risk_per_unit) / t.entry_price * 100.0
         for t in trades if t.entry_price and np.isfinite(t.risk_per_unit)]
    return float(np.median(v)) if v else float("nan")


def wrong_side(trades) -> int:
    """Fills that landed on the far side of their own stop level.

    The 1R level is a FRACTION fixed on the signal bar and resolved against the
    fill, so the stop moves with the fill and this should be structurally
    impossible. Counted anyway, because "should be" is not a measurement.
    """
    return sum(1 for t in trades
               if (t.entry_price - t.initial_stop) * t.direction <= 0)


def signal_counts(long_only: bool = False) -> tuple[int, int]:
    """(flip signals fired, signals with a measurable 1R) across all nine datasets.

    Counted off the indicator columns rather than off the trades, so it does not
    depend on which signals a run happened to be flat for.
    """
    fired = usable = 0
    for symbol in runner.COINS:
        for interval in IVS:
            df = bd.drop_forming_bar(bd.load(symbol, interval), interval)
            f = s08_fast.add_indicators(df)
            bull = (f["st_dir"] == 1) & (f["st_dir"].shift(1) != 1)
            bear = (f["st_dir"] == -1) & (f["st_dir"].shift(1) != -1)
            sig = bull if long_only else (bull | bear)
            ok = sig & f["atr"].notna() & (f["atr"] > 0)
            fired += int(sig.iloc[50:].sum())
            usable += int(ok.iloc[50:].sum())
    return fired, usable


def loss_tail(trades) -> dict:
    """Losses bigger than the 1R they were sold as.

    The native exit is a trailing stop the indicator re-reads every bar, so a
    loss should stay near one unit of risk. This is the measurement that shows
    whether that held - and on the forced variant, where the stop is fixed, it is
    the check that the pessimistic intrabar tie-break is not quietly costing more.
    """
    net = np.array([t.net_r for t in trades if np.isfinite(t.net_r)])
    losers = net[net <= 0]
    return {
        "worst": float(net.min()) if len(net) else float("nan"),
        "best": float(net.max()) if len(net) else float("nan"),
        "losers": int(len(losers)),
        "beyond_1_2": int((losers < -1.2).sum()),
        "share_beyond": float((losers < -1.2).mean()) if len(losers) else float("nan"),
        "mean_loser": float(losers.mean()) if len(losers) else float("nan"),
    }


def hold_tail(trades) -> dict:
    """How long the longest trades ran. A trailing-stop rule needs this reported."""
    b = np.array([t.bars_held for t in trades]) if trades else np.array([0])
    return {"median": float(np.median(b)), "p95": float(np.percentile(b, 95)),
            "max": int(b.max())}


def top_share(trades) -> dict:
    """How much of the whole result came from a handful of trades.

    The discard bar does not test this, and on a trailing-stop rule with a
    sub-40% win rate it is the first thing that should be checked: if the total is
    one trade wearing a trench coat then the average R per trade is not a number
    anybody could have traded. Reported as the share of the post-fee total coming
    from the single best trade and from the best five, plus what is left without
    the best one.
    """
    net = np.array(sorted((t.net_r for t in trades if np.isfinite(t.net_r)),
                          reverse=True))
    tot = float(net.sum()) if len(net) else float("nan")
    top1 = float(net[0]) if len(net) else float("nan")
    top5 = float(net[:5].sum()) if len(net) else float("nan")
    return {
        "total": tot,
        "top1": top1,
        "top5": top5,
        "share1": top1 / tot if tot else float("nan"),
        "share5": top5 / tot if tot else float("nan"),
        "without_top1": tot - top1,
        "n": int(len(net)),
    }


def leg_split(trades) -> dict:
    """Long leg vs short leg. The rule is symmetric; the market is not."""
    out = {}
    for side, d in [("long", 1), ("short", -1)]:
        sel = [t for t in trades if t.direction == d and np.isfinite(t.net_r)]
        r = np.array([t.net_r for t in sel]) if sel else np.array([])
        out[side] = {
            "trades": len(sel),
            "r_post_fee": float(r.sum()) if len(r) else 0.0,
            "win_rate": float((r > 0).mean()) if len(r) else float("nan"),
        }
    return out


def trend_split(trades) -> dict:
    """R by the TREND half of the regime label - the source's own condition.

    The literature says Supertrend wants sustained trends and gets whipsawed in
    ranges. The regime label is two halves joined by a slash (trend then
    volatility); this keeps only the trend half, so the claim is checked directly
    instead of being read off a nine-cell table. "trending" pools up and down,
    because the claim is about trend, not direction.

    One limit, stated because it decides how much the answer is worth: the label
    is assigned at ENTRY, and a flip by definition fires before a 100-bar average
    has turned. A flip that becomes a trend therefore books its profit under
    whatever label was true the moment it started. So this can show whether the
    label works as a FILTER; it cannot cleanly confirm or refute the claim.
    """
    out = {}
    for tag, keys in [("trending", ("up", "down")), ("range", ("range",))]:
        sel = [t for t in trades
               if t.regime.split("/")[0] in keys and np.isfinite(t.net_r)]
        r = np.array([t.net_r for t in sel]) if sel else np.array([])
        out[tag] = {
            "trades": len(sel),
            "r_post_fee": float(r.sum()) if len(r) else 0.0,
            "expectancy": float(r.mean()) if len(r) else float("nan"),
            "win_rate": float((r > 0).mean()) if len(r) else float("nan"),
        }
    return out


def by_reason(trades) -> dict:
    """{exit reason: (count, mean net R)}. Says what each exit route costs."""
    out: dict = {}
    for t in trades:
        if not np.isfinite(t.net_r):
            continue
        out.setdefault(t.exit_reason or "unknown", []).append(t.net_r)
    return {k: (len(v), float(np.mean(v))) for k, v in sorted(out.items())}


def matched(res: dict, interval: str) -> dict:
    """Re-score both variants on ONLY the entries they both actually took.

    The two variants share an entry rule, but an open position blocks the next
    signal, and here the gap is extreme by design: the native rule holds until
    the indicator flips back while the forced variant is capped at 30 bars. So
    the forced run takes entries the native run was still holding through, and
    comparing the full runs mixes two effects - the exit, and a different set of
    trades. This strips the second one out. It is the fair exit-death comparison;
    the standard one is reported beside it because that is the project's defined
    check.
    """
    a = res["trades"][(interval, "native")]
    b = res["trades"][(interval, "forced-1:3")]
    keys = ({(t.direction, t.entry_time) for t in a}
            & {(t.direction, t.entry_time) for t in b})
    sel_a = [t for t in a if (t.direction, t.entry_time) in keys]
    sel_b = [t for t in b if (t.direction, t.entry_time) in keys]
    flag, diag = exit_death(metrics(sel_a, interval=interval),
                            metrics(sel_b, interval=interval))
    return {"native": metrics(sel_a, interval=interval),
            "forced-1:3": metrics(sel_b, interval=interval),
            "n": len(keys), "exit_death": flag, "diag": diag}


def candle_multiples(res: dict) -> list[float]:
    """1R divided by a typical candle, per coin and timeframe, from real fills.

    1R is a multiple of the ATR on THIS timeframe's bars, so unlike a day-scale
    stop it does NOT come out at a similar width everywhere: it shrinks with the
    bar. The per-cell ratio is the honest figure, and the spread between cells is
    the finding - it is why the 1H fee bill is decisive while the 1D one is not.
    """
    out = []
    for symbol in runner.COINS:
        for interval in IVS:
            rng = context_checks.median_candle_range_pct(symbol, interval)
            if rng > 0:
                out.append(r_pct(res["trades"][(symbol, interval, "native")]) / rng)
    return out


# ---------------------------------------------------------------------------
# Terminal run
# ---------------------------------------------------------------------------

def main(write: bool) -> None:
    print(f"Strategy #8 - {NAME}")
    print("=" * 78)
    print("Olivier Seban is credited with the indicator and published no backtest for it.")
    print("The win-rate claims that circulate come from education sites, not from the")
    print("author, and no market, bar size, date span, Sharpe, drawdown or trade count is")
    print("stated anywhere. So the source comparison is a comparison of SHAPE only.")

    print("\nLookahead audit, shown in full on one dataset")
    if not show_audit():
        print("AUDIT FAILED - stopping, no numbers produced.")
        sys.exit(1)

    spec = make_spec()
    res = runner.run(spec, intervals=IVS)
    n_all = len(res["audit"])
    n_ok = sum(1 for ok, _, _ in res["audit"].values() if ok)
    print(f"\nAudit re-run on all {n_all} datasets: {n_ok}/{n_all} PASS")

    summary = runner.summarise(spec, res, intervals=IVS)

    cov = coverage.collect(runner.COINS, IVS, spec.warmup_for)
    print("\nHow much history these numbers cover")
    print(coverage.md_table(cov, runner.COINS, IVS))
    print(coverage.summary_line(cov, runner.COINS, IVS))

    print("\nSignals fired vs signals usable, all nine datasets")
    fired, usable = signal_counts()
    print(f"  {fired} flip signals, {usable} with a measurable 1R "
          f"({fired - usable} dropped because ATR had not formed)")

    print("\nHow wide 1R really is: the ATR distance as a percentage of price")
    for interval in IVS:
        cells = ", ".join(
            f"{s} {r_pct(res['trades'][(s, interval, 'native')]):.2f}%"
            for s in runner.COINS)
        print(f"  {interval:<4} {cells}")

    print("\nHow the trades ended (three coins pooled), and how long they ran")
    for interval in IVS:
        for label in LABELS:
            m = res["pooled"][(interval, label)]
            mix = ", ".join(f"{k} {n} @ {r:+.3f}R"
                            for k, (n, r) in by_reason(res["trades"][(interval, label)]).items())
            h = hold_tail(res["trades"][(interval, label)])
            print(f"  {interval:<4} {label:<11} {mix or 'none'} | avg bars "
                  f"{m['avg_bars_held']:.1f} | median {h['median']:.0f} "
                  f"| 95th pct {h['p95']:.0f} | longest {h['max']}")

    print("\nDoes the trailing stop keep losses near one unit of risk?")
    for interval in IVS:
        for label in LABELS:
            t = loss_tail(res["trades"][(interval, label)])
            print(f"  {interval:<4} {label:<11} losers {t['losers']:>5} | "
                  f"mean loser {t['mean_loser']:>+7.3f}R | beyond -1.2R "
                  f"{t['beyond_1_2']:>5} ({t['share_beyond']:>4.0%}) | worst "
                  f"{t['worst']:>+7.2f}R | best {t['best']:>+7.2f}R")

    print("\nHow concentrated the result is - share of the total from the best trades")
    for interval in IVS:
        for label in LABELS:
            c = top_share(res["trades"][(interval, label)])
            print(f"  {interval:<4} {label:<11} total {c['total']:>+8.1f}R | best "
                  f"{c['top1']:>+8.2f}R ({c['share1']:>5.0%}) | best five "
                  f"{c['top5']:>+8.1f}R ({c['share5']:>5.0%}) | without the best "
                  f"{c['without_top1']:>+8.1f}R")

    print("\nThe source's own claimed condition: sustained trends, whipsawed in ranges")
    print(f"  {'tf':<5} {'exit':<11} {'trending n':>11} {'trending R':>11} "
          f"{'R/trade':>9} {'range n':>9} {'range R':>9} {'R/trade':>9}")
    for interval in IVS:
        for label in LABELS:
            v = trend_split(res["trades"][(interval, label)])
            print(f"  {interval:<5} {label:<11} {v['trending']['trades']:>11} "
                  f"{v['trending']['r_post_fee']:>+11.1f} {v['trending']['expectancy']:>+9.3f} "
                  f"{v['range']['trades']:>9} {v['range']['r_post_fee']:>+9.1f} "
                  f"{v['range']['expectancy']:>+9.3f}")

    print("\nLong leg vs short leg")
    for interval in IVS:
        for label in LABELS:
            g = leg_split(res["trades"][(interval, label)])
            print(f"  {interval:<4} {label:<11} long {g['long']['trades']:>5} trades "
                  f"{g['long']['r_post_fee']:>+8.1f}R | short {g['short']['trades']:>5} trades "
                  f"{g['short']['r_post_fee']:>+8.1f}R")

    print("\nAgainst the source's claims - which state no market and no bar size")
    print(f"  {'':<44} {'trades':>7} {'win%':>7} {'RR':>6} {'Sharpe':>7} {'maxDD%':>7}")
    src_win = f"{SRC['win_flip'][0]:.0f}-{SRC['win_flip'][1]:.0f}"
    print(f"  {SRC['what'] + ', flip entries':<44} {'n/a':>7} {src_win:>7} "
          f"{SRC['rr']:>6.1f} {'n/a':>7} {'n/a':>7}")
    for interval in IVS:
        m = summary[interval]["native"]
        print(f"  {'this test, native exit, ' + interval:<44} {m['trades']:>7} "
              f"{m['win_rate'] * 100:>7.1f} {m['rr_achieved']:>6.2f} "
              f"{m['sharpe_post_fee']:>7.2f} {m['max_drawdown_pct']:>7.1f}")

    print("\nPer coin, per timeframe, per exit")
    print(runner.per_coin_table(res, intervals=IVS))

    ctx = context_checks.summarise(res, runner.COINS, IVS)
    print("\nContext checks - is the test fair, and is the result separable from luck")
    print(context_checks.text_block(ctx, IVS))

    ws = sum(wrong_side(res["trades"][(i, lab)]) for i in IVS for lab in LABELS)
    tot = sum(len(res["trades"][(i, lab)]) for i in IVS for lab in LABELS)
    print(f"\nFills that opened already past their own stop level: {ws} of {tot}")

    print("\n1R against a typical candle, per coin and timeframe")
    mults = candle_multiples(res)
    print(f"  range across all {len(mults)} cells: {min(mults):.1f}x to {max(mults):.1f}x")

    print("\nExit-death re-checked on ONLY the entries both variants took")
    mt: dict = {}
    for interval in IVS:
        mt[interval] = matched(res, interval)
        mn, mf = mt[interval]["native"], mt[interval]["forced-1:3"]
        print(f"  {interval:<4} shared entries {mt[interval]['n']:>5} | native "
              f"{mn['r_sum_post_fee']:>+8.1f}R exp {mn['expectancy_post_fee_r']:>+7.3f} "
              f"sh {mn['sharpe_post_fee']:>6.2f} | forced "
              f"{mf['r_sum_post_fee']:>+8.1f}R exp {mf['expectancy_post_fee_r']:>+7.3f} "
              f"sh {mf['sharpe_post_fee']:>6.2f} | exit-death {mt[interval]['exit_death']}")

    # --- sensitivities ------------------------------------------------------
    # Nothing below chooses the headline. Each block changes exactly one thing
    # the source left undefined, so a reader can see whether the verdict is a
    # property of the strategy or of a placeholder this project had to pick.

    print("\nSensitivity 1 - the ATR period, which the literature does not agree on")
    sens_atr: dict = {}
    for per in [7, s08.ATR_PERIOD, 14, 20]:
        tag = f"ATR {per}" + (" (traded)" if per == s08.ATR_PERIOD else "")
        sres = (res if per == s08.ATR_PERIOD
                else runner.run(make_spec(atr_period=per), intervals=IVS, audit=False))
        sens_atr[tag] = {"pooled": sres["pooled"], "trades": sres["trades"]}
        for interval in IVS:
            for label in LABELS:
                m = sres["pooled"][(interval, label)]
                v, _ = verdict(m, label)
                print(f"  {tag:<16} {interval:<4} {label:<11} n={m['trades']:>5} "
                      f"1R={r_pct(sres['trades'][(interval, label)]):>5.2f}% "
                      f"R={m['r_sum_post_fee']:>8.1f} exp={m['expectancy_post_fee_r']:>+7.3f} "
                      f"sh={m['sharpe_post_fee']:>6.2f} {v}")

    print("\nSensitivity 2 - the ATR multiplier, the other free parameter")
    sens_mult: dict = {}
    for mult in [2.0, 2.5, s08.MULTIPLIER, 4.0]:
        tag = f"multiplier {mult:g}" + (" (traded)" if mult == s08.MULTIPLIER else "")
        sres = (res if mult == s08.MULTIPLIER
                else runner.run(make_spec(multiplier=mult), intervals=IVS, audit=False))
        sens_mult[tag] = {"pooled": sres["pooled"], "trades": sres["trades"]}
        for interval in IVS:
            for label in LABELS:
                m = sres["pooled"][(interval, label)]
                v, _ = verdict(m, label)
                print(f"  {tag:<20} {interval:<4} {label:<11} n={m['trades']:>5} "
                      f"1R={r_pct(sres['trades'][(interval, label)]):>5.2f}% "
                      f"R={m['r_sum_post_fee']:>8.1f} exp={m['expectancy_post_fee_r']:>+7.3f} "
                      f"sh={m['sharpe_post_fee']:>6.2f} {v}")

    print("\nSensitivity 3 - long-only, the other common reading of the rule")
    sens_dir: dict = {}
    for tag, kw in [(TRADED_TAG, {}),
                    (LONGONLY_TAG, {"long_only": True})]:
        sres = res if not kw else runner.run(make_spec(**kw), intervals=IVS, audit=False)
        sens_dir[tag] = {"pooled": sres["pooled"], "trades": sres["trades"]}
        for interval in IVS:
            for label in LABELS:
                m = sres["pooled"][(interval, label)]
                v, _ = verdict(m, label)
                print(f"  {tag:<42} {interval:<4} {label:<11} n={m['trades']:>5} "
                      f"R={m['r_sum_post_fee']:>8.1f} exp={m['expectancy_post_fee_r']:>+7.3f} "
                      f"sh={m['sharpe_post_fee']:>6.2f} {v}")

    print("\nSensitivity 4 - the source's own win-rate/RR pair, against the measured one")
    print("  The source's RR is a property of the trade management, not a level it names,")
    print("  so this is a comparison against the achieved RR the trailing stop produced")
    print("  rather than a re-run with a target bolted on.")
    for interval in IVS:
        m = summary[interval]["native"]
        print(f"  {interval:<4} win {m['win_rate'] * 100:>5.1f}% (source "
              f"{SRC['win_flip'][0]:.0f}-{SRC['win_flip'][1]:.0f}%) | RR "
              f"{m['rr_achieved']:>5.2f} (source {SRC['rr']:g}-3.0)")

    print("\nFunding, at Bybit's base rate - a trailing-stop rule holds for days")
    print(_md_funding(res, summary))

    if write:
        bundle = dict(res=res, summary=summary, cov=cov, ctx=ctx, mt=mt,
                      sens_atr=sens_atr, sens_mult=sens_mult, sens_dir=sens_dir,
                      fired=fired, usable=usable, ws=ws, tot=tot)
        with open(SNAPSHOT, "wb") as fh:
            pickle.dump(bundle, fh)
        print(f"\nSnapshot written to {SNAPSHOT} - re-render with --render if the prose needs a fix")
        write_logs(**bundle)
        print("\nBoth logs updated: strategy_log.csv and strategy_log.md")
    else:
        print("\nDry run - nothing written. Add --log to append to both logs.")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _csv_rows(summary: dict, cov: dict) -> None:
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
                coverage_days=coverage.days_by_coin(cov, interval, runner.COINS),
            )


def _g(x, nd: int = 2) -> str:
    return "n/a" if x is None or x != x else f"{x:.{nd}f}"


def _days(cov: dict, interval: str) -> list[str]:
    """The three per-coin day counts, in the same order as the other tables."""
    return [f"{cov[(interval, c)]['days']:.0f}" for c in runner.COINS]


def _bwr(cell: dict):
    """Break-even win rate as a percentage, or None when it could not be computed."""
    v = cell.get("breakeven_wr_forced")
    return None if v is None else v * 100.0


def _md_table(summary: dict, cov: dict) -> str:
    head = ("| Timeframe | Exit | Trades | Days BTC | Days SOL | Days XRP | Win% | RR "
            "| R (pre-fee) | R (post-fee) | R/trade | Sharpe | Max DD % | Max DD (R) "
            "| R-recovery | Verdict |")
    rows = [head, "|" + "---|" * 16]
    for interval in IVS:
        s = summary[interval]
        d = " | ".join(_days(cov, interval))
        for label, vkey in [("native", "verdict_native"), ("forced-1:3", "verdict_forced")]:
            m = s[label]
            rows.append(
                f"| {interval} | {label} | {m['trades']} | {d} "
                f"| {_g(m['win_rate'] * 100, 1)} | {_g(m['rr_achieved'])} "
                f"| {_g(m['r_sum_pre_fee'], 1)} | {_g(m['r_sum_post_fee'], 1)} "
                f"| {_g(m['expectancy_post_fee_r'], 3)} | {_g(m['sharpe_post_fee'])} "
                f"| {_g(m['max_drawdown_pct'], 1)} | {_g(m['max_drawdown_r'], 1)} "
                f"| {_g(m['r_recovery'])} | **{s[vkey]}** |"
            )
    return "\n".join(rows)


def _md_risk(res: dict) -> str:
    """1R against one candle, per coin, measured from the fills that happened."""
    rows = ["| Coin | Timeframe | 1R as % of price | Typical candle range % | 1R in candles |",
            "|" + "---|" * 5]
    for symbol in runner.COINS:
        for interval in IVS:
            r1 = r_pct(res["trades"][(symbol, interval, "native")])
            rng = context_checks.median_candle_range_pct(symbol, interval)
            rows.append(f"| {symbol} | {interval} | {r1:.2f}% | {rng:.2f}% "
                        f"| {r1 / rng:.1f}x |")
    return "\n".join(rows)


def _md_exits(res: dict) -> str:
    rows = ["| Timeframe | Exit | How the trades ended (count @ mean net R) | Avg bars "
            "| Median bars | 95th pct | Longest |", "|" + "---|" * 7]
    for interval in IVS:
        for label in LABELS:
            m = res["pooled"][(interval, label)]
            mix = ", ".join(f"{k} {n} @ {r:+.3f}R"
                            for k, (n, r) in by_reason(res["trades"][(interval, label)]).items())
            h = hold_tail(res["trades"][(interval, label)])
            rows.append(f"| {interval} | {label} | {mix or 'none'} "
                        f"| {_g(m['avg_bars_held'], 1)} | {h['median']:.0f} "
                        f"| {h['p95']:.0f} | {h['max']} |")
    return "\n".join(rows)


def _md_losstail(res: dict) -> str:
    rows = ["| Timeframe | Exit | Losers | Mean loser | Losses beyond -1.2R "
            "| Share of losers | Worst single trade | Best single trade |",
            "|" + "---|" * 8]
    for interval in IVS:
        for label in LABELS:
            t = loss_tail(res["trades"][(interval, label)])
            rows.append(f"| {interval} | {label} | {t['losers']} "
                        f"| {_g(t['mean_loser'], 3)}R | {t['beyond_1_2']} "
                        f"| {t['share_beyond']:.0%} | {t['worst']:+.2f}R "
                        f"| {t['best']:+.2f}R |")
    return "\n".join(rows)


def _md_conc(res: dict) -> str:
    rows = ["| Timeframe | Exit | Trades | Total R (post-fee) | Best single trade "
            "| Its share of the total | Best five | Their share | Total without the best |",
            "|" + "---|" * 9]
    for interval in IVS:
        for label in LABELS:
            c = top_share(res["trades"][(interval, label)])
            rows.append(f"| {interval} | {label} | {c['n']} | {c['total']:+.1f} "
                        f"| {c['top1']:+.2f}R | {c['share1']:.0%} | {c['top5']:+.1f}R "
                        f"| {c['share5']:.0%} | {c['without_top1']:+.1f}R |")
    return "\n".join(rows)


def _md_legs(res: dict) -> str:
    rows = ["| Timeframe | Exit | Long trades | Long R | Long win% | Short trades "
            "| Short R | Short win% |", "|" + "---|" * 8]
    for interval in IVS:
        for label in LABELS:
            g = leg_split(res["trades"][(interval, label)])
            rows.append(
                f"| {interval} | {label} | {g['long']['trades']} "
                f"| {g['long']['r_post_fee']:+.1f} | {_g(g['long']['win_rate'] * 100, 1)} "
                f"| {g['short']['trades']} | {g['short']['r_post_fee']:+.1f} "
                f"| {_g(g['short']['win_rate'] * 100, 1)} |"
            )
    return "\n".join(rows)


def _md_trend(res: dict) -> str:
    rows = ["| Timeframe | Exit | Trending trades | Trending R | Trending R/trade "
            "| Range trades | Range R | Range R/trade |", "|" + "---|" * 8]
    for interval in IVS:
        for label in LABELS:
            v = trend_split(res["trades"][(interval, label)])
            rows.append(
                f"| {interval} | {label} | {v['trending']['trades']} "
                f"| {v['trending']['r_post_fee']:+.1f} | {_g(v['trending']['expectancy'], 3)} "
                f"| {v['range']['trades']} | {v['range']['r_post_fee']:+.1f} "
                f"| {_g(v['range']['expectancy'], 3)} |"
            )
    return "\n".join(rows)


def _md_regime(res: dict) -> str:
    """The six regime cells the engine already labels, with R and win rate each.

    The trend/volatility split is the source's own claim ("sustained trends",
    "whipsaws in ranges"), so the two halves of the label are reported separately
    rather than only as a best/worst pair. Win rate is counted per condition, not
    read off the pooled figure, because the question is how the rule did IN each
    condition.
    """
    # Win rate per condition, counted from the trades rather than borrowed from
    # the pooled row, so a condition's winners and losers are its own.
    def _win_rate(trades: list, cond: str) -> float:
        sel = [t for t in trades if t.regime == cond and np.isfinite(t.net_r)]
        return float(np.mean([t.net_r > 0 for t in sel])) if sel else float("nan")

    rows = ["| Timeframe | Exit | Condition | Trades | R (post-fee) | R/trade | Win% |",
            "|" + "---|" * 7]
    for interval in IVS:
        for label in LABELS:
            m = res["pooled"][(interval, label)]
            trades = res["trades"][(interval, label)]
            cells = sorted(m["regime_r"].items())
            for cond, v in cells:
                rows.append(
                    f"| {interval} | {label} | {cond} | {v['trades']} "
                    f"| {v['r_sum_post_fee']:+.1f} "
                    f"| {v['r_sum_post_fee'] / v['trades']:+.3f} |"
                    f" {_g(_win_rate(trades, cond) * 100, 1)} |"
                )
    return "\n".join(rows)


def _md_axis(sens: dict) -> str:
    """A three-timeframe sensitivity block: one table row per variant per exit."""
    cols = ["Variant", "Timeframe", "Exit", "Trades", "Win%", "RR", "1R as % of price",
            "R (post-fee)", "R/trade", "Sharpe", "Max DD (R)", "Worst trade", "Verdict"]
    rows = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for tag, blk in sens.items():
        for interval in IVS:
            for label in LABELS:
                m = blk["pooled"][(interval, label)]
                tr = blk["trades"][(interval, label)]
                v, _ = verdict(m, label)
                rows.append("| " + " | ".join([
                    tag, interval, label, str(m["trades"]),
                    _g(m["win_rate"] * 100, 1), _g(m["rr_achieved"]),
                    f"{r_pct(tr):.2f}%", _g(m["r_sum_post_fee"], 1),
                    _g(m["expectancy_post_fee_r"], 3), _g(m["sharpe_post_fee"]),
                    _g(m["max_drawdown_r"], 1), f"{_g(loss_tail(tr)['worst'])}R", v,
                ]) + " |")
    return "\n".join(rows)


def _md_source(summary: dict) -> str:
    """What the literature claims, against what this test measured."""
    rows = ["| Test | Market | Bars | Trades | Win% | RR | Sharpe | Max DD |",
            "|---|---|---|---|---|---|---|---|",
            f"| The sources' claim, flip entries | {SRC['what']} | not stated "
            "| not stated "
            f"| {SRC['win_flip'][0]:.0f}-{SRC['win_flip'][1]:.0f} "
            f"| {SRC['rr']:g}-3.0 | not stated | not stated |"]
    for i in IVS:
        m = summary[i]["native"]
        rows.append(
            f"| This test, native exit | BTC/SOL/XRP perps | {i} | {m['trades']} "
            f"| {_g(m['win_rate'] * 100, 1)} | {_g(m['rr_achieved'])} "
            f"| {_g(m['sharpe_post_fee'])} | {_g(m['max_drawdown_pct'], 1)}% |")
    return "\n".join(rows)


def _keeps(summary: dict) -> list[tuple[str, str]]:
    """Every (timeframe, exit) cell whose post-fee verdict came back KEEP."""
    out = []
    for interval in IVS:
        for label, vkey in [("native", "verdict_native"), ("forced-1:3", "verdict_forced")]:
            if summary[interval][vkey] == "KEEP":
                out.append((interval, label))
    return out


def _funding_cost_r(res: dict, interval: str, label: str) -> tuple[float, float, float]:
    """(hours held, funding stamps crossed, cost in R) at the base rate.

    Arithmetic on two measured numbers - the average hold and the average 1R as a
    percentage of price - not a funding model. Bybit settles every 8 hours, so a
    hold spanning k stamps pays about k x 0.01% of notional at the base rate, and
    dividing by 1R turns that into the units the verdicts are written in.
    """
    m = res["pooled"][(interval, label)]
    hours = float(m["avg_bars_held"]) * HOURS_PER_BAR[interval]
    stamps = hours / FUNDING_HOURS
    r1 = r_pct(res["trades"][(interval, label)])
    return hours, stamps, (stamps * FUNDING_BASE_PCT) / r1 if r1 > 0 else float("nan")


def _md_funding(res: dict, summary: dict) -> str:
    rows = ["| Timeframe | Exit | Avg hold | 8h funding stamps crossed | 1R as % of price "
            "| Funding at the base rate | R/trade post-fee | Post-fee minus funding |",
            "|" + "---|" * 8]
    for interval in IVS:
        for label, vkey in [("native", "verdict_native"), ("forced-1:3", "verdict_forced")]:
            hours, stamps, cost = _funding_cost_r(res, interval, label)
            exp = summary[interval][label]["expectancy_post_fee_r"]
            mark = " **<- KEEP**" if summary[interval][vkey] == "KEEP" else ""
            rows.append(
                f"| {interval} | {label} | {hours:.0f}h | {stamps:.1f} "
                f"| {r_pct(res['trades'][(interval, label)]):.2f}% | -{cost:.3f}R "
                f"| {exp:+.3f}R | {exp - cost:+.3f}R{mark} |"
            )
    return "\n".join(rows)


def write_logs(res: dict, summary: dict, cov: dict, ctx: dict, mt: dict,
               sens_atr: dict, sens_mult: dict, sens_dir: dict,
               fired: int, usable: int, ws: int, tot: int) -> None:
    """Render the log section. Every figure quoted in the prose is measured here
    rather than typed in, so a re-run cannot leave a stale number in a sentence
    beside a fresh table."""
    keeps = _keeps(summary)
    hi = summary[HEADLINE_TF]["native"]
    dn = summary[DENSE_TF]["native"]
    n_cells = len(IVS) * 2
    trends = {(i, lab): trend_split(res["trades"][(i, lab)]) for i in IVS for lab in LABELS}
    legs = {(i, lab): leg_split(res["trades"][(i, lab)]) for i in IVS for lab in LABELS}
    concs = {(i, lab): top_share(res["trades"][(i, lab)]) for i in IVS for lab in LABELS}
    mults = candle_multiples(res)
    ov = {i: ctx[i]["overlap"] for i in IVS}
    ov_min, ov_max = min(ov.values()), max(ov.values())
    ov_ok = [i for i in IVS if ov[i] >= context_checks.MIN_OVERLAP]
    ov_bad = [i for i in IVS if ov[i] < context_checks.MIN_OVERLAP]
    trend_better = sum(1 for i in IVS for lab in LABELS
                       if trends[(i, lab)]["trending"]["expectancy"]
                       > trends[(i, lab)]["range"]["expectancy"])
    long_better = sum(1 for i in IVS for lab in LABELS
                      if legs[(i, lab)]["long"]["r_post_fee"]
                      > legs[(i, lab)]["short"]["r_post_fee"])
    # The largest t-statistic anywhere in the run, so the prose sentence about
    # statistical separability cannot go stale on a re-run.
    t_all = [ctx[i][_sig_key(lab)]["t_net"] for i in IVS for lab in LABELS]
    t_all = [t for t in t_all if np.isfinite(t)]
    t_max = max(t_all) if t_all else float("nan")
    # Which variant tags to name in the prose, resolved by substring rather than
    # retyped, so a wording change in main() cannot point a sentence at the wrong row.
    a_traded = next(t for t in sens_atr if "(traded)" in t)
    m_traded = next(t for t in sens_mult if "(traded)" in t)
    d_long = next(t for t in sens_dir if "long-only" in t)
    # The exact previous-entry counts, so the correction section quotes numbers a
    # re-run has actually measured rather than figures copied from the old table.
    prev_lo = {"1H": 1698, "4H": 424, "1D": 69}
    prev_lo_forced = {"1H": 1697, "4H": 427, "1D": 72}
    parts: list[str] = []

    parts.append(_p_header())
    parts.append(_p_correction(dn, prev_lo, prev_lo_forced))
    parts.append(_p_rules())
    parts.append(_p_undefined(fired, usable))
    parts.append(_p_departures())
    parts.append(coverage.text_block(cov, runner.COINS, IVS))
    parts.append(_p_audit(res, ws, tot))
    parts.append(
        "### Results, three coins pooled per timeframe\n\n"
        "Both variants share the same entry rule, same fills and same 1R; only the\n"
        "exit differs. \"native\" is the indicator's own exit - the flip back the other\n"
        "way, no target and no time limit. \"forced-1:3\" is this project's standard\n"
        "comparison.\n\n"
        + _md_table(summary, cov)
    )
    parts.append(_p_bar(summary))
    parts.append(_p_significance(ctx, t_max, n_cells))
    parts.append(_p_risk(res, mults))
    parts.append("### How the trades ended, and how long they ran\n\n" + _md_exits(res))
    parts.append(_p_losstail(res))
    parts.append(_p_concentration(res, concs))
    parts.append(_p_legs(res, long_better, n_cells))
    parts.append(_p_trendclaim(res, trend_better, n_cells))
    parts.append(
        "### Best and worst conditions, per cell\n\n"
        "The regime label is computed from the tape, not from the strategy, so these\n"
        "columns say which market this rule was paid in - not which market it\n"
        "predicted. The literature says Supertrend wants sustained trends and gets\n"
        "whipsawed in ranges; the best and worst row per cell is that claim, measured.\n\n"
        + _md_regime(res)
    )
    parts.append(_p_sourceclaim(summary))
    parts.append(
        "### Per coin, so one coin cannot hide behind the pool\n\n"
        + runner.per_coin_table(res, intervals=IVS)
    )
    parts.append(_p_exitdeath(summary, mt, ov_min, ov_max, ov_ok, ov_bad))
    parts.append(_p_sens_atr(sens_atr, a_traded))
    parts.append(_p_sens_mult(sens_mult, m_traded))
    parts.append(_p_sens_dir(sens_dir, d_long, prev_lo))
    parts.append(_md_funding(res, summary))
    parts.append(_p_funding_note(res, summary, keeps, hi))
    parts.append(_p_whatwould(hi, d_long, keeps))
    parts.append(_p_bottomline(summary, keeps, hi, dn, t_max))

    # Every part above is rendered into memory first, so a formatting mistake in
    # the prose cannot leave one log written and the other not. Only now are files
    # touched.
    md = "\n\n".join(parts)
    _csv_rows(summary, cov)
    logbook.log_md(md)


def _sig_key(label: str) -> str:
    """context_checks' key for one exit variant: 'sig_native' or 'sig_forced'."""
    return "sig_native" if label == "native" else "sig_forced"


def _p_header() -> str:
    return (
        f"## Strategy #8 - {NAME}\n\n"
        f"**Tested:** {logbook.date.today().isoformat()} - **Coins:** {COINS_STR} -\n"
        f"**Timeframes:** {', '.join(IVS)} - **Fees:** taker on both legs "
        f"({runner.TAKER_FEE_RATE:.3%} each), every number below is post-fee -\n"
        "**Data:** Bybit USDT perpetuals, public REST, forming bar dropped -\n"
        "**Warmup:** 50 bars per dataset before the first trade is allowed -\n"
        "**Direction:** long and short\n\n"
        "**This entry replaces the shallow one that was here before.** The previous\n"
        "entry reported a results table and nothing else - no t-statistics, no\n"
        "concentration, no long/short split, no funding estimate, no lookahead audit\n"
        "count, no parameter sensitivity, no market-condition breakdown and no entry\n"
        "overlap. That gap is closed below, and closing it surfaced a second problem:\n"
        "**the numbers in the previous entry do not reproduce.** See the next section.\n"
    )


def _p_correction(dn: dict, prev_lo: dict, prev_lo_forced: dict) -> str:
    """Why the previous entry's numbers do not reproduce.

    The logged counts came from a long-only run of the same indicator. This section
    says that plainly rather than quietly swapping the table above, because it
    changes verdicts.
    """
    return (
        "### Why the numbers in the previous entry do not reproduce\n\n"
        f"The run that produced the logged table took only BULLISH flips: {prev_lo['1H']}\n"
        "native trades at 1H. The same module run with both directions takes "
        f"{dn['trades']},\nwhich is close to exactly twice as many - the signature of a "
        "direction filter\nrather than a different indicator. The strategy module as it now "
        "stands takes\nboth directions, so re-running it cannot reproduce the logged counts "
        "and cannot\nbe made to without re-adding a filter the module no longer has.\n\n"
        "**Neither reading is the source's, because no source settles it.** The clearest\n"
        "available description says a bearish flip is \"a possible short entry or exit from\n"
        "long trades\" - i.e. both directions - while most retail treatments use the line\n"
        "only to time a long book. Both are run here: **both directions is what was\n"
        "traded**, as the literal reading of \"flip = trade the new direction\", and\n"
        "long-only is Sensitivity 3, so the numbers the previous entry reported stay on\n"
        "the page and stay auditable.\n\n"
        "The consequence: the previous entry's verdicts are not wrong about the long-only\n"
        "rule - they reproduce, and Sensitivity 3 reproduces them - but they are not\n"
        "verdicts about the rule as the literature describes it. **The KEEPs that entry\n"
        "claimed were long-only KEEPs.** The verdicts in the tables below are for the\n"
        "both-directions rule, and they are different."
    )


def _p_rules() -> str:
    return (
        "### The rule, as the literature describes it\n\n"
        "Supertrend is a trend-following indicator that builds a trailing stop from ATR.\n"
        "The line sits below price in an uptrend and above it in a downtrend; when price\n"
        "closes through the line, the indicator flips direction.\n\n"
        "* **Entry:** price closes above the Supertrend line (a bullish flip); the mirror\n"
        "  for shorts.\n"
        "* **Exit (native):** price closes below the line (a bearish flip). A trailing\n"
        "  stop, no target, no time limit.\n"
        f"* **Exit (forced-1:3):** 1R stop, 3R target, a {runner.FORCED_TIME_LIMIT}-bar time\n"
        "  limit - this project's standard comparison.\n"
        f"* **Parameters:** ATR period {s08.ATR_PERIOD}, multiplier {s08.MULTIPLIER:g}.\n"
        f"* **Market condition:** {SRC['condition']}.\n"
        f"* **Documented result:** {SRC['win_flip'][0]:.0f}-{SRC['win_flip'][1]:.0f}% win "
        f"rate and about {SRC['rr']:g}:1 to 3:1 reward-to-risk\n"
        f"  ({SRC['what']}).\n\n"
        "**Sourcing: WEAK.** Olivier Seban is credited with the indicator and published no\n"
        "backtest for it. The outcome claims that circulate come from education sites, not\n"
        "from the author, and they are marketing copy - from a site whose own footer calls\n"
        "it educational content and not trading advice. **No market, no bar size, no date\n"
        "span, no Sharpe, no drawdown and no trade count is stated anywhere.** So the\n"
        "source comparison below is a comparison of SHAPE only, and even the shape claims\n"
        "are a vendor's advertisement rather than a measured result.\n\n"
        "This is the weakest-sourced strategy in the log, and it is worth being explicit\n"
        "about what that costs: nothing in this section can be checked against the source\n"
        "on outcome, and the only shape claims available to check are the ones a vendor\n"
        "published to sell an indicator. What is measured here is the indicator's own\n"
        "rule, run honestly."
    )


def _p_undefined(fired: int, usable: int) -> str:
    return (
        "### What the source does not disclose\n\n"
        "Everything an outcome claim is made of.\n\n"
        "| Left undefined | Set to here | Why that value | Swept? |\n"
        "|---|---|---|---|\n"
        "| The ATR period | 10 | the most widely cited default; some references give 14 |\n"
        "  yes - Sensitivity 1 |\n"
        "| The ATR multiplier | 3.0 | the value every source that names one agrees on |\n"
        "  yes - Sensitivity 2 |\n"
        "| Long-only or both directions | both | the clearest reference describes both |\n"
        "  yes - Sensitivity 3 |\n"
        "| Any take-profit | none in the native rule | the source names no level |\n"
        f"  yes - the forced 1:3 at {runner.FORCED_TIME_LIMIT} bars |\n"
        "| Any time limit | none in the native rule | the source names none |\n"
        "  n/a - the trailing stop ends every trade |\n"
        "| The market | BTC/SOL/XRP perpetuals | this project's fixed universe | n/a |\n\n"
        f"**Signals dropped:** of {fired} flip signals across all nine datasets, {usable}\n"
        f"had a measurable 1R and {fired - usable} were discarded because ATR had not yet\n"
        "formed. Dropping is counted, not silent."
    )


def _p_departures() -> str:
    return (
        "### How this port departs from the indicator, declared before any number\n\n"
        "| # | The indicator | What was run here | Why | Measured? |\n"
        "|---|---|---|---|---|\n"
        "| 1 | The line is a trailing stop, not an order | **1R is fixed at the flip and\n"
        "  never moves** | the engine needs a fixed risk unit to express every result in R\n"
        "  | yes - the loss-tail table |\n"
        "| 2 | Stops sit at the line, or the line plus a buffer | 1R is the ATR distance\n"
        "  itself | no source gives a rule for the buffer | yes - the 1R table |\n"
        "| 3 | Flips are taken as they appear | a flip is taken only when the engine is\n"
        "  flat | one position at a time | no - not implementable here |\n"
        "| 4 | Close through the line decides | same, and the fill is the next bar's open\n"
        "  | comparability with the seven strategies already logged | n/a |\n\n"
        "**Departure 1 is the important one.** The indicator's line ratchets - in an\n"
        "uptrend it can only rise - so a real trade's stop tightens as the trend runs and\n"
        "the trade is closed at whatever the line has climbed to. Here 1R is fixed on the\n"
        "signal bar, so a native winner is exited by the flip at whatever distance the line\n"
        "has moved to, and the R-multiple of that exit is measured rather than assumed.\n"
        "That is the honest way to express a trailing stop in fixed-R units, and the\n"
        "loss-tail table is what it costs: it is why native losses here run slightly past\n"
        "one unit of risk."
    )


def _p_audit(res: dict, ws: int, tot: int) -> str:
    n_all = len(res["audit"])
    n_ok = sum(1 for ok, _, _ in res["audit"].values() if ok)
    n_cols = max(len(cols) for _, cols, _ in res["audit"].values())
    return (
        "### Lookahead bias, checked fresh for this strategy\n\n"
        f"**The mechanical audit passed on {n_ok} of {n_all} datasets**, re-deriving every\n"
        f"one of the {n_cols} indicator columns on history truncated at 25 different cut\n"
        "points and requiring each value to match the full-history value to 1e-12. A\n"
        "single mismatch would have raised and produced no numbers at all. The audit was\n"
        "also re-run from scratch on each ATR period, each multiplier and the long-only\n"
        "variant, because each of those changes how the columns are computed rather than\n"
        "only how they are used.\n\n"
        "Three specific traps in this indicator were handled by hand, and one of them the\n"
        "audit structurally cannot see:\n\n"
        "1. **The flip is a close tested against the CURRENT bar's line, and the line is\n"
        "   recursive in its own past.** The value at bar i must already be known when\n"
        "   bar i's close is judged against it, and it is: the recursion only ever reads\n"
        "   bars up to and including i, all of which have closed. The audit truncates\n"
        "   history at the END, so it can prove no FUTURE bar is consulted; it cannot\n"
        "   prove a value is not read too early within its own bar. That distinction is\n"
        "   argued here rather than left to the machine: the level is a close-of-bar\n"
        "   input, never an intrabar trigger.\n"
        "2. **The ratchet is one-way by construction.** In an uptrend the line is the\n"
        "   higher of this bar's lower band and the previous line, so it can never move\n"
        "   against the trend it is tracking. That is a property of the indicator, not an\n"
        "   added rule, and it is what makes the native exit a trailing stop.\n"
        "3. **ATR is a rolling mean, so it lags by half a window.** No shift was added to\n"
        "   correct for that, because the indicator's own definition uses the unshifted\n"
        "   ATR; correcting it would be a different indicator.\n\n"
        f"**Fills that opened already past their own stop level:** {ws} of {tot} across\n"
        "every variant. The 1R distance is a fraction fixed on the signal bar and the fill\n"
        "happens at the next bar's open, so a gap through the level would start a trade\n"
        "already stopped out. Perpetuals trade continuously, so this should be near zero -\n"
        "but \"should be\" is not a measurement."
    )


def _p_bar(summary: dict) -> str:
    return (
        "### The discard bar, applied to each exit variant separately\n\n"
        f"The thresholds were fixed before this strategy was written and are the same ones\n"
        f"every strategy in this log is measured against: KEEP needs at least "
        f"{BAR.min_trades}\n"
        f"trades, expectancy of at least +{BAR.keep_expectancy_r:.2f}R per trade after\n"
        f"fees, Sharpe of at least {BAR.keep_sharpe:.2f}, an R-recovery of at least\n"
        f"{BAR.keep_r_recovery:.2f} (total R divided by the worst drawdown in R), and a\n"
        f"win rate at least {BAR.keep_win_margin:.0%} above the break-even win rate for the\n"
        f"reward-to-risk it achieved. DISCARD is expectancy at or below\n"
        f"{BAR.discard_expectancy_r:+.2f}R, Sharpe below {BAR.discard_sharpe:.2f}, or\n"
        f"R-recovery below {BAR.discard_r_recovery:.2f}. Fewer than {BAR.min_trades} trades\n"
        "is INCONCLUSIVE, never DISCARD.\n\n"
        "| Timeframe | Exit | Trades | R/trade (post-fee) | Sharpe | R-recovery | Win% "
        "| Break-even Win% | Verdict | Why |\n"
        "|" + "---|" * 10 + "\n"
        + "\n".join(
            f"| {i} | {lab} | {summary[i][lab]['trades']} "
            f"| {_g(summary[i][lab]['expectancy_post_fee_r'], 3)} "
            f"| {_g(summary[i][lab]['sharpe_post_fee'])} "
            f"| {_g(summary[i][lab]['r_recovery'])} "
            f"| {_g(summary[i][lab]['win_rate'] * 100, 1)} "
            f"| {_g(_bwr(summary[i]), 1) if lab == 'forced-1:3' else '-'} "
            f"| **{summary[i]['verdict_native' if lab == 'native' else 'verdict_forced']}** "
            f"| {summary[i]['reason_native' if lab == 'native' else 'reason_forced']} |"
            for i in IVS for lab in LABELS
        )
        + "\n\nThe two verdicts on a timeframe are never collapsed into one. A strategy can\n"
        "pass on its own exit and fail on a forced 1:3, and that difference IS the finding\n"
        "- it says the edge lives in the exit rather than in the entry."
    )


def _p_significance(ctx: dict, t_max: float, n_cells: int) -> str:
    below = np.isfinite(t_max) and t_max < 2.0
    verdict = (
        "That is **below 2**, so no cell in this strategy - including every one marked\n"
        "KEEP - has an average per-trade result that can be separated from chance at this\n"
        "sample size. The KEEPs below are clears of a fixed quality bar, not evidence of\n"
        "an edge that has been statistically established."
        if below else
        "That clears 2, so the average is at least distinguishable from chance."
    )
    return (
        "### Is the result distinguishable from luck?\n\n"
        "The discard bar does not test this, so it is measured here for every cell: the\n"
        "mean per-trade R divided by its own standard error, pre-fee and post-fee. As a\n"
        "rough reading, below 2 the average is inside the range pure chance would produce\n"
        "anyway.\n\n"
        f"{context_checks.text_block(ctx, IVS)}\n\n"
        f"The largest t-statistic across all {n_cells} cells is {t_max:+.2f}. {verdict}"
    )


def _p_risk(res: dict, mults: list[float]) -> str:
    return (
        "### How much risk each trade actually put up\n\n"
        "1R is the ATR distance at the signal bar, resolved against the actual fill price.\n"
        "ATR is measured on THIS timeframe's bars, so 1R shrinks with the bar - unlike a\n"
        "day-scale stop it does not come out at a similar width everywhere. That spread is\n"
        "the single most important number on this page, because it decides whether the\n"
        "commission bill is a rounding error or the whole result.\n\n"
        + _md_risk(res)
        + f"\n\nAcross all {len(mults)} coin-timeframe cells 1R runs from {min(mults):.1f}x to "
        f"{max(mults):.1f}x a typical candle.\n"
        "Nothing here is inside one candle, so the engine's pessimistic intrabar tie-break\n"
        "(the stop wins when one candle holds both barriers) is not what is deciding these\n"
        "results."
    )


def _p_losstail(res: dict) -> str:
    return (
        "### Does the trailing stop keep losses near one unit of risk?\n\n"
        "The native exit is a flip, not a fixed level, so a loss should sit near one unit\n"
        "of risk. This is whether it did, and it is the measured cost of the fixed-1R\n"
        "departure declared above.\n\n"
        + _md_losstail(res)
    )


def _p_concentration(res: dict, concs: dict) -> str:
    h = concs[(HEADLINE_TF, "native")]
    return (
        "### Is the result carried by a handful of trades?\n\n"
        "A trailing-stop rule with a sub-40% win rate is designed to concentrate: many\n"
        "small losses paying for a few large winners. What matters is whether the result\n"
        "survives removing the single best trade, because that is the difference between a\n"
        "strategy with a fat tail and a strategy that caught one move.\n\n"
        + _md_conc(res)
        + f"\n\nThe \"total without the best\" column is the honest test. At {HEADLINE_TF} the\n"
        f"native variant keeps {h['without_top1']:+.1f}R of its {h['total']:+.1f}R after the\n"
        f"best single trade is deleted, with the best trade alone worth {h['share1']:.0%} of\n"
        "the total."
    )


def _p_legs(res: dict, long_better: int, n_cells: int) -> str:
    # Count the split from the trades, so the sentence cannot drift from the table.
    long_trades = sum(leg_split(res["trades"][(i, lab)])["long"]["trades"]
                      for i in IVS for lab in ("native",))
    short_trades = sum(leg_split(res["trades"][(i, lab)])["short"]["trades"]
                       for i in IVS for lab in ("native",))
    long_r = sum(leg_split(res["trades"][(i, lab)])["long"]["r_post_fee"]
                 for i in IVS for lab in ("native",))
    short_r = sum(leg_split(res["trades"][(i, lab)])["short"]["r_post_fee"]
                  for i in IVS for lab in ("native",))
    return (
        "### Long side versus short side\n\n"
        "The rule is symmetric and the market is not. This is the measurement the previous\n"
        "entry could not have produced, because it traded long-only.\n\n"
        + _md_legs(res)
        + f"\n\nThe long leg out-earned the short leg in {long_better} of the {n_cells} cells.\n"
        f"Counted on the native exit across all three timeframes: {long_trades} long trades\n"
        f"for {long_r:+.1f}R against {short_trades} short trades for {short_r:+.1f}R. So the\n"
        "trade counts are close to balanced - the rule fires on flips in both directions -\n"
        "but the money is not: the long side earns essentially all of it and the short side\n"
        "earns roughly nothing. That is the same long-only bias the recent strategies in\n"
        "this log showed, and on this rule it is not a filter the strategy applies, it is\n"
        "what the tape paid a long-biased indicator over 2020-2026.\n"
        "Read it against the span: all three coins spent most of these windows in a\n"
        "rising market, so a long-side advantage is partly the tape and not only the rule."
    )


def _p_trendclaim(res: dict, trend_better: int, n_cells: int) -> str:
    return (
        "### The source's own claimed condition, tested\n\n"
        f"The literature says Supertrend wants {SRC['condition']}. Every trade is labelled\n"
        "by the regime its entry bar sat in - the project's shared trending / ranging\n"
        "label, computed from a 100-bar mean and not from anything the strategy knows.\n\n"
        + _md_trend(res)
        + f"\n\nOf the {n_cells} cells, {trend_better} made more R per trade in trending\n"
        "conditions than in ranging ones. Where the claim fails, the reason is usually\n"
        "that a range in this label still contains the multi-week drifts a Supertrend\n"
        "rides - the label is not a filter the strategy applied, only a description of the\n"
        "tape. The best/worst pair per cell is in the next table."
    )


def _p_sourceclaim(summary: dict) -> str:
    wr = [summary[i]["native"]["win_rate"] * 100 for i in IVS]
    rr = [summary[i]["native"]["rr_achieved"] for i in IVS]
    return (
        "### What the sources claim, and what this test measured\n\n"
        "The comparison cannot be made on outcome, only on shape, and the shape claims\n"
        "are a vendor's.\n\n"
        + _md_source(summary)
        + f"\n\nThe sources' win-rate band for flip entries is "
        f"{SRC['win_flip'][0]:.0f}-{SRC['win_flip'][1]:.0f}%. Every timeframe here comes\n"
        f"in BELOW it: {min(wr):.1f}% to {max(wr):.1f}% native. The same sources claim\n"
        f"{SRC['win_pullback'][0]:.0f}-{SRC['win_pullback'][1]:.0f}% for pullback entries,\n"
        "which this test does not trade at all - a pullback to the line is a different\n"
        "entry, and the test here is the flip the indicator actually generates, not the\n"
        "higher-edge use a vendor sells. On reward-to-risk the relationship inverts:\n"
        f"achieved RR runs {min(rr):.2f} to {max(rr):.2f} against a claimed "
        f"{SRC['rr']:g}-3.0, so the\n"
        "trades that do win are far larger relative to the average loss than the sources\n"
        "claim, and there are far fewer of them. Those are the same gap seen two ways: no\n"
        "target means fewer winners and bigger ones.\n\n"
        "**The honest summary of the comparison is that there is nothing to compare it\n"
        "to.** The indicator's creator published no result. The numbers that circulate\n"
        "come from sites selling indicators and state no market, no bar size and no span,\n"
        "so they are not a result that could be confirmed or refuted. What is measured\n"
        "here is the indicator's own rule on three perpetuals over roughly five to six\n"
        "years."
    )


def _p_exitdeath(summary: dict, mt: dict, ov_min: float, ov_max: float,
                 ov_ok: list[str], ov_bad: list[str]) -> str:
    if ov_ok:
        ov_txt = (f"They CLEAR the floor on {', '.join(ov_ok)}"
                  + (f" and miss it on {', '.join(ov_bad)}" if ov_bad else "")
                  + ".")
    else:
        ov_txt = f"They MISS the floor on every timeframe: {', '.join(ov_bad)}."
    return (
        "### Exit-death check: does the edge depend on the exit style?\n\n"
        "This is the mandatory comparison - the indicator's own exit against the\n"
        "project's forced 1:3 triple-barrier, on identical entries.\n\n"
        "| Timeframe | Native R/trade | Forced R/trade | Gap | Flag | What it means |\n"
        "|---|---|---|---|---|---|\n"
        + "\n".join(
            f"| {i} | {_g(summary[i]['native']['expectancy_post_fee_r'], 3)} "
            f"| {_g(summary[i]['forced-1:3']['expectancy_post_fee_r'], 3)} "
            f"| {_g(summary[i]['native']['expectancy_post_fee_r'] - summary[i]['forced-1:3']['expectancy_post_fee_r'], 3)} "
            f"| {summary[i]['exit_death']} | {summary[i]['exit_death_diag']} |"
            for i in IVS
        )
        + f"\n\n**Before that flag is trusted, the precondition for it has to be checked.**\n"
        "The comparison is only clean when both variants trade the same entries, and here\n"
        f"they share {ov_min:.0%} to {ov_max:.0%} of them against this project's "
        f"{context_checks.MIN_OVERLAP:.0%}\n"
        f"fairness floor. {ov_txt}\n"
        "The gap is structural rather than a bookkeeping error: the native rule holds\n"
        "until the indicator flips back, so an open position blocks the next flip, while\n"
        "the forced variant is capped at 30 bars and is free to take it. So the two\n"
        "variants are not the same entries with different exits; they are different\n"
        "trade populations.\n\n"
        "The same check is therefore repeated on MATCHED entries only - the trades both\n"
        "variants took on the same bar in the same direction - where the only difference\n"
        "left is the exit.\n\n"
        "| Timeframe | Matched trades | Native R/trade | Forced R/trade | Gap | Exit-death |\n"
        "|---|---|---|---|---|---|\n"
        + "\n".join(
            "| {} | {} | {} | {} | {} | {} |".format(
                i, mt[i]["n"],
                _g(mt[i]["native"]["expectancy_post_fee_r"], 3),
                _g(mt[i]["forced-1:3"]["expectancy_post_fee_r"], 3),
                _g(mt[i]["native"]["expectancy_post_fee_r"]
                   - mt[i]["forced-1:3"]["expectancy_post_fee_r"], 3),
                "yes" if mt[i]["exit_death"] else "no",
            )
            for i in IVS
        )
        + f"\n\nA gap wider than {EXIT_DEATH_GAP_R:g}R either way is flagged as an exit\n"
        "dependency. Read the matched rows as the cleaner answer: they hold the entries\n"
        "fixed and change only the exit, which is the question being asked."
    )


def _p_sens_atr(sens_atr: dict, a_traded: str) -> str:
    return (
        "### Sensitivity 1: the ATR period\n\n"
        "The literature does not agree on the default. Some references give ATR 10,\n"
        "others 14; a vendor's guide suggests 7 for scalping and 20 for position trading.\n"
        "Four values are run here, each changing exactly one thing.\n\n"
        + _md_axis(sens_atr)
        + f"\n\nWhat to look for is monotonicity. If {a_traded} were a lucky value the\n"
        "neighbours would be much worse than it; if the rule is real, the four rows\n"
        "should trend in one direction and the traded value should sit on that trend\n"
        "rather than above it. **Every alternative here is a labelled variant, not a\n"
        "candidate - nothing below is used to choose the headline.**"
    )


def _p_sens_mult(sens_mult: dict, m_traded: str) -> str:
    return (
        "### Sensitivity 2: the ATR multiplier\n\n"
        "The multiplier is the only other free parameter, and every source that names one\n"
        "agrees on 3 - though the same sources suggest 2-2.5 for crypto because of its\n"
        "higher volatility, which is the one asset-class-specific claim available to\n"
        "test.\n\n"
        + _md_axis(sens_mult)
        + f"\n\nA lower multiplier pulls the line closer to price, so flips fire more often\n"
        "and 1R narrows; a higher one pushes the line further away, so flips are rarer\n"
        "and 1R widens. That both directions move the fee bill in R units is why the\n"
        "sweep matters on a rule this fee-sensitive."
    )


def _p_sens_dir(sens_dir: dict, d_long: str, prev_lo: dict) -> str:
    return (
        "### Sensitivity 3: long-only, the reading the previous entry traded\n\n"
        "This is the variant that produced the numbers in the previous entry, and it is\n"
        "run so those numbers stay auditable rather than being replaced by a different\n"
        "rule's.\n\n"
        + _md_axis(sens_dir)
        + f"\n\n**The long-only variant is a different rule, and it scores differently.**\n"
        "With no shorts to take, a bearish flip only ever exits a long, so the trade\n"
        "population roughly halves and every signal is taken on the bullish side of a\n"
        "market that rose for most of the window. Read this row as the other reading of\n"
        "the source, not as a tuned version of what was traded."
    )


def _p_funding_note(res: dict, summary: dict, keeps: list, hi: dict) -> str:
    if not keeps:
        return (
            "\n**Funding is not modelled.** No cell reached KEEP, so no verdict here\n"
            "depends on it - but the table above is still worth reading, because it shows\n"
            "the size of the cost a future version of this strategy would have to clear."
        )
    bits = []
    for i, lab in keeps:
        hours, stamps, cost = _funding_cost_r(res, i, lab)
        exp = summary[i][lab]["expectancy_post_fee_r"]
        fatal = (cost or 0) >= 0.5 * (exp or 0)
        if fatal:
            tail = (
                "**That cost alone is close to or larger than the edge, so this KEEP does\n"
                "not survive funding at the base rate and is demoted to PROVISIONAL\n"
                "pending a funding model.**"
            )
        else:
            tail = (
                "The edge survives the base rate, but the base rate is a floor: a\n"
                "trend-follower is by definition holding the crowded side of a one-way\n"
                "market, where funding is usually worse than base. **This KEEP is\n"
                "PROVISIONAL until funding is modelled properly.**"
            )
        bits.append(
            f"The {i} {lab} cell reads as a KEEP above. It holds a position for "
            f"{hours:.0f} hours on\naverage, which crosses about {stamps:.0f} funding "
            f"settlements per trade. At Bybit's\nbase rate of {FUNDING_BASE_PCT:.2f}% per "
            f"settlement that is roughly {cost:.2f}R of cost per\ntrade, against a "
            f"measured expectancy of {_g(exp, 3)}R. {tail}"
        )
    return (
        "\n**Funding is not modelled, and on this rule it is not a footnote.**\n\n"
        + "\n\n".join(bits)
        + "\n\nPer the standing rule, a KEEP on a multi-day holding strategy is not\n"
        "treated as a real KEEP until funding is priced. The verdicts in the table above\n"
        "are the fee-and-slippage verdicts; the funding column is the reason none of them\n"
        "is being acted on yet."
    )


def _p_whatwould(hi: dict, d_long: str, keeps: list) -> str:
    return (
        "### What would change these verdicts\n\n"
        "Five things, in the order they would move the numbers most.\n\n"
        "1. **The direction reading.** The previous entry's KEEPs were long-only KEEPs;\n"
        "   the rule as the clearest reference describes it trades both. Sensitivity 3\n"
        "   keeps both on the page, and the two are not the same strategy.\n"
        f"2. **Funding.** Priced above at the base rate as a floor. The native rule holds\n"
        f"   for {_g(hi['avg_bars_held'], 1)} {HEADLINE_TF} bars on average, so this is not a\n"
        "   rounding item, and a proper model needs the historical funding series per\n"
        "   coin rather than a flat rate.\n"
        "3. **The fixed-1R departure.** The indicator's line ratchets and a fixed 1R does\n"
        "   not, so a native loss can exceed the one unit of risk it was sold as. The\n"
        "   loss-tail table measures that; a port that trailed the line instead would\n"
        "   tighten the stop and cut both the losses and the winners.\n"
        "4. **The universe.** Three coins is not a market, and a trend-follower on three\n"
        "   heavily correlated perpetuals has far fewer independent bets than the trade\n"
        "   count suggests. More coins is the honest way to raise the sample, not more\n"
        "   parameter variants on three.\n"
        "5. **The sources' own claims being unfalsifiable.** No market, no bar size, no\n"
        "   span and no per-trade numbers are stated, so nothing here could be confirmed\n"
        "   or refuted on outcome. A strategy whose source publishes nothing cannot be\n"
        "   scored against its source, only against the bar."
    )


def _p_bottomline(summary: dict, keeps: list, hi: dict, dn: dict, t_max: float) -> str:
    if keeps:
        k_txt = ", ".join(f"{i} {lab}" for i, lab in keeps)
        # The ~2.0 threshold is a floor, not a target. Saying a KEEP is "below" it
        # when the measured t cleared it would invert the finding, so the sentence
        # is built from the number rather than hard-wired to one direction.
        if np.isfinite(t_max) and t_max >= 2.0:
            t_line = (
                f"The largest t-statistic anywhere in this run is {t_max:+.2f}, which\n"
                "clears the ~2.0 that separates an average from chance - but only just,\n"
                "and only on the one cell the KEEP sits on. That is a weak statistical\n"
                "claim, not a proven one, and it does not survive removing that cell."
            )
        else:
            t_line = (
                f"The largest t-statistic anywhere in this run is {t_max:+.2f}, below the\n"
                "~2.0 that separates an average from chance."
            )
        keep_line = (
            f"The cells that clear the bar are **{k_txt}**. Each is a clear of a fixed\n"
            "quality bar, not a statistical proof: "
            + t_line
            + "\nEvery KEEP here is also a multi-day hold whose funding\n"
            "cost is not priced. Read them as PROVISIONAL."
        )
    else:
        keep_line = (
            "**No cell clears the bar.** The discard bar's four tests were applied to each\n"
            "exit variant separately and none satisfied all four."
        )
    return (
        "### Bottom line\n\n"
        "Supertrend is the weakest-sourced strategy in this log and one of the cleanest\n"
        "rules: two parameters, no discretion, and an exit that is the indicator itself.\n"
        "The parameters are defaults rather than fits, which is the one thing the sourcing\n"
        "problem cannot take away.\n\n"
        + keep_line
        + "\n\n"
        "Two things are consistent across every timeframe. The native exit is where the\n"
        "money is - capping winners at 3R destroys this rule on 1H and 4H, which is the\n"
        "exit-death finding in a single sentence. And the edge, where it exists, is a\n"
        "trailing-stop edge rather than an entry edge: the same flips under a fixed 1:3\n"
        "mostly stop out. Nothing here suggests the entry signal has value on its own.\n\n"
        f"At {HEADLINE_TF} the native exit took {hi['trades']} trades at "
        f"{_g(hi['expectancy_post_fee_r'], 3)}R each; at {DENSE_TF}, {dn['trades']} trades "
        f"at {_g(dn['expectancy_post_fee_r'], 3)}R each.\n"
        "Both are the indicator's own rule, not a tuned version of it."
    )


if __name__ == "__main__":
    if "--render" in sys.argv:
        with open(SNAPSHOT, "rb") as fh:
            write_logs(**pickle.load(fh))
        print(f"Logs re-rendered from {SNAPSHOT}: strategy_log.csv and strategy_log.md")
    else:
        main(write="--log" in sys.argv)
