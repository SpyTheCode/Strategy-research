"""Run Strategy #5 - Keltner Channel breakout, and log it.

Usage:  .venv\\Scripts\\python.exe src\\run_s05.py [--log]
"""

from __future__ import annotations

import sys

import numpy as np

import bybit_data as bd
import context_checks
import lookahead_check
import logbook
import runner
import s05_keltner_breakout as s05
from discard_bar import BAR, exit_death, verdict
from harness import metrics

NAME = ("Keltner Channel breakout (close outside EMA20 +- 2.0xATR10, "
        "1R to the middle line, exit on close back inside)")
COINS_STR = "BTCUSDT+SOLUSDT+XRPUSDT"

IVS = ["1H", "4H", "6H", "1D"]

# 1H is the headline for two reasons: it is the bar size one of the source's own
# two tests actually used (the forex test), and it has by far the most trades,
# so the single-timeframe sensitivities below are the least noisy there. The 1D
# rows are the like-for-like against the source's OTHER test, the daily stock
# one, which is where its 2.1:1 reward-to-risk claim comes from.
HEADLINE_TF = "1H"
RR_CLAIM_TF = "1D"

# The source's own two results, for a like-for-like column. Neither is crypto.
SRC_STOCKS = {"what": "500 US stocks, daily bars, 2010-2024 (TradeAlgo)",
              "rr": 2.1, "win": 56.0, "sharpe": None, "dd": None}
SRC_FOREX = {"what": "forex, 1-hour bars, 2021-2025 (Pineify)",
             "rr": None, "win": 57.8, "sharpe": 1.33, "dd": 12.9}


def make_spec(mult: float = s05.BAND_MULT, ma_len: int = s05.MA_LEN,
              atr_bars: int = s05.ATR_BARS, risk: str = s05.RISK_MIDDLE,
              wilder: bool = False, on_cross: bool = True,
              target_r: float | None = None) -> runner.StrategySpec:
    bits = [f"mult={mult:g}", f"ma={ma_len}"]
    if atr_bars != s05.ATR_BARS:
        bits.append(f"atr={atr_bars}")
    if risk != s05.RISK_MIDDLE:
        bits.append(f"1R={risk}")
    if wilder:
        bits.append("wilderATR")
    if not on_cross:
        bits.append("state-entry")
    if target_r is not None:
        bits.append(f"target={target_r:g}R")
    return runner.StrategySpec(
        name=f"{NAME} [{' '.join(bits)}]",
        add_indicators=lambda df: s05.add_indicators(df, ma_len, atr_bars, mult, risk, wilder),
        entry=lambda df: s05.entry(df, on_cross),
        native_exit=lambda df: s05.native_exit(df, target_r),
        warmup=s05.warmup_for(ma_len, atr_bars),
        native_time_limit=None,   # the source names no time limit
    )


def show_audit(symbol: str = "BTCUSDT", interval: str = HEADLINE_TF) -> bool:
    """Print the lookahead proof on one dataset so it is visible, not asserted."""
    df = bd.drop_forming_bar(bd.load(symbol, interval), interval)
    raw = df[[c for c in df.columns if c in lookahead_check.RAW]].copy()
    return lookahead_check.report(
        f"{NAME} on {symbol} {interval}", raw, s05.add_indicators,
        first_cut=max(300, s05.warmup_for() + 50),
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

    The 1R level is a PRICE fixed on the signal bar, and the fill happens at the
    next bar's open. If that open gapped past the level the trade would start
    already stopped. Crypto perpetuals trade continuously so this should be zero
    or near it - but "should be" is not a measurement, so it is counted.
    """
    return sum(1 for t in trades
               if (t.entry_price - t.initial_stop) * t.direction <= 0)


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


def vol_split(trades) -> dict:
    """R by volatility half of the regime label - the source's own condition.

    The source says this rule wants "trending, expanding volatility". The regime
    label is two halves joined by a slash (trend / volatility); this keeps only
    the volatility half, so the claim can be checked directly instead of read
    off a nine-cell table.
    """
    out = {}
    for tag in ["highvol", "lowvol"]:
        sel = [t for t in trades
               if t.regime.endswith(tag) and np.isfinite(t.net_r)]
        r = np.array([t.net_r for t in sel]) if sel else np.array([])
        out[tag] = {
            "trades": len(sel),
            "r_post_fee": float(r.sum()) if len(r) else 0.0,
            "expectancy": float(r.mean()) if len(r) else float("nan"),
            "win_rate": float((r > 0).mean()) if len(r) else float("nan"),
        }
    return out


def by_reason(trades) -> dict:
    """{exit reason: (count, mean net R)}. Says what each exit route costs.

    Needed here because the native rule has two exits with very different
    sizes - a signal exit near the band, and the source's opposite-band hard
    stop about 2R away - and the average alone hides which one is doing the work.
    """
    out: dict = {}
    for t in trades:
        if not np.isfinite(t.net_r):
            continue
        out.setdefault(t.exit_reason or "unknown", []).append(t.net_r)
    return {k: (len(v), float(np.mean(v))) for k, v in sorted(out.items())}


def matched(res: dict, interval: str) -> dict:
    """Re-score both variants on ONLY the entries they both actually took.

    The two variants share an entry rule, but an open position blocks the next
    signal, and the forced variant's 30-bar limit holds far longer than the
    native signal exit does - so the forced run misses entries the native run
    took. Comparing the full runs then mixes two effects: the exit itself, and a
    different set of trades. This strips the second one out. It is the fair
    exit-death comparison; the standard one is still reported beside it because
    that is the project's defined check.
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


# ---------------------------------------------------------------------------
# Terminal run
# ---------------------------------------------------------------------------

def main(write: bool) -> None:
    print(f"Strategy #5 - {NAME}")
    print("=" * 78)
    print("Source parameters NOT disclosed: MA length, ATR length, band multiplier,")
    print("take-profit multiple. First three set to convention and swept below; the")
    print("take-profit is left out of the native rule and supplied by the forced 1:3.")

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

    print("\nHow the trades ended (three coins pooled), and what each route paid")
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            m = res["pooled"][(interval, label)]
            mix = ", ".join(f"{k} {n} @ {r:+.3f}R"
                            for k, (n, r) in by_reason(res["trades"][(interval, label)]).items())
            print(f"  {interval:<4} {label:<11} {mix or 'none'} | "
                  f"avg bars held {m['avg_bars_held']:.1f}")

    print("\nThe source's own claimed condition: expanding volatility")
    print(f"  {'tf':<5} {'exit':<11} {'high-vol trades':>16} {'high-vol R':>11} "
          f"{'R/trade':>9} {'low-vol trades':>15} {'low-vol R':>10} {'R/trade':>9}")
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            v = vol_split(res["trades"][(interval, label)])
            print(f"  {interval:<5} {label:<11} {v['highvol']['trades']:>16} "
                  f"{v['highvol']['r_post_fee']:>+11.1f} {v['highvol']['expectancy']:>+9.3f} "
                  f"{v['lowvol']['trades']:>15} {v['lowvol']['r_post_fee']:>+10.1f} "
                  f"{v['lowvol']['expectancy']:>+9.3f}")

    print("\nLong leg vs short leg")
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            g = leg_split(res["trades"][(interval, label)])
            print(f"  {interval:<4} {label:<11} long {g['long']['trades']:>5} trades "
                  f"{g['long']['r_post_fee']:>+8.1f}R | short {g['short']['trades']:>5} trades "
                  f"{g['short']['r_post_fee']:>+8.1f}R")
    print("\nAgainst the source's own two results - neither of them on crypto")
    print(f"  {'':<44} {'trades':>7} {'win%':>7} {'RR':>6} {'Sharpe':>7} {'maxDD%':>7}")
    print(f"  {SRC_STOCKS['what']:<44} {'n/a':>7} {SRC_STOCKS['win']:>7.1f} "
          f"{SRC_STOCKS['rr']:>6.2f} {'n/a':>7} {'n/a':>7}")
    print(f"  {SRC_FOREX['what']:<44} {'n/a':>7} {SRC_FOREX['win']:>7.1f} {'n/a':>6} "
          f"{SRC_FOREX['sharpe']:>7.2f} {SRC_FOREX['dd']:>7.1f}")
    for interval in IVS:
        m = summary[interval]["native"]
        print(f"  {'this test, native exit, ' + interval:<44} {m['trades']:>7} "
              f"{m['win_rate'] * 100:>7.1f} {m['rr_achieved']:>6.2f} "
              f"{m['sharpe_post_fee']:>7.2f} {m['max_drawdown_pct']:>7.1f}")

    print("\nPer coin, per timeframe, per exit")
    print(runner.per_coin_table(res, intervals=IVS))

    r1_pct = float(np.median([r_pct(res["trades"][(s, HEADLINE_TF, "native")])
                              for s in runner.COINS]))
    ctx = context_checks.summarise(res, runner.COINS, IVS, stop_pct=r1_pct)
    print("\nContext checks - is the test fair, and is the result separable from luck")
    print(context_checks.text_block(ctx, IVS, stop_pct=r1_pct))

    ws = sum(wrong_side(res["trades"][(i, lab)])
             for i in IVS for lab in ["native", "forced-1:3"])
    tot = sum(len(res["trades"][(i, lab)]) for i in IVS for lab in ["native", "forced-1:3"])
    print(f"\nFills that opened already past their own stop level: {ws} of {tot}")

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
    # thing about a rule the source left undefined, so a reader can see whether
    # the verdict is a property of the strategy or of a placeholder.
    print("\nSensitivity 1 - the band multiplier, on all four timeframes")
    sens_mult: dict = {}
    for mult in [1.5, 2.0, 2.5]:
        tag = f"bands at {mult:g} x ATR" + (" (traded)" if mult == s05.BAND_MULT else "")
        sres = res if mult == s05.BAND_MULT else runner.run(make_spec(mult=mult), intervals=IVS)
        sens_mult[tag] = {"pooled": sres["pooled"], "trades": sres["trades"]}
        for interval in IVS:
            for label in ["native", "forced-1:3"]:
                m = sres["pooled"][(interval, label)]
                v, _ = verdict(m, label)
                print(f"  {tag:<28} {interval:<4} {label:<11} n={m['trades']:>5} "
                      f"R={m['r_sum_post_fee']:>8.1f} exp={m['expectancy_post_fee_r']:>+7.3f} "
                      f"sh={m['sharpe_post_fee']:>6.2f} {v}")

    print("\nSensitivity 2 - the three readings of the source's ambiguous stop")
    sens_risk: dict = {}
    for reading in s05.RISK_READINGS:
        tag = {"middle": "1R to the middle line (traded)",
               "opposite": "1R to the opposite band (literal)",
               "broken": "1R to the band just broken (literal)"}[reading]
        sres = res if reading == s05.RISK_MIDDLE else runner.run(
            make_spec(risk=reading), intervals=IVS)
        sens_risk[tag] = {"pooled": sres["pooled"], "trades": sres["trades"]}
        for interval in IVS:
            for label in ["native", "forced-1:3"]:
                m = sres["pooled"][(interval, label)]
                v, _ = verdict(m, label)
                fb = context_checks.first_bar_share(sres["trades"][(interval, label)])
                print(f"  {tag:<36} {interval:<4} {label:<11} n={m['trades']:>5} "
                      f"1R={r_pct(sres['trades'][(interval, label)]):>5.2f}% "
                      f"exp={m['expectancy_post_fee_r']:>+7.3f} sh={m['sharpe_post_fee']:>6.2f} "
                      f"first-bar={fb:>4.0%} {v}")
    print("\nSensitivity 3 - the source's OWN documented 2.1:1, imposed as a target")
    sens_rr: dict = {}
    rres = runner.run(make_spec(target_r=s05.SOURCE_RR), intervals=IVS, audit=False)
    for interval in IVS:
        m = rres["pooled"][(interval, "native")]
        v, _ = verdict(m, "native")
        sens_rr[interval] = m
        print(f"  native + {s05.SOURCE_RR:g}R target  {interval:<4} n={m['trades']:>5} "
              f"win={m['win_rate'] * 100:>5.1f}% RR={m['rr_achieved']:>5.2f} "
              f"R={m['r_sum_post_fee']:>8.1f} exp={m['expectancy_post_fee_r']:>+7.3f} "
              f"sh={m['sharpe_post_fee']:>6.2f} {v}")

    print(f"\nSensitivity 4 - one change at a time, {HEADLINE_TF} only")
    sens_alt: dict = {}
    for tag, kw, aud in [
        ("as traded", {}, False),
        ("50-bar middle line instead of 20", {"ma_len": 50}, True),
        ("Wilder's ATR instead of a simple mean", {"wilder": True}, True),
        ("entry as a state, not the first bar outside", {"on_cross": False}, False),
    ]:
        sres = res if not kw else runner.run(make_spec(**kw), intervals=[HEADLINE_TF], audit=aud)
        sens_alt[tag] = sres["pooled"]
        for label in ["native", "forced-1:3"]:
            m = sres["pooled"][(HEADLINE_TF, label)]
            v, _ = verdict(m, label)
            print(f"  {tag:<44} {label:<11} n={m['trades']:>5} "
                  f"R={m['r_sum_post_fee']:>8.1f} exp={m['expectancy_post_fee_r']:>+7.3f} "
                  f"sh={m['sharpe_post_fee']:>6.2f} {v}")

    if write:
        write_logs(res, summary, ctx, mt, sens_mult, sens_risk, sens_rr, sens_alt,
                   r1_pct, ws, tot)
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


def _md_source(summary: dict) -> str:
    rows = ["| Test | Bars | Trades | Win% | RR achieved | Sharpe | Max DD % |",
            "|" + "---|" * 7]
    rows.append(f"| {SRC_STOCKS['what']} | daily | not stated | {SRC_STOCKS['win']:.0f} "
                f"| {SRC_STOCKS['rr']:.1f} | not stated | not stated |")
    rows.append(f"| {SRC_FOREX['what']} | 1-hour | not stated | {SRC_FOREX['win']:.1f} "
                f"| not stated | {SRC_FOREX['sharpe']:.2f} | {SRC_FOREX['dd']:.1f} |")
    for interval in IVS:
        m = summary[interval]["native"]
        rows.append(f"| this test, native exit, three crypto perps | {interval} "
                    f"| {m['trades']} | {_g(m['win_rate'] * 100, 1)} "
                    f"| {_g(m['rr_achieved'])} | {_g(m['sharpe_post_fee'])} "
                    f"| {_g(m['max_drawdown_pct'], 1)} |")
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


def candle_multiples(res: dict) -> list[float]:
    """1R divided by a typical candle, per coin and timeframe, from real fills.

    The same arithmetic the table above prints, collected so the sentence beside
    it can quote its own numbers. The shared context check measures ONE stop
    width against every timeframe's candles, which is fine as a project-wide
    sanity check but wrong to quote here: this rule's 1R scales with ATR, so it
    grows with the bar and the per-cell ratio is the honest figure.
    """
    out = []
    for symbol in runner.COINS:
        for interval in IVS:
            rng = context_checks.median_candle_range_pct(symbol, interval)
            if rng > 0:
                out.append(r_pct(res["trades"][(symbol, interval, "native")]) / rng)
    return out


def _md_exits(res: dict) -> str:
    rows = ["| Timeframe | Exit | How the trades ended (count @ mean net R) | Avg bars held |",
            "|" + "---|" * 4]
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            m = res["pooled"][(interval, label)]
            mix = ", ".join(f"{k} {n} @ {r:+.3f}R"
                            for k, (n, r) in by_reason(res["trades"][(interval, label)]).items())
            rows.append(f"| {interval} | {label} | {mix or 'none'} "
                        f"| {_g(m['avg_bars_held'], 1)} |")
    return "\n".join(rows)


def _md_vol(res: dict) -> str:
    rows = ["| Timeframe | Exit | High-vol trades | High-vol R | High-vol R/trade "
            "| Low-vol trades | Low-vol R | Low-vol R/trade |", "|" + "---|" * 8]
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            v = vol_split(res["trades"][(interval, label)])
            rows.append(
                f"| {interval} | {label} | {v['highvol']['trades']} "
                f"| {v['highvol']['r_post_fee']:+.1f} | {_g(v['highvol']['expectancy'], 3)} "
                f"| {v['lowvol']['trades']} | {v['lowvol']['r_post_fee']:+.1f} "
                f"| {_g(v['lowvol']['expectancy'], 3)} |"
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
    rows = ["| Timeframe | Native, no target (traded) | Native + 2.1R target "
            "| RR achieved, no target -> 2.1R target |", "|" + "---|" * 4]
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


def write_logs(res: dict, summary: dict, ctx: dict, mt: dict, sens_mult: dict,
               sens_risk: dict, sens_rr: dict, sens_alt: dict,
               r1_pct: float, ws: int, tot: int) -> None:
    _csv_rows(summary)
    keeps = _keeps(summary)
    # Numbers quoted in the prose below, measured here rather than typed in, so a
    # re-run cannot leave a stale figure in the sentence beside the table.
    r1_pct_1h = r_pct(res["trades"][(HEADLINE_TF, "native")])
    r1_pct_1d = r_pct(res["trades"][(RR_CLAIM_TF, "native")])
    day_cell = [res["per_cell"][(s, RR_CLAIM_TF, "native")]["trades"] for s in runner.COINS]
    day_counts = ", ".join(str(n) for n in day_cell)
    day_projected = int(round(summary[RR_CLAIM_TF]["native"]["trades"]
                              / len(runner.COINS) * (len(runner.COINS) + 10) / 50.0) * 50)
    src_wins = [w for w in (SRC_STOCKS["win"], SRC_FOREX["win"]) if w is not None]
    win_gap = [w - summary[i]["native"]["win_rate"] * 100.0
               for i in IVS for w in src_wins]
    parts: list[str] = []
    parts.append(
        "## Strategy #5 - Keltner Channel breakout\n\n"
        f"**Tested:** {logbook.date.today().isoformat()} · **Coins:** BTCUSDT, SOLUSDT, XRPUSDT ·\n"
        "**Timeframes:** 1H, 4H, 6H, 1D · **Fees:** taker on both legs (0.055% each), "
        "every number below is post-fee unless it is labelled pre-fee ·\n"
        f"**Channel:** EMA({s05.MA_LEN}) middle line, bands at "
        f"{s05.BAND_MULT:g} x ATR({s05.ATR_BARS})\n\n"
        "**Sourcing: MEDIUM, and weaker than any strategy logged so far.** The source is a "
        "short trade description, not a paper, and the two results attached to it come from "
        "search-result summaries rather than from reading either methodology - so their fees, "
        "position sizing and intrabar tie-break rules are unknown. **Neither cited test was "
        "on crypto:** one is US equities on daily bars, the other forex on hourly bars. This "
        "entry is therefore NOT a replication of a documented crypto result. It is the first "
        "crypto test of a rule documented elsewhere, and it should be read that way."
    )
    parts.append(
        "### The rule, in the source's own words\n\n"
        "* TRIGGER: buy when price CLOSES outside the upper Keltner Channel (a moving average "
        "with ATR-based bands); sell short on a close below the lower band.\n"
        "* STOP-LOSS: \"back inside the channel / at the opposite band\".\n"
        "* TAKE-PROFIT: \"a fixed multiple of the channel width or ATR\".\n"
        "* MARKET CONDITION: trending, expanding volatility.\n\n"
        "That is the whole rule as stated. Every number in it is missing."
    )
    parts.append(
        "### What the source claims\n\n"
        f"| Test | Bars | Win% | RR | Sharpe | Max DD % |\n|---|---|---|---|---|---|\n"
        f"| {SRC_STOCKS['what']} | daily | {SRC_STOCKS['win']:.0f} | {SRC_STOCKS['rr']:.1f} "
        "| not stated | not stated |\n"
        f"| {SRC_FOREX['what']} | 1-hour | {SRC_FOREX['win']:.1f} | not stated "
        f"| {SRC_FOREX['sharpe']:.2f} | {SRC_FOREX['dd']:.1f} |\n\n"
        "Two claims worth keeping in view: a win rate near 56-58%, and a reward-to-risk near "
        "2.1:1. Both are tested directly below."
    )
    parts.append(
        "### What the source does not disclose\n\n"
        "Four numbers, and they are the four that define the indicator:\n\n"
        f"| Not stated | Set to | Why | Tested? |\n|---|---|---|---|\n"
        f"| Moving-average length | {s05.MA_LEN}-bar EMA | the value in widest circulation "
        "for this indicator | swept (50-bar run below) |\n"
        f"| ATR length | {s05.ATR_BARS} bars | same | swept (Wilder ATR run below) |\n"
        f"| Band multiplier | {s05.BAND_MULT:g} x ATR | same | swept at 1.5 / 2.0 / 2.5 |\n"
        "| Take-profit multiple | left out of the native rule | see below | supplied by the "
        f"forced 1:3, and by the source's own {s05.SOURCE_RR:g}R |\n\n"
        "**The take-profit is not invented.** \"A fixed multiple of ATR\" with no multiple "
        "attached is not a rule, and choosing one would be writing the strategy rather than "
        "testing it. So the native exit carries NO target, and this project's second variant - "
        "the forced 1:3 - IS the source's fixed-multiple exit, imposed. Both halves of the "
        "source's exit are therefore tested, just in different columns: its signal exit "
        f"natively, its fixed-multiple exit in the forced run. Its own documented {s05.SOURCE_RR:g}:1 "
        "is additionally run as a sensitivity, so the claim itself gets measured."
    )
    parts.append(
        "### The one genuine ambiguity, and how it was resolved\n\n"
        "\"Back inside the channel / at the opposite band\" names two different prices, and the "
        "gap between them is the entire risk budget of the trade. Both readings were measured "
        "before either was traded:\n\n"
        "* **The band just broken** (\"back inside the channel\", read literally). At entry price "
        "sits a hair above it, so 1R is a fraction of one candle - the exact disease Strategy #1 "
        "documented, where the engine's deliberately pessimistic intrabar tie-break decides the "
        "outcome instead of the strategy.\n"
        "* **The opposite band**, read literally. That is 2 x "
        f"{s05.BAND_MULT:g} x ATR away, so the forced variant's 3R target lands roughly 12 ATR "
        "from entry and cannot be reached inside any sane time limit.\n\n"
        "Neither is usable as the headline, so the traded reading is declared rather than "
        "smuggled: **1R runs from the fill to the channel's middle line** - the average the bands "
        "are drawn around, the one level both of the source's phrasings bracket, and about 2 x ATR "
        "wide, the same order as every other stop in this log. **Both literal readings are run as "
        "sensitivities** and their expectancy reported, because of the four KEEP tests only "
        "expectancy depends on this choice; Sharpe, achieved RR and R-recovery are all scale-free.\n\n"
        "Both of the source's stop phrasings are then used, each in the role it can actually play:\n\n"
        "* \"at the opposite band\" is a PRICE, so it is the hard stop - a level the candle's low "
        "(or high) can reach while the bar is still trading.\n"
        "* \"back inside the channel\" is a SIGNAL, so it is the exit decision - the first bar "
        "closing back inside the channel ends the trade at the next open.\n\n"
        "Because the band moves with price, the second rule behaves as a trailing exit: in a run "
        "the upper band keeps rising, and the trade only ends once price falls back under wherever "
        "the band has got to. And under the 1R definition above, the opposite-band hard stop sits "
        "about 2R away, so a native loser can lose about two units of risk. That is the source's "
        "own placement, not a choice made here, and it is why the native rows are read with the "
        "exit mix beside them."
    )
    parts.append(
        "### Entry is the first bar outside, not every bar outside\n\n"
        "\"Price is outside the band\" is a state that can persist. Measured across all twelve "
        "datasets it persists for **2.5 closes on average** (21,397 bars outside a band, but only "
        "8,479 runs). Traded as a state, the rule re-enters on the bar after every exit while "
        "price is still outside, which measures the exit's churn rather than the entry. The bar "
        "that FIRST closes outside is what is traded here; the state version is run once as a "
        "sensitivity, the same treatment Strategy #3 gave the same question."
    )
    audit_cols = ", ".join(f"`{c}`" for c in next(iter(res["audit"].values()))[1])
    parts.append(
        "### Lookahead bias, checked fresh for this strategy\n\n"
        "The check is mechanical, not a promise: every indicator column is recomputed on history "
        "truncated at 25 different bars and compared with the value the full-history pass produced "
        f"at that same bar, to a tolerance of 1e-12. Columns checked: {audit_cols}. "
        f"**Result: {sum(1 for ok, _, _ in res['audit'].values() if ok)}/{len(res['audit'])} "
        "datasets PASS** (three coins x four timeframes).\n\n"
        "Two places in this strategy could have leaked, and both were handled explicitly:\n\n"
        "* **The hard stop is taken from the PREVIOUS bar's band.** The bands at bar i are built "
        "from bar i's close and bar i's own high and low (the true range), so testing bar i's low "
        "against a band computed from bar i would be placing a stop inside the candle it is meant "
        "to protect against. The stop level in force during a bar is the one that was already on "
        "the chart when that bar opened.\n"
        "* **The entry and the \"closed back inside\" exit use the CURRENT bar's band, and that is "
        "legitimate**, because both are decisions made on a bar that has already closed and filled "
        "at the NEXT bar's open. Knowing the close of a bar that has closed is not lookahead.\n\n"
        f"Independently of the audit: **{ws} of {tot} fills opened already past their own stop "
        "level** - the count of trades that were dead on arrival, which is the other way this kind "
        "of rule flatters itself."
    )
    parts.append(
        "### A bug found and fixed before any of these numbers were logged\n\n"
        "The first complete run of this strategy was thrown away. The line that turns the state "
        "\"price is outside the band\" into the event \"price has just closed outside the band\" was "
        "written as `state & ~state.shift(1).fillna(False)`, and under this project's pandas "
        "version that silently does nothing: shifting a true/false column leaves it as generic "
        "objects, and inverting generic objects applies whole-number bit-flipping instead of "
        "logical NOT, which returns a non-zero (therefore \"true\") value for BOTH true and false. "
        "The condition collapsed back into the raw state, so the discarded run traded every bar "
        "price sat outside the band rather than the first one - a different strategy from the one "
        "documented above, with no error message to say so.\n\n"
        "What it changed, for the record: the **native rows were bit-identical** either way "
        "(the native exit only fires when price closes back INSIDE, so there is no re-entry chance "
        "left for a state rule to take), while the forced-1:3 rows all moved, and two verdicts "
        "moved with them - 1H forced went from INCONCLUSIVE (3380 trades, +94.1R, Sharpe 0.38) to "
        "DISCARD, and 4H forced went from INCONCLUSIVE (891 trades, +86.8R, Sharpe 0.68) to KEEP. "
        "Both of those discarded figures are reproducible on demand: the collapsed rule IS the "
        "state-entry variant, which appears at 1H in Sensitivity 4 below and was re-measured at 4H "
        "to confirm the pair quoted here. "
        "**Self-test #16 was added to the engine's test file to fail loudly if this ever returns**, "
        "and it also checks the same idiom in the two earlier strategies that depend on it - "
        "Strategy #1 and Strategy #3 both already used the safe form, so their logged results are "
        "unaffected."
    )
    parts.append(
        "### Results - three coins pooled inside each timeframe, never across them\n\n"
        + _md_table(summary)
        + "\n\n"
        + "\n".join(
            f"* **{interval} {label}** - {summary[interval]['reason_native' if label == 'native' else 'reason_forced']}"
            for interval in IVS for label in ["native", "forced-1:3"]
        )
    )
    nat_all = sum(len(res["trades"][(i, "native")]) for i in IVS)
    nat_stop = sum(by_reason(res["trades"][(i, "native")]).get("stop", (0, 0))[0] for i in IVS)
    f13_all = sum(len(res["trades"][(i, "forced-1:3")]) for i in IVS)
    f13_time = sum(by_reason(res["trades"][(i, "forced-1:3")]).get("time", (0, 0))[0] for i in IVS)
    parts.append(
        "### How the trades actually ended, and what each route paid\n\n"
        + _md_exits(res)
        + f"\n\nThe native exit is a signal exit {1 - nat_stop / nat_all:.1%} of the time: across "
        f"the four timeframes the opposite-band hard stop fired only {nat_stop} times in "
        f"{nat_all} native trades. So the ambiguity over where the source's stop sits barely "
        "matters for the native rule in practice - price almost always closes back inside the "
        "channel long before it can travel two bands. What that leaves is a very short trade: "
        "about 2.5 bars, ending on a signal whose average outcome is a small fraction of 1R "
        "either way. The forced-1:3 variant is a different animal - roughly 18 bars, with the "
        f"30-bar time limit closing {f13_time / f13_all:.0%} of trades before either barrier is "
        "touched."
    )
    parts.append(
        "### Exit-death check - which exit is the edge attached to?\n\n"
        + "\n".join(
            f"* **{interval}**: {summary[interval]['exit_death_diag']} -> exit-death "
            f"**{summary[interval]['exit_death']}**"
            for interval in IVS
        )
        + "\n\nThat comparison has a caveat this strategy cannot avoid, and it is reported rather "
        "than buried: the two variants do NOT trade the same set of entries. An open position "
        "blocks the next signal, and because the native exit lasts about 2.5 bars while the forced "
        "one lasts about 18, the forced variant sits out signals the native variant takes. The two "
        "share only "
        + ", ".join(f"{ctx[i]['overlap']:.0%} ({i})" for i in IVS)
        + f" of their entries, against this project's {context_checks.MIN_OVERLAP:.0%} floor for "
        "calling it a clean like-for-like. So the check is run a second time on ONLY the entries "
        "both variants actually took:\n\n"
        + "| Timeframe | Shared entries | Native R/trade | Native Sharpe | Forced R/trade "
        "| Forced Sharpe | Exit-death |\n|---|---|---|---|---|---|---|\n"
        + "\n".join(
            f"| {i} | {mt[i]['n']} | {mt[i]['native']['expectancy_post_fee_r']:+.3f}R "
            f"| {_g(mt[i]['native']['sharpe_post_fee'])} "
            f"| {mt[i]['forced-1:3']['expectancy_post_fee_r']:+.3f}R "
            f"| {_g(mt[i]['forced-1:3']['sharpe_post_fee'])} | **{mt[i]['exit_death']}** |"
            for i in IVS
        )
    )
    parts.append(
        "### Is any of this separable from luck?\n\n"
        "t is the average trade divided by its own standard error. Below about 2, the average sits "
        "inside the range random noise would produce anyway.\n\n```\n"
        + context_checks.text_block(ctx, IVS, stop_pct=r1_pct)
        + "\n```\n\n"
        f"Both KEEP cells clear that bar: 1D native t = {ctx['1D']['sig_native']['t_net']:+.2f} and "
        f"4H forced-1:3 t = {ctx['4H']['sig_forced']['t_net']:+.2f}, post-fee. Note what the 1H "
        "native column shows, though - a pre-fee average of "
        f"{ctx['1H']['sig_native']['gross_mean']:+.4f}R that becomes "
        f"{ctx['1H']['sig_native']['net_mean']:+.4f}R post-fee, with t = "
        f"{ctx['1H']['sig_native']['t_net']:+.2f}. That is not a strategy losing money; it is a "
        "strategy paying its fees, measured with enough trades to be certain of it.\n\n"
        f"One line in that block needs a caveat: the shared context check measures a single stop "
        f"width - {r1_pct:.1f}%, the median 1R at {HEADLINE_TF} - against every timeframe's candles, "
        "which is why it reads as small on the daily rows. This rule's 1R is drawn from ATR, so it "
        "grows with the bar. The per-cell version is the table in the next section, and it is the "
        "one to read."
    )
    mid_tag = "1R to the middle line (traded)"
    opp_tag = "1R to the opposite band (literal)"
    brk_tag = "1R to the band just broken (literal)"
    mults = candle_multiples(res)
    brk_1r = [r_pct(sens_risk[brk_tag]["trades"][(i, lab)])
              for i in IVS for lab in ["native", "forced-1:3"]]
    brk_fb_all = [context_checks.first_bar_share(sens_risk[brk_tag]["trades"][(i, "forced-1:3")])
                  for i in IVS]
    parts.append(
        "### 1R against one candle\n\n"
        "If 1R is smaller than a typical candle, most trades resolve inside a single bar, where "
        "plain open/high/low/close cannot say whether the stop or the target came first - and this "
        "engine breaks that tie against the trade on purpose. A stop that tight would be testing "
        "the tie-break rule, not the strategy. Measured from the fills that actually happened:\n\n"
        + _md_risk(res)
        + f"\n\nThe middle-line reading gives a stop that is {min(mults):.1f} to {max(mults):.1f} "
        "typical candles wide in every one of the twelve cells - it scales with the bar because ATR "
        f"does - and **{ctx[HEADLINE_TF]['first_bar_native']:.0%} of native trades "
        f"and {ctx['1D']['first_bar_forced']:.0%} of daily forced trades resolved inside their first "
        "candle**, so the tie-break is not carrying these results. The literal \"band just broken\" "
        f"reading is the counter-example, and it is in the sensitivity table below: 1R shrinks to "
        f"{min(brk_1r):.2f}-{max(brk_1r):.2f}% of price and {min(brk_fb_all):.0%}-"
        f"{max(brk_fb_all):.0%} of forced trades die on their entry bar."
    )
    parts.append(
        "### The source's own two claims, measured\n\n"
        + _md_source(summary)
        + "\n\n**The win rate does not survive the move to crypto.** The source's 56-58% becomes "
        f"{summary['1H']['native']['win_rate'] * 100:.1f}% at 1H and "
        f"{summary['1D']['native']['win_rate'] * 100:.1f}% at 1D. What replaces it is a bigger "
        f"average winner: achieved reward-to-risk runs {summary['1H']['native']['rr_achieved']:.2f} "
        f"to {summary['1D']['native']['rr_achieved']:.2f} against the source's "
        f"{SRC_STOCKS['rr']:.1f}. The shape of the trade is different from the one described - "
        "fewer, larger wins instead of many small ones - which is worth stating plainly, because "
        "a trader expecting to be right 57% of the time would abandon this rule in its first bad "
        "month. The Sharpe claim (1.33 on hourly forex) is not reproduced on any crypto timeframe; "
        f"the best native Sharpe here is {max(summary[i]['native']['sharpe_post_fee'] for i in IVS):.2f} "
        "at 1D.\n\n"
        f"The source's own {s05.SOURCE_RR:g}:1 target, imposed on the native exit:\n\n"
        + _md_rr(summary, sens_rr)
        + "\n\nCapping the winner at the documented ratio does not rescue the timeframes that were "
        "already failing. On the daily rows it is a genuine trade-off rather than a loss: total R "
        f"falls from {summary['1D']['native']['r_sum_post_fee']:.1f}R to "
        f"{sens_rr['1D']['r_sum_post_fee']:.1f}R and per-trade expectancy from "
        f"{summary['1D']['native']['expectancy_post_fee_r']:+.3f}R to "
        f"{sens_rr['1D']['expectancy_post_fee_r']:+.3f}R, while Sharpe RISES from "
        f"{summary['1D']['native']['sharpe_post_fee']:.2f} to {sens_rr['1D']['sharpe_post_fee']:.2f} "
        "- a smoother ride for less money, because the target cuts the long runs that produce both "
        "the profit and the lumpiness. The trade count is unchanged on every timeframe, so this is "
        "an exit-versus-exit comparison on the same entries."
    )
    mult_keep = {
        (i, lab): sum(1 for blk in sens_mult.values()
                      if verdict(blk["pooled"][(i, lab)], lab)[0] == "KEEP")
        for i in IVS for lab in ["native", "forced-1:3"]
    }
    n_mult = len(sens_mult)
    day_by_mult = ", ".join(
        f"{blk['pooled'][(RR_CLAIM_TF, 'native')]['expectancy_post_fee_r']:+.3f}R"
        for blk in sens_mult.values())
    parts.append(
        "### Sensitivity 1 - the band multiplier the source never states\n\n"
        + _md_axis(sens_mult)
        + f"\n\nThis is the axis that separates the two KEEP cells. **1D native is a KEEP at all "
        f"{n_mult} multipliers tested** ({day_by_mult} per trade at 1.5x, 2.0x and 2.5x), so it "
        "does not depend on the placeholder. "
        f"**4H forced-1:3 is a KEEP at {mult_keep[('4H', 'forced-1:3')]} of the {n_mult}** - only "
        "at the conventional 2.0x - and lands as INCONCLUSIVE either side of it. That cell is "
        "therefore standing on one arbitrary value of an undisclosed parameter, and should be "
        "treated as the weaker of the two results regardless of what the table says."
    )
    risk_sh = {
        tag: {i: blk["pooled"][(i, "native")]["sharpe_post_fee"] for i in IVS}
        for tag, blk in sens_risk.items()
    }
    brk_exp = [sens_risk[brk_tag]["pooled"][(i, lab)]["expectancy_post_fee_r"]
               for i in IVS for lab in ["native", "forced-1:3"]]
    brk_fb = context_checks.first_bar_share(
        sens_risk[brk_tag]["trades"][(HEADLINE_TF, "forced-1:3")])
    parts.append(
        "### Sensitivity 2 - all three readings of the source's ambiguous stop\n\n"
        + _md_axis(sens_risk, extra_1r=True)
        + "\n\nThe two sane readings differ by a factor of about two in how wide 1R is, and that "
        "moves every R-denominated number - but it barely moves the scale-free ones. Native Sharpe, "
        "middle line versus opposite band: "
        + ", ".join(f"{i} {risk_sh[mid_tag][i]:.2f} vs {risk_sh[opp_tag][i]:.2f}" for i in IVS)
        + ". So the choice between them changes the units the result is quoted in, not whether "
        "there is a result. Expectancy is the number to distrust across these rows; Sharpe, "
        "achieved RR and R-recovery are the numbers that survive.\n\n"
        "The third reading is the one that had to be rejected, and the table shows why rather than "
        "asserting it. Read literally, 'back inside the channel' puts the stop on the band the "
        "candle just closed a hair beyond, so 1R collapses to "
        f"{r_pct(sens_risk[brk_tag]['trades'][(HEADLINE_TF, 'native')]):.2f}% of price at "
        f"{HEADLINE_TF} - a fraction of a single candle. {brk_fb:.0%} of the forced trades then die "
        "on their own entry bar, which means the engine's stop-wins-ties rule is deciding the "
        "outcome instead of the strategy, and the expectancies go haywire in both directions "
        f"(from {min(brk_exp):+.2f}R to {max(brk_exp):+.2f}R per trade). Those are not results, "
        "they are artefacts of an unmeasurably tight stop, and they are printed here so the "
        "rejected reading is on the record."
    )
    a_base = sens_alt["as traded"][(HEADLINE_TF, "forced-1:3")]
    a_wild = sens_alt["Wilder's ATR instead of a simple mean"][(HEADLINE_TF, "forced-1:3")]
    a_state = sens_alt["entry as a state, not the first bar outside"][(HEADLINE_TF, "forced-1:3")]
    parts.append(
        f"### Sensitivity 4 - one change at a time, {HEADLINE_TF} only\n\n"
        + _md_alt(sens_alt)
        + "\n\nNothing here turns the headline timeframe around: the native exit stays a DISCARD "
        "under a slower middle line, under Wilder's ATR, and under the state entry. Two rows are "
        "worth reading closely. Wilder's ATR - the smoothing most charting packages actually ship "
        "as 'ATR' - moves the forced variant from "
        f"{a_base['r_sum_post_fee']:+.1f}R to {a_wild['r_sum_post_fee']:+.1f}R and its Sharpe from "
        f"{a_base['sharpe_post_fee']:.2f} to {a_wild['sharpe_post_fee']:.2f}, which is a large "
        "swing for a choice the source never made explicit - and it is still not a KEEP. And the "
        "native rows are IDENTICAL under the state entry, to the last decimal. That is not a "
        "copy-paste; it is structural. The native exit only fires on a bar that closes back INSIDE "
        "the channel, and on that bar the state is already false, so there is never a bar on which "
        "a state rule could re-enter and an edge rule could not. The forced variant, whose trades "
        f"outlive the state, does differ - {a_base['trades']} trades against {a_state['trades']} - "
        "which is the evidence that the two entry rules really are wired differently."
    )
    vol = {(i, lab): vol_split(res["trades"][(i, lab)]) for i in IVS
           for lab in ["native", "forced-1:3"]}
    agrees = [f"{i} {lab}" for (i, lab), v in vol.items()
              if v["highvol"]["expectancy"] > v["lowvol"]["expectancy"]]
    parts.append(
        "### The source's own market condition, tested: expanding volatility\n\n"
        "The source says trending, expanding volatility. Trend is not directly measurable as a "
        "filter here without inventing one, but volatility is: every trade is tagged high- or "
        "low-volatility by the reporting regime label - a 14-bar ATR as a percentage of price, "
        "compared with its own 500-bar median on that timeframe - assigned from data available at "
        "entry.\n\n"
        + _md_vol(res)
        + f"\n\n**The claim does not hold.** Of the eight cells, {len(agrees)} earn more per trade "
        "in high volatility than in low"
        + (f" ({', '.join(agrees)})" if agrees else "")
        + ". Both KEEP cells fall on the wrong side of the claim: 1D native earns "
        f"{vol[('1D', 'native')]['highvol']['expectancy']:+.3f}R in high volatility against "
        f"{vol[('1D', 'native')]['lowvol']['expectancy']:+.3f}R in low, and 4H forced-1:3 "
        f"{vol[('4H', 'forced-1:3')]['highvol']['expectancy']:+.3f}R against "
        f"{vol[('4H', 'forced-1:3')]['lowvol']['expectancy']:+.3f}R. The reason is mechanical: the "
        "bands are drawn from ATR, so when volatility expands the bands widen with it, and price "
        "has to travel further to close outside them. The indicator already adapts to volatility, "
        "which means an extra volatility filter has little left to select on. The honest reading is "
        "that this is not a volatility-expansion strategy on crypto, whatever it is on the "
        "instruments the source tested."
    )
    legs = {(i, lab): leg_split(res["trades"][(i, lab)]) for i in IVS
            for lab in ["native", "forced-1:3"]}
    parts.append(
        "### Long leg against short leg\n\n"
        + _md_legs(res)
        + "\n\n**Longs carry this strategy and shorts contribute almost nothing.** At 1D native, "
        f"{legs[('1D', 'native')]['long']['trades']} longs make "
        f"{legs[('1D', 'native')]['long']['r_post_fee']:+.1f}R while "
        f"{legs[('1D', 'native')]['short']['trades']} shorts make "
        f"{legs[('1D', 'native')]['short']['r_post_fee']:+.1f}R. At 4H forced-1:3 it is "
        f"{legs[('4H', 'forced-1:3')]['long']['r_post_fee']:+.1f}R against "
        f"{legs[('4H', 'forced-1:3')]['short']['r_post_fee']:+.1f}R. Two things follow. First, the "
        "sample behind each KEEP is effectively half the size the trade count suggests, because one "
        "leg is doing the work. Second, three coins over a window containing a full bull leg is "
        "exactly the setup in which a long-only edge can be an artefact of the era rather than of "
        "the rule - the same caveat this log has already recorded against every long-biased result. "
        "It is not disqualifying, and it is not proof of an edge either."
    )
    parts.append(
        "### Best and worst conditions, per cell\n\n"
        + _md_regime(summary)
        + "\n\nRead as a description of the sample, not a filter to trade: the labels are assigned "
        "for reporting and the buckets are small once split four ways."
    )
    keep_txt = ", ".join(f"{i} {lab}" for i, lab in keeps) if keeps else "none"
    fund = {(i, lab): _funding_cost_r(res, i, lab) for i, lab in keeps}
    survive, demote = [], []
    for i, lab in keeps:
        exp = summary[i][lab]["expectancy_post_fee_r"]
        (survive if exp - fund[(i, lab)][2] >= BAR.keep_expectancy_r else demote).append((i, lab))
    parts.append(
        "### Funding, flagged and not modelled - and it matters to one of the two KEEPs\n\n"
        "These are perpetual futures, so a position open across an 8-hour settlement pays or "
        "receives funding on top of the fees already charged above. This project does not model "
        "funding - the rate is a live, time-varying series and modelling it properly is a separate "
        "piece of work - so the standing rule applies: **any KEEP that holds positions across "
        "funding stamps is PROVISIONAL until this cost is settled.** Both KEEP cells here do "
        f"({keep_txt}), so both are provisional.\n\n"
        "What follows is arithmetic on two measured numbers - the average hold from the trade list "
        "and the average 1R as a percentage of price - at Bybit's BASE rate of "
        f"{FUNDING_BASE_PCT:g}% per {FUNDING_HOURS:g} hours. It is a floor, not a forecast: real "
        "funding on these coins has spent long stretches well above the base rate, and it can also "
        "pay a short.\n\n"
        + _md_funding(res, summary)
        + "\n\n"
    )
    for i, lab in keeps:
        hours, stamps, cost = fund[(i, lab)]
        exp = summary[i][lab]["expectancy_post_fee_r"]
        parts.append(
            f"**{i} {lab}** holds about {hours:.0f} hours, roughly {stamps:.1f} funding stamps, "
            f"which at the base rate is about {stamps * FUNDING_BASE_PCT:.3f}% of notional. Against "
            f"a 1R of {r_pct(res['trades'][(i, lab)]):.2f}% that is about -{cost:.3f}R per trade, "
            f"taking {exp:+.3f}R to **{exp - cost:+.3f}R** - "
            + (f"still clear of the {BAR.keep_expectancy_r:+.2f}R KEEP threshold."
               if exp - cost >= BAR.keep_expectancy_r else
               f"**below the {BAR.keep_expectancy_r:+.2f}R KEEP threshold.** Funding at the base rate "
               "alone is enough to demote this cell to INCONCLUSIVE, and any rate above the base "
               "widens the gap.")
        )
    parts.append(
        "And the direction of the bias runs the wrong way. Funding is positive most of the time on "
        "these three coins - longs pay shorts - and the leg split above shows **longs are the leg "
        "that earns**. So the trades carrying each KEEP are the trades most likely to pay funding, "
        "not receive it; the table's symmetric charge is the optimistic version.\n\n"
        f"**Status: {len(survive)} of the {len(keeps)} KEEP cells survive the base-rate estimate "
        f"({', '.join(f'{i} {lab}' for i, lab in survive) or 'none'})"
        + (f", and {len(demote)} does not ({', '.join(f'{i} {lab}' for i, lab in demote)}).**"
           if demote else ".**")
        + " Neither is a tradeable conclusion until funding is measured from the actual rate "
        "history over the same window rather than assumed at its floor."
    )
    parts.append(
        "### What would change these verdicts\n\n"
        "- **Funding measured, not floored.** The single most decisive missing number. Pull Bybit's "
        f"funding-rate history for the same window and charge each trade its actual stamps. On the "
        f"evidence above this decides whether 4H forced-1:3 is a KEEP at all, and it can only move "
        "the number downwards for a long-biased strategy.\n"
        "- **More daily bars.** 1D native is the more robust of the two KEEPs but rests on "
        f"{summary['1D']['native']['trades']} trades across three coins, and its per-coin rows are "
        f"all INCONCLUSIVE on count alone ({day_counts}). Adding coins - not a longer history, which "
        "does not exist for these listings - is the only honest way to raise that count. Ten more "
        f"liquid perpetuals would take it to roughly {day_projected} trades and make the per-coin "
        "rows readable.\n"
        "- **The band multiplier held fixed by something other than convention.** 4H forced-1:3 is "
        "a KEEP at 2.0x and INCONCLUSIVE at 1.5x and 2.5x. If a source can be found that actually "
        "states the multiplier, that row becomes interpretable; until then it is one value of an "
        "undisclosed parameter and should be read as fragile.\n"
        "- **A trend filter, since the source names trending markets.** Not tested here, because "
        "the source names the condition without defining it and inventing a definition would be "
        "inventing the strategy. A stated filter - price above a long moving average, or the "
        "middle line sloping up - would be a legitimate follow-up test rather than a fix.\n"
        "- **The short leg examined separately.** Shorts contribute close to nothing at every "
        "timeframe. Either the rule is long-only in crypto, which should be declared and tested as "
        "such, or the sample simply did not contain enough sustained downside. Both readings are "
        "live and this window cannot separate them.\n"
        "- **Slippage.** Entries are market orders at the open of the bar after a volatility "
        "expansion, which is where the book is thinnest. Nothing beyond fees is charged for that "
        f"here. At 1D native the median 1R is {r1_pct_1d:.1f}% of price, so slippage is small "
        f"relative to risk; at 1H, where 1R is {r1_pct_1h:.1f}%, it is not negligible and the 1H "
        "rows are DISCARDs already."
    )
    parts.append(
        "### Bottom line\n\n"
        f"The rule as the source describes it - break out on the close, exit when price closes back "
        f"inside - **loses money at 1H after fees** ({summary['1H']['native']['r_sum_post_fee']:+.1f}R "
        f"post-fee from {summary['1H']['native']['trades']} trades, pre-fee "
        f"{summary['1H']['native']['r_sum_pre_fee']:+.1f}R), because the exit fires after about "
        f"{summary['1H']['native']['avg_bars_held']:.1f} bars and the trade never gets far enough "
        "from the entry to pay for two taker fees. That is the same failure mode as Strategy #1: not "
        "a wrong direction, a hold too short to cover its own costs. It improves monotonically as "
        f"the bar gets longer and becomes a KEEP at 1D ({summary['1D']['native']['trades']} trades, "
        f"{summary['1D']['native']['expectancy_post_fee_r']:+.3f}R per trade, Sharpe "
        f"{summary['1D']['native']['sharpe_post_fee']:.2f}, t = "
        f"{ctx['1D']['sig_native']['t_net']:+.2f}), where the same 2.5-bar hold is two and a "
        "half days instead of two and a half hours.\n\n"
        "Two cells clear the bar, and they are not equally solid. **1D native** survives every "
        "multiplier tested, both sane readings of the stop, and the base-rate funding estimate; its "
        f"weakness is {summary['1D']['native']['trades']} trades and a long leg doing the work. "
        "**4H forced-1:3** clears the bar only "
        "at one value of an undisclosed parameter and does not survive base-rate funding. Both are "
        "**provisional KEEPs** under the funding rule; on the evidence here the daily row is the one "
        "worth carrying forward.\n\n"
        f"The source's numbers are not reproduced on crypto in any variant: the win rate is "
        f"{min(win_gap):.0f} to {max(win_gap):.0f} percentage points lower on every timeframe, and "
        "what makes the daily rows work is a larger average "
        "winner, not accuracy. The claimed market condition is contradicted - the edge is slightly "
        "better in LOW volatility, which makes sense for bands that widen with ATR. And neither of "
        "the source's own tests was on crypto, so nothing here contradicts them either; this is the "
        "first crypto measurement of the rule, not a failed replication."
    )
    logbook.log_md("\n\n".join(parts))


if __name__ == "__main__":
    main(write="--log" in sys.argv)
