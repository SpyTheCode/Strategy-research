"""Run Strategy #6 - Ichimoku Cloud trend trading, and log it.

Usage:  .venv\\Scripts\\python.exe src\\run_s06.py [--log]
"""

from __future__ import annotations

import sys

import numpy as np

import bybit_data as bd
import context_checks
import lookahead_check
import logbook
import runner
import s06_ichimoku as s06
from discard_bar import BAR, exit_death, verdict
from harness import metrics

NAME = ("Ichimoku Cloud trend trading (close beyond the 9/26/52 cloud with the "
        "conversion line past the base line, 1R to the far cloud edge, stop "
        "trails the cloud)")
COINS_STR = "BTCUSDT+SOLUSDT+XRPUSDT"

IVS = ["1H", "4H", "6H", "1D"]

# 1H is the headline for the single-timeframe sensitivities: the source states no
# bar size at all, so there is no timeframe to match, and 1H simply has the most
# trades and therefore the least noise. 1D is reported beside it because the
# daily chart is the indicator's own home - Hosoda designed it on daily bars -
# so it is the closest thing to a conventional reading of the rule.
HEADLINE_TF = "1H"
CONVENTIONAL_TF = "1D"

# The source's own claim. Note how little of it there is: a reward-to-risk, a
# RANGE of win rates, and the reason for the range. No market, no bar size, no
# Sharpe, no drawdown, no trade count, no date span.
SRC = {"what": "market and bar size NOT stated (Pineify)",
       "rr": s06.SOURCE_RR, "win_lo": 39.0, "win_hi": 58.0,
       "sharpe": None, "dd": None}


def make_spec(conv: int = s06.CONV, base: int = s06.BASE,
              span_b: int = s06.SPAN_B, disp: int = s06.DISP,
              risk: str = s06.RISK_CLOUD, chikou: bool = False,
              on_cross: bool = True, target_r: float | None = None,
              signal_exit: bool = False) -> runner.StrategySpec:
    bits = [f"{conv}/{base}/{span_b}", f"disp={disp}"]
    if risk != s06.RISK_CLOUD:
        bits.append(f"1R={risk}")
    if chikou:
        bits.append("chikou-confirm")
    if not on_cross:
        bits.append("state-entry")
    if target_r is not None:
        bits.append(f"target={target_r:g}R")
    if signal_exit:
        bits.append("signal-exit")
    return runner.StrategySpec(
        name=f"{NAME} [{' '.join(bits)}]",
        add_indicators=lambda df: s06.add_indicators(
            df, conv, base, span_b, disp, risk, chikou),
        entry=lambda df: s06.entry(df, on_cross),
        native_exit=lambda df: s06.native_exit(df, target_r, signal_exit),
        warmup=s06.warmup_for(conv, base, span_b, disp),
        native_time_limit=None,   # the source names no time limit
    )


def show_audit(symbol: str = "BTCUSDT", interval: str = HEADLINE_TF) -> bool:
    """Print the lookahead proof on one dataset so it is visible, not asserted."""
    df = bd.drop_forming_bar(bd.load(symbol, interval), interval)
    raw = df[[c for c in df.columns if c in lookahead_check.RAW]].copy()
    return lookahead_check.report(
        f"{NAME} on {symbol} {interval}", raw, s06.add_indicators,
        first_cut=max(300, s06.warmup_for() + 50),
    )


# ---------------------------------------------------------------------------
# Measurements this strategy needs that the shared code does not provide
# ---------------------------------------------------------------------------

def r_pct(trades) -> float:
    """Median 1R as a percentage of the entry price, measured from real fills.

    Not computed from the indicator: taken from the trades that actually
    happened, so it is the risk that was really carried.
    """
    v = [abs(t.risk_per_unit) / t.entry_price * 100.0
         for t in trades if t.entry_price and np.isfinite(t.risk_per_unit)]
    return float(np.median(v)) if v else float("nan")


def wrong_side(trades) -> int:
    """Fills that landed on the far side of their own stop level.

    The 1R level is a PRICE fixed on the signal bar and the fill happens at the
    next bar's open, so a gap through the level would start the trade already
    stopped. Crypto perpetuals trade continuously so this should be near zero -
    but "should be" is not a measurement, so it is counted.
    """
    return sum(1 for t in trades
               if (t.entry_price - t.initial_stop) * t.direction <= 0)


def dropped_signals(risk: str, conv: int = s06.CONV, base: int = s06.BASE,
                    span_b: int = s06.SPAN_B, disp: int = s06.DISP) -> tuple[int, int]:
    """(signals fired, signals unusable) for one reading of the source's stop.

    A stop on the wrong side of the entry is not a stop, so `entry()` refuses it.
    Under the traded reading that can never happen; under the base-line reading it
    happens often, and the two readings are only comparable if the size of that
    difference is on the page. Counted straight off the indicator columns, across
    every coin and timeframe, so it does not depend on which signals a run
    happened to be flat for.
    """
    fired = usable = 0
    for symbol in runner.COINS:
        for interval in IVS:
            df = bd.drop_forming_bar(bd.load(symbol, interval), interval)
            d = s06.add_indicators(df, conv, base, span_b, disp, risk)
            ok_l = d["long_entry"] & (d["ich_stop_long"] < d["close"])
            ok_s = d["short_entry"] & (d["ich_stop_short"] > d["close"])
            fired += int(d["long_entry"].sum() + d["short_entry"].sum())
            usable += int(ok_l.sum() + ok_s.sum())
    return fired, fired - usable


def loss_tail(trades) -> dict:
    """What the loosening stop costs: losses bigger than the 1R they were sold as.

    The stop is re-read from the cloud every bar and no ratchet is added, so the
    level can move AWAY from the trade. When it does, the loss exceeds one unit of
    risk. This measures how often and how badly, which is the only honest way to
    quote R-based numbers from a stop that is allowed to drift.
    """
    net = np.array([t.net_r for t in trades if np.isfinite(t.net_r)])
    losers = net[net <= 0]
    return {
        "worst": float(net.min()) if len(net) else float("nan"),
        "losers": int(len(losers)),
        "beyond_1_2": int((losers < -1.2).sum()),
        "share_beyond": float((losers < -1.2).mean()) if len(losers) else float("nan"),
        "mean_loser": float(losers.mean()) if len(losers) else float("nan"),
        "best": float(net.max()) if len(net) else float("nan"),
    }


def hold_tail(trades) -> dict:
    """How long the longest trades ran. A trend rule with no time limit needs this."""
    b = np.array([t.bars_held for t in trades]) if trades else np.array([0])
    return {"median": float(np.median(b)), "p95": float(np.percentile(b, 95)),
            "max": int(b.max())}


def top_share(trades) -> dict:
    """How much of the whole result came from a handful of trades.

    The discard bar does not test this, and on a rule with a 25% win rate and no
    take-profit it is the first thing that should be checked: a trailing stop that
    is allowed to run produces a few enormous winners, and if the total is one
    trade wearing a trench coat then the average R per trade is not a number
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

    The source says this rule wants "sustained trends" and "gets chopped up in
    ranges". The regime label is two halves joined by a slash (trend / volatility);
    this keeps only the trend half, so the claim is checked directly instead of
    being read off a nine-cell table. "trending" pools up and down, because the
    rule is symmetric and the claim is about trend, not direction.
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
    signal, and here the gap is extreme: the native rule holds until a trailing
    stop is hit while the forced variant is capped at 30 bars, so the forced run
    takes entries the native run was still holding through. Comparing the full
    runs then mixes two effects - the exit, and a different set of trades. This
    strips the second one out. It is the fair exit-death comparison; the standard
    one is reported beside it because that is the project's defined check.
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

    The shared context check measures ONE stop width against every timeframe's
    candles, which is a fine project-wide sanity check but wrong to quote here:
    this rule's 1R is the distance to a cloud edge built from 52 bars of range, so
    it grows with the bar and the per-cell ratio is the honest figure.
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
    print(f"Strategy #6 - {NAME}")
    print("=" * 78)
    print("Source parameters NOT disclosed: all four of them (9/26/52/26 here), plus")
    print("the take-profit. The take-profit is left out of the native rule on purpose -")
    print("one of the source's two suggestions is the lagging span, which as a price is")
    print("the close 26 bars in the future, and the other names no multiple.")

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

    print("\nHow the trades ended (three coins pooled), and how long they ran")
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            m = res["pooled"][(interval, label)]
            mix = ", ".join(f"{k} {n} @ {r:+.3f}R"
                            for k, (n, r) in by_reason(res["trades"][(interval, label)]).items())
            h = hold_tail(res["trades"][(interval, label)])
            print(f"  {interval:<4} {label:<11} {mix or 'none'} | avg bars "
                  f"{m['avg_bars_held']:.1f} | median {h['median']:.0f} "
                  f"| 95th pct {h['p95']:.0f} | longest {h['max']}")

    print("\nWhat the loosening stop costs: losses bigger than the 1R they were sold as")
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            t = loss_tail(res["trades"][(interval, label)])
            print(f"  {interval:<4} {label:<11} losers {t['losers']:>5} | "
                  f"mean loser {t['mean_loser']:>+7.3f}R | beyond -1.2R "
                  f"{t['beyond_1_2']:>5} ({t['share_beyond']:>4.0%}) | worst "
                  f"{t['worst']:>+7.2f}R | best {t['best']:>+7.2f}R")

    print("\nHow concentrated the result is - share of the total from the best trades")
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            c = top_share(res["trades"][(interval, label)])
            print(f"  {interval:<4} {label:<11} total {c['total']:>+8.1f}R | best "
                  f"{c['top1']:>+8.2f}R ({c['share1']:>5.0%}) | best five "
                  f"{c['top5']:>+8.1f}R ({c['share5']:>5.0%}) | without the best "
                  f"{c['without_top1']:>+8.1f}R")

    print("\nThe source's own claimed condition: sustained trends, chopped up in ranges")
    print(f"  {'tf':<5} {'exit':<11} {'trending n':>11} {'trending R':>11} "
          f"{'R/trade':>9} {'range n':>9} {'range R':>9} {'R/trade':>9}")
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            v = trend_split(res["trades"][(interval, label)])
            print(f"  {interval:<5} {label:<11} {v['trending']['trades']:>11} "
                  f"{v['trending']['r_post_fee']:>+11.1f} {v['trending']['expectancy']:>+9.3f} "
                  f"{v['range']['trades']:>9} {v['range']['r_post_fee']:>+9.1f} "
                  f"{v['range']['expectancy']:>+9.3f}")

    print("\nLong leg vs short leg")
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            g = leg_split(res["trades"][(interval, label)])
            print(f"  {interval:<4} {label:<11} long {g['long']['trades']:>5} trades "
                  f"{g['long']['r_post_fee']:>+8.1f}R | short {g['short']['trades']:>5} trades "
                  f"{g['short']['r_post_fee']:>+8.1f}R")

    print("\nAgainst the source's own claim - which states no market and no bar size")
    print(f"  {'':<44} {'trades':>7} {'win%':>7} {'RR':>6} {'Sharpe':>7} {'maxDD%':>7}")
    src_win = f"{SRC['win_lo']:.0f}-{SRC['win_hi']:.0f}"
    print(f"  {SRC['what']:<44} {'n/a':>7} {src_win:>7} {SRC['rr']:>6.1f} "
          f"{'n/a':>7} {'n/a':>7}")
    for interval in IVS:
        m = summary[interval]["native"]
        print(f"  {'this test, native exit, ' + interval:<44} {m['trades']:>7} "
              f"{m['win_rate'] * 100:>7.1f} {m['rr_achieved']:>6.2f} "
              f"{m['sharpe_post_fee']:>7.2f} {m['max_drawdown_pct']:>7.1f}")

    print("\nPer coin, per timeframe, per exit")
    print(runner.per_coin_table(res, intervals=IVS))

    r1_pct = float(np.median([r_pct(res["trades"][(s, HEADLINE_TF, "native")])
                              for s in runner.COINS]))
    ctx = context_checks.summarise(res, runner.COINS, IVS)
    print("\nContext checks - is the test fair, and is the result separable from luck")
    print(context_checks.text_block(ctx, IVS))

    ws = sum(wrong_side(res["trades"][(i, lab)])
             for i in IVS for lab in ["native", "forced-1:3"])
    tot = sum(len(res["trades"][(i, lab)]) for i in IVS for lab in ["native", "forced-1:3"])
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
    # Nothing below is used to choose the headline. Each row changes exactly one
    # thing the source left undefined, so a reader can see whether the verdict is
    # a property of the strategy or of a placeholder.
    print("\nSensitivity 1 - the whole parameter set, which the source itself blames")
    sens_set: dict = {}
    for tag, (c, b, sb, dp) in s06.SETTINGS.items():
        traded = (c, b, sb, dp) == (s06.CONV, s06.BASE, s06.SPAN_B, s06.DISP)
        sres = res if traded else runner.run(
            make_spec(conv=c, base=b, span_b=sb, disp=dp), intervals=IVS)
        sens_set[tag] = {"pooled": sres["pooled"], "trades": sres["trades"]}
        for interval in IVS:
            for label in ["native", "forced-1:3"]:
                m = sres["pooled"][(interval, label)]
                v, _ = verdict(m, label)
                print(f"  {tag:<46} {interval:<4} {label:<11} n={m['trades']:>5} "
                      f"R={m['r_sum_post_fee']:>8.1f} exp={m['expectancy_post_fee_r']:>+7.3f} "
                      f"sh={m['sharpe_post_fee']:>6.2f} {v}")

    print("\nSensitivity 2 - the two readings of the source's ambiguous stop")
    sens_risk: dict = {}
    drops: dict = {}
    for reading in s06.RISK_READINGS:
        tag = {"cloud": "1R to the far cloud edge (traded)",
               "base": "1R to the base line (literal)"}[reading]
        drops[tag] = dropped_signals(reading)
        sres = res if reading == s06.RISK_CLOUD else runner.run(
            make_spec(risk=reading), intervals=IVS)
        sens_risk[tag] = {"pooled": sres["pooled"], "trades": sres["trades"]}
        print(f"  {tag}: {drops[tag][0]} signals fired across all twelve datasets, "
              f"{drops[tag][1]} unusable (stop on the wrong side of the entry)")
        for interval in IVS:
            for label in ["native", "forced-1:3"]:
                m = sres["pooled"][(interval, label)]
                v, _ = verdict(m, label)
                fb = context_checks.first_bar_share(sres["trades"][(interval, label)])
                print(f"  {tag:<36} {interval:<4} {label:<11} n={m['trades']:>5} "
                      f"1R={r_pct(sres['trades'][(interval, label)]):>5.2f}% "
                      f"exp={m['expectancy_post_fee_r']:>+7.3f} sh={m['sharpe_post_fee']:>6.2f} "
                      f"first-bar={fb:>4.0%} {v}")

    print(f"\nSensitivity 3 - the source's OWN documented {s06.SOURCE_RR:g}:1, imposed as a target")
    sens_rr: dict = {}
    rres = runner.run(make_spec(target_r=s06.SOURCE_RR), intervals=IVS, audit=False)
    for interval in IVS:
        m = rres["pooled"][(interval, "native")]
        v, _ = verdict(m, "native")
        sens_rr[interval] = m
        print(f"  native + {s06.SOURCE_RR:g}R target  {interval:<4} n={m['trades']:>5} "
              f"win={m['win_rate'] * 100:>5.1f}% RR={m['rr_achieved']:>5.2f} "
              f"R={m['r_sum_post_fee']:>8.1f} exp={m['expectancy_post_fee_r']:>+7.3f} "
              f"sh={m['sharpe_post_fee']:>6.2f} {v}")

    print(f"\nSensitivity 4 - one change at a time, {HEADLINE_TF} only")
    sens_alt: dict = {}
    for tag, kw, aud in [
        ("as traded", {}, False),
        ("entry as a state, not the first bar the pair turns true", {"on_cross": False}, False),
        ("exit added: close when the trigger stops being true", {"signal_exit": True}, False),
        ("lagging-span confirmation added", {"chikou": True}, True),
    ]:
        sres = res if not kw else runner.run(make_spec(**kw), intervals=[HEADLINE_TF], audit=aud)
        sens_alt[tag] = sres["pooled"]
        for label in ["native", "forced-1:3"]:
            m = sres["pooled"][(HEADLINE_TF, label)]
            v, _ = verdict(m, label)
            print(f"  {tag:<56} {label:<11} n={m['trades']:>5} "
                  f"R={m['r_sum_post_fee']:>8.1f} exp={m['expectancy_post_fee_r']:>+7.3f} "
                  f"sh={m['sharpe_post_fee']:>6.2f} {v}")

    print("\nFunding, at Bybit's base rate - this rule holds for days, so it matters")
    print(_md_funding(res, summary))

    if write:
        write_logs(res, summary, ctx, mt, sens_set, sens_risk, sens_rr, sens_alt,
                   drops, r1_pct, ws, tot)
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
            "| R/trade | Sharpe | Max DD % | Max DD (R) | R-recovery | Verdict |")
    rows = [head, "|" + "---|" * 13]
    for interval in IVS:
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
        for label in ["native", "forced-1:3"]:
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
        for label in ["native", "forced-1:3"]:
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
        for label in ["native", "forced-1:3"]:
            c = top_share(res["trades"][(interval, label)])
            rows.append(f"| {interval} | {label} | {c['n']} | {c['total']:+.1f} "
                        f"| {c['top1']:+.2f}R | {c['share1']:.0%} | {c['top5']:+.1f}R "
                        f"| {c['share5']:.0%} | {c['without_top1']:+.1f}R |")
    return "\n".join(rows)


def _md_trend(res: dict) -> str:
    rows = ["| Timeframe | Exit | Trending trades | Trending R | Trending R/trade "
            "| Range trades | Range R | Range R/trade |", "|" + "---|" * 8]
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            v = trend_split(res["trades"][(interval, label)])
            rows.append(
                f"| {interval} | {label} | {v['trending']['trades']} "
                f"| {v['trending']['r_post_fee']:+.1f} | {_g(v['trending']['expectancy'], 3)} "
                f"| {v['range']['trades']} | {v['range']['r_post_fee']:+.1f} "
                f"| {_g(v['range']['expectancy'], 3)} |"
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


def _md_axis(sens: dict, extra_1r: bool = False) -> str:
    """A four-timeframe sensitivity block: one table row per variant per exit."""
    cols = ["Variant", "Timeframe", "Exit", "Trades", "Win%", "RR"]
    if extra_1r:
        cols += ["1R as % of price", "Died on entry bar"]
    cols += ["R (post-fee)", "R/trade", "Sharpe", "R-recovery", "Verdict"]
    rows = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for tag, blk in sens.items():
        for interval in IVS:
            for label in ["native", "forced-1:3"]:
                m = blk["pooled"][(interval, label)]
                tr = blk["trades"][(interval, label)]
                v, _ = verdict(m, label)
                cells = [tag, interval, label, str(m["trades"]),
                         _g(m["win_rate"] * 100, 1), _g(m["rr_achieved"])]
                if extra_1r:
                    cells += [f"{r_pct(tr):.2f}%",
                              f"{context_checks.first_bar_share(tr):.0%}"]
                cells += [_g(m["r_sum_post_fee"], 1), _g(m["expectancy_post_fee_r"], 3),
                          _g(m["sharpe_post_fee"]), _g(m["r_recovery"]), v]
                rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def _md_rr(summary: dict, sens_rr: dict) -> str:
    rows = [f"| Timeframe | Native, no target (traded) | Native + {s06.SOURCE_RR:g}R target "
            f"| RR achieved, no target -> {s06.SOURCE_RR:g}R target |", "|" + "---|" * 4]
    for interval in IVS:
        a = summary[interval]["native"]
        b = sens_rr[interval]
        rows.append(
            f"| {interval} | {a['trades']} trades, {_g(a['win_rate'] * 100, 1)}% win, "
            f"{_g(a['r_sum_post_fee'], 1)}R, Sharpe {_g(a['sharpe_post_fee'])} "
            f"| {b['trades']} trades, {_g(b['win_rate'] * 100, 1)}% win, "
            f"{_g(b['r_sum_post_fee'], 1)}R, Sharpe {_g(b['sharpe_post_fee'])} "
            f"| {_g(a['rr_achieved'])} -> {_g(b['rr_achieved'])} |"
        )
    return "\n".join(rows)


def _md_alt(sens_alt: dict) -> str:
    rows = [f"| Variant ({HEADLINE_TF}) | Exit | Trades | Win% | RR | R (post-fee) "
            "| R/trade | Sharpe | Fee cost/trade | Verdict |", "|" + "---|" * 10]
    for tag, pooled in sens_alt.items():
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


def _md_regime(summary: dict) -> str:
    rows = ["| Timeframe | Exit | Best condition | Worst condition |", "|" + "---|" * 4]
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            m = summary[interval][label]
            rows.append(f"| {interval} | {label} | {m['best_regime']} | {m['worst_regime']} |")
    return "\n".join(rows)


HOURS_PER_BAR = {"1H": 1.0, "4H": 4.0, "6H": 6.0, "1D": 24.0}
FUNDING_BASE_PCT = 0.01      # Bybit's base rate per 8-hour stamp, as a percent
FUNDING_HOURS = 8.0


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
    dividing by 1R turns that into the units the verdicts are written in. This
    strategy needs the check more than any logged so far: it holds for tens of
    bars by design, so on the daily chart a single trade can span a hundred
    settlements.
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


def write_logs(res: dict, summary: dict, ctx: dict, mt: dict, sens_set: dict,
               sens_risk: dict, sens_rr: dict, sens_alt: dict, drops: dict,
               r1_pct: float, ws: int, tot: int) -> None:
    _csv_rows(summary)
    keeps = _keeps(summary)
    # Numbers quoted in the prose below, measured here rather than typed in, so a
    # re-run cannot leave a stale figure in the sentence beside the table.
    mults = candle_multiples(res)
    hi = summary[HEADLINE_TF]["native"]
    cv = summary[CONVENTIONAL_TF]["native"]
    day_cell = [res["per_cell"][(s, CONVENTIONAL_TF, "native")]["trades"]
                for s in runner.COINS]
    day_counts = ", ".join(str(n) for n in day_cell)
    tails = {(i, lab): loss_tail(res["trades"][(i, lab)])
             for i in IVS for lab in ["native", "forced-1:3"]}
    trends = {(i, lab): trend_split(res["trades"][(i, lab)])
              for i in IVS for lab in ["native", "forced-1:3"]}
    legs = {(i, lab): leg_split(res["trades"][(i, lab)])
            for i in IVS for lab in ["native", "forced-1:3"]}
    # Does the source's "sustained trends, chopped up in ranges" claim hold? Counted
    # across every timeframe-and-exit cell, both directions, so the prose cannot drift.
    trend_better = sum(1 for i in IVS for lab in ["native", "forced-1:3"]
                       if trends[(i, lab)]["trending"]["expectancy"]
                       > trends[(i, lab)]["range"]["expectancy"])
    long_better = sum(1 for i in IVS for lab in ["native", "forced-1:3"]
                      if legs[(i, lab)]["long"]["r_post_fee"]
                      > legs[(i, lab)]["short"]["r_post_fee"])
    n_cells = len(IVS) * 2
    # The source's claim is a RANGE of win rates rather than a number, so the
    # comparison table reports where each timeframe falls against it.
    wr_lo = min(summary[i]["native"]["win_rate"] * 100.0 for i in IVS)
    wr_hi = max(summary[i]["native"]["win_rate"] * 100.0 for i in IVS)
    rr_lo = min(summary[i]["native"]["rr_achieved"] for i in IVS)
    rr_hi = max(summary[i]["native"]["rr_achieved"] for i in IVS)
    concs = {(i, lab): top_share(res["trades"][(i, lab)])
             for i in IVS for lab in ["native", "forced-1:3"]}
    trend_holds = [f"{i} {lab}" for i in IVS for lab in ["native", "forced-1:3"]
                   if trends[(i, lab)]["trending"]["expectancy"]
                   > trends[(i, lab)]["range"]["expectancy"]]
    trend_fails = [f"{i} {lab}" for i in IVS for lab in ["native", "forced-1:3"]
                   if not (trends[(i, lab)]["trending"]["expectancy"]
                           > trends[(i, lab)]["range"]["expectancy"])]
    # The single cell where the source's claim is contradicted hardest, so the
    # sentence that names it cannot go stale on a re-run.
    worst_cell = max(
        ((i, lab) for i in IVS for lab in ["native", "forced-1:3"]),
        key=lambda k: (trends[k]["range"]["expectancy"]
                       - trends[k]["trending"]["expectancy"]),
    )
    cloud_tag = "1R to the far cloud edge (traded)"
    base_tag = "1R to the base line (literal)"
    # Sensitivity 3 is the only variant that has a target at all, so it is the row the
    # source's win-rate/RR pair should be read against. Counted, never asserted.
    rr_wr = [sens_rr[i]["win_rate"] * 100 for i in IVS]
    rr_rr = [sens_rr[i]["rr_achieved"] for i in IVS]
    rr_in_band = [i for i in IVS
                  if SRC["win_lo"] <= sens_rr[i]["win_rate"] * 100 <= SRC["win_hi"]]
    rr_positive = [i for i in IVS if sens_rr[i]["expectancy_post_fee_r"] > 0]
    range_better_native = sum(
        1 for i in IVS
        if trends[(i, "native")]["range"]["expectancy"]
        > trends[(i, "native")]["trending"]["expectancy"]
    )
    ov_min_pct = min(ctx[i]["overlap"] for i in IVS)
    ov_max_pct = max(ctx[i]["overlap"] for i in IVS)
    # Which whole native columns the single best headline trade out-earns. An on-page
    # comparison rather than a claim about the rest of the log.
    _best1 = tails[(HEADLINE_TF, "native")]["best"]
    beaten_cols = [i for i in IVS
                   if i != HEADLINE_TF
                   and np.isfinite(summary[i]["native"]["r_sum_post_fee"])
                   and _best1 > summary[i]["native"]["r_sum_post_fee"]]
    parts: list[str] = []

    parts.append(
        f"## Strategy #6 - {NAME}\n\n"
        f"**Tested:** {logbook.date.today().isoformat()} - **Coins:** {COINS_STR} -\n"
        f"**Timeframes:** {', '.join(IVS)} - **Fees:** taker on both legs "
        f"({runner.TAKER_FEE_RATE:.3%} each), every number below is post-fee -\n"
        f"**Data:** Bybit USDT perpetuals, public REST, forming bar dropped -\n"
        f"**Warmup:** {s06.warmup_for()} bars per dataset before the first trade is allowed"
    )

    parts.append(
        "**Sourcing: MEDIUM, and weaker than Strategy #5's.** The source is a short trade\n"
        "description, not a paper, and two things #5 at least had are missing. It does not\n"
        f"say what MARKET its {SRC['win_lo']:.0f}-{SRC['win_hi']:.0f}% win rates came from, "
        "and it does not say what BAR\n"
        "SIZE. So there is no like-for-like column to build here: the claim cannot be matched\n"
        "against this test on market or on timeframe, only on shape. And the claim is a RANGE\n"
        "rather than a number - the source attributes the spread to \"settings\", which is what\n"
        "makes the parameter sweep below mandatory rather than optional. It is the source's own\n"
        "stated reason its results move."
    )

    parts.append(
        "### The rule, in the source's own words\n\n"
        "* **Trigger:** \"Price breaks above the cloud with the conversion line crossing above\n"
        "  the base line (bullish); mirror for shorts.\"\n"
        "* **Stop-loss:** \"Below the cloud / below the base line.\"\n"
        "* **Take-profit:** \"Commonly the lagging span or a fixed multiple.\"\n"
        "* **Market condition:** \"Sustained trends. It's a lagging system and gets chopped up\n"
        "  in ranges.\"\n"
        f"* **Documented result:** about {SRC['rr']:g}:1 reward-to-risk on win rates ranging\n"
        f"  {SRC['win_lo']:.0f}-{SRC['win_hi']:.0f}% \"depending on settings\" "
        f"({SRC['what']})."
    )

    parts.append(
        "### What the source does not disclose\n\n"
        "Every number the indicator is made of, and the take-profit as well.\n\n"
        "| Left undefined | Set to here | Why that value | Swept? |\n"
        "|---|---|---|---|\n"
        f"| Conversion-line window | {s06.CONV} bars | Goichi Hosoda's original setting, "
        "the chart-package default | yes, whole sets |\n"
        f"| Base-line window | {s06.BASE} bars | same | yes, whole sets |\n"
        f"| Second cloud edge | {s06.SPAN_B} bars | same | yes, whole sets |\n"
        f"| Forward displacement | {s06.DISP} bars | same | yes, whole sets |\n"
        "| Take-profit multiple | none in the native rule | the source names no multiple "
        f"| yes - the forced 1:3, and the source's own {SRC['rr']:g}:1 |\n"
        "| Which stop of the two | the far cloud edge | the only one that is always on the "
        "correct side of the entry | yes, both readings |\n\n"
        "Because the source blames its own spread on settings, the three parameter sets in\n"
        "Sensitivity 1 are not decoration: they are the source's caveat, measured."
    )

    parts.append(
        "### Why the take-profit could not be taken literally\n\n"
        "The source offers two exits and neither one is usable as written.\n\n"
        "**The lagging span is not a price you can trade to.** The lagging span is simply the\n"
        f"close, drawn {s06.DISP} bars in the PAST. So the lagging-span value sitting at bar i "
        "on a\n"
        f"chart is the close of bar i+{s06.DISP} - a price that does not exist yet when the "
        "decision is\n"
        "made. Using it as a take-profit level is not a parameter choice, it is time travel,\n"
        "and it is the single biggest lookahead trap in this indicator. It is therefore not\n"
        "implemented. The lagging span is not thrown away, though: it has one legitimate use,\n"
        f"as a CONFIRMATION phrased in the only direction that does not consume the future -\n"
        f"is today's close above the close {s06.DISP} bars ago - and that is run in Sensitivity 4.\n\n"
        "**\"A fixed multiple\" names no multiple,** so it is not a rule. Choosing one would be\n"
        "writing the strategy instead of testing it. So the native exit carries NO target, and\n"
        f"this project's second variant - the forced 1:3 - IS the source's fixed-multiple exit,\n"
        f"imposed. The source's own documented {SRC['rr']:g}:1 is additionally run as a labelled\n"
        "sensitivity so the claim itself gets measured rather than quoted."
    )

    parts.append(
        "### The stop is a two-way ambiguity, and it was not silently resolved\n\n"
        "\"Below the cloud / below the base line\" names two different prices, and the gap\n"
        "between them is the entire risk budget of the trade. Both were measured; the traded\n"
        "one was declared in advance on a structural argument, not on which one scored better.\n\n"
        f"* **Below the cloud (traded).** For a long, 1R runs from the fill to the BOTTOM of the\n"
        "  cloud. Entry requires a close above the cloud's TOP, and the bottom is by\n"
        "  construction at or below the top, so this stop is ALWAYS on the correct side of the\n"
        f"  entry: of {drops[cloud_tag][0]} signals across all twelve datasets, "
        f"{drops[cloud_tag][1]} had to be discarded for an\n"
        "  impossible stop.\n"
        f"* **Below the base line (sensitivity).** The base line is a {s06.BASE}-bar midpoint. "
        "When price\n"
        f"  breaks out above a cloud drawn from data {s06.DISP} bars old, the base line can "
        "easily sit\n"
        "  ABOVE the entry, which is not a stop-loss at all but a level already passed. Those\n"
        f"  signals have to be thrown away: the same {drops[base_tag][0]} signals, of which "
        f"{drops[base_tag][1]} "
        f"({drops[base_tag][1] / drops[base_tag][0]:.0%})\n"
        "  are unusable under this reading. The count is reported, not hidden.\n\n"
        "Of the discard bar's four tests only expectancy depends on this choice; Sharpe,\n"
        "achieved reward-to-risk and R-recovery are all scale-free. Both readings are scored\n"
        "in Sensitivity 2."
    )

    parts.append(
        "### The stop trails, and it can also loosen\n\n"
        "The cloud is re-read on every bar, so in a run the cloud bottom rises underneath a\n"
        "long and the stop follows it up: the source's stop is a trailing stop by construction,\n"
        "not by an added rule. But a cloud bottom can also FALL, and the plain reading of \"stop\n"
        "below the cloud\" then puts the stop further away than it was at entry. No ratchet was\n"
        "added to prevent that, because a ratchet is a rule the source does not contain, and\n"
        "Strategy #5 set the precedent of letting a source-placed stop be whatever the source\n"
        "placed. The consequence is that a native loser can lose MORE than one unit of risk,\n"
        f"so it is measured: the worst single native trade on {HEADLINE_TF} was "
        f"{tails[(HEADLINE_TF, 'native')]['worst']:+.2f}R, and\n"
        f"{tails[(HEADLINE_TF, 'native')]['share_beyond']:.0%} of native losers on that "
        f"timeframe went beyond -1.2R. The full table is below."
    )

    parts.append(
        "### What the native exit actually is\n\n"
        "The trailing stop above, and nothing else. The source states no signal exit at all -\n"
        "its two exits are an unknowable level and an unstated multiple - so a trend system held\n"
        "until its trailing stop is hit is the honest minimum, and that is the native rule. The\n"
        "obvious candidate exit, closing the trade when the entry condition stops being true, is\n"
        "NOT in the source, so it is run as a labelled sensitivity instead of being smuggled\n"
        "into the headline. The native rule also carries no time limit, which is why the hold\n"
        "tail is reported: with no target and no clock, a winner runs until the cloud catches it.\n\n"
        "**Entry is edge-triggered, not a state.** \"Price is above the cloud and the conversion\n"
        "line is above the base line\" is a state that can persist for hundreds of bars. Traded\n"
        "as a state, the rule re-enters on the bar after every exit while the state holds, which\n"
        "measures the exit's churn rather than the entry. What is traded is the first bar on\n"
        "which BOTH conditions hold - which fires on whichever of the source's two events\n"
        "happens second, since requiring both on the same bar is almost never satisfied. The\n"
        "state version is Sensitivity 4, the same treatment Strategies #3 and #5 gave the same\n"
        "question."
    )

    n_all = len(res["audit"])
    n_ok = sum(1 for ok, _, _ in res["audit"].values() if ok)
    n_cols = max(len(cols) for _, cols, _ in res["audit"].values())
    parts.append(
        "### Lookahead bias, checked fresh for this strategy\n\n"
        f"**The mechanical audit passed on {n_ok} of {n_all} datasets**, re-deriving every\n"
        f"one of the {n_cols} indicator columns on history truncated at 25 different cut points "
        "and\n"
        "requiring each value to match the full-history value to 1e-12. A single mismatch would\n"
        "have raised and produced no numbers at all. Beyond the mechanical test, three specific\n"
        "traps in this indicator were handled by hand:\n\n"
        "1. **The displacement is backward in the data, forward on the chart.** The two cloud\n"
        f"   edges are drawn {s06.DISP} bars to the RIGHT of the bars they were computed from, so "
        "the\n"
        f"   cloud a trader can see at bar i was computed from data at bar i-{s06.DISP}. That is a "
        "shift\n"
        "   into the PAST and it is legitimate. The un-shifted series is deliberately never used\n"
        "   for anything: it is the cloud that will be drawn in the future, not today's cloud.\n"
        "2. **The lagging span was refused as a price.** Covered above - as a take-profit level\n"
        f"   it is the close {s06.DISP} bars ahead. It appears only as a closed-bar comparison.\n"
        "3. **Intrabar levels are taken from the previous bar.** The stop is a price the\n"
        "   candle's own low or high is tested against while the bar is still trading. The base\n"
        "   line at bar i is built from bar i's own high and low, so testing bar i's low against\n"
        "   a base line computed from bar i would be placing the stop inside the candle it is\n"
        "   meant to protect against. Both stop levels are shifted one bar, so there is one rule\n"
        "   to audit rather than two.\n\n"
        f"**Fills that opened already past their own stop:** {ws} of {tot} across every variant.\n"
        "The 1R level is fixed on the signal bar and the fill happens at the next bar's open, so\n"
        "a gap through the level would start a trade already stopped out. Perpetuals trade\n"
        "continuously, so this should be near zero - but \"should be\" is not a measurement."
    )

    parts.append(
        "### Results, three coins pooled per timeframe\n\n"
        "Both variants share the same entry rule and the same fills; only the exit differs.\n"
        "\"native\" is the source's own exit - the trailing cloud stop, no target, no time limit.\n"
        f"\"forced-1:3\" is this project's standard comparison and is also the source's own\n"
        f"fixed-multiple exit made concrete: a 3R target with a "
        f"{runner.FORCED_TIME_LIMIT}-bar time limit.\n\n"
        + _md_table(summary)
    )

    parts.append(
        "### What the source claims, and what this test measured\n\n"
        "The source states neither the market nor the bar size, so this is a comparison of\n"
        "SHAPE only - there is no like-for-like row to build.\n\n"
        "| Test | Market | Bars | Trades | Win% | RR |\n"
        "|---|---|---|---|---|---|\n"
        f"| The source's claim | not stated | not stated | not stated "
        f"| {SRC['win_lo']:.0f}-{SRC['win_hi']:.0f} | {SRC['rr']:g} |\n"
        + "\n".join(
            f"| This test, native exit | BTC/SOL/XRP perps | {i} "
            f"| {summary[i]['native']['trades']} "
            f"| {_g(summary[i]['native']['win_rate'] * 100, 1)} "
            f"| {_g(summary[i]['native']['rr_achieved'])} |"
            for i in IVS
        )
        + "\n\nEvery timeframe comes in "
        + ("BELOW" if wr_hi < SRC["win_lo"] else "around")
        + f" the bottom of the source's range - {wr_lo:.1f}% to {wr_hi:.1f}% "
        f"against a claimed\n{SRC['win_lo']:.0f}-{SRC['win_hi']:.0f}% - and every timeframe "
        f"comes in far ABOVE its claimed reward-to-risk: {rr_lo:.2f} to\n{rr_hi:.2f} against "
        f"{SRC['rr']:g}. Those two gaps are the same gap. A win rate and a reward-to-risk are\n"
        "not independent, and the source's pair implies a take-profit that closes trades early;\n"
        "this test has no take-profit at all, because the source never says what its multiple is,\n"
        "so winners run until a trailing stop catches them. Fewer of them survive and the ones\n"
        f"that do are far larger. Sensitivity 3 tests exactly that by imposing the source's own\n"
        f"{SRC['rr']:g}:1, and it is the right row to read against the claim - not this one.\n\n"
        "**On that row the claim's SHAPE reproduces and its profitability does not.** With the\n"
        f"source's own {SRC['rr']:g}R target attached, the win rate rises to "
        f"{min(rr_wr):.1f}-{max(rr_wr):.1f}% and achieved RR falls to\n"
        f"{min(rr_rr):.2f}-{max(rr_rr):.2f} against the claimed {SRC['rr']:g} - so the pair of "
        f"numbers the source quotes is reachable on\nthis market, landing inside the claimed "
        f"{SRC['win_lo']:.0f}-{SRC['win_hi']:.0f}% band at {len(rr_in_band)} of the {len(IVS)} "
        f"timeframes"
        + (f" ({', '.join(rr_in_band)})" if rr_in_band else "")
        + ".\nWhat does not come with it is the money: post-fee expectancy is positive at "
        f"{len(rr_positive)} of {len(IVS)}\ntimeframes"
        + (f" ({', '.join(rr_positive)})" if rr_positive else "")
        + ", and that variant is DISCARD or INCONCLUSIVE everywhere. The source's\nwin rate and "
        "reward-to-risk are reproducible; they are simply not the part worth having."
    )

    parts.append(
        "### How much risk each trade actually put up\n\n"
        "1R here is the distance from the fill to the far cloud edge, which is built from\n"
        f"{s06.SPAN_B} bars of range, so it grows with the bar size rather than staying fixed.\n\n"
        + _md_risk(res)
        + f"\n\nAcross all {len(mults)} coin-timeframe cells 1R runs from {min(mults):.1f}x to "
        f"{max(mults):.1f}x a typical candle.\n"
        "That matters because a stop inside one candle is decided by the engine's pessimistic\n"
        "intrabar tie-break rather than by the strategy - the disease Strategy #1 documented.\n"
        "Nothing here is anywhere near that thin."
    )

    parts.append("### How the trades ended, and how long they ran\n\n" + _md_exits(res))

    parts.append(
        "### What the loosening stop cost\n\n"
        "The stop is re-read from the cloud every bar with no ratchet, so a loss can exceed the\n"
        "one unit of risk it was sold as. This is the size of that effect.\n\n"
        + _md_losstail(res)
    )

    parts.append(
        "### How much of the result is a handful of trades\n\n"
        "The discard bar does not test this, and on this strategy it is the first thing that\n"
        "should be checked. A trailing stop with no target and no time limit produces a few\n"
        "enormous winners"
        + (f" - the best single {HEADLINE_TF} native trade is worth more R than this "
           f"strategy's\nentire "
           + ", ".join(beaten_cols) + " native column"
           + ("s, each taken on its own" if len(beaten_cols) != 1 else " taken on its own")
           if beaten_cols else "")
        + " - and an average R per trade is\nonly meaningful if it is not one trade wearing a "
        "trench coat.\n\n"
        + _md_conc(res)
        + "\n\nTwo notes on reading that table. A share above 100% is not an error: the best five\n"
        "trades can exceed the net total because everything else in the book is net negative\n"
        "underneath them. And where the total itself is negative the share is arithmetic noise -\n"
        "ignore the percentage on those rows and read the R figures instead.\n\n"
        + f"**This is the most important caveat on every native row.** At {HEADLINE_TF} the "
        f"single best trade\nis {concs[(HEADLINE_TF, 'native')]['share1']:.0%} of the whole "
        f"post-fee total, and the best five are "
        f"{concs[(HEADLINE_TF, 'native')]['share5']:.0%}; at {CONVENTIONAL_TF} the best trade\n"
        f"alone is {concs[(CONVENTIONAL_TF, 'native')]['share1']:.0%} of the total. "
        + ("Strip the single best trade out and the native column still stays\npositive on every "
           "timeframe, which is the one reassuring part of the table"
           if all(concs[(i, "native")]["without_top1"] > 0 for i in IVS) else
           "Strip the single best trade out and the native column\nturns negative on "
           + ", ".join(i for i in IVS if concs[(i, "native")]["without_top1"] <= 0)
           + ", which is disqualifying on its own")
        + " - but the\n"
        "distribution is the opposite of the steady grind the R-per-trade figures suggest. The\n"
        "forced variant, which caps every winner at 3R, has no such concentration and also has no\n"
        "such result, and those two facts are the same fact."
    )

    parts.append(
        "### The source's own claimed condition: sustained trends, chopped up in ranges\n\n"
        "This is the one claim in the source that can be checked directly. The regime label is\n"
        "two halves joined by a slash (trend / volatility); this keeps only the trend half and\n"
        "pools up-trend with down-trend, because the rule is symmetric and the claim is about\n"
        "trend, not direction. The label is assigned from a 100-bar average and its own 20-bar\n"
        "slope, both known at the time of the trade, and it is reporting-only - no trade was\n"
        "filtered on it.\n\n"
        + _md_trend(res)
        + f"\n\n**The source's claim is NOT confirmed.** R per trade is higher in trending "
        f"conditions in only\n{trend_better} of the {n_cells} timeframe-and-exit cells "
        f"({', '.join(trend_holds) if trend_holds else 'none'}), and higher in RANGES in\n"
        f"{n_cells - trend_better} ({', '.join(trend_fails) if trend_fails else 'none'}). "
        + (f"The widest contradiction is {worst_cell[0]} {worst_cell[1]}, where the range bucket "
           f"earns\n{trends[worst_cell]['range']['expectancy']:+.3f}R per trade against "
           f"{trends[worst_cell]['trending']['expectancy']:+.3f}R in trending conditions - the "
           "reverse of what the source says\nshould happen.\n\n"
           if trend_fails else "\n\n")
        + "The most likely reason is mechanical rather than damning, and it cuts both ways. The\n"
        "regime label is assigned AT ENTRY from a 100-bar average and its 20-bar slope, and this\n"
        "rule is designed to enter BEFORE that average has turned: a breakout from a quiet stretch\n"
        "is labelled \"range\" on the bar it fires, and if it then becomes a sustained trend the\n"
        "profit is still booked against the \"range\" label. So the split measures what the market\n"
        "looked like when the trade was taken, not what it did afterwards - which means this test\n"
        "cannot confirm the source's claim and cannot refute it either. What it does establish is\n"
        "that the claim gives no usable filter: R per trade is HIGHER in labelled ranges on the\n"
        f"native exit at {range_better_native} of the {len(IVS)} timeframes, so switching this rule "
        "off in ranges would have\nremoved some of its best trades rather than its worst."
    )

    parts.append(
        "### Long leg vs short leg\n\n"
        "The rule is symmetric. The market is not: these three coins spent most of the sample in\n"
        "a long-run uptrend, so a symmetric rule is expected to earn more on the long side.\n\n"
        + _md_legs(res)
        + f"\n\nThe long leg out-earns the short leg in {long_better} of {n_cells} cells."
    )

    parts.append("### Per coin, per timeframe, per exit\n\n" + runner.per_coin_table(res, intervals=IVS))

    parts.append(
        "### Context checks - is the test fair, and is the result separable from luck\n\n"
        + context_checks.text_block(ctx, IVS)
        + f"\n\nThe stop-against-candle check is deliberately not printed here. It takes a single "
        f"1R\npercentage, and on this strategy 1R is not one percentage: it is built from "
        f"{s06.SPAN_B} bars of\nrange, so it runs from {r1_pct:.2f}% of price at {HEADLINE_TF} to "
        "several times that on daily bars. The\nper-cell version of the same check is the risk "
        f"table above, which puts every one of the\n{len(mults)} cells between {min(mults):.1f}x "
        f"and {max(mults):.1f}x a typical candle.\n\n"
        f"**The overlap line is the one that matters.** The two variants share only "
        f"{ov_min_pct:.0%} to {ov_max_pct:.0%} of their\nentries, well under the "
        f"{context_checks.MIN_OVERLAP:.0%} this project asks for before comparing exits. That is "
        "not a\nbug, it is the native exit having no time limit: while one native trade is still "
        "running, the\nforced variant has already been stopped or timed out and has taken further "
        "entries the\nnative run never saw. It is also why the exit-death check below is repeated "
        "on only the\nentries both variants actually took."
    )

    ed_rows = "\n".join(
        f"| {i} | {summary[i]['native']['expectancy_post_fee_r']:+.3f}R "
        f"| {summary[i]['forced-1:3']['expectancy_post_fee_r']:+.3f}R "
        f"| **{summary[i]['exit_death']}** | {summary[i]['exit_death_diag']} "
        f"| {mt[i]['n']} | {mt[i]['native']['expectancy_post_fee_r']:+.3f}R "
        f"| {mt[i]['forced-1:3']['expectancy_post_fee_r']:+.3f}R "
        f"| **{mt[i]['exit_death']}** |"
        for i in IVS
    )
    parts.append(
        "### Exit-death check - which exit style the edge depends on\n\n"
        "The mandatory check compares the two exits on the full runs. It is reported first\n"
        "because it is the project's defined test, but on this strategy it is contaminated: an\n"
        "open position blocks the next signal, the native rule holds until a trailing stop is\n"
        f"hit while the forced variant is capped at {runner.FORCED_TIME_LIMIT} bars, so the "
        "forced run takes entries the\n"
        "native run was still holding through. The right-hand columns re-score both variants on\n"
        "ONLY the entries they both actually took, which isolates the exit from the different\n"
        "trade population.\n\n"
        "| Timeframe | Native R/trade | Forced R/trade | Exit-death | Diagnosis "
        "| Shared entries | Native (shared) | Forced (shared) | Exit-death (shared) |\n"
        "|---|---|---|---|---|---|---|---|\n"
        + ed_rows
    )

    parts.append(
        "### Sensitivity 1 - the whole parameter set, which the source itself blames\n\n"
        "The source says its win rate moves with \"settings\" and never says which. So all four\n"
        "parameters are moved together as complete sets: Hosoda's original (traded), a slightly\n"
        "slower set, and the doubling that is commonly recommended for a market that trades 24/7\n"
        "instead of in daily sessions. Nothing here chose the headline.\n\n"
        + _md_axis(sens_set)
    )

    parts.append(
        "### Sensitivity 2 - the two readings of the source's ambiguous stop\n\n"
        f"* **{cloud_tag}:** {drops[cloud_tag][0]} signals fired across all twelve datasets, "
        f"{drops[cloud_tag][1]} unusable.\n"
        f"* **{base_tag}:** the same {drops[base_tag][0]} signals, "
        f"{drops[base_tag][1]} unusable "
        f"({drops[base_tag][1] / drops[base_tag][0]:.0%}) because the base\n"
        "  line sits on the wrong side of the entry - a stop already passed is not a stop.\n\n"
        "\"Died on entry bar\" is the share of trades that ended on the very first bar, which is\n"
        "the tell for a stop too close to the fill to be a strategy decision.\n\n"
        + _md_axis(sens_risk, extra_1r=True)
    )

    parts.append(
        f"### Sensitivity 3 - the source's own documented {SRC['rr']:g}:1, imposed as a target\n\n"
        "The native rule has no target because the source names no multiple. This adds one: the\n"
        f"source's own {SRC['rr']:g}:1. It is a sensitivity, never the traded rule.\n\n"
        + _md_rr(summary, sens_rr)
    )

    parts.append(
        f"### Sensitivity 4 - one change at a time, {HEADLINE_TF} only\n\n"
        "Each row changes exactly one thing the source left open, so a reader can see whether the\n"
        "verdict is a property of the strategy or of a placeholder. The last row is the only\n"
        "honest use of the lagging span: today's close against the close\n"
        f"{s06.DISP} bars ago, two bars that have both already happened.\n\n"
        + _md_alt(sens_alt)
    )

    parts.append(
        "### Best and worst conditions, per variant\n\n"
        "Reporting-only labels, assigned from data known at the time of each trade.\n\n"
        + _md_regime(summary)
    )

    parts.append(
        "### The discard bar, applied to each exit variant separately\n\n"
        "The two exits are never collapsed into one verdict. The thresholds are the project's\n"
        f"standing ones: KEEP needs at least {BAR.min_trades} trades, "
        f"{BAR.keep_expectancy_r:+.2f}R per trade, Sharpe\n"
        f"{BAR.keep_sharpe:.2f}, R-recovery {BAR.keep_r_recovery:.2f}, and for a native exit an "
        f"achieved reward-to-risk of at\n"
        f"least {BAR.keep_rr_native:.2f}. A count under {BAR.min_trades} returns INCONCLUSIVE, "
        "not DISCARD.\n\n"
        "| Timeframe | Exit | Trades | R/trade | Sharpe | R-recovery | Verdict | Why |\n"
        "|---|---|---|---|---|---|---|---|\n"
        + "\n".join(
            f"| {i} | {lab} | {summary[i][lab]['trades']} "
            f"| {_g(summary[i][lab]['expectancy_post_fee_r'], 3)} "
            f"| {_g(summary[i][lab]['sharpe_post_fee'])} "
            f"| {_g(summary[i][lab]['r_recovery'])} | **{summary[i][vk]}** "
            f"| {summary[i][rk]} |"
            for i in IVS
            for lab, vk, rk in [("native", "verdict_native", "reason_native"),
                                ("forced-1:3", "verdict_forced", "reason_forced")]
        )
        + "\n\nFor the forced variant the fee drag has a break-even win rate attached, because a "
        "fixed\n3R target makes that arithmetic meaningful: "
        + ", ".join(f"{i} needs {summary[i]['breakeven_wr_forced'] * 100:.1f}%"
                    for i in IVS)
        + "."
    )

    keeps_txt = ", ".join(f"{i} {lab}" for i, lab in keeps) if keeps else "none"
    fund = {(i, lab): _funding_cost_r(res, i, lab) for i, lab in keeps}
    survive, demote = [], []
    for i, lab in keeps:
        exp = summary[i][lab]["expectancy_post_fee_r"]
        (survive if exp - fund[(i, lab)][2] >= BAR.keep_expectancy_r
         else demote).append((i, lab))
    parts.append(
        "### Funding, flagged and not modelled - and on this strategy it is the main event\n\n"
        "These are perpetual futures, so a position open across an 8-hour settlement pays or\n"
        "receives funding on top of the fees already charged above. This project does not model\n"
        "funding - the rate is a live, time-varying series and modelling it properly is separate\n"
        "work - so the standing rule applies: **any KEEP that holds positions across funding\n"
        f"stamps is PROVISIONAL until this cost is settled.** This rule holds for tens of bars by\n"
        f"design - the native average is {hi['avg_bars_held']:.1f} bars at {HEADLINE_TF} and "
        f"{cv['avg_bars_held']:.1f} bars at {CONVENTIONAL_TF} - so every\n"
        f"cell crosses stamps, and the KEEP cells ({keeps_txt}) are provisional by that rule.\n\n"
        "What follows is arithmetic on two measured numbers - the average hold and the average 1R\n"
        f"as a percentage of price - at Bybit's BASE rate of {FUNDING_BASE_PCT:g}% per "
        f"{FUNDING_HOURS:g} hours. It is a floor,\n"
        "not a forecast: real funding on these coins has spent long stretches well above the base\n"
        "rate. It can also pay a short.\n\n"
        + _md_funding(res, summary)
    )

    for i, lab in keeps:
        hours, stamps, cost = fund[(i, lab)]
        exp = summary[i][lab]["expectancy_post_fee_r"]
        parts.append(
            f"**{i} {lab}** holds about {hours:.0f} hours, roughly {stamps:.1f} funding stamps, "
            f"which at the base rate is about {stamps * FUNDING_BASE_PCT:.3f}% of notional. "
            f"Against a 1R of {r_pct(res['trades'][(i, lab)]):.2f}% that is about "
            f"-{cost:.3f}R per trade, taking {exp:+.3f}R to **{exp - cost:+.3f}R** - "
            + (f"still clear of the {BAR.keep_expectancy_r:+.2f}R KEEP threshold."
               if exp - cost >= BAR.keep_expectancy_r else
               f"**below the {BAR.keep_expectancy_r:+.2f}R KEEP threshold.** Funding at the base "
               "rate alone is enough to demote this cell to INCONCLUSIVE, and any rate above the "
               "base widens the gap.")
        )
    parts.append(
        "And the direction of the bias runs the wrong way. Funding is positive most of the time on\n"
        f"these three coins - longs pay shorts - and the leg split above shows the long leg earning\n"
        f"more in {long_better} of {n_cells} cells. So the trades carrying the result are the trades "
        "most likely to\n"
        "PAY funding rather than receive it, which makes the table's symmetric charge the optimistic\n"
        "version.\n\n"
        f"**Status: {len(survive)} of the {len(keeps)} KEEP cells survive the base-rate estimate"
        + (f" ({', '.join(f'{i} {lab}' for i, lab in survive)})" if survive else "")
        + (f", and {len(demote)} do not ({', '.join(f'{i} {lab}' for i, lab in demote)})."
           if demote else ".")
        + "** None is a tradeable conclusion until funding is measured from the actual rate history\n"
        "over the same window rather than assumed at its floor."
    )

    parts.append(
        "### What would change these verdicts\n\n"
        "- **Funding measured, not floored.** The single most decisive missing number, and more so\n"
        "  here than on any strategy logged yet: this rule holds positions for days by design, so\n"
        f"  the daily cells cross roughly {_funding_cost_r(res, CONVENTIONAL_TF, 'native')[1]:.0f} "
        "settlements per trade. Pull Bybit's funding-rate\n"
        "  history for the same window and charge each trade its actual stamps. It can only move\n"
        "  the number downwards for a long-biased strategy.\n"
        f"- **More {CONVENTIONAL_TF} bars.** The daily rows rest on "
        f"{cv['trades']} trades across three coins "
        f"({day_counts}\n"
        "  per coin), which is the thinnest sample in the table. Adding liquid perpetuals - not a\n"
        "  longer history, which does not exist for these listings - is the only honest way to\n"
        "  raise that count.\n"
        "- **A source that states its parameters.** The win rate the source quotes is a range it\n"
        "  blames on settings, and Sensitivity 1 shows the verdict moving with the settings too.\n"
        "  Until a source states the four windows, every row here is one arbitrary point in a\n"
        "  space the source itself says is unstable.\n"
        "- **A ratchet on the stop, declared as an addition.** The loss tail above exists only\n"
        "  because the cloud is allowed to fall away from a trade. A one-way trailing stop would\n"
        "  remove that tail, but it is a rule the source does not contain, so adding it here would\n"
        "  be writing the strategy. It is the obvious next test, labelled as a departure.\n"
        "- **Slippage.** Entries are market orders at the open of the bar after a breakout, which\n"
        f"  is where the book is thinnest. Nothing beyond fees is charged for that. At the traded\n"
        f"  reading 1R is {min(mults):.1f}x to {max(mults):.1f}x a typical candle, so slippage is "
        "small relative to risk -\n"
        "  but it is not zero, and it is not modelled."
    )

    v_txt = "; ".join(f"{i} native **{summary[i]['verdict_native']}**, forced-1:3 "
                      f"**{summary[i]['verdict_forced']}**" for i in IVS)
    ed_yes = [i for i in IVS if summary[i]["exit_death"] == "yes"]
    parts.append(
        "### Bottom line\n\n"
        "The rule as the source describes it - wait for a close beyond the cloud with the\n"
        "conversion line past the base line, then hold while the cloud trails behind price - is\n"
        f"positive after fees on every timeframe tested: {hi['r_sum_post_fee']:+.1f}R from "
        f"{hi['trades']} trades at {HEADLINE_TF}\n"
        f"({hi['expectancy_post_fee_r']:+.3f}R per trade, Sharpe {_g(hi['sharpe_post_fee'])}, "
        f"t = {ctx[HEADLINE_TF]['sig_native']['t_net']:+.2f}) and "
        f"{cv['r_sum_post_fee']:+.1f}R from {cv['trades']} trades at\n"
        f"{CONVENTIONAL_TF} ({cv['expectancy_post_fee_r']:+.3f}R per trade, Sharpe "
        f"{_g(cv['sharpe_post_fee'])}). Verdicts: {v_txt}.\n\n"
        "Four things carry more weight than the headline numbers.\n\n"
        f"**The edge is in the exit, not the entry.** Exit-death fires at "
        + ("every timeframe tested" if len(ed_yes) == len(IVS)
           else (", ".join(ed_yes) if ed_yes else "no timeframe"))
        + ", and\nit fires the same way on the matched comparison, where both variants are scored on "
        "only the\n"
        f"entries they both took (overlap across the four timeframes bottoms out at {ov_min_pct:.0%}, so "
        "the\nfull-run comparison is genuinely a different trade population and the matched one is "
        "the\nhonest read). What the entry produces is a slight directional lean; what turns it into "
        "a\nresult is being allowed to hold. Capping the hold at "
        f"{runner.FORCED_TIME_LIMIT} bars with a 3R target - the\n"
        "source's own fixed-multiple exit, made concrete - changes the answer, which means this\n"
        "strategy cannot be traded with a short leash and stay the same strategy.\n\n"
        "**Most of the result is a handful of trades.** At "
        f"{HEADLINE_TF} the single best trade is "
        f"{concs[(HEADLINE_TF, 'native')]['share1']:.0%} of the entire post-fee\ntotal and the best "
        f"five are {concs[(HEADLINE_TF, 'native')]['share5']:.0%}; at {CONVENTIONAL_TF} the best "
        f"trade alone is {concs[(CONVENTIONAL_TF, 'native')]['share1']:.0%}. "
        + ("Taking the best trade\nout leaves every native timeframe positive, so the edge is not "
           "literally one trade"
           if all(concs[(i, "native")]["without_top1"] > 0 for i in IVS) else
           "Taking the best trade out\nturns "
           + ", ".join(i for i in IVS if concs[(i, "native")]["without_top1"] <= 0)
           + " negative, which is disqualifying on its own")
        + " - but an\naverage of "
        f"{hi['expectancy_post_fee_r']:+.3f}R per trade drawn from a distribution that lopsided is "
        "not the steady\ngrind it reads as, and it is the reason the Sharpe numbers sit far below "
        "what the R totals\nsuggest.\n\n"
        "**The source's claim about WHEN it works is not confirmed.** It says this rule wants\n"
        f"sustained trends and gets chopped up in ranges, and R per trade is higher in trending\n"
        f"conditions in only {trend_better} of {n_cells} cells. The regime label is assigned at "
        "entry, and this rule enters\nbefore a 100-bar average can have turned, so a breakout that "
        "becomes a trend books its\nprofit under the \"range\" label - which means the test can "
        "neither confirm the claim nor\nrefute it. What it does settle is that the claim is not a "
        "usable filter: trading this rule only\nin labelled trends would have removed its best "
        f"trades at {range_better_native} of the {len(IVS)} timeframes.\n\n"
        "**The numbers are honest but the risk is not one unit.** No ratchet was added, so a\n"
        "falling cloud loosens the stop and the worst native trade at "
        f"{HEADLINE_TF} returned "
        f"{tails[(HEADLINE_TF, 'native')]['worst']:.2f}R - not\n"
        f"the -1.00R the R-based tables imply. Read every R figure here as an average over a "
        "loss\ndistribution with a tail, not as a bounded bet.\n\n"
        f"**And the binding uncertainty is funding, not fees.** A rule that holds "
        f"{cv['avg_bars_held']:.0f} daily bars crosses\n"
        f"about {_funding_cost_r(res, CONVENTIONAL_TF, 'native')[1]:.0f} settlements per trade. At "
        "the base rate alone that is the cost calculated above;\n"
        "at the rates these coins have actually paid in trending markets it is larger, and it lands\n"
        "on the long leg, which is the leg that earns. Any KEEP above is PROVISIONAL for that\n"
        "reason and should not be treated as a real KEEP until the rate history is charged against\n"
        "each trade."
    )

    logbook.log_md("\n\n".join(parts))


if __name__ == "__main__":
    main(write="--log" in sys.argv)
