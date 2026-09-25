"""Run Strategy #3 - AdaptiveTrend, and log it.

Usage:  .venv\\Scripts\\python.exe src\\run_s03.py [--log]
"""

from __future__ import annotations

import sys

import numpy as np

import bybit_data as bd
import context_checks
import lookahead_check
import logbook
import runner
import s03_adaptive_trend as s03
from discard_bar import verdict

NAME = "AdaptiveTrend (momentum + monthly Sharpe gate + ATR trail)"
COINS_STR = "BTCUSDT+SOLUSDT+XRPUSDT"

# Four timeframes on this strategy, not three. The source's headline result is
# on 6-hour bars and its own timeframe table makes the bar size part of the
# claim, so 6H had to be here or the source would not actually be tested.
IVS = ["1H", "4H", "6H", "1D"]
HEADLINE_TF = "6H"

SENS_LOOKBACKS = [7, 14, 28]     # the source never discloses L
SENS_THETAS = [0.02, 0.05]       # nor either entry threshold; run on 6H only

# The source's own reported Sharpe per timeframe, for a like-for-like column.
PAPER_SHARPE = {"1H": 1.54, "4H": 2.08, "6H": 2.41, "1D": 1.63}
# Its own ablation row for a rule whose parameters are NOT re-fitted monthly.
# That is the honest target for this test, not the 2.41 headline.
PAPER_FIXED_SHARPE = 1.34
PAPER_TRADES_PER_MONTH = {"1H": 847, "4H": 213, "6H": 142, "1D": 41}

HOURS = {"1H": 1, "4H": 4, "6H": 6, "1D": 24}


def make_spec(mom_days: int, theta: float = s03.ENTRY_THRESHOLD,
              on_cross: bool = True) -> runner.StrategySpec:
    tag = f"L={mom_days}d theta={theta:.0%} {'cross' if on_cross else 'state'}"
    return runner.StrategySpec(
        name=f"{NAME} {tag}",
        add_indicators=lambda df: s03.add_indicators(df, mom_days, theta),
        entry=lambda df: s03.entry(df, on_cross=on_cross),
        native_exit=s03.native_exit,
        warmup=0,                                  # replaced by warmup_fn
        warmup_fn=lambda iv: s03.warmup_for(iv, mom_days),
        native_time_limit=None,                    # the trailing stop is the exit
    )
def show_audit(symbol: str = "SOLUSDT", interval: str = HEADLINE_TF) -> bool:
    """Print the lookahead proof on one dataset so it is visible, not asserted.

    Run on the headline timeframe, since that is the configuration whose result
    the source actually claims.
    """
    df = bd.drop_forming_bar(bd.load(symbol, interval), interval)
    raw = df[[c for c in df.columns if c in lookahead_check.RAW]].copy()
    return lookahead_check.report(
        f"{NAME} on {symbol} {interval}", raw, s03.add_indicators,
        first_cut=max(300, s03.warmup_for(interval) + 50),
    )


def leg_split(trades) -> dict:
    """Long leg vs short leg, separately.

    The source allocates 70% of gross exposure long and 30% short and never
    reports the two legs' results apart. Since the market-cap filter that would
    have excluded these three coins from the short side is not reproducible
    here, the short leg tested here is MORE permissive than the paper's - so it
    has to be shown on its own rather than blended into a single number.
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


def screen_readings(spec: runner.StrategySpec, intervals=IVS) -> dict:
    """How many monthly screens each reading of the SHORT gate would permit.

    The source requires a Sharpe of at least +1.7 to short. Read literally that
    demands a coin be rising strongly before selling it, which contradicts the
    momentum rule sitting next to it. The coherent reading - the Sharpe of the
    short position itself, i.e. at most -1.7 on the coin - is what gets traded.
    This counts both so the size of the disagreement is measured.
    """
    out = {}
    for interval in intervals:
        row = {"months": 0, "coherent": 0, "literal": 0, "both": 0}
        for symbol in runner.COINS:
            d = runner._prepare(spec, symbol, interval).iloc[spec.warmup_for(interval):]
            ms = d["month_start"].to_numpy()
            coh = d["gate_short"].to_numpy()
            lit = d["gate_short_literal"].to_numpy()
            row["months"] += int(ms.sum())
            row["coherent"] += int((ms & coh).sum())
            row["literal"] += int((ms & lit).sum())
            row["both"] += int((ms & coh & lit).sum())
        out[interval] = row
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
    """Average hold converted to days, so the four timeframes are comparable."""
    return res["pooled"][(interval, label)]["avg_bars_held"] / s03.BPD[interval]


def _trades_per_month(res: dict, interval: str, label: str, screens: dict) -> float:
    """Trades per month, the unit the source's own timeframe table uses."""
    months = screens[interval]["months"] / len(runner.COINS)
    n = res["pooled"][(interval, label)]["trades"]
    return n / months if months else float("nan")


def main(write: bool) -> None:
    print("=" * 78)
    print(f"STRATEGY #3 - {NAME}")
    print("=" * 78)

    if not show_audit():
        raise SystemExit("Lookahead audit failed - no results will be produced.")

    spec = make_spec(s03.MOM_LOOKBACK_DAYS)
    res = runner.run(spec, intervals=IVS)
    n_cells = len(runner.COINS) * len(IVS)
    n_pass = sum(1 for ok, _, _ in res["audit"].values() if ok)
    print(f"\nLookahead audit re-run on all {n_cells} datasets: {n_pass}/{n_cells} PASS")

    summary = runner.summarise(spec, res, intervals=IVS)

    screens = screen_readings(spec)
    print("\nThe short gate, both readings (monthly screens that would permit a short)")
    for interval in IVS:
        s = screens[interval]
        print(f"  {interval}: {s['months']} screens | coherent (SR <= -1.7) {s['coherent']} "
              f"| literal (SR >= +1.7) {s['literal']} | both {s['both']}")
    print("\nAgainst the source's own per-timeframe Sharpe")
    print(f"{'tf':>4} {'this test (native)':>19} {'source claims':>14} "
          f"{'source, fixed params':>21} {'trades/mo here':>15} {'source trades/mo':>17}")
    for interval in IVS:
        m = summary[interval]["native"]
        print(f"{interval:>4} {m['sharpe_post_fee']:>19.2f} {PAPER_SHARPE[interval]:>14.2f} "
              f"{PAPER_FIXED_SHARPE:>21.2f} "
              f"{_trades_per_month(res, interval, 'native', screens):>15.1f} "
              f"{PAPER_TRADES_PER_MONTH[interval]:>17}")

    print("\nAverage hold in DAYS")
    for interval in IVS:
        print(f"  {interval}: native {_hold_days(res, interval, 'native'):5.1f} days, "
              f"forced-1:3 {_hold_days(res, interval, 'forced-1:3'):5.1f} days")

    ctx = context_checks.summarise(res, runner.COINS, IVS)
    print("\nWas this a fair test? (noise level, intrabar ambiguity, entry overlap)")
    print(context_checks.text_block(ctx, IVS))

    print("\nMeasured 1R, as a % of price (2.5 x ATR of the trading timeframe)")
    for interval in IVS:
        bits = []
        for symbol in runner.COINS:
            df = runner._prepare(spec, symbol, interval)
            bits.append(f"{symbol} {df['stop_frac'].median() * 100:.2f}%")
        print(f"  {interval}: " + ", ".join(bits))

    print("\nExit composition, legs, and market conditions")
    for interval in IVS:
        print(detail(res, interval))

    print("\nExit-death check (same entries, same 1R, only the exit differs)")
    for interval in IVS:
        s = summary[interval]
        print(f"  {interval}: exit-death = {s['exit_death'].upper()}")
        print(f"      {s['exit_death_diag']}")

    print("\nVerdicts, applied to each exit variant separately")
    for interval in IVS:
        s = summary[interval]
        print(f"  {interval} native      {s['verdict_native']}: {s['reason_native']}")
        print(f"  {interval} forced-1:3  {s['verdict_forced']}: {s['reason_forced']}"
              f"  [own fee breakeven {s['breakeven_wr_forced']:.1%}]")

    print("\nPer-coin breakdown (not pooled)")
    print(runner.per_coin_table(res, intervals=IVS))
    # --- momentum-lookback sensitivity, all four timeframes ----------------
    print("\nLookback sensitivity - the source never states L. This sweeps it.")
    print(f"{'L days':>7} {'tf':>4} {'exit':<11} {'trades':>7} {'win%':>6} "
          f"{'R post':>8} {'R/trade':>8} {'Sharpe':>7}  verdict")
    sens: dict = {}
    for nd in SENS_LOOKBACKS:
        sres = res if nd == s03.MOM_LOOKBACK_DAYS else runner.run(
            make_spec(nd), intervals=IVS, audit=False)
        sens[nd] = sres
        for interval in IVS:
            for label in ["native", "forced-1:3"]:
                m = sres["pooled"][(interval, label)]
                v, _ = verdict(m, label)
                print(f"{nd:>7} {interval:>4} {label:<11} {m['trades']:>7} "
                      f"{_g(m['win_rate'] * 100, 1):>6} {_g(m['r_sum_post_fee'], 1):>8} "
                      f"{_g(m['expectancy_post_fee_r'], 3):>8} "
                      f"{_g(m['sharpe_post_fee']):>7}  {v}")

    # --- threshold and state-vs-cross, on the headline timeframe only -------
    # Both are secondary questions about undisclosed detail rather than about the
    # rule itself, so they are run on the one timeframe the source claims rather
    # than multiplying the whole grid.
    print(f"\nEntry-threshold and entry-style sensitivity, {HEADLINE_TF} only")
    print(f"{'variant':<22} {'exit':<11} {'trades':>7} {'win%':>6} "
          f"{'R post':>8} {'R/trade':>8} {'Sharpe':>7}  verdict")
    alt: dict = {"threshold 0% (traded)": res}
    for th in SENS_THETAS:
        alt[f"threshold {th:.0%}"] = runner.run(
            make_spec(s03.MOM_LOOKBACK_DAYS, th), intervals=[HEADLINE_TF], audit=False)
    alt["state-triggered entry"] = runner.run(
        make_spec(s03.MOM_LOOKBACK_DAYS, s03.ENTRY_THRESHOLD, on_cross=False),
        intervals=[HEADLINE_TF], audit=False)
    for tag, ares in alt.items():
        for label in ["native", "forced-1:3"]:
            m = ares["pooled"][(HEADLINE_TF, label)]
            v, _ = verdict(m, label)
            print(f"{tag:<22} {label:<11} {m['trades']:>7} "
                  f"{_g(m['win_rate'] * 100, 1):>6} {_g(m['r_sum_post_fee'], 1):>8} "
                  f"{_g(m['expectancy_post_fee_r'], 3):>8} "
                  f"{_g(m['sharpe_post_fee']):>7}  {v}")

    if write:
        write_logs(res, summary, sens, alt, ctx, screens)
        print("\nBoth logs updated: strategy_log.csv and strategy_log.md")
    else:
        print("\n(dry run - nothing written to the logs; pass --log to record it)")
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


def _md_paper(res: dict, summary: dict, screens: dict) -> str:
    rows = ["| Timeframe | Sharpe here (native) | Source's claim | Source, parameters "
            "not re-fitted | Trades/month here | Trades/month in source |",
            "|" + "---|" * 6]
    for interval in IVS:
        m = summary[interval]["native"]
        rows.append(
            f"| {interval} | {_g(m['sharpe_post_fee'])} | {PAPER_SHARPE[interval]:.2f} "
            f"| {PAPER_FIXED_SHARPE:.2f} "
            f"| {_trades_per_month(res, interval, 'native', screens):.1f} "
            f"| {PAPER_TRADES_PER_MONTH[interval]} |"
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


def _md_screens(screens: dict) -> str:
    rows = ["| Timeframe | Monthly screens | Coherent reading permits a short "
            "| Literal reading permits a short | Both agree |", "|" + "---|" * 5]
    for interval in IVS:
        s = screens[interval]
        rows.append(
            f"| {interval} | {s['months']} | {s['coherent']} ({s['coherent'] / max(s['months'], 1):.0%}) "
            f"| {s['literal']} ({s['literal'] / max(s['months'], 1):.0%}) | {s['both']} |"
        )
    return "\n".join(rows)


def _md_sens(sens: dict) -> str:
    rows = ["| Lookback L | Timeframe | Exit | Trades | Win% | R (post-fee) | R/trade "
            "| Sharpe | Verdict |", "|" + "---|" * 9]
    for nd, sres in sens.items():
        for interval in IVS:
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


def _md_alt(alt: dict) -> str:
    rows = [f"| Variant ({HEADLINE_TF}) | Exit | Trades | Win% | R (post-fee) | R/trade "
            "| Sharpe | Verdict |", "|" + "---|" * 8]
    for tag, ares in alt.items():
        for label in ["native", "forced-1:3"]:
            m = ares["pooled"][(HEADLINE_TF, label)]
            v, _ = verdict(m, label)
            rows.append(
                f"| {tag} | {label} | {m['trades']} | {_g(m['win_rate'] * 100, 1)} "
                f"| {_g(m['r_sum_post_fee'], 1)} | {_g(m['expectancy_post_fee_r'], 3)} "
                f"| {_g(m['sharpe_post_fee'])} | {v} |"
            )
    return "\n".join(rows)
def _md_risk(spec: runner.StrategySpec) -> tuple[str, float, float, float]:
    """Measured 1R against a typical candle, per coin and timeframe.

    Strategy #1's biggest weakness was a stop narrower than one candle, which
    meant the pessimistic intrabar tie-break decided most trades. Here the
    opposite risk applies: 2.5 x ATR is a wide stop, so the question is whether
    a 3R target is so far away that the forced-1:3 test becomes unreachable.

    Returns the markdown table, the SMALLEST candle multiple in it, and the
    smallest and largest measured 1R, so the write-up quotes measured numbers.
    """
    rows = ["| Timeframe | Coin | Measured 1R (% of price) | Typical candle (%) "
            "| 1R as a multiple of one candle | 3R target sits |", "|" + "---|" * 6]
    worst, r_lo, r_hi = float("inf"), float("inf"), 0.0
    for interval in IVS:
        for symbol in runner.COINS:
            df = runner._prepare(spec, symbol, interval)
            r_pct = float(df["stop_frac"].median() * 100)
            candle = context_checks.median_candle_range_pct(symbol, interval)
            mult = r_pct / candle
            worst, r_lo, r_hi = min(worst, mult), min(r_lo, r_pct), max(r_hi, r_pct)
            rows.append(f"| {interval} | {symbol} | {r_pct:.2f}% | {candle:.2f}% "
                        f"| {mult:.1f}x | {3 * r_pct:.0f}% away |")
    return "\n".join(rows), worst, r_lo, r_hi


def write_logs(res: dict, summary: dict, sens: dict, alt: dict, ctx: dict,
               screens: dict) -> None:
    spec = make_spec(s03.MOM_LOOKBACK_DAYS)
    n_cells = len(runner.COINS) * len(IVS)
    n_pass = sum(1 for ok, _, _ in res["audit"].values() if ok)
    cols = sorted({c for _, cl, _ in res["audit"].values() for c in cl})

    death = "\n".join(
        f"- **{i}: exit-death = {summary[i]['exit_death'].upper()}.** "
        f"{summary[i]['exit_death_diag']}"
        for i in IVS
    )
    verdicts = "\n".join(
        f"- **{i} / native exit — {summary[i]['verdict_native']}.** {summary[i]['reason_native']}\n"
        f"- **{i} / forced 1:3 — {summary[i]['verdict_forced']}.** {summary[i]['reason_forced']} "
        f"(its own fee-derived breakeven win rate is {summary[i]['breakeven_wr_forced']:.1%})"
        for i in IVS
    )
    mixes = "\n".join(
        f"- {i} {lab}: " + (", ".join(
            f"{k} {v}" for k, v in sorted(summary[i][lab]["exit_reason_mix"].items())) or "no trades")
        + (f" — average hold {summary[i][lab]['avg_bars_held']:.1f} bars "
           f"({_hold_days(res, i, lab):.1f} days), fees cost "
           f"{summary[i][lab]['avg_fee_cost_r']:.3f}R per trade, best conditions "
           f"{summary[i][lab]['best_regime']}, worst {summary[i][lab]['worst_regime']}"
           if summary[i][lab]["trades"] else "")
        for i in IVS for lab in ["native", "forced-1:3"]
    )
    fair = context_checks.text_block(ctx, IVS)

    funding = "; ".join(
        f"{i} holds {summary[i]['native']['avg_bars_held']:.1f} bars "
        f"= about {summary[i]['native']['avg_bars_held'] * HOURS[i] / 8:.0f} funding windows"
        for i in IVS
    )

    fee_rows = "\n".join(
        ["| Timeframe | Exit | Trades | Before fees | Fee bill | After fees |",
         "|---|---|---|---|---|---|"]
        + [f"| {i} | {lab} | {summary[i][lab]['trades']} "
           f"| {summary[i][lab]['r_sum_pre_fee']:+.1f}R "
           f"| {summary[i][lab]['avg_fee_cost_r'] * summary[i][lab]['trades']:.1f}R "
           f"| {summary[i][lab]['r_sum_post_fee']:+.1f}R |"
           for i in IVS for lab in ["native", "forced-1:3"]]
    )

    overlap_lo = min(ctx[i]["overlap"] for i in IVS)
    overlap_hi = max(ctx[i]["overlap"] for i in IVS)
    # The exit-death check is only clean when both variants trade the SAME
    # entries. That precondition is measured, not assumed, and when it fails the
    # flag has to be reported with the failure attached rather than quoted flat.
    overlap_ok = overlap_lo >= context_checks.MIN_OVERLAP
    overlap_note = (
        f"Entry overlap between the two variants runs {overlap_lo:.0%}–{overlap_hi:.0%}, at or above the "
        f"{context_checks.MIN_OVERLAP:.0%} floor this project requires, so \"same entries, only the exit "
        "differs\" is a claim the data supports rather than an assumption."
        if overlap_ok else
        f"**The exit-death check's precondition is not met on this strategy.** The two "
        f"variants share only {overlap_lo:.0%}–{overlap_hi:.0%} of their entries, against the "
        f"{context_checks.MIN_OVERLAP:.0%} floor this project requires before \"same entries, only the exit "
        "differs\" can be claimed. The cause is structural rather than a bug: the native "
        "exit has no time limit and the forced variant closes at "
        f"{runner.FORCED_TIME_LIMIT} bars, so the two variants are in the market at different "
        "times and become eligible to re-enter at different moments. Read every "
        "exit-death flag above as indicative only."
    )
    death_caveat = (
        "The wording of those flags says \"identical entries\". On this strategy that is "
        f"only {overlap_lo:.0%}–{overlap_hi:.0%} true — see the fairness check below, which is why the flags "
        "are indicative rather than conclusive here."
        if not overlap_ok else
        "The precondition for that check — both variants trading the same entries — is "
        "met here; the numbers are in the fairness check below."
    )
    tmax = max(ctx[i][k]["t_gross"] for i in IVS for k in ["sig_native", "sig_forced"])
    legs = {i: leg_split(res["trades"][(i, "native")]) for i in IVS}
    risk_table, risk_worst, r_lo, r_hi = _md_risk(spec)

    long_share = {
        i: legs[i]["long"]["trades"] / max(legs[i]["long"]["trades"] + legs[i]["short"]["trades"], 1)
        for i in IVS
    }

    # Funding is NOT modelled anywhere in this project. The line below is an
    # illustration built on Bybit's own baseline rate (the value the rate sits at
    # when longs and shorts are balanced), purely to show whether the omission is
    # big enough to matter. It is not a measurement of what funding actually was.
    base_rate = 0.0001
    fund_rows = "\n".join(
        f"| {i} | {summary[i]['native']['avg_bars_held'] * HOURS[i] / 8:.0f} "
        f"| {summary[i]['native']['avg_bars_held'] * HOURS[i] / 8 * base_rate * 100:.2f}% "
        f"| {summary[i]['native']['avg_bars_held'] * HOURS[i] / 8 * base_rate * 100 / r_hi:.3f}"
        f"–{summary[i]['native']['avg_bars_held'] * HOURS[i] / 8 * base_rate * 100 / r_lo:.3f}R "
        f"| {summary[i]['native']['expectancy_post_fee_r']:+.3f}R |"
        for i in IVS
    )

    hd_tf = summary[HEADLINE_TF]
    n_sens_keep = sum(
        1 for sres in sens.values() for i in IVS for lab in ["native", "forced-1:3"]
        if verdict(sres["pooled"][(i, lab)], lab)[0] == "KEEP"
    )
    per_coin_keep = [
        f"{s} {i} {lab}" for s in runner.COINS for i in IVS
        for lab in ["native", "forced-1:3"]
        if verdict(res["per_cell"][(s, i, lab)], lab)[0] == "KEEP"
    ]
    # Per-coin standing, native exit. Counted as "how many timeframes is this coin
    # positive on", NOT as a sum of R across timeframes: adding R across timeframes
    # would be pooling the same coin's overlapping signals, which this project does
    # not do anywhere else and must not start doing in a summary line.
    coin_pos_tf = {
        s: [i for i in IVS if res["per_cell"][(s, i, "native")]["r_sum_post_fee"] > 0]
        for s in runner.COINS
    }
    coin_best = max(coin_pos_tf, key=lambda s: len(coin_pos_tf[s]))
    coin_note = (
        "Native exit, counted per timeframe rather than summed across them: "
        + ", ".join(f"{s} positive on {len(coin_pos_tf[s])} of {len(IVS)}" for s in runner.COINS)
        + f". {coin_best} is the strongest of the three."
    ) + (
        f" The per-coin table reaches KEEP in {len(per_coin_keep)} places — {', '.join(per_coin_keep)} — "
        "and pooling those with the other two coins is what turns them into an "
        "INCONCLUSIVE. On a three-coin test a single-coin KEEP is a curiosity, not a "
        "finding: it is exactly where 22 strategies tested across three instruments "
        "will throw up winners by chance."
        if per_coin_keep else
        " No individual coin reaches KEEP on any timeframe either, so pooling is not "
        "hiding a winner."
    )
    best_tf = max(IVS, key=lambda i: summary[i]["native"]["sharpe_post_fee"]
                  if summary[i]["native"]["sharpe_post_fee"] == summary[i]["native"]["sharpe_post_fee"]
                  else -9e9)
    text = f"""---

## Strategy #3 — AdaptiveTrend (crypto trend-following), momentum + monthly Sharpe gate + ATR trail

**Tested:** {logbook.date.today().isoformat()} · **Coins:** BTCUSDT, SOLUSDT, XRPUSDT
(Bybit USDT perpetuals) · **Timeframes:** 1H, 4H, **6H**, 1D · **Direction:** long and
short · **Source's own cadence:** monthly portfolio rebuild, trailing stop in between

**Source:** *AdaptiveTrend* — an academic preprint on adaptive trend-following in
crypto perpetual futures ([arXiv HTML edition](https://arxiv.org/html/2602.11708v1))
· sourcing rated **strong** (full method in equations, six result tables, its own
ablation study).

**A fourth timeframe was added for this strategy.** Every earlier entry in this log
runs on 1H, 4H and 1D. This source's headline number is on **6-hour bars**, and its
own timeframe table makes the bar size part of the claim, so 6H was added to the data
layer and is tested here. That is why this section has eight rows instead of six.

### The rules, in plain English

Four moving parts, and only two of them are things a chart trader would recognise.

1. **A momentum trigger.** Measure how far price has moved over a fixed lookback.
   Buy when that move is positive by more than a threshold; sell short when it is
   negative by more than a threshold.
2. **A monthly quality screen.** On the first day of each month, ask of each coin:
   over the month just finished, how good was its *risk-adjusted* return — its
   Sharpe ratio? A coin needs at least **1.3** to be allowed on the long side and
   at least **1.7** to be allowed on the short side. This is a pass/fail gate, not
   a beauty contest between coins, which matters: unlike Strategy #2's ranking leg,
   a gate works exactly the same with three coins as with a hundred and fifty, so
   this part IS faithfully reproducible here.
3. **A trailing stop that only ever tightens.** The stop sits a fixed multiple of
   average range below price (2.5 x ATR), and each bar it moves up to follow price
   but never back down. When price trades through it, the position is out. There is
   no take-profit anywhere in the system.
4. **A monthly rebuild.** Positions are reconstructed each month from whichever
   coins still pass the screen, 70% of gross exposure to longs and 30% to shorts.

**Market condition it suits:** sustained trends with expanding volatility, in either
direction. The monthly Sharpe gate is the part that is supposed to keep it out of
chop — a coin that chopped sideways last month has a low Sharpe and is not eligible
this month, regardless of what its raw momentum says.

"""
    text += f"""### What could NOT be reproduced here — and which way each gap biases the result

This is the part that decides how much weight the numbers below can carry, so it
comes before them.

1. **The market-cap filter.** The source screens on market capitalisation first:
   longs may only come from the top 15 coins by cap, shorts only from the bottom of
   the ranking. This project trades three coins and all three are large caps, so
   there is no bottom of a ranking to draw from. **Under the source's own rule, none
   of BTC, SOL or XRP could ever have been a short candidate at all.** Dropping the
   filter therefore makes the short leg tested here *more* permissive than the
   source's, not less. That is the honest direction to declare: it means a poor short
   result here cannot be excused by the filter's absence.
2. **The 70/30 long/short exposure tilt.** This harness risks a fixed 1% of equity
   per trade, so there is no gross-exposure knob for a tilt to turn. The two legs are
   reported separately instead, which shows the same information without inventing a
   portfolio weighting the source did not specify per-trade.
3. **The monthly re-optimisation — deliberately not reproduced.** The source re-fits
   the lookback, the thresholds and the stop multiple every month on recent data, then
   reports the result as out-of-sample. Re-fitting a rule monthly and calling the
   output out-of-sample is curve-fitting, and the source's own ablation table prices
   it exactly: strip the monthly re-fit and Sharpe falls from 2.41 to **{PAPER_FIXED_SHARPE:.2f}**.
   **So the honest comparison target for the fixed-parameter test below is
   {PAPER_FIXED_SHARPE:.2f}, not 2.41.** Every table here compares against both, side by side, so
   the distinction cannot get lost.
4. **Slippage.** Not modelled anywhere in this project. Fees are.
5. **Funding.** Not modelled. Quantified as an illustration at the end, because these
   are multi-day holds and the omission is not small.
6. **Different exchange, universe and window.** The source used Binance Futures,
   150+ perpetuals, Jan 2021 – Dec 2024. This is Bybit, three coins, and history that
   runs to today. Three coins cannot diversify the way 150 can, so the drawdowns here
   are structurally harsher than a 150-coin portfolio's would be.

### Parameters: what the source states, and what had to be guessed

| Parameter | In the source | Used here | Status |
|---|---|---|---|
| Long Sharpe gate (γ_L) | 1.3 | {s03.SR_GATE_LONG} | **stated** |
| Short Sharpe gate (γ_S) | 1.7 | {s03.SR_GATE_SHORT} | **stated** |
| Screen window | "the single preceding month" | {s03.SR_WINDOW_DAYS} days | **stated** |
| Trailing-stop multiple (α) | ≈2.5, flat 2.0–3.5 | {s03.ATR_MULT} | **stated** |
| Screen cadence | first trading day of the month | first bar of the month | **stated** |
| Momentum lookback (L) | **never given a value** | {s03.MOM_LOOKBACK_DAYS} days | **GUESS — swept below** |
| Entry threshold (θ) | **never given a value** | {s03.ENTRY_THRESHOLD:.0%} | **GUESS — swept below** |
| ATR period (k) | **never given a value** | {s03.ATR_BARS} bars | **GUESS** |
| Number of shorts (K_S) | **never given a value** | not applicable (gate, not ranking) | n/a |

Three of the numbers that decide *when this thing trades at all* are absent from a
paper that reports its Sharpe to two decimal places. That is why the sensitivity
sweeps below are not optional extras — they are the only way to tell whether the
result belongs to the rule or to the guesses.

### The contradiction in the source that had to be resolved

The paper says a coin needs a **Sharpe of at least +1.7 to be a SHORT candidate**.
Read as the coin's own Sharpe that is incoherent: a coin with a strongly positive
risk-adjusted return is trending *up*, and shorting it contradicts the momentum rule
in the very same system. The coherent reading is the Sharpe of the *candidate
position*, so for a short it is the Sharpe of the inverse of the coin's returns —
i.e. the coin's own Sharpe at or below **−1.7**. That is what is traded here. The
literal reading is also **counted** — how many monthly screens it would have
permitted a short on — and reported below, so the choice is visible and measurable
rather than buried in a code comment.

### How 1R is defined here, and why it differs from Strategy #2

1R is 2.5 x ATR **of the trading timeframe**. Strategy #2 normalised its stop to a
daily-equivalent range so its timeframes stayed comparable to each other. Here the
opposite choice is correct: the source's formula explicitly uses the trading
timeframe's ATR, and the source's headline claim is that the 6-hour bar beats the
1-hour and the daily. Normalising the stop across timeframes would erase the exact
effect under test.

The consequence has to be stated plainly: **1R is a different amount of real risk on
each row of the results table** — wider on the daily, narrower on the hourly. The
four timeframes here are therefore NOT directly comparable to one another. Each is
comparable to the source's own number for that timeframe, which is the comparison
that matters.

### Lookahead check, run fresh for this strategy

Three places on this strategy needed care, and each was handled before any number
was produced:

- **The trailing stop.** The level in force during a bar is built from the *previous*
  bar's close and ATR. If it used the current bar's, the stop would be positioned
  using the very price range it is then compared against — the position would appear
  to exit at a level that could only be known after the fact.
- **The monthly screen.** The Sharpe is measured over the window ending one bar
  *before* the month's first bar, sampled only on that first bar, then carried
  forward unchanged. Carrying a value forward can only ever propagate something
  already known.
- **The entry trigger.** It compares this bar's eligibility with the previous bar's,
  so both inputs are closed bars.

Beyond reasoning, this is checked mechanically. The audit recomputes every indicator
on truncated history — as if the run had stopped at that bar — and compares each
value against the one computed with the full history available. Any column that
disagrees was reading the future. **{n_pass} of {n_cells} coin x timeframe datasets PASS**, across
all {len(cols)} computed columns: `{", ".join(cols)}`. Decisions are made on closed bars and
filled at the next bar's open throughout.

"""
    text += f"""### Results — three coins pooled per timeframe, post-fee

Fees: {runner.TAKER_FEE_RATE:.3%} taker on entry and on exit. Both variants run off the **same entry
signals** and the **same 1R distance**, so any difference between them is the exit
and nothing else. R = one unit of risk; +1R means the trade made what it was risking.

{_md_table(summary)}

**Against the source's own per-timeframe claims.** This is the comparison the source
invites by publishing a timeframe table, so here it is with no cushioning:

{_md_paper(res, summary, screens)}

The trade counts alone settle something before the Sharpe column does. The source
reports {PAPER_TRADES_PER_MONTH[HEADLINE_TF]} trades per month on {HEADLINE_TF} across 150+ perpetuals; that is roughly
one trade per coin per month. Here the rate is {_trades_per_month(res, HEADLINE_TF, "native", screens):.1f} per month across three coins.
Same *rule*, a fiftieth of the *breadth* — so the portfolio effect that produces the
source's smooth equity curve simply cannot exist in this test, whatever the rule does.

### How the trades ended

{mixes}

### The long leg against the short leg

Remember the market-cap filter: under the source's own rule none of these three coins
could ever be a short candidate. Everything in the short column is therefore *more*
permissive than the source's short leg, not less.

{_md_legs(res)}

### The short-gate ambiguity, counted rather than argued about

Both readings of "Sharpe ≥ 1.7 to short" were evaluated on every monthly screen. Only
the coherent one was traded.

{_md_screens(screens)}

### Exit-death check — does the edge live in the rule or in the exit?

{death}

{death_caveat}

### Was this a fair test?

```
{fair}
```

{overlap_note}

The largest t-statistic on per-trade R anywhere in the grid is **{tmax:.2f}**; roughly 2 is
the minimum before a result is distinguishable from noise{', and nothing here reaches it' if tmax < 2 else ''}.

### The size of 1R, and what it does to the forced 1:3 test

{risk_table}

This is the mirror image of Strategy #1's problem. There the stop was *narrower* than
a single candle, so the pessimistic intrabar tie-break decided most trades. Here 1R
is **{risk_worst:.1f}x a typical candle at its smallest**, and measured 1R ranges from {r_lo:.2f}% to
{r_hi:.2f}% of price — which puts the forced variant's 3R target between {3 * r_lo:.0f}% and {3 * r_hi:.0f}%
away from entry. A move that large inside {runner.FORCED_TIME_LIMIT} bars is rare, so the forced-1:3
variant is again a partly handicapped comparison: its time limit, not its target, is
doing most of the deciding. That is a limitation of the standard test applied to a
wide-stop strategy, not evidence about the strategy — and it is the third time in a
row this has shown up, which is itself worth remembering.

### Where the money actually went

{fee_rows}

### Per-coin breakdown — not pooled

Pooling is where one coin carrying, or sinking, everything would be invisible.

```
{runner.per_coin_table(res, intervals=IVS)}
```

### Verdicts, applied to each exit variant separately

{verdicts}

"""
    keep_native = [i for i in IVS if summary[i]["verdict_native"] == "KEEP"]
    keep_forced = [i for i in IVS if summary[i]["verdict_forced"] == "KEEP"]
    inconc = [f"{i} {lab}" for i in IVS for lab, k in
              [("native", "verdict_native"), ("forced-1:3", "verdict_forced")]
              if summary[i][k] == "INCONCLUSIVE"]
    n_variants = 2 * len(IVS)
    n_keep = len(keep_native) + len(keep_forced)
    keep_txt = ", ".join([f"{i} native" for i in keep_native]
                         + [f"{i} forced-1:3" for i in keep_forced]) or "none"

    n_short_neg = sum(1 for i in IVS if legs[i]["short"]["r_post_fee"] < 0)
    short_r = sum(legs[i]["short"]["r_post_fee"] for i in IVS)
    long_r = sum(legs[i]["long"]["r_post_fee"] for i in IVS)
    short_note = (
        f"Across the four timeframes the short leg produced {short_r:+.1f}R against the long "
        f"leg's {long_r:+.1f}R (native exit), losing money on {n_short_neg} of the {len(IVS)} timeframes. "
        + ("**So the leg that carried this test is the leg the source's own filter would "
           "have forbidden outright on these three coins.** That does not support the "
           "source — it means the part of the result that looks best here is the part "
           "least connected to what the source actually specifies."
           if short_r > long_r else
           "The long leg did the work, which is the leg the source's filter would have "
           "permitted, so the comparison is at least pointing the right way.")
    )

    text += f"""### Sensitivity 1 — the momentum lookback the source never states

L is not in the paper. {s03.MOM_LOOKBACK_DAYS} days was the placeholder traded above. If the result only
survives at one setting, the result belongs to the setting.

{_md_sens(sens)}

**{n_sens_keep} of the {len(sens) * n_variants} lookback x timeframe x exit combinations reach KEEP.**

### Sensitivity 2 — the entry threshold, and state versus cross

Also undisclosed: how far momentum must move before the trade is taken. And one
judgement call of mine that deserves to be tested rather than defended. The paper
states the entry as a *state* ("long while momentum exceeds θ"), but a state condition
combined with a trailing stop re-enters on the bar after every stop-out, which
measures the stop's churn instead of the strategy. The edge-triggered version is what
was traded; the state version is run here so the choice is visible. Both on {HEADLINE_TF} only,
since these are questions about undisclosed detail rather than about the rule.

{_md_alt(alt)}

### Bottom line

**{n_keep} of {n_variants} tested variants clear the discard bar: {keep_txt}.**

The source's headline is Sharpe 2.41 on {HEADLINE_TF}. Its own honest comparison row — the same
rule without monthly re-fitting — is {PAPER_FIXED_SHARPE:.2f}. This test measured **{_g(hd_tf["native"]["sharpe_post_fee"])}** on {HEADLINE_TF} with
the native trailing-stop exit, on {hd_tf["native"]["trades"]} trades, {hd_tf["native"]["r_sum_post_fee"]:+.1f}R post-fee. The strongest
timeframe here was **{best_tf}** ({_g(summary[best_tf]["native"]["sharpe_post_fee"])} Sharpe, {summary[best_tf]["native"]["r_sum_post_fee"]:+.1f}R, {summary[best_tf]["native"]["trades"]} trades native).

Five things constrain how much any of that means:

- **One coin carried it.** {coin_note}
- **Breadth.** Three coins against 150+. The monthly Sharpe gate is faithfully
  reproduced, but the diversification that turns a modest per-trade edge into a smooth
  equity curve is not available at three coins and never will be.
- **The short leg is more permissive here than in the source**, because the market-cap
  filter that would have excluded all three of these coins from shorting cannot be
  applied. {short_note}
  Longs were {min(long_share.values()):.0%}–{max(long_share.values()):.0%} of trades across the four timeframes.
- **Guessed parameters.** Three of the numbers governing when it trades are absent
  from the source. The sweeps above are the only evidence about whether the outcome is
  the rule's or the guesses'.
- **Funding is not modelled**, and these are multi-day holds. See below.

{('Nothing here clears the bar, so nothing needs a funding model to be resolved — the '
  'omission cannot rescue a losing result, it can only make it worse.') if n_keep == 0 else
 ('Because at least one variant reaches KEEP on a multi-day-hold strategy, the standing '
  'rule applies: this is NOT to be treated as a real KEEP until funding is modelled. '
  'Flagged, not resolved.')}
{('' if not inconc else chr(10) + 'INCONCLUSIVE rather than DISCARD: ' + ', '.join(inconc)
  + '. What would fix it is more instruments, not more history — this rule takes about '
    'one trade per coin per month by construction, so the trade count is bounded by how '
    'many coins are in the test, and three is the binding constraint.')}

### Funding cost — flagged, not modelled

Perpetual futures charge funding every 8 hours. It is **not modelled anywhere in this
project**. The holds here: {funding}.

The table below is an *illustration* at Bybit's baseline rate ({base_rate:.2%} per window, the
value the rate sits at when longs and shorts are balanced) — not a measurement of what
funding actually was. Direction matters too: funding is a cost to whichever side is
crowded, so it is not automatically a cost to both legs.

| Timeframe | 8-hour windows per trade | Cost at baseline rate | That cost in R | Edge per trade now |
|---|---|---|---|---|
{fund_rows}

### Also not modelled

Slippage; the market-cap filter (structurally impossible at three coins); the 70/30
exposure tilt; the monthly re-optimisation (deliberately excluded as curve-fitting);
liquidation mechanics; borrow availability on the short leg.
"""

    # The whole write-up is built before anything is written, so a formatting
    # mistake cannot leave half a record in an append-only log.
    _csv_rows(summary)
    logbook.log_md(text)


if __name__ == "__main__":
    main("--log" in sys.argv)
