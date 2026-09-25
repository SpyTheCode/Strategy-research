"""Run Strategy #7 - Turtle / Donchian 20-day breakout (System 1), and log it.

Usage:  .venv\\Scripts\\python.exe src\\run_s07.py [--log]

The full run is ~40 minutes of simulation, so before the logs are rendered every
computed object is snapshotted to SNAPSHOT. `--render` skips the simulation and
re-renders the logs from that snapshot, which turns a formatting mistake in the
log prose into a seconds-long retry instead of another 40-minute run.
"""

from __future__ import annotations

import pickle
import sys

import numpy as np
import pandas as pd

import bybit_data as bd
import context_checks
import coverage
import lookahead_check
import logbook
import runner
import s07_turtle_donchian as s07
from discard_bar import BAR, EXIT_DEATH_GAP_R, exit_death, verdict
from harness import metrics

SNAPSHOT = r"c:\tmp\s07_bundle.pkl"

NAME = ("Turtle/Donchian 20-day breakout, System 1 (enter a new 20-day extreme, "
        "2N stop with N the 20-day ATR, exit on the 10-day channel, no pyramiding)")
COINS_STR = "BTCUSDT+SOLUSDT+XRPUSDT"

IVS = ["1H", "4H", "6H", "1D"]

# 1D is the headline. Unlike Strategy #6, this rule DOES have a home bar size: the
# Turtles traded daily bars, the channel and the ATR are both written in days, and
# a daily chart is the only timeframe where "20-day high" needs no translation.
# 1H is reported beside it as the densest sample - the most trades, so the least
# noise - not as the preferred reading.
HEADLINE_TF = "1D"
DENSE_TF = "1H"

# The source's own claim, and how little of it there is. Every per-trade field is
# None on purpose: the article publishes no win rate, no reward-to-risk, no
# Sharpe, no drawdown and no trade count. The only figure it gives is a dollar
# total its own author calls "completely misleading", so there is nothing here to
# match this test against on outcome.
SRC = {"what": "43 futures markets 2007-2025, bar size not stated (RogueQuant)",
       "rr": None, "win": None, "sharpe": None, "dd": None, "trades": None,
       "only_figure": "$1,147,318 total profit across all 43 markets",
       "author_says": "completely misleading"}

LABELS = ["native", "forced-1:3"]


def make_spec(entry_days: int = s07.ENTRY_DAYS, exit_days: int = s07.EXIT_DAYS,
              n_days: int = s07.N_DAYS, stop_n: float = s07.STOP_N,
              scale: str = s07.SCALE_DAY, long_only: bool = False,
              use_2n: bool = True, use_channel: bool = True,
              ratchet: bool = False, resting: bool = False) -> runner.StrategySpec:
    bits = [f"{entry_days}/{exit_days}d", f"{stop_n:g}N"]
    if scale != s07.SCALE_DAY:
        bits.append("bar-native")
    if long_only:
        bits.append("long-only")
    if not use_2n:
        bits.append("no-2N-stop")
    if not use_channel:
        bits.append("no-channel-exit")
    if ratchet:
        bits.append("ratcheted")
    if resting:
        bits.append("resting-stop-fill")
    return runner.StrategySpec(
        name=f"{NAME} [{' '.join(bits)}]",
        add_indicators=lambda df: s07.add_indicators(
            df, entry_days, exit_days, n_days, stop_n, scale, long_only, resting),
        entry=(s07.resting_entry_stub if resting else s07.entry),
        native_exit=lambda df: s07.native_exit(df, use_2n, use_channel, ratchet),
        warmup=0,
        warmup_fn=lambda iv: s07.warmup_for(iv, entry_days, n_days, scale),
        native_time_limit=None,      # the source names no time limit
        resting=resting,
    )


def show_audit(symbol: str = "BTCUSDT", interval: str = HEADLINE_TF) -> bool:
    """Print the lookahead proof on one dataset so it is visible, not asserted."""
    df = bd.drop_forming_bar(bd.load(symbol, interval), interval)
    raw = df[[c for c in df.columns if c in lookahead_check.RAW]].copy()
    return lookahead_check.report(
        f"{NAME} on {symbol} {interval}", raw, s07.add_indicators,
        first_cut=max(300, s07.warmup_for(interval) + 50),
    )


# ---------------------------------------------------------------------------
# Measurements this strategy needs that the shared code does not provide
# ---------------------------------------------------------------------------

def r_pct(trades) -> float:
    """Median 1R as a percentage of the entry price, from real fills.

    Not read off the indicator: taken from the trades that happened, so it is the
    risk that was really carried. 2N on these coins is wide, and how wide is the
    single most important number for judging whether the stop is a stop at all.
    """
    v = [abs(t.risk_per_unit) / t.entry_price * 100.0
         for t in trades if t.entry_price and np.isfinite(t.risk_per_unit)]
    return float(np.median(v)) if v else float("nan")


def wrong_side(trades) -> int:
    """Fills that landed on the far side of their own stop level.

    1R is a FRACTION fixed on the signal bar and resolved against the fill, so the
    stop moves with the fill and this should be structurally impossible. Counted
    anyway, because "should be" is not a measurement.
    """
    return sum(1 for t in trades
               if (t.entry_price - t.initial_stop) * t.direction <= 0)


def signal_counts(**kw) -> tuple[int, int]:
    """(breakout signals fired, signals with a measurable 1R) across all twelve datasets.

    A signal is unusable when N has not formed yet, which after the warmup should
    never happen. Counted off the indicator columns rather than off the trades, so
    it does not depend on which signals the engine happened to be flat for.
    """
    fired = usable = 0
    for symbol in runner.COINS:
        for interval in IVS:
            df = bd.drop_forming_bar(bd.load(symbol, interval), interval)
            f = s07.add_indicators(df, **kw)
            w = s07.warmup_for(interval, kw.get("entry_days", s07.ENTRY_DAYS),
                               kw.get("n_days", s07.N_DAYS),
                               kw.get("scale", s07.SCALE_DAY))
            sub = f.iloc[w:]
            sig = sub["turt_long_entry"] | sub["turt_short_entry"]
            fired += int(sig.sum())
            usable += int((sig & sub["turt_stop_frac"].notna()
                           & (sub["turt_stop_frac"] > 0)).sum())
    return fired, usable


def loss_tail(trades) -> dict:
    """Losses bigger than the 1R they were sold as.

    The 2N stop is a fixed floor and the channel exit only ever sits at or above
    it, so a loss should not exceed one unit of risk except when a bar gaps
    through the level. This is the measurement that shows whether that holds - and
    in the no-2N sensitivity, where the channel exit is alone and free to drift
    away from the trade, it is the measurement that shows what the floor was worth.
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

    The discard bar does not test this, and on a trend-following rule it is the
    first thing that should be checked. The Turtles' documented return profile is
    a few very large winners paying for many small losses, so a lopsided
    distribution is not a defect here - it is the system working as designed. What
    matters is whether the average R per trade is a number anybody could have
    traded, or whether it is one trade wearing a trench coat.
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
    """Long leg vs short leg.

    The rule is symmetric and the source's own retelling is not - it calls the
    system long-only in one sentence and describes selling the 20-day low in the
    next. This is the measurement that decides whether that matters.
    """
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

    The source says this rule wants "strong trends" and "loses steadily in
    ranges". The regime label is two halves joined by a slash (trend then
    volatility); this keeps only the trend half, so the claim is checked directly.
    "trending" pools up and down, because the rule is symmetric and the claim is
    about trend, not direction.

    One limit, stated because it decides how much the answer is worth: the label
    is assigned at ENTRY, and a breakout by definition enters before a 100-bar
    average has turned. A breakout that becomes a trend therefore books its profit
    under whatever label was true the moment it started. So this can show whether
    the label works as a FILTER; it cannot cleanly confirm or refute the claim.
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
    """{exit reason: (count, mean net R)}. Says what each exit route costs.

    On this strategy it is nearly useless on its own and that is worth knowing:
    the engine records "stop" for ANY intrabar stop, and both of this rule's exits
    - the 2N floor and the 10-day channel - are intrabar stops. `which_stop` below
    splits them apart, and the three-way exit decomposition settles it properly.
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
    signal, and here the gap is extreme by design: the native rule has no time
    limit at all and can hold a Donchian breakout for months, while the forced
    variant is capped at 30 bars. So the forced run takes entries the native run
    was still holding through, and comparing the full runs mixes two effects - the
    exit, and a different set of trades. This strips the second one out. It is the
    fair exit-death comparison; the standard one is reported beside it because that
    is the project's defined check.
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
    candles. That is the wrong figure to quote here, and this rule is the clearest
    case in the log of why: 1R is 2N where N is a DAY-scale range, so 1R is roughly
    the same percentage of price on all four timeframes while the candle it is
    measured against shrinks by 24x from daily to hourly. The per-cell ratio is the
    honest figure and the spread between cells is the finding.
    """
    out = []
    for symbol in runner.COINS:
        for interval in IVS:
            rng = context_checks.median_candle_range_pct(symbol, interval)
            if rng > 0:
                out.append(r_pct(res["trades"][(symbol, interval, "native")]) / rng)
    return out


# --- which of the two stops actually fired, and what execution costs -----------
# Both of this rule's exits are intrabar stops, so `exit_reason` cannot tell them
# apart: every native trade comes back "stop". These two measurements rebuild the
# frames the run traded and read the levels back off them at the recorded
# timestamps. That is legitimate because Trade.entry_time and Trade.exit_time are
# the open_time of the bar the fill happened on, so the lookup is a lookup of
# something that was already on the chart - no future bar is consulted.

_PREP: dict = {}


def prepared(symbol: str, interval: str, resting: bool = False):
    """The exact frame the runner traded, cached, with a timestamp -> row map."""
    key = (symbol, interval, resting)
    if key not in _PREP:
        df = runner._prepare(make_spec(resting=resting), symbol, interval)
        _PREP[key] = (df, {t: i for i, t in enumerate(df["open_time"])})
    return _PREP[key]


def which_stop(res: dict, interval: str) -> dict:
    """Split the native "stop" exits into the 2N floor and the 10-day channel.

    For a long the level enforced is the HIGHER of the two, so the channel was in
    force exactly when it sat above the initial 2N stop. Reported as count and mean
    net R per route, because the interesting question is not only how often each
    fires but what each one pays: the 2N floor should cluster near -1R and the
    channel should be where the winners are given back.
    """
    tally = {"2N floor": [], "10-day channel": [], "channel not formed": []}
    for symbol in runner.COINS:
        df, pos = prepared(symbol, interval)
        lo = df["turt_exit_lo"].to_numpy(dtype=float)
        hi = df["turt_exit_hi"].to_numpy(dtype=float)
        for t in res["trades"][(symbol, interval, "native")]:
            if t.exit_reason != "stop":
                continue
            i = pos.get(t.exit_time)
            if i is None:
                continue
            cand = lo[i] if t.direction > 0 else hi[i]
            if not np.isfinite(cand):
                k = "channel not formed"
            elif (cand - t.initial_stop) * t.direction > 0:
                k = "10-day channel"
            else:
                k = "2N floor"
            tally[k].append(t.net_r)
    return {k: (len(v), float(np.mean(v)) if v else float("nan"))
            for k, v in tally.items()}


def entry_slip(res: dict, interval: str, resting: bool = False) -> dict:
    """How far each fill landed from the channel level a resting order sat on.

    This is the price of departure #5, measured in percent of the trigger. The
    Turtles rested a buy stop at the 20-day high and were filled AT it; this
    project waits for the bar to close beyond it and pays the next open. Positive
    means the fill was worse than the trigger for that direction.

    `resting=True` reads the same number off the resting run, where it should be
    zero except on bars that opened already through the level - so the two columns
    together separate execution cost from the different trade population the two
    execution styles necessarily take.
    """
    back = 0 if resting else 1
    v: list[float] = []
    for symbol in runner.COINS:
        df, pos = prepared(symbol, interval, resting=resting)
        hi = df["turt_don_hi"].to_numpy(dtype=float)
        lo = df["turt_don_lo"].to_numpy(dtype=float)
        for t in res["trades"][(symbol, interval, "native")]:
            i = pos.get(t.entry_time)
            if i is None or i - back < 0:
                continue
            trig = hi[i - back] if t.direction > 0 else lo[i - back]
            if not np.isfinite(trig) or trig <= 0:
                continue
            v.append((t.entry_price - trig) * t.direction / trig * 100.0)
    a = np.array(v)
    return {"n": int(len(a)),
            "median": float(np.median(a)) if len(a) else float("nan"),
            "mean": float(a.mean()) if len(a) else float("nan"),
            "p95": float(np.percentile(a, 95)) if len(a) else float("nan")}


# ---------------------------------------------------------------------------
# Terminal run
# ---------------------------------------------------------------------------

def main(write: bool) -> None:
    print(f"Strategy #7 - {NAME}")
    print("=" * 78)
    print("The source publishes NO per-trade numbers - no win rate, no reward-to-risk,")
    print("no Sharpe, no drawdown, no trade count. Its only figure is a dollar total its")
    print(f"own author calls \"{SRC['author_says']}\". So there is nothing to match this")
    print("test against on outcome, only on shape. Five departures from the original are")
    print("declared in the module docstring; the largest is that the engine holds one")
    print("position, so this is a SINGLE-UNIT Turtle with no pyramiding.")

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

    print("\nSignals fired vs signals usable, all twelve datasets")
    fired, usable = signal_counts()
    print(f"  {fired} breakout signals, {usable} with a measurable 1R "
          f"({fired - usable} dropped because N had not formed)")

    print("\nHow wide 1R really is: 2N as a percentage of the entry price")
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

    print("\nWhich of the two native stops actually fired - the 2N floor or the channel")
    for interval in IVS:
        w = which_stop(res, interval)
        bits = " | ".join(f"{k} {n} @ {r:+.3f}R" for k, (n, r) in w.items() if n)
        print(f"  {interval:<4} {bits}")

    print("\nDoes the fixed 2N floor keep losses near 1R? Losses beyond what was risked")
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

    print("\nThe source's own claimed condition: strong trends, loses steadily in ranges")
    print(f"  {'tf':<5} {'exit':<11} {'trending n':>11} {'trending R':>11} "
          f"{'R/trade':>9} {'range n':>9} {'range R':>9} {'R/trade':>9}")
    for interval in IVS:
        for label in LABELS:
            v = trend_split(res["trades"][(interval, label)])
            print(f"  {interval:<5} {label:<11} {v['trending']['trades']:>11} "
                  f"{v['trending']['r_post_fee']:>+11.1f} {v['trending']['expectancy']:>+9.3f} "
                  f"{v['range']['trades']:>9} {v['range']['r_post_fee']:>+9.1f} "
                  f"{v['range']['expectancy']:>+9.3f}")

    print("\nLong leg vs short leg - the source's own internal contradiction")
    for interval in IVS:
        for label in LABELS:
            g = leg_split(res["trades"][(interval, label)])
            print(f"  {interval:<4} {label:<11} long {g['long']['trades']:>5} trades "
                  f"{g['long']['r_post_fee']:>+8.1f}R | short {g['short']['trades']:>5} trades "
                  f"{g['short']['r_post_fee']:>+8.1f}R")

    print("\nWhat the closed-bar fill costs against a resting stop at the same level")
    for interval in IVS:
        s = entry_slip(res, interval)
        print(f"  {interval:<4} {s['n']:>5} fills | median {s['median']:+.3f}% worse "
              f"than the trigger | mean {s['mean']:+.3f}% | 95th pct {s['p95']:+.3f}%")

    print("\nPer coin, per timeframe, per exit")
    print(runner.per_coin_table(res, intervals=IVS))

    r1_pct = float(np.median([r_pct(res["trades"][(s, HEADLINE_TF, "native")])
                              for s in runner.COINS]))
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
    # Nothing below chooses the headline. Each block changes exactly one thing the
    # source left undefined, or one declared departure from the original, so a
    # reader can see whether the verdict is a property of the strategy or of a
    # placeholder this project had to pick.

    print("\nSensitivity 1 - the two readings of \"20 days\" on an intraday chart")
    sens_scale: dict = {}
    for tag, kw, aud in [
        ("20 calendar days, converted per timeframe (traded)", {}, False),
        ("20 bars, whatever a bar happens to be", {"scale": s07.SCALE_BAR}, True),
    ]:
        sres = res if not kw else runner.run(make_spec(**kw), intervals=IVS, audit=aud)
        sens_scale[tag] = {"pooled": sres["pooled"], "trades": sres["trades"]}
        for interval in IVS:
            for label in LABELS:
                m = sres["pooled"][(interval, label)]
                v, _ = verdict(m, label)
                print(f"  {tag:<52} {interval:<4} {label:<11} n={m['trades']:>5} "
                      f"1R={r_pct(sres['trades'][(interval, label)]):>5.2f}% "
                      f"R={m['r_sum_post_fee']:>8.1f} exp={m['expectancy_post_fee_r']:>+7.3f} "
                      f"sh={m['sharpe_post_fee']:>6.2f} {v}")

    print("\nSensitivity 2 - the exit, split into its two halves (native only)")
    print("  The forced-1:3 rows are identical across all three by construction -")
    print("  the forced variant never consults the native exit - so they are omitted.")
    sens_exit: dict = {}
    for tag, kw in [
        ("2N floor AND 10-day channel (traded)", {}),
        ("2N floor only, no channel exit", {"use_channel": False}),
        ("10-day channel only, no 2N floor", {"use_2n": False}),
    ]:
        sres = res if not kw else runner.run(make_spec(**kw), intervals=IVS, audit=False)
        sens_exit[tag] = {"pooled": sres["pooled"], "trades": sres["trades"]}
        for interval in IVS:
            m = sres["pooled"][(interval, "native")]
            t = loss_tail(sres["trades"][(interval, "native")])
            v, _ = verdict(m, "native")
            print(f"  {tag:<38} {interval:<4} n={m['trades']:>5} "
                  f"R={m['r_sum_post_fee']:>8.1f} exp={m['expectancy_post_fee_r']:>+7.3f} "
                  f"sh={m['sharpe_post_fee']:>6.2f} worst={t['worst']:>+7.2f}R "
                  f"beyond-1.2R={t['beyond_1_2']:>4} {v}")

    print("\nSensitivity 3 - execution: this project's next-open fill vs the Turtles' own")
    print("               resting stop, on identical trigger prices")
    sens_exec: dict = {}
    for tag, kw, aud in [
        ("decide on the close, fill at the next open (traded)", {}, False),
        ("stop order resting at the channel, filled inside the bar", {"resting": True}, True),
    ]:
        sres = res if not kw else runner.run(make_spec(**kw), intervals=IVS, audit=aud)
        sens_exec[tag] = {"pooled": sres["pooled"], "trades": sres["trades"]}
        for interval in IVS:
            slip = entry_slip(sres, interval, resting=bool(kw))
            for label in LABELS:
                m = sres["pooled"][(interval, label)]
                v, _ = verdict(m, label)
                print(f"  {tag:<54} {interval:<4} {label:<11} n={m['trades']:>5} "
                      f"slip={slip['median']:+.3f}% "
                      f"R={m['r_sum_post_fee']:>8.1f} exp={m['expectancy_post_fee_r']:>+7.3f} "
                      f"sh={m['sharpe_post_fee']:>6.2f} {v}")

    print("\nSensitivity 4 - the stop multiple, which the source states as 2N")
    sens_stop: dict = {}
    for mult in [1.0, s07.STOP_N, 3.0]:
        tag = f"{mult:g}N stop" + (" (traded)" if mult == s07.STOP_N else "")
        sres = (res if mult == s07.STOP_N
                else runner.run(make_spec(stop_n=mult), intervals=IVS, audit=False))
        sens_stop[tag] = {"pooled": sres["pooled"], "trades": sres["trades"]}
        for interval in IVS:
            for label in LABELS:
                m = sres["pooled"][(interval, label)]
                v, _ = verdict(m, label)
                print(f"  {tag:<20} {interval:<4} {label:<11} n={m['trades']:>5} "
                      f"1R={r_pct(sres['trades'][(interval, label)]):>5.2f}% "
                      f"R={m['r_sum_post_fee']:>8.1f} exp={m['expectancy_post_fee_r']:>+7.3f} "
                      f"sh={m['sharpe_post_fee']:>6.2f} {v}")

    print("\nSensitivity 5 - System 2, the original's own slower pair (55 in, 20 out)")
    sens_sys: dict = {}
    for tag, kw, aud in [
        (f"System 1: {s07.ENTRY_DAYS} in, {s07.EXIT_DAYS} out (traded)", {}, False),
        (f"System 2: {s07.S2_ENTRY_DAYS} in, {s07.S2_EXIT_DAYS} out",
         {"entry_days": s07.S2_ENTRY_DAYS, "exit_days": s07.S2_EXIT_DAYS}, True),
    ]:
        sres = res if not kw else runner.run(make_spec(**kw), intervals=IVS, audit=aud)
        sens_sys[tag] = {"pooled": sres["pooled"], "trades": sres["trades"]}
        for interval in IVS:
            for label in LABELS:
                m = sres["pooled"][(interval, label)]
                v, _ = verdict(m, label)
                print(f"  {tag:<40} {interval:<4} {label:<11} n={m['trades']:>5} "
                      f"R={m['r_sum_post_fee']:>8.1f} exp={m['expectancy_post_fee_r']:>+7.3f} "
                      f"sh={m['sharpe_post_fee']:>6.2f} {v}")

    print(f"\nSensitivity 6 - one change at a time, {HEADLINE_TF} and {DENSE_TF} only")
    sens_alt: dict = {}
    for tag, kw in [
        (TRADED_TAG, {}),
        ("long-only, the source's other reading", {"long_only": True}),
        (RATCHET_TAG, {"ratchet": True}),
    ]:
        sres = (res if not kw else
                runner.run(make_spec(**kw), intervals=[DENSE_TF, HEADLINE_TF], audit=False))
        sens_alt[tag] = sres["pooled"]
        for interval in [DENSE_TF, HEADLINE_TF]:
            for label in LABELS:
                m = sres["pooled"][(interval, label)]
                v, _ = verdict(m, label)
                print(f"  {tag:<50} {interval:<4} {label:<11} n={m['trades']:>5} "
                      f"R={m['r_sum_post_fee']:>8.1f} exp={m['expectancy_post_fee_r']:>+7.3f} "
                      f"sh={m['sharpe_post_fee']:>6.2f} {v}")

    print("\nFunding, at Bybit's base rate - this rule holds for weeks, so it matters")
    print(_md_funding(res, summary))

    if write:
        bundle = dict(res=res, summary=summary, cov=cov, ctx=ctx, mt=mt,
                      sens_scale=sens_scale, sens_exit=sens_exit, sens_exec=sens_exec,
                      sens_stop=sens_stop, sens_sys=sens_sys, sens_alt=sens_alt,
                      fired=fired, usable=usable, r1_pct=r1_pct, ws=ws, tot=tot)
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
    """The three per-coin day counts, in the same order as the retrofitted tables."""
    return [f"{cov[(interval, c)]['days']:.0f}" for c in runner.COINS]


def _mx(cell: dict, label: str):
    """Post-fee R/trade out of one half of a matched() result, or None if it is empty."""
    m = cell.get(label)
    if not m:
        return None
    return m.get("expectancy_post_fee_r")


def _mgap(cell: dict):
    """Native minus forced R/trade on matched entries, or None if either side is missing."""
    a, b = _mx(cell, "native"), _mx(cell, "forced-1:3")
    if a is None or b is None:
        return None
    return a - b


def _bwr(cell: dict):
    """Break-even win rate as a percentage, or None when the summariser could not compute one."""
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


def _md_whichstop(res: dict) -> str:
    rows = ["| Timeframe | 2N floor fired | Its mean net R | 10-day channel fired "
            "| Its mean net R | Channel not formed |", "|" + "---|" * 6]
    for interval in IVS:
        w = which_stop(res, interval)
        rows.append(
            f"| {interval} | {w['2N floor'][0]} | {_g(w['2N floor'][1], 3)}R "
            f"| {w['10-day channel'][0]} | {_g(w['10-day channel'][1], 3)}R "
            f"| {w['channel not formed'][0]} |"
        )
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


def _md_regime(summary: dict) -> str:
    rows = ["| Timeframe | Exit | Best condition | Worst condition |", "|" + "---|" * 4]
    for interval in IVS:
        for label in LABELS:
            m = summary[interval][label]
            rows.append(f"| {interval} | {label} | {m['best_regime']} | {m['worst_regime']} |")
    return "\n".join(rows)


def _md_slip(sens_exec: dict) -> str:
    """What the closed-bar fill costs against a resting order at the same level.

    Both rows are measured the same way - the fill price against the channel level
    the order would have rested on - so the two are directly comparable. The native
    row reads the level off the signal bar, the resting row off the fill bar,
    because that is where each one's trigger actually sat.
    """
    rows = ["| Execution | Timeframe | Fills measured | Median worse than trigger "
            "| Mean | 95th percentile |", "|" + "---|" * 6]
    for tag, blk in sens_exec.items():
        rest = "resting" in tag
        for interval in IVS:
            s = entry_slip({"trades": blk["trades"]}, interval, resting=rest)
            rows.append(f"| {tag} | {interval} | {s['n']} | {_g(s['median'], 3)}% "
                        f"| {_g(s['mean'], 3)}% | {_g(s['p95'], 3)}% |")
    return "\n".join(rows)


def _md_axis(sens: dict, native_only: bool = False) -> str:
    """A four-timeframe sensitivity block: one row per variant per exit.

    `native_only` is for the exit decomposition, where the forced-1:3 rows are
    identical across every variant by construction - the forced variant never
    consults the native exit - so printing them three times would only suggest
    that something was measured when nothing was.
    """
    labels = ["native"] if native_only else LABELS
    cols = ["Variant", "Timeframe", "Exit", "Trades", "Win%", "RR", "1R as % of price",
            "R (post-fee)", "R/trade", "Sharpe", "Max DD (R)", "Worst trade", "Verdict"]
    rows = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for tag, blk in sens.items():
        for interval in IVS:
            for label in labels:
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


RATCHET_TAG = "channel exit ratcheted, which the source does NOT say"
TRADED_TAG = "as traded"


def _ratchet_delta(sens_alt: dict) -> tuple[float, int]:
    """How far the ratcheted variant moved off as-traded: worst R/trade gap, worst trade-count gap.

    Returned so the prose can state what the ratchet actually did instead of
    speculating about it. Zero on both means the extra rule never bound.
    """
    base, alt = sens_alt.get(TRADED_TAG), sens_alt.get(RATCHET_TAG)
    if not base or not alt:
        return float("nan"), 0
    d_exp, d_n = 0.0, 0
    for interval in [DENSE_TF, HEADLINE_TF]:
        for label in LABELS:
            a, b = base.get((interval, label)), alt.get((interval, label))
            if not a or not b:
                continue
            ea, eb = a["expectancy_post_fee_r"], b["expectancy_post_fee_r"]
            if ea is not None and eb is not None:
                d_exp = max(d_exp, abs(ea - eb))
            d_n = max(d_n, abs(a["trades"] - b["trades"]))
    return d_exp, d_n


def _md_alt(sens_alt: dict) -> str:
    """The two-timeframe block. Only 1H and 1D were run, so only those are shown."""
    rows = ["| Variant | Timeframe | Exit | Trades | Win% | RR | R (post-fee) | R/trade "
            "| Sharpe | Max DD (R) | Verdict |", "|" + "---|" * 11]
    for tag, pooled in sens_alt.items():
        for interval in [DENSE_TF, HEADLINE_TF]:
            for label in LABELS:
                m = pooled[(interval, label)]
                v, _ = verdict(m, label)
                rows.append(
                    f"| {tag} | {interval} | {label} | {m['trades']} "
                    f"| {_g(m['win_rate'] * 100, 1)} | {_g(m['rr_achieved'])} "
                    f"| {_g(m['r_sum_post_fee'], 1)} | {_g(m['expectancy_post_fee_r'], 3)} "
                    f"| {_g(m['sharpe_post_fee'])} | {_g(m['max_drawdown_r'], 1)} | {v} |"
                )
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

    This strategy needs the check more than any logged so far. It has no time limit
    at all and holds until the 10-day channel is broken, so the average hold is tens
    of bars by design - and on the daily chart tens of bars is tens of DAYS, which
    is a hundred settlements or more on a single trade. The number below is a floor,
    not a forecast: it uses the base rate, and a real perpetual charges the base
    rate only when the market is balanced. A trend-follower is by definition holding
    the crowded side of a one-way market, where the rate is usually worse.
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
               sens_scale: dict, sens_exit: dict, sens_exec: dict, sens_stop: dict,
               sens_sys: dict, sens_alt: dict, fired: int, usable: int,
               r1_pct: float, ws: int, tot: int) -> None:
    keeps = _keeps(summary)

    # Every number quoted in the prose below is measured here rather than typed in,
    # so a re-run cannot leave a stale figure in a sentence beside a fresh table.
    mults = candle_multiples(res)
    hi = summary[HEADLINE_TF]["native"]     # 1D - the Turtles' own bar size
    dn = summary[DENSE_TF]["native"]        # 1H - the densest sample
    day_counts = ", ".join(f"{cov[(HEADLINE_TF, s)]['days']:.0f}" for s in runner.COINS)
    tails = {(i, lab): loss_tail(res["trades"][(i, lab)]) for i in IVS for lab in LABELS}
    trends = {(i, lab): trend_split(res["trades"][(i, lab)]) for i in IVS for lab in LABELS}
    legs = {(i, lab): leg_split(res["trades"][(i, lab)]) for i in IVS for lab in LABELS}
    concs = {(i, lab): top_share(res["trades"][(i, lab)]) for i in IVS for lab in LABELS}
    stops = {i: which_stop(res, i) for i in IVS}
    slips = {i: entry_slip(res, i) for i in IVS}
    n_cells = len(IVS) * 2
    trend_holds = [f"{i} {lab}" for i in IVS for lab in LABELS
                   if trends[(i, lab)]["trending"]["expectancy"]
                   > trends[(i, lab)]["range"]["expectancy"]]
    trend_fails = [f"{i} {lab}" for i in IVS for lab in LABELS
                   if not (trends[(i, lab)]["trending"]["expectancy"]
                           > trends[(i, lab)]["range"]["expectancy"])]
    trend_better = len(trend_holds)
    long_better = sum(1 for i in IVS for lab in LABELS
                      if legs[(i, lab)]["long"]["r_post_fee"]
                      > legs[(i, lab)]["short"]["r_post_fee"])
    range_better_native = sum(
        1 for i in IVS
        if trends[(i, "native")]["range"]["expectancy"]
        > trends[(i, "native")]["trending"]["expectancy"])
    ov_min, ov_max = min(ctx[i]["overlap"] for i in IVS), max(ctx[i]["overlap"] for i in IVS)
    # Variant tags are resolved by substring rather than retyped, so a wording change
    # in main cannot silently point a sentence at the wrong table row.
    t_both = next(t for t in sens_exit if "AND" in t)
    t_2n = next(t for t in sens_exit if "no channel" in t)
    t_ch = next(t for t in sens_exit if "no 2N" in t)
    x_next = next(t for t in sens_exec if "resting" not in t)
    x_rest = next(t for t in sens_exec if "resting" in t)
    s_day = next(t for t in sens_scale if "calendar" in t)
    s_bar = next(t for t in sens_scale if "whatever a bar" in t)
    y_s1 = next(t for t in sens_sys if "System 1" in t)
    y_s2 = next(t for t in sens_sys if "System 2" in t)
    # How much of the native result the fixed floor is responsible for, per timeframe:
    # the share of native stop exits that were the 2N floor rather than the channel.
    floor_share = {}
    for i in IVS:
        n_f, n_c = stops[i]["2N floor"][0], stops[i]["10-day channel"][0]
        floor_share[i] = n_f / (n_f + n_c) if (n_f + n_c) else float("nan")
    parts: list[str] = []

    parts.append(
        f"## Strategy #7 - {NAME}\n\n"
        f"**Tested:** {logbook.date.today().isoformat()} - **Coins:** {COINS_STR} -\n"
        f"**Timeframes:** {', '.join(IVS)} - **Fees:** taker on both legs "
        f"({runner.TAKER_FEE_RATE:.3%} each), every number below is post-fee -\n"
        f"**Data:** Bybit USDT perpetuals, public REST, forming bar dropped -\n"
        "**Warmup:** "
        + ", ".join(f"{iv} {s07.warmup_for(iv)} bars" for iv in IVS)
        + " (the rule is written in calendar days, so\nthe warmup is a different number "
        "of bars on every timeframe)"
    )

    parts.append(
        "**Sourcing: MEDIUM - the rules are verifiable, the results are not.** This is the\n"
        "weakest outcome claim in the log so far, and the gap is not a detail. The source\n"
        f"describes a real, published, decades-old system tested on {SRC['what']},\n"
        "and it publishes **no per-trade numbers at all**: no win rate, no reward-to-risk, no\n"
        "Sharpe, no drawdown, no trade count. The single figure it gives is\n"
        f"\"{SRC['only_figure']}\", which the author himself calls\n"
        f"\"{SRC['author_says']}\" - correctly, because a dollar total says nothing without the\n"
        "capital, the sizing or the span behind it. The per-trade metrics are paywalled.\n\n"
        "So unlike Strategy #6 there is no claimed win-rate band to test against. **Nothing in\n"
        "this section can be matched against the source on outcome, only on shape.** Two further\n"
        "gaps sit on top of that: the tested market is FUTURES over 2007-2025, not crypto\n"
        "perpetuals over 2020-2026, and no bar size is named anywhere - though the original is a\n"
        f"daily system, which is why {HEADLINE_TF} is the headline timeframe here."
    )

    parts.append(
        "### The rule, in the source's own words\n\n"
        f"* **Trigger:** buy a new {s07.ENTRY_DAYS}-day high; sell short a new "
        f"{s07.ENTRY_DAYS}-day low.\n"
        "* **Stop-loss:** ATR-based, with position size scaled to volatility so that every\n"
        "  market risks the same amount of money.\n"
        f"* **Take-profit:** exit on a {s07.EXIT_DAYS}-day low (for longs). A trailing channel "
        "exit, no fixed target.\n"
        "* **Market condition:** strong trends. Loses steadily in ranges.\n"
        f"* **Documented result:** {SRC['only_figure']} - and nothing else.\n\n"
        "The published Turtle rules fill the gaps the article leaves, and they are quoted here\n"
        "because they are what was actually implemented. **System 1:** enter on a\n"
        f"{s07.ENTRY_DAYS}-day channel breakout, stop 2N away where N is the {s07.N_DAYS}-day "
        f"average true range,\nexit on the {s07.EXIT_DAYS}-day channel in the opposite direction, "
        "risk about 1% of the account per\nunit with the unit size divided by N, and pyramid up to "
        f"four units at half-N intervals.\n**System 2** is the same shape at {s07.S2_ENTRY_DAYS} "
        f"days in and {s07.S2_EXIT_DAYS} days out, and is run as Sensitivity 5."
    )

    parts.append(
        "### Where this port departs from the original, declared before any number was produced\n\n"
        "| # | The original | What was run here | Why | Measured? |\n"
        "|---|---|---|---|---|\n"
        "| 1 | Pyramid up to four units at half-N intervals | **one unit, no pyramiding** "
        "| the engine holds one position at a time | no - not implementable here |\n"
        "| 2 | Unit size = 1% of equity divided by N | fixed 1% of equity risked with the stop "
        f"{s07.STOP_N:g}N away | the same arithmetic reaching the same place | n/a |\n"
        f"| 3 | \"{s07.ENTRY_DAYS} days\" on daily bars | {s07.ENTRY_DAYS} calendar DAYS, converted "
        "per timeframe ("
        + ", ".join(f"{s07.ENTRY_DAYS * s07.BPD[iv]} bars at {iv}" for iv in IVS)
        + ") | the rule is written in days, not bars | yes - Sensitivity 1 |\n"
        f"| 4 | N = {s07.N_DAYS}-day ATR on daily bars | a day-scale range averaged over "
        f"{s07.N_DAYS} days, on every timeframe | an hourly ATR would put the stop two candles "
        "from the fill | yes - Sensitivity 1 |\n"
        "| 5 | Buy stop resting above the channel, filled inside the breakout bar "
        "| **decide on the closed bar, fill at the next open** | comparability with the six "
        "strategies already logged | yes - Sensitivity 3 |\n\n"
        "**Departure 1 is the one that matters most, and it cannot be measured away.** Pyramiding\n"
        "is what turns a Turtle winner into a large winner, and it also multiplies the loss when a\n"
        "breakout fails after the adds. Every number in this section is therefore a SINGLE UNIT,\n"
        "and **the system's own documented return profile is not reproducible from it.** That is a\n"
        "limit of this test, stated plainly, not a finding about the system.\n\n"
        "**Departure 4 has a proof rather than an argument.** N is the average true range of the\n"
        f"last {s07.N_DAYS} DAYS - a daily quantity. Measuring it as an average HOURLY range would "
        f"put the\n{s07.STOP_N:g}N stop about two hourly candles from the fill, which is not the "
        "rule and would be dead on\narrival. So the true range is measured over a rolling "
        f"day-length window of bars and then\naveraged over {s07.N_DAYS} days of them. At "
        f"{HEADLINE_TF} that expression collapses EXACTLY to the plain\n{s07.N_DAYS}-bar ATR - the "
        "original's own N - which was checked directly: the largest difference\nbetween the two "
        "series across all three coins on daily bars is 0.0. That collapse is the\ntest that it is "
        "the same quantity and not a new one."
    )

    parts.append(
        "### What the source does not disclose\n\n"
        "Everything an outcome claim is made of. This table is unusually short because there is\n"
        "unusually little to fill it with.\n\n"
        "| Left undefined | Set to here | Why that value | Swept? |\n"
        "|---|---|---|---|\n"
        f"| Bar size | {HEADLINE_TF} headline, all four reported | the original is a daily system "
        "| yes - all four timeframes |\n"
        f"| \"{s07.ENTRY_DAYS} days\": days or bars? | calendar days | the rule is written in days "
        "| yes - Sensitivity 1 |\n"
        f"| The stop multiple | {s07.STOP_N:g}N | the published Turtle rule states 2N "
        "| yes - Sensitivity 4 |\n"
        "| Long-only or both sides? | both sides | the original traded both, and so does the "
        "recovered source | yes - Sensitivity 6 |\n"
        "| Does the channel exit ratchet? | no | re-reading the channel every bar is what the "
        "rule says | yes - Sensitivity 6 |\n"
        "| Any time limit | none in the native rule | the source names none "
        f"| yes - the forced 1:3 caps holds at {runner.FORCED_TIME_LIMIT} bars |\n\n"
        f"**Signals dropped:** of {fired} breakout signals across all twelve datasets, {usable} had "
        f"a\nmeasurable 1R and {fired - usable} were discarded because N had not yet formed. "
        "Dropping is\ncounted, not silent."
    )

    parts.append(coverage.text_block(cov, runner.COINS, IVS))

    n_all = len(res["audit"])
    n_ok = sum(1 for ok, _, _ in res["audit"].values() if ok)
    n_cols = max(len(cols) for _, cols, _ in res["audit"].values())
    parts.append(
        "### Lookahead bias, checked fresh for this strategy\n\n"
        f"**The mechanical audit passed on {n_ok} of {n_all} datasets**, re-deriving every one of "
        f"the\n{n_cols} indicator columns on history truncated at 25 different cut points and "
        "requiring each\nvalue to match the full-history value to 1e-12. A single mismatch would "
        "have raised and\nproduced no numbers at all. The audit was also re-run from scratch on the "
        "bar-native scale,\non the resting-order variant and on System 2, because each of those "
        "changes how the columns\nare computed rather than only how they are used.\n\n"
        "Four specific traps in this rule were handled by hand, and one of them the audit\n"
        "structurally cannot see:\n\n"
        "1. **The entry channel excludes the bar it judges.** The 20-day high is the highest high\n"
        "   of the bars BEFORE the bar being tested, so \"a new 20-day high\" is this bar's close\n"
        "   against a level that was already on the chart when the bar opened. Without that shift\n"
        "   the channel would contain the bar's own high, `close > channel` could never be true,\n"
        "   and the rule would silently produce no trades at all rather than raise.\n"
        "2. **The exit channel is shifted for the same reason, and it matters more.** That level is\n"
        "   tested against the HIGH and LOW of the bar it sits on - it is a stop - so it must be\n"
        "   knowable before the range it is compared with exists.\n"
        "3. **N is deliberately NOT shifted, and the audit cannot catch that.** N sizes a decision\n"
        "   taken at the CLOSE of bar i from bars up to and including bar i, all of which have\n"
        "   closed. The audit truncates history at the END, so it can prove a value does not depend\n"
        "   on FUTURE bars; it cannot prove a value is not read too early within its own bar. That\n"
        "   distinction is argued here rather than left to the machine: N is an input to a\n"
        "   close-of-bar decision, never a level tested inside a bar.\n"
        "4. **The two measurements that read the chart after the fact read only closed bars.** The\n"
        "   \"which stop fired\" and \"execution slippage\" tables below rebuild the traded frame and\n"
        "   look levels up at each trade's recorded entry and exit timestamps. Those timestamps are\n"
        "   bar open times in both engine paths, and the levels looked up are the shifted channel\n"
        "   values - so the lookup only ever reads something that was already on the chart when the\n"
        "   trade happened. In the resting variant both trigger prices and the risk unit are\n"
        "   shifted one bar, because there they ARE levels tested inside bar i.\n\n"
        f"**Fills that opened already past their own stop level:** {ws} of {tot} across every "
        "variant.\nThe 1R distance is fixed on the signal bar and the fill happens at the next "
        "bar's open, so a\ngap through the level would start a trade already stopped out. Perpetuals "
        "trade continuously,\nso this should be near zero - but \"should be\" is not a measurement."
    )

    parts.append(
        "### Results, three coins pooled per timeframe\n\n"
        "Both variants share the same entry rule and the same fills; only the exit differs.\n"
        f"\"native\" is the source's own exit - the {s07.STOP_N:g}N stop and the "
        f"{s07.EXIT_DAYS}-day channel, whichever price\nreaches first, no target and no time "
        f"limit. \"forced-1:3\" is this project's standard\ncomparison: a 3R target with a "
        f"{runner.FORCED_TIME_LIMIT}-bar time limit.\n\n"
        + _md_table(summary, cov)
    )

    parts.append(
        "### What the source claims, and what this test measured\n\n"
        "This table is here to show that the comparison cannot be made, not to make it.\n\n"
        "| Test | Market | Bars | Trades | Win% | RR | Sharpe | Max DD |\n"
        "|---|---|---|---|---|---|---|---|\n"
        f"| The source's claim | 43 futures markets, 2007-2025 | not stated | not stated "
        "| not stated | not stated | not stated | not stated |\n"
        + "\n".join(
            f"| This test, native exit | BTC/SOL/XRP perps | {i} "
            f"| {summary[i]['native']['trades']} "
            f"| {_g(summary[i]['native']['win_rate'] * 100, 1)} "
            f"| {_g(summary[i]['native']['rr_achieved'])} "
            f"| {_g(summary[i]['native']['sharpe_post_fee'])} "
            f"| {_g(summary[i]['native']['max_drawdown_pct'], 1)}% |"
            for i in IVS
        )
        + "\n\nEvery cell in the claim row is \"not stated\" because the source states nothing. "
        "The one\nfigure it does publish - a dollar total across 43 markets - its own author calls "
        f"\"{SRC['author_says']}\",\nand he is right: without the capital, the sizing and the span "
        "it is not a result. So this\nstrategy is the first in the log where **the source's outcome "
        "cannot be confirmed or refuted at\nall.** What can be checked is the SHAPE the rules "
        "imply - a low win rate paid for by a high\nreward-to-risk, most of the money in a few very "
        "large winners, and losses bounded near the risk\nunit - and that shape is what the tables "
        "below test.\n\nWhat can also be checked, and is worth more than the claim, is that this "
        "rule is **not a rule\nthis project chose**. The lengths, the stop multiple and the exit "
        "channel are all published,\ndecades old, and were fixed before the first backtest ran. "
        "There is no fitting risk in the\nparameters themselves - only in the four places the "
        "article left ambiguous, and each of those\nis swept below."
    )

    parts.append(
        "### How much risk each trade actually put up\n\n"
        f"1R is {s07.STOP_N:g}N, the published stop distance, and N is a day-scale average true "
        "range. So 1R is a\nvolatility measurement rather than a fixed percentage - which is the "
        "whole point of the\noriginal's sizing rule - and it comes out at a similar width on every "
        "timeframe, because the\nquantity being averaged is a DAY's range regardless of the bar "
        "size.\n\n"
        + _md_risk(res)
        + f"\n\nAcross all {len(mults)} coin-timeframe cells 1R runs from {min(mults):.1f}x to "
        f"{max(mults):.1f}x a typical candle. That\nmatters because a stop inside one candle is "
        "decided by the engine's pessimistic intrabar\ntie-break rather than by the strategy - the "
        f"disease Strategy #1 documented. At {HEADLINE_TF} 1R is about\none daily candle, which is "
        "the thinnest cell here and still not in that territory; at 1H it is\ntens of candles wide."
    )

    parts.append(
        "### How the trades ended, and how long they ran\n\n"
        "The native rule has no target and no clock, so a winner runs until the channel catches\n"
        "it. The hold tail is reported for that reason, and it is what makes funding the main\n"
        "uncertainty on this strategy rather than a footnote.\n\n"
        + _md_exits(res)
    )

    parts.append(
        "### Which of the two native stops actually fired\n\n"
        "The engine records \"stop\" for any intrabar stop, and BOTH of this rule's exits are\n"
        f"intrabar stops - the fixed {s07.STOP_N:g}N floor and the trailing "
        f"{s07.EXIT_DAYS}-day channel. So the exit mix above\ncannot separate them. This table "
        "does, by comparing the channel level at the exit bar against\nthe trade's own initial "
        f"stop: whichever sits closer to price is the one that was enforced.\n\n"
        + _md_whichstop(res)
        + f"\n\nAt {HEADLINE_TF} the fixed floor accounts for {floor_share[HEADLINE_TF]:.0%} of "
        f"native stop exits and the channel for the\nrest. Read that with the exit decomposition "
        "in Sensitivity 2, which answers the same question\nwithout needing any classification at "
        "all - it simply runs each half of the exit on its own."
    )

    parts.append(
        "### Does the fixed floor keep losses near one unit of risk?\n\n"
        f"The {s07.STOP_N:g}N stop is a FIXED level and the {s07.EXIT_DAYS}-day channel exit is "
        "re-read every bar, so for a long the\nlevel actually enforced is whichever of the two is "
        "HIGHER. Early in a trade that is the 2N\nfloor; once the channel has climbed above it the "
        "channel takes over and the stop trails. That\npairing is the source's own, and its "
        "consequence is that a loss should not exceed one unit of\nrisk except when a bar gaps "
        "through the level. Here is whether that held.\n\n"
        + _md_losstail(res)
    )

    parts.append(
        "### Is the result carried by a handful of trades?\n\n"
        "A trend-follower is SUPPOSED to concentrate - the whole design accepts many small losses "
        "to\npay for a few very large winners, so a high top-trade share is the rule working, not "
        "a\nwarning. What matters is whether the result survives removing the single best trade, "
        "because\nthat is the difference between a strategy with a fat tail and a strategy that "
        "caught one move.\n\n"
        + _md_conc(res)
        + f"\n\nThe \"total without the best\" column is the honest test. At {HEADLINE_TF} the "
        f"native variant keeps\n{concs[(HEADLINE_TF, 'native')]['without_top1']:+.1f}R of its "
        f"{concs[(HEADLINE_TF, 'native')]['total']:+.1f}R after the best single trade is deleted, "
        f"with the best trade alone worth\n{concs[(HEADLINE_TF, 'native')]['share1']:.0%} of the "
        "total."
    )

    parts.append(
        "### The source's market-condition claim, tested\n\n"
        "The source says this system wants strong trends and loses steadily in ranges. That is a\n"
        "testable claim, and it is the ONE claim in the article specific enough to check. Every "
        "trade\nis labelled by the regime its entry bar sat in - the project's shared trending / "
        "ranging\nlabel, computed from a 100-bar mean and not from anything the strategy knows.\n\n"
        + _md_trend(res)
        + f"\n\nOf the {n_cells} cells, {trend_better} made more R per trade in trending conditions "
        f"than in ranging ones.\nOn the native exit specifically the claim held in {trend_holds} of "
        f"{len(IVS)} timeframes and failed in {trend_fails};\n{range_better_native} native cells "
        "actually did BETTER in ranges. Where it fails, the reason is\nusually that a range in "
        "this label still contains the multi-week drifts a 20-day channel\ntrades - the label is "
        "not a filter the strategy applied, only a description of the tape."
    )

    parts.append(
        "### Long side versus short side\n\n"
        "The original traded both directions and so does this test. One retelling of the system\n"
        "calls it long-only, which is why the long-only reading is run as a labelled sensitivity\n"
        "further down rather than argued about here.\n\n"
        + _md_legs(res)
        + f"\n\nThe long leg out-earned the short leg in {long_better} of the {n_cells} cells. "
        "Read that against the\nspan: all three coins spent most of these windows in a rising "
        "market, so a long-side\nadvantage is partly the tape and not only the rule."
    )

    parts.append(
        "### Per coin, so one coin cannot hide behind the pool\n\n"
        + runner.per_coin_table(res, intervals=IVS)
    )

    parts.append(
        "### Statistical context checks\n\n"
        + context_checks.text_block(ctx, IVS, stop_pct=r1_pct)
        + f"\n\nOne caveat specific to this strategy: the entry overlap between the two variants "
        f"runs from\n{ov_min:.0%} to {ov_max:.0%}. Both variants take the same signals, so the "
        "overlap should be near total; where\nit falls short it is because the native variant has "
        "no time limit, so it can still be holding a\ntrade when a later signal fires and the "
        "forced variant - which exits after "
        f"{runner.FORCED_TIME_LIMIT} bars - is\nfree to take it. That is a real difference in the "
        "trade population, not a bookkeeping error, and\nit is one reason the two columns are never "
        "netted against each other."
    )

    parts.append(
        "### Exit-death check: does the edge depend on the exit style?\n\n"
        "This is the mandatory comparison - the source's own exit against the project's forced\n"
        "1:3 triple-barrier, on identical entries.\n\n"
        "| Timeframe | Native R/trade | Forced R/trade | Gap | Flag | What it means |\n"
        "|---|---|---|---|---|---|\n"
        + "\n".join(
            f"| {i} | {_g(summary[i]['native']['expectancy_post_fee_r'], 3)} "
            f"| {_g(summary[i]['forced-1:3']['expectancy_post_fee_r'], 3)} "
            f"| {_g(summary[i]['native']['expectancy_post_fee_r'] - summary[i]['forced-1:3']['expectancy_post_fee_r'], 3)} "
            f"| {summary[i]['exit_death']} | {summary[i]['exit_death_diag']} |"
            for i in IVS
        )
        + "\n\nThe full comparison above pools every trade each variant took, and those populations "
        "are not\nidentical for the reason just given. So the same check is repeated on MATCHED "
        "entries only -\nthe trades both variants took on the same bar in the same direction - "
        f"where the only difference\nleft is the exit.\n\n"
        "| Timeframe | Matched trades | Native R/trade | Forced R/trade | Gap | Exit-death |\n"
        "|---|---|---|---|---|---|\n"
        + "\n".join(
            "| {} | {} | {} | {} | {} | {} |".format(
                i,
                mt[i]["n"],
                _g(_mx(mt[i], "native"), 3),
                _g(_mx(mt[i], "forced-1:3"), 3),
                _g(_mgap(mt[i]), 3),
                "yes" if mt[i]["exit_death"] else "no",
            )
            for i in IVS
        )
        + f"\n\nA gap wider than {EXIT_DEATH_GAP_R:g}R either way is flagged as an "
        "exit dependency. Read the matched rows as\nthe cleaner answer: they hold the entries fixed "
        "and change only the exit, which is the question\nbeing asked."
    )

    parts.append(
        "### Sensitivity 1: what \"20 days\" means on an intraday chart\n\n"
        "This is the largest of the four ambiguities the article leaves, and no source picks\n"
        "between the two readings. **Twenty DAYS** converts the rule per timeframe - "
        f"{s07.ENTRY_DAYS * 24} bars at 1H,\n{s07.ENTRY_DAYS * 6} at 4H, {s07.ENTRY_DAYS * 4} at "
        f"6H, {s07.ENTRY_DAYS} at 1D - and is what was traded, on the precedent set by\nStrategies "
        "#2, #3 and #4. **Twenty BARS** is what a chart package does when a Donchian-20 is\ndropped "
        "on an hourly chart: a genuinely different rule, roughly a 20-hour channel, and it is\nrun "
        "here in full.\n\n"
        + _md_axis(sens_scale)
        + "\n\nThe two readings are not variations of one rule; at 1H they are a 20-day channel and "
        "a 20-hour\nchannel. Only the 1D rows are identical by construction, and they are the "
        "arithmetic check that\nboth paths compute the same thing when a bar IS a day."
    )

    parts.append(
        "### Sensitivity 2: which half of the native exit earns\n\n"
        f"The native exit is two rules at once - the fixed {s07.STOP_N:g}N floor and the trailing "
        f"{s07.EXIT_DAYS}-day channel.\nRunning each half alone answers what the exit mix cannot: "
        "which one the result depends on.\nOnly the native rows are shown, because the forced-1:3 "
        "rows are identical across all three\nvariants by construction - the forced exit replaces "
        "the native exit entirely.\n\n"
        + _md_axis(sens_exit, native_only=True)
        + "\n\nRead these three rows as a decomposition, not as three candidate strategies. "
        f"\"{t_2n}\"\nis a fixed-stop breakout with no way out but the stop, so its winners run "
        f"until they lose.\n\"{t_ch}\" keeps 1R defined as {s07.STOP_N:g}N - the risk the system "
        "intended - but enforces no floor, so\na loss can run past it, which is what its worst-trade "
        f"column is there to show.\n\"{t_both}\" is the source's rule."
    )

    parts.append(
        "### Sensitivity 3: the execution departure, priced\n\n"
        "The Turtles rested buy and sell stops at the channel and were filled INSIDE the breakout\n"
        "bar. This project decides on a closed bar and fills at the next open, which is strictly\n"
        "worse - it pays away the rest of the breakout bar and any gap after it. Both are run on\n"
        "identical trigger prices so the cost is measured rather than argued.\n\n"
        + _md_axis(sens_exec)
        + "\n\nThe two variants do not take the same trades: a resting order fires the moment price "
        "touches\nthe channel, so it enters on bars where the close later fell back inside and the "
        "closed-bar\nrule never fired at all. To separate the pure execution cost from the different "
        "trade\npopulation, the fill price of every trade is compared with the channel level a "
        "resting order\nwould have sat on.\n\n"
        + _md_slip(sens_exec)
        + "\n\nA positive number is money paid away versus the trigger. The resting rows are not "
        "zero because\na bar can OPEN through a resting stop, in which case the engine fills at the "
        "open - the worse\nprice - exactly as a real stop order would."
    )

    parts.append(
        "### Sensitivity 4: the stop multiple\n\n"
        f"{s07.STOP_N:g}N is published, so this is not a parameter search - it is a check that the "
        "published number is\nnot sitting on a cliff. 1N halves the risk unit and 3N raises it by "
        "half; because position size\nis 1% of equity divided by the stop distance either way, a "
        "wider stop does not risk more money\nper trade, it takes a smaller position and gives the "
        "trade more room.\n\n"
        + _md_axis(sens_stop)
        + f"\n\nWhat to look for is monotonicity. If {s07.STOP_N:g}N were a lucky value the "
        "neighbours would be much worse\nthan it; if the rule is real, the three rows should trend "
        "in one direction and 2N should sit on\nthat trend rather than above it."
    )

    parts.append(
        "### Sensitivity 5: System 2, the original's slower pair\n\n"
        f"The published system came in two halves. System 1 is {s07.ENTRY_DAYS} days in and "
        f"{s07.EXIT_DAYS} out, which is what was\ntraded. System 2 is the same shape at "
        f"{s07.S2_ENTRY_DAYS} days in and {s07.S2_EXIT_DAYS} out - a slower channel that takes\n"
        "fewer, larger positions. The Turtles ran both. Running it here costs nothing and doubles "
        "the\nevidence about whether the shape works at all, independently of the exact lengths.\n\n"
        + _md_axis(sens_sys)
        + f"\n\n\"{y_s2}\" is not a tuning of \"{y_s1}\" - both length pairs are\npublished, "
        "decades old, and were fixed long before this data existed. If both work the shape is\n"
        "doing the work; if only one works, the lengths are."
    )

    r_dexp, r_dn = _ratchet_delta(sens_alt)
    ratchet_bound = not (r_dexp == 0.0 and r_dn == 0)
    parts.append(
        "### Sensitivity 6: two readings the source leaves open\n\n"
        "Run on 1H and 1D only - the densest sample and the headline - because these two variants\n"
        "test wording, not timeframe behaviour.\n\n"
        "**Long-only.** One retelling of this system calls it long-only and then, in the same "
        "breath,\nlists selling below the 20-day low. The original traded both sides and the "
        "recovered source\ndescribes both, so both were traded; this row is the other reading.\n\n"
        "**Ratcheted channel exit.** \"Exit on a 10-day low\" is re-read from scratch every bar, "
        "so as\nprice falls the 10-day low can fall with it and the exit level LOOSENS. A ratchet - "
        "holding the\nlevel at its best value - is a rule the source does not contain, and none was "
        "added, on the\nprecedent of Strategies #5 and #6. This row is what adding it would have "
        "done.\n\n"
        + _md_alt(sens_alt)
        + "\n\n"
        + (
            "The long-only row is a real fork in the reading and it moves the numbers, so it is "
            "reported\nas a finding about the other reading - not as a verdict on the rule that was "
            "actually traded.\n\n"
            + (
                "The ratcheted row moved the result: R/trade differs by up to "
                f"{r_dexp:.3f}R and the trade count by\nup to {r_dn}. That is a finding about a "
                "variant this log did not test and does not claim, so it\nbelongs in the \"what to "
                "try next\" column rather than in any verdict above."
                if ratchet_bound else
                "The ratcheted row came back **identical to as-traded, to every decimal place "
                "printed and on\nboth timeframes** - same trade count, same win rate, same R. That "
                "is not a bug and it is worth\nstating plainly: the level this test enforces is "
                "already the HIGHER of the channel level and the\nfixed 2N floor (the lower, for a "
                "short). A ratchet could only ever bind in the narrow case where\nthe channel "
                "level falls back below its own earlier best while still sitting outside the "
                "floor -\nand across every trade on both timeframes, that case never decided an "
                "exit. So the loosening\ndescribed above is real in the rule but inert in the "
                "results: the fixed floor is already doing\nthe job a ratchet would have done. "
                "Nothing here argues for adding the rule."
            )
        )
    )

    parts.append(
        "### Best and worst conditions, per cell\n\n"
        "The regime label is computed from the tape, not from the strategy, so these columns say\n"
        "which market this rule was paid in - not which market it predicted.\n\n"
        + _md_regime(summary)
    )

    parts.append(
        "### The discard bar, applied to each exit variant separately\n\n"
        "The thresholds were fixed before this strategy was written and are the same ones every\n"
        f"strategy in this log is measured against: KEEP needs at least {BAR.min_trades} trades, "
        f"expectancy of at least\n+{BAR.keep_expectancy_r:.2f}R per trade after fees, Sharpe of at "
        f"least {BAR.keep_sharpe:.2f}, an R-recovery of at least "
        f"{BAR.keep_r_recovery:.2f}\n(total R divided by the worst drawdown in R), and a win rate at "
        f"least {BAR.keep_win_margin:.0%} above the break-even\nwin rate for the reward-to-risk it "
        f"achieved. DISCARD is expectancy at or below "
        f"{BAR.discard_expectancy_r:+.2f}R, Sharpe below\n{BAR.discard_sharpe:.2f}, or R-recovery "
        f"below {BAR.discard_r_recovery:.2f}. Fewer than {BAR.min_trades} trades is INCONCLUSIVE, "
        "never DISCARD.\n\n"
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
        + "\n\nThe two verdicts on a timeframe are never collapsed into one. A strategy can pass on "
        "its own\nexit and fail on a forced 1:3, and that difference IS the finding - it says the "
        "edge lives in the\nexit rather than in the entry.\n\n"
        f"One number on the {HEADLINE_TF} native row deserves to be read carefully rather than "
        f"rounded: its Sharpe is\n{_g(hi['sharpe_post_fee'])} against a KEEP threshold of "
        f"{BAR.keep_sharpe:.2f}. "
        + ("That is BELOW the bar, not at it, and it is the reason\nthat cell is not a KEEP. "
           "A hair's-breadth miss is still a miss; the threshold was set before the\nnumber existed "
           "and is not being moved to accommodate it."
           if (hi["sharpe_post_fee"] is not None
               and np.isfinite(hi["sharpe_post_fee"])
               and hi["sharpe_post_fee"] < BAR.keep_sharpe)
           else "That clears the bar, but by a margin thin enough that a\ndifferent data window "
                "could put it on the other side.")
    )

    parts.append(_md_funding(res, summary))

    if keeps:
        parts.append(
            "**Funding is not modelled, and this strategy is the one where that matters most.**\n\n"
            + "\n\n".join(
                f"The {i} {lab} cell reads as a KEEP above. It holds a position for "
                f"{_funding_cost_r(res, i, lab)[0]:.0f} hours on\naverage, which crosses about "
                f"{_funding_cost_r(res, i, lab)[1]:.0f} funding settlements per trade. At Bybit's "
                f"base rate of\n{FUNDING_BASE_PCT:.2f}% per settlement that is roughly "
                f"{_funding_cost_r(res, i, lab)[2]:.2f}R of cost per trade, against a measured\n"
                f"expectancy of {_g(summary[i][lab]['expectancy_post_fee_r'], 3)}R. "
                + ("**That cost alone is larger than the edge, so this KEEP does not survive "
                   "funding and is\ndemoted to PROVISIONAL pending a funding model.**"
                   if (_funding_cost_r(res, i, lab)[2] or 0) >= (summary[i][lab]["expectancy_post_fee_r"] or 0)
                   else "The edge survives the base rate, but the base\nrate is a floor: a "
                        "trend-follower is by definition holding the crowded side of a one-way\n"
                        "market, where funding is usually worse than base. **This KEEP is "
                        "PROVISIONAL until funding is\nmodelled properly.**")
                for i, lab in keeps
            )
            + "\n\nPer the standing rule, a KEEP on a multi-day holding strategy is not treated as "
            "a real KEEP\nuntil funding is priced. The verdicts in the table above are the "
            "fee-and-slippage verdicts;\nthe funding column is the reason none of them is being "
            "acted on yet."
        )
    else:
        parts.append(
            "**Funding is not modelled.** No cell reached KEEP, so no verdict here depends on it - "
            "but the\ntable above is still worth reading, because it shows the size of the cost a "
            "future version of\nthis strategy would have to clear. At an average hold of "
            f"{_g(hi['avg_bars_held'], 1)} daily bars, the {HEADLINE_TF} native\nvariant crosses "
            f"roughly {_funding_cost_r(res, HEADLINE_TF, 'native')[1]:.0f} funding settlements per "
            "trade. Funding does not make a losing strategy\nlose more slowly; it is a cost that "
            "scales with holding time, and this rule holds longer than\nanything else in the log."
        )

    parts.append(
        "### What would change these verdicts\n\n"
        "Five things, in the order they would move the numbers most.\n\n"
        "1. **Pyramiding.** The single largest departure and the only one that cannot be measured "
        "away\n   from inside this engine, which holds one position at a time. The Turtles added up "
        "to four\n   units at half-N intervals, and that is what turns a winner into a large winner "
        "- and what\n   deepens the loss when a breakout fails after the adds. Every number here is "
        "a single unit, so\n   the system's own documented return profile is not reproducible from "
        "it in either direction.\n"
        "2. **Funding.** Priced above at the base rate as a floor. On a rule that holds for "
        f"{_g(hi['avg_bars_held'], 1)} daily\n   bars this is not a rounding item, and a proper "
        "model needs the historical funding series per\n   coin rather than a flat rate.\n"
        f"3. **Execution.** \"{x_rest}\" is the original's own\n   execution and "
        f"\"{x_next}\" is what this project\n   trades. Sensitivity 3 measures the gap in R and in "
        f"percent; at {HEADLINE_TF} the median fill came in\n   "
        f"{_g(slips[HEADLINE_TF]['median'], 3)}% worse than the level a resting order would have sat "
        "on. Anyone running\n   this for real would rest the stops and should read the resting rows, "
        "not the traded ones.\n"
        f"4. **The reading of \"20 days\".** \"{s_day}\" was\n   traded; "
        f"\"{s_bar}\" is the other reading and is a\n   different rule, not a variation. If the two "
        "disagree on the intraday timeframes, then those\n   timeframes are reporting on a rule "
        "choice this project made and the source did not.\n"
        f"5. **More history, and other coins.** The windows here are {day_counts} days for BTC, SOL "
        f"and XRP\n   at {HEADLINE_TF}. The source tested 43 markets over 18 years. A 20-day channel "
        "system takes few\n   trades per market per year by design, so the honest way to raise the "
        "sample is more markets,\n   not more parameter variants on three coins."
    )

    parts.append(
        "### Bottom line\n\n"
        "The rule is genuinely old and genuinely published, which makes it the least fitted "
        "strategy in\nthis log - the lengths, the stop multiple and the exit channel were all fixed "
        "decades before\nthis data existed. It is also the strategy with the weakest outcome claim: "
        "the article that\nprompted the test publishes no per-trade numbers at all, so nothing here "
        "could be checked\nagainst it on outcome, only on shape.\n\n"
        f"On shape it behaves the way a trend-follower should. At {HEADLINE_TF} the native exit won "
        f"{_g(hi['win_rate'] * 100, 1)}% of\n{hi['trades']} trades at a reward-to-risk of "
        f"{_g(hi['rr_achieved'])}, with losses held near one unit of risk - "
        f"{tails[(HEADLINE_TF, 'native')]['share_beyond']:.0%} of\nlosers ran past 1.2R - and the "
        f"result concentrated in a few large winners. At {DENSE_TF} the same rule\ntook "
        f"{dn['trades']} trades for {_g(dn['expectancy_post_fee_r'], 3)}R each. Both are the "
        "published rule, not a tuned version of it.\n\n"
        "The verdicts are in the discard-bar table and are not restated here as a single word, "
        "because\nthere is no single word: each timeframe carries a verdict per exit variant and "
        f"they differ. What\nunifies them is the caveat - the exit that earns is "
        f"\"{t_both}\", the position\nsize is one unit where the original used four, and the holding "
        "time is long enough that funding\nis the largest unpriced number on the page."
    )

    # Every part above is rendered into memory first, so a formatting mistake in the
    # prose cannot leave one log written and the other not. Only now are files touched.
    md = "\n\n".join(parts)
    _csv_rows(summary, cov)
    logbook.log_md(md)


if __name__ == "__main__":
    if "--render" in sys.argv:
        with open(SNAPSHOT, "rb") as fh:
            write_logs(**pickle.load(fh))
        print(f"Logs re-rendered from {SNAPSHOT}: strategy_log.csv and strategy_log.md")
    else:
        main(write="--log" in sys.argv)
