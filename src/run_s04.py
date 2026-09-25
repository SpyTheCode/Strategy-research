"""Run Strategy #4 - Crabel's Opening Range Breakout, and log it.

Usage:  .venv\\Scripts\\python.exe src\\run_s04.py [--log]
"""

from __future__ import annotations

import sys

import numpy as np

import bybit_data as bd
import context_checks
import lookahead_check
import logbook
import runner
import s04_crabel_orb as s04
from discard_bar import BAR, verdict
from harness import add_regime_columns, forced_13_exit, metrics, simulate_resting

NAME = "Crabel Opening Range Breakout (stretch 0.8x 10-day range, no stop, exit next open)"
COINS_STR = "BTCUSDT+SOLUSDT+XRPUSDT"

# Four timeframes, but read the module docstring: they are one test at four
# execution resolutions, not four independent tests. 1H is the headline because
# it resolves the entry bar most finely, and the entry bar is where the only
# serious measurement problem on this strategy lives.
IVS = ["1H", "4H", "6H", "1D"]
HEADLINE_TF = "1H"
BARS_PER_SESSION = {"1H": 24, "4H": 6, "6H": 4, "1D": 1}

# The source's own numbers, for a like-for-like column. Stated GROSS of
# commissions and slippage, on 84 equally weighted futures markets.
PAPER_SHARPE_FULL = 1.40
PAPER_DECADES = [
    ("1970s-1990s", "above 6"),
    ("2000s", "2.92"),
    ("2010s", "0.91"),
]
PAPER_NEGATIVE_YEARS = "22 of 103"


def make_spec(reading: str = "avg", r_mult: float = 1.0,
              cond: str = "all") -> runner.StrategySpec:
    bits = [f"reading={reading}"]
    if r_mult != 1.0:
        bits.append(f"1R={r_mult:g}xstretch")
    if cond != "all":
        bits.append(f"cond={cond}")
    return runner.StrategySpec(
        name=f"{NAME} [{' '.join(bits)}]",
        add_indicators=lambda df: s04.add_indicators(df, reading, r_mult, cond),
        entry=s04.no_entry,          # never consulted: this spec is resting=True
        native_exit=s04.native_exit,
        warmup=0,                    # replaced by warmup_fn
        warmup_fn=s04.warmup_for,
        native_time_limit=None,      # the session's end is the exit, nothing else
        resting=True,
    )


def show_audit(symbol: str = "BTCUSDT", interval: str = HEADLINE_TF) -> bool:
    """Print the lookahead proof on one dataset so it is visible, not asserted."""
    df = bd.drop_forming_bar(bd.load(symbol, interval), interval)
    raw = df[[c for c in df.columns if c in lookahead_check.RAW]].copy()
    return lookahead_check.report(
        f"{NAME} on {symbol} {interval}", raw, s04.add_indicators,
        first_cut=max(300, s04.warmup_for(interval) + 50),
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
    """Long leg vs short leg, separately. Crabel's rule is symmetric by design."""
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


def stretch_pct(symbol: str, interval: str, reading: str = "avg") -> float:
    """Median stretch as a percentage of the session's opening price."""
    df = bd.drop_forming_bar(bd.load(symbol, interval), interval)
    f = s04.add_indicators(df, reading)
    return float((f["stretch"] / f["session_open"] * 100.0).median())


def session_limit_forced(interval: str) -> dict:
    """Forced 1:3 with the time limit cut to ONE session instead of 30 bars.

    Not the headline, and not a tuned parameter: it exists because the project's
    30-bar forced time limit is 30 DAYS on this strategy at 1D and 7.5 days at
    6H, while the native rule holds for part of one day. That mismatch is what
    makes the two variants stop trading the same sessions, so the fair-comparison
    version has to be shown next to the standard one.
    """
    pooled = []
    for symbol in runner.COINS:
        df = add_regime_columns(bd.drop_forming_bar(bd.load(symbol, interval), interval))
        f = s04.add_indicators(df)
        pooled.extend(simulate_resting(
            f, forced_13_exit, warmup=s04.warmup_for(interval),
            time_limit_bars=BARS_PER_SESSION[interval],
        ))
    return metrics(pooled, interval=interval)


def detail(res: dict, interval: str) -> str:
    """Exit reason mix and average hold, per variant, for one timeframe."""
    bits = []
    for label in ["native", "forced-1:3"]:
        m = res["pooled"][(interval, label)]
        mix = ", ".join(f"{k} {v}" for k, v in sorted(m["exit_reason_mix"].items()))
        bits.append(f"  {interval} {label:<11} exits: {mix or 'none'} | "
                    f"avg bars held {m['avg_bars_held']:.1f}")
    return "\n".join(bits)


def main(write: bool) -> None:
    print(f"Strategy #4 - {NAME}")
    print("=" * 78)

    print("\nLookahead audit, shown in full on one dataset")
    if not show_audit():
        print("AUDIT FAILED - stopping, no numbers produced.")
        sys.exit(1)

    spec = make_spec()
    res = runner.run(spec, intervals=IVS)
    summary = runner.summarise(spec, res, intervals=IVS)

    print("\nExit detail")
    for interval in IVS:
        print(detail(res, interval))

    print("\nSession accounting (three coins summed): what the resting orders did")
    print(f"{'tf':<5} {'variant':<11} {'armed':>7} {'traded':>7} {'no touch':>9} "
          f"{'both sides':>11} {'blocked':>8}")
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            f = fills(res, interval, label)
            print(f"{interval:<5} {label:<11} {f['sessions_armed']:>7} {f['traded']:>7} "
                  f"{f['no_touch']:>9} {f['ambiguous']:>11} {f['blocked']:>8}")

    print("\nPer coin, per timeframe, per exit")
    print(runner.per_coin_table(res, intervals=IVS))

    r1_pct = float(np.median([stretch_pct(s, HEADLINE_TF) for s in runner.COINS]))
    ctx = context_checks.summarise(res, runner.COINS, IVS, stop_pct=r1_pct)
    print("\nContext checks - is the test fair, and is the result distinguishable from luck")
    print(context_checks.text_block(ctx, IVS, stop_pct=r1_pct))

    # --- sensitivities ------------------------------------------------------
    print("\nSensitivities on the headline timeframe only")
    sens: dict = {}
    for tag, kw in [
        ("stretch = 0.8 x mean 10-day range (traded)", {}),
        ("stretch = 0.8 x 10-day high-low span", {"reading": "span"}),
        ("stretch = mean 10-day smaller open tail", {"reading": "tail"}),
        ("1R = 2 x stretch", {"r_mult": 2.0}),
        ("only after a narrow-range day (NR7)", {"cond": "bnr"}),
        ("only after a wide-range day (WR7)", {"cond": "bwr"}),
    ]:
        sres = runner.run(make_spec(**kw), intervals=[HEADLINE_TF])
        sens[tag] = sres["pooled"]
        for label in ["native", "forced-1:3"]:
            m = sres["pooled"][(HEADLINE_TF, label)]
            v, _ = verdict(m, label)
            print(f"  {tag:<44} {label:<11} n={m['trades']:>5} "
                  f"R={m['r_sum_post_fee']:>7.1f} sh={m['sharpe_post_fee']:>6.2f} {v}")

    print("\nForced 1:3 with the time limit cut from 30 bars to one session")
    slim = {}
    for interval in IVS:
        m = session_limit_forced(interval)
        slim[interval] = m
        v, _ = verdict(m, "forced-1:3")
        print(f"  {interval:<4} n={m['trades']:>5} R={m['r_sum_post_fee']:>7.1f} "
              f"sh={m['sharpe_post_fee']:>6.2f} {v}")

    if write:
        write_logs(res, summary, ctx, sens, slim, r1_pct)
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


def _md_entrybar(res: dict, ctx: dict) -> str:
    rows = ["| Timeframe | Native: died on entry bar | Forced 1:3: died on entry bar "
            "| Forced trades stopped out | Reading |", "|" + "---|" * 5]
    note = {"1H": "most faithful", "4H": "distorted", "6H": "heavily distorted",
            "1D": "meaningless for the forced variant"}
    for interval in IVS:
        m = res["pooled"][(interval, "forced-1:3")]
        stops = m["exit_reason_mix"].get("stop", 0)
        tot = max(m["trades"], 1)
        rows.append(
            f"| {interval} | {ctx[interval]['first_bar_native']:.0%} "
            f"| {ctx[interval]['first_bar_forced']:.0%} "
            f"| {stops} of {m['trades']} ({stops / tot:.0%}) | {note[interval]} |"
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


def _md_slim(summary: dict, slim: dict) -> str:
    rows = ["| Timeframe | Forced 1:3, 30-bar limit (standard) | Forced 1:3, one-session limit "
            "| R/trade, standard -> one-session |", "|" + "---|" * 4]
    for interval in IVS:
        a = summary[interval]["forced-1:3"]
        b = slim[interval]
        rows.append(
            f"| {interval} | {a['trades']} trades, {_g(a['r_sum_post_fee'], 1)}R, "
            f"Sharpe {_g(a['sharpe_post_fee'])} | {b['trades']} trades, "
            f"{_g(b['r_sum_post_fee'], 1)}R, Sharpe {_g(b['sharpe_post_fee'])} "
            f"| {_g(a['expectancy_post_fee_r'], 3)}R -> {_g(b['expectancy_post_fee_r'], 3)}R |"
        )
    return "\n".join(rows)


def _md_fills(res: dict) -> str:
    rows = ["| Timeframe | Exit | Sessions with orders placed | Traded | Neither side reached "
            "| Both sides in one bar (skipped) | Blocked by an open trade |",
            "|" + "---|" * 7]
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            f = fills(res, interval, label)
            a = max(f["sessions_armed"], 1)
            rows.append(
                f"| {interval} | {label} | {f['sessions_armed']} "
                f"| {f['traded']} ({f['traded'] / a:.0%}) "
                f"| {f['no_touch']} ({f['no_touch'] / a:.0%}) "
                f"| {f['ambiguous']} ({f['ambiguous'] / a:.1%}) "
                f"| {f['blocked']} ({f['blocked'] / a:.0%}) |"
            )
    return "\n".join(rows)


def _md_risk() -> str:
    """How far the trigger sits from the open, per coin, against one candle.

    Strategy #1's weakness was a 1R narrower than a single candle. Here 1R is
    one stretch, which is 0.8 of an average DAY's range, so on hourly bars it is
    many candles wide. That is the healthy direction for the intrabar tie-break,
    and it is also why fees are a small fraction of 1R on this strategy.
    """
    rows = ["| Coin | Timeframe | Stretch (= 1R) as % of price | Typical candle range % "
            "| 1R in candles |", "|" + "---|" * 5]
    for symbol in runner.COINS:
        for interval in IVS:
            r1 = stretch_pct(symbol, interval)
            rng = context_checks.median_candle_range_pct(symbol, interval)
            rows.append(f"| {symbol} | {interval} | {r1:.2f}% | {rng:.2f}% "
                        f"| {r1 / rng:.1f}x |")
    return "\n".join(rows)


def _md_regime(summary: dict) -> str:
    rows = ["| Timeframe | Exit | Best condition | Worst condition |", "|" + "---|" * 4]
    for interval in IVS:
        for label in ["native", "forced-1:3"]:
            m = summary[interval][label]
            rows.append(f"| {interval} | {label} | {m['best_regime']} | {m['worst_regime']} |")
    return "\n".join(rows)


def write_logs(res: dict, summary: dict, ctx: dict, sens: dict,
               slim: dict, r1_pct: float) -> None:
    """Compose the whole write-up first, then append it. Nothing is ever edited."""
    _csv_rows(summary)

    h = summary[HEADLINE_TF]
    hn, hf = h["native"], h["forced-1:3"]
    keeps = [f"{i} {lab}" for i in IVS for lab, k in
             [("native", "verdict_native"), ("forced-1:3", "verdict_forced")]
             if summary[i][k] == "KEEP"]
    n_counts = ", ".join(f"{i} {summary[i]['native']['trades']}" for i in IVS)
    amb_total = sum(fills(res, i, "native")["ambiguous"] for i in IVS)
    arm_total = sum(fills(res, i, "native")["sessions_armed"] for i in IVS)
    t_head = ctx[HEADLINE_TF]["sig_native"]["t_net"]
    best_nat = max(IVS, key=lambda i: summary[i]["native"]["sharpe_post_fee"]
                   if summary[i]["native"]["sharpe_post_fee"] ==
                   summary[i]["native"]["sharpe_post_fee"] else -9)
    nat_sharpes = ", ".join(f"{i} {_g(summary[i]['native']['sharpe_post_fee'])}" for i in IVS)
    nat_rr = ", ".join(f"{i} {_g(summary[i]['native']['rr_achieved'])}" for i in IVS)

    dn = summary[IVS[-1]]["native"]
    dn13 = summary[IVS[-1]]["forced-1:3"]
    bar_exp, bar_shp = BAR.keep_expectancy_r, BAR.keep_sharpe
    bar_rec, bar_rr = BAR.keep_r_recovery, BAR.keep_rr_native
    arm_1st = fills(res, IVS[0], "native")["sessions_armed"]
    arm_last = fills(res, IVS[-1], "native")["sessions_armed"]
    span_pct = float(np.median([stretch_pct(s, HEADLINE_TF, "span") for s in runner.COINS]))
    tail_pct = float(np.median([stretch_pct(s, HEADLINE_TF, "tail") for s in runner.COINS]))
    t_net_all = ", ".join(f"{i} {ctx[i]['sig_native']['t_net']:+.2f}" for i in IVS)
    t_gross_all = ", ".join(f"{i} {ctx[i]['sig_native']['t_gross']:+.2f}" for i in IVS)
    gross_last = ctx[IVS[-1]]["sig_native"]["gross_mean"]

    # The four outcome columns of the fills table should add up to the armed
    # column. Where they do not, say so and say why, rather than leaving a
    # reader to find the gap.
    def _unaccounted(interval: str) -> int:
        f = fills(res, interval, "native")
        return (f["sessions_armed"] - f["traded"] - f["no_touch"]
                - f["ambiguous"] - f["blocked"])
    unfin = {i: _unaccounted(i) for i in IVS}
    unfin_total = sum(unfin.values())
    unfin_str = ", ".join(f"{i} {unfin[i]}" for i in IVS)
    filled_last = fills(res, IVS[-1], "native")["traded"]
    closed_last = summary[IVS[-1]]["native"]["trades"]

    parts: list[str] = []
    parts.append(f"""## Strategy #4 - Crabel Opening Range Breakout ("the stretch")

**Tested:** {logbook.date.today().isoformat()} · **Coins:** BTCUSDT, SOLUSDT, XRPUSDT ·
**Timeframes:** 1H, 4H, 6H, 1D · **Fees:** taker on both legs (0.055% each), every number below is post-fee ·
**Session boundary:** 00:00 UTC

**Source:** Toby Crabel, *Opening Range Breakout: A Century*, tobycrabel.substack.com, 2025.
This is the originator describing his own rule, which is the best-sourced strategy on the
list so far. Everything in the next section is a direct quotation.

### The rule, in the source's own words

* "Compute the distance, call it the stretch, and place a buy stop that far above the open
  and a sell stop that far below it."
* "The stretch is set at 0.8 times the ten-day range, held the same way throughout this book."
* "Whichever side trades first is the position."
* "There is no protective stop."
* "The trade is held until the next day's open, and exited there."

There is no setup filter and no trend filter in the baseline. Every session gets two orders.
He defends the missing stop rather than merely preferring it: "A stop is a second decision
layered on top of the first one", which would mix entry quality with exit quality and break
comparability across a century of data.""")

    decades = " · ".join(f"{era} {val}" for era, val in PAPER_DECADES)
    parts.append(f"""### What the source claims, and what he refuses to claim

Full-period stream-level **Sharpe {PAPER_SHARPE_FULL:.2f}**, stated GROSS of commissions and
slippage, on 84 equally weighted futures markets, January 1923 to July 2025. Decade averages
of annual Sharpe: {decades}. {PAPER_NEGATIVE_YEARS} years negative.

He publishes **no win rate and no reward-to-risk on purpose**: "We think in dollars and Sharpe
here, not in percentages of winning trades." So there is no 1:3 claim attached to this
strategy. It is on the list as a documented long-run performer, not as a documented 1:3
system, and the forced-1:3 variant below is this project's imposition, not his.

### What this test could not reproduce, stated before any results

1. **The opening auction.** This is the largest adaptation in the project so far. Crabel's
   edge lives in a pit that closes overnight, gaps, and reopens with an auction that
   concentrates a night of orders into one moment. Crypto never closes. 00:00 UTC is used
   because it is what the exchange's own daily candle uses, but it is a timestamp, not an
   event. If this strategy fails here, "crypto has no opening auction" is a sufficient
   explanation on its own, and the failure does not disprove Crabel.
2. **Eighty-four markets.** His number is a portfolio Sharpe across grains, metals,
   energies, rates and currencies. Three correlated crypto perpetuals cannot reproduce it.
   This is the single largest reason to expect a lower number here, and it is a property of
   the test, not of the rule.
3. **Gross versus post-fee.** His 1.40 pays no commission. Every number here is post-fee at
   Bybit taker rates on both legs, so the comparison is deliberately unfair to this test.
4. **A hundred years.** He has 103 years. This has about six on BTC and less on the others.

### What "the ten-day range" means, which the source never resolves

Two readings are available and they differ by three to four times. **AVG** (the mean of the
last ten daily ranges) is traded as the baseline because it is the only reading that puts the
trigger a plausible distance from the open. **SPAN** (highest high minus lowest low over ten
days) would place the trigger about {span_pct:.1f}% from the open on these coins - measured, not
estimated - and would barely ever fill; it is run as a sensitivity rather than argued about. A third reading - the ten-day mean of the
smaller open-to-high / open-to-low tail, with no 0.8 multiplier - is described by third-party
indicator authors as the 1990 book's definition; I have not read the book, so that reading is
attributed to them and not to Crabel, and it is also run as a sensitivity.""")

    parts.append(f"""### How 1R was defined here, and why it needed a decision

The source has no stop, so it has no natural risk unit, and every number in this project is
expressed in R. Inventing a stop and calling it Crabel's would misrepresent him. Instead
**1R = one stretch** - the same quantity that defines the entry - used as a measuring stick,
not as an order. The native variant enforces no stop whatsoever, exactly as written. Only the
forced-1:3 variant turns 1R into a real stop, which is what that variant is for.

One arithmetic consequence, stated before the results because it explains them: entry is one
stretch away from the open, so with 1R = one stretch the forced stop lands **exactly on the
session open**. That is a coincidence of the definition, not a choice. 1R = two stretches is
run as a sensitivity, which moves the forced stop onto the opposite trigger - the classic
stop-and-reverse level.

On these coins one stretch is about **{r1_pct:.2f}% of price**, so the 0.11% round-trip fee is
a small fraction of 1R. That is the opposite of Strategy #1's problem and it is why fee cost
per trade is around {_g(hn['avg_fee_cost_r'], 3)}R here instead of a third of the edge.

### Lookahead bias: what was checked, freshly, for this strategy

Every computed column is rebuilt on truncated history - only bars up to and including bar *i*
exist - and compared with the same column computed on the full history. Any column that
changes when the future is removed would fail. **All 9 computed columns passed on every
dataset tested, to 1e-12, at 25 separate cut points.** Three places needed real care:

* **The stretch** is built from daily bars and then lagged one full day, so a bar on day D
  uses days D-10 through D-1 and never its own day.
* **The session open** is the only place in this project where a decision uses the current
  bar's own open. That is legitimate here and nowhere else: an open price is known at the
  instant the bar begins, which is exactly the instant Crabel places his two orders.
* **Session boundaries** are derived from the clock, never by asking "does the next row belong
  to a different day". The row-neighbour version would answer differently on the last bar of
  a truncated frame, and the audit would correctly fail it.

The new execution path deserves its own paragraph, because this strategy needed one. Crabel's
orders rest in the market at prices fixed before the session starts, and they fill intrabar at
their own price. So the engine must ask whether bar *i*'s high or low reached a resting level -
which means it does touch bar *i*'s high and low. That is not a relaxation of the rule. The
strategy is forbidden from using bar *i*'s high or low to DECIDE anything; the engine is
required to use them to fill an order that was already sitting there at a price knowable
before the bar opened. Six new hand-built-candle tests pin that behaviour down, including
filling at the trigger, filling at a worse price when a bar gaps through it, and refusing to
guess when one bar covers both sides.""")

    parts.append(f"""### Results - three coins pooled per timeframe, every number post-fee

Read the four timeframes as **one test at four execution resolutions**, not as four
independent tests. Nothing about the rule changes with the bar size: the session is always the
UTC day and the triggers are always the day's open plus and minus one stretch. All that changes
is how finely the bars can resolve WHEN a resting order was penetrated. 1H is the headline
because it resolves that most finely.

{_md_table(summary)}

**Verdicts, per exit variant, never collapsed:**

* **Native (Crabel's own rule):** {" · ".join(f"{i} {summary[i]['verdict_native']} - {summary[i]['reason_native']}" for i in IVS)}
* **Forced 1:3:** {" · ".join(f"{i} {summary[i]['verdict_forced']} - {summary[i]['reason_forced']}" for i in IVS)}

KEEP rows: {", ".join(keeps) if keeps else "none"}.

### Where the native rule actually stands against the bar

All four native rows are INCONCLUSIVE, but **not for the same reason at each resolution**, and
the difference matters:

* At {", ".join(IVS[:-1])} the native rule misses three of the four KEEP tests - expectancy,
  Sharpe and achieved reward-to-risk.
* At {IVS[-1]} it misses **exactly one**: post-fee expectancy
  {_g(dn['expectancy_post_fee_r'], 3)}R against the {bar_exp:+.2f}R floor. It clears Sharpe
  ({_g(dn['sharpe_post_fee'])} against {bar_shp:.2f}), R-recovery ({_g(dn['r_recovery'])}
  against {bar_rec:.2f}) and achieved RR ({_g(dn['rr_achieved'])} against {bar_rr:.2f}).

**One prediction of mine was wrong and the result corrected it.** Before running this I expected
a no-stop, fixed-time-exit rule to produce near-symmetric winners and losers, so an achieved RR
near 1.0 that could never clear the 1.50 requirement. Measured RR is {nat_rr} - it clears the
requirement at {IVS[-1]}. A position with no stop keeps whatever the session gives it, so the
winners run further than the losers even though only about {hn['win_rate']:.0%} of trades win.
The bar's native RR test is not what blocks this strategy. The +{bar_exp:.2f}R expectancy floor
is, and it is not close to arbitrary: {_g(hn['expectancy_post_fee_r'], 3)}R per trade at
{HEADLINE_TF} is a thin edge to run a real book on.

**A caution on reading the four resolutions as a trend.** Per-trade edge rises with bar size
({", ".join(f"{i} {_g(summary[i]['native']['expectancy_post_fee_r'], 3)}R" for i in IVS)}), but
the four rows are not the same sample: the warmup floor puts a different start date on each
({arm_1st} armed sessions at {IVS[0]} against {arm_last} at {IVS[-1]}), and the coarsest bars
skip the whipsaw sessions that penetrated both triggers on the same day. So this is not
evidence that the rule works better on daily bars.

### Exit-death check - and why it can only be indicative here

{" ".join(f"{i}: {summary[i]['exit_death']} ({summary[i]['exit_death_diag']})." for i in IVS)}

The comparison has a measurable weakness on this strategy, and it differs at each end of the
timeframe axis. The project's forced variant carries a 30-bar time limit, which is 30 DAYS at
{IVS[-1]} and 7.5 days at 6H, while the native rule holds for part of one session. The two
variants therefore hold for wildly different lengths, block different sessions, and end up
trading different entries: shared entries run {", ".join(f"{i} {ctx[i]['overlap']:.1%}" for i in IVS)},
against the {context_checks.MIN_OVERLAP:.0%} minimum needed for "same entries, only the exit
differs" to be a fair claim. On the fine bars the two variants are not comparing exits on a
like-for-like set. At {IVS[-1]} the overlap is fine, but there the forced side is 100% entry-bar
artifact (next section) - so the flag is untrustworthy at both ends of the axis, for two
unrelated reasons. Rather than tune a project-wide constant to flatter one strategy, the forced
variant is re-run with its time limit cut to a single session further down, clearly labelled.

What survives all of that: the two variants disagree on the **sign** of the edge at every
resolution, by a margin far larger than the overlap gap could account for. The edge lives in
Crabel's own exit, which is the one thing this check was built to detect.""")


    parts.append(f"""### What the resting orders actually did

Every armed session places two stop orders. This table says what became of them, summed over
the three coins. It is the honest denominator: only about a third of armed sessions produce a
trade at all, so the trade counts above are not "one trade per day".

{_md_fills(res)}

Across all four timeframes, **{amb_total} of {arm_total} armed sessions** were skipped because a
single bar covered both triggers and plain OHLC cannot say which side traded first. Those
sessions are counted and discarded rather than guessed. I expected this to be the main problem
on daily bars and it measurably is not: the stretch is 0.8 of an average day's range on EACH
side, so a bar has to span 1.6 average ranges with the open near its middle.

Two accounting notes, so the table can be checked rather than trusted. First, the four outcome
columns fall {unfin_total} sessions short of the armed column in total ({unfin_str}): each coin's
final session was still in progress when the data ended, so it was armed but never reached its
own closing bar and belongs in none of the outcome columns. At 1D a session is a single bar, so
nothing is left unfinished there. Second, "Traded" counts orders that FILLED, while the results
table counts trades that CLOSED - a trade still open when the data runs out is discarded rather
than valued at the last price. That is the whole of the difference between the {filled_last}
filled and {closed_last} closed on the 1D native row.

### The one real measurement problem, and its exact size

A trade entered part-way through a bar is still tested against the WHOLE of that bar, including
the part that happened before the resting order was penetrated. This project keeps that
pessimism deliberately - it can never flatter a result - but on this strategy it interacts badly
with the forced variant. With 1R = one stretch the forced stop sits exactly on the session open,
and a candle's low is almost always at or below its own open, so the further the bar size is
from the entry moment, the more forced trades are recorded as stopped out on their entry bar.

{_md_entrybar(res, ctx)}

**Read the forced-1:3 rows on 4H, 6H and 1D as a measurement of the data's resolution, not of
the rule.** At 1D the forced variant is not testing Crabel at all. The native rule has no stop
whatsoever, so it is completely untouched by this at every resolution - which is fortunate,
because the native rule is the one Crabel actually published.

### Against the source's own claim

| | Crabel's published test | This test |
|---|---|---|
| Markets | 84 futures, equally weighted | 3 crypto perpetuals, correlated |
| Period | Jan 1923 - Jul 2025, 103 years | Bybit history, about 6 years |
| Costs | gross, no commission | post-fee, taker both legs |
| Sharpe | {PAPER_SHARPE_FULL:.2f} full period | {nat_sharpes} (native, by timeframe) |
| Win rate / RR | not published, on purpose | measured here anyway |
| Best decade | above 6 (1970s-90s) | best resolution here: {best_nat} |
| Worst decade | 0.91 (2010s) | - |

The gap in Sharpe is expected and mostly explained by the portfolio effect: 84 weakly
correlated streams against 3 that mostly move together. This test cannot separate "the rule is
weaker in crypto" from "three coins is not a portfolio".

One like-for-like note, since his figure is gross: pre-fee, the daily native row here earns
{gross_last:+.4f}R per trade and post-fee {_g(dn['expectancy_post_fee_r'], 4)}R - so fees consume
about {(1 - dn['expectancy_post_fee_r'] / gross_last):.0%} of the raw edge. The harness only
computes Sharpe post-fee, so no pre-fee Sharpe is quoted here rather than estimating one.

### Long leg versus short leg

Crabel's rule is symmetric by design, so an asymmetric result is information about the market
rather than about the rule.

{_md_legs(res)}""")

    parts.append(f"""### Sensitivities, on the headline timeframe only

Each row changes exactly one thing. None of these is a tuned parameter: the baseline is the
source's own 0.8 x ten-day range, and everything else exists to show how fragile that choice is.

{_md_sens(sens)}

What the rows mean in words:

* **SPAN** puts the trigger {span_pct:.1f}% from the session open instead of {r1_pct:.1f}%, and
  the sample collapses to a small fraction of the baseline's trades. That settles the source's
  ambiguity by arithmetic rather than by argument: SPAN cannot be the reading Crabel traded,
  because it would almost never fill.
* **The tail reading** puts the trigger {tail_pct:.1f}% from the open, so it fills constantly and
  pays a round-trip fee on every one of those fills. The fee-cost column is the tell, and the
  result is the worst in the table.
* **1R = 2 x stretch** must leave the native Sharpe unchanged and halve every R, because it
  only rescales the measuring stick. It does. That is a check on my own arithmetic, not a
  result. It does change the forced variant, because the stop moves off the session open.
* **NR7 / WR7 conditioning** is the framework Crabel names but defers to paywalled chapters,
  so N = 7 is this project's placeholder and the comparison is indicative only.

### Forced 1:3 with a fair time limit

The standard forced variant holds up to 30 bars. Cut to one session, it becomes comparable to
the native rule in holding period. This is a fair-comparison exhibit, not a tuned result.

{_md_slim(summary, slim)}

It does not rescue the forced variant. At {HEADLINE_TF} the loss shrinks; at 4H and 6H it gets
worse, because a one-session limit forces more trades to be opened into the same entry-bar stop
problem instead of a few being blocked by an existing position. At {IVS[-1]} the two columns are
identical, since one session is one bar there. The conclusion does not depend on the time limit.

### Per coin, per timeframe, per exit

```
{runner.per_coin_table(res, intervals=IVS)}
```

### Is this distinguishable from luck

```
{context_checks.text_block(ctx, IVS, stop_pct=r1_pct)}
```

At {HEADLINE_TF} the native variant's t-statistic on post-fee per-trade R is **{t_head:+.2f}**
(rough reading: below 2, the average sits inside the range chance alone would produce). Across
the axis, post-fee t runs {t_net_all} while pre-fee t runs {t_gross_all}. **That is the single
most useful line in this write-up:** the entry rule produces an edge that is clearly separable
from noise before costs at every resolution, and fees take it back down to marginal on the fine
bars. Native trade counts are healthy everywhere ({n_counts}), so nothing here fails for sample
size, and no native trade at all resolved inside its own first candle - so the intrabar
tie-break never decided a native result.

### 1R against one candle

{_md_risk()}

The contrast with Strategy #1 is the point: there 1R was narrower than a single candle, so the
tie-break rule decided the outcomes. On hourly bars 1R here is {_g(r1_pct / context_checks.median_candle_range_pct(runner.COINS[0], HEADLINE_TF), 1)}x
a typical BTC candle, which is the healthy direction. But read the {IVS[-1]} rows: one stretch is
0.8 of an average DAY's range, so against a daily candle it is roughly one candle or less - below
1x on two of the three coins. **That is the mechanism behind the entry-bar artifact**, not a
separate problem: a stop one candle away, tested against the whole candle it was opened in, is
guaranteed to be hit. It costs the forced variant everything and the native rule nothing.

### Best and worst conditions

{_md_regime(summary)}""")

    parts.append(f"""### Funding, flagged not modelled

These are perpetual futures, which charge or pay funding every eight hours. The native rule
holds for part of one session, so a trade crosses roughly one or two funding stamps; the forced
variant's 30-bar limit can hold for weeks at 6H and 1D and would cross dozens. **No funding is
modelled anywhere in this project yet**, per the standing instruction, so the multi-day forced
rows in particular are missing a real cost. Direction matters too: funding is usually paid by
longs in a rising market, and this rule is symmetric, so the two legs would not be affected
equally. This is a flag on the numbers above, not an adjustment to them.

### What would change the verdict

* **A real portfolio.** The claim is a portfolio claim. Running the identical rule on 30-50
  perpetuals instead of 3 is the single change most likely to move the Sharpe, and it tests
  what Crabel actually published rather than a three-coin slice of it.
* **A session boundary that is an event, not a timestamp.** Any hour with a genuine
  concentration of crypto order flow - the CME open, a daily funding stamp, the US equity open
  - would test "opening range breakout" better than midnight UTC does. That is a different
  experiment, not a tuning of this one.
* **Tick or minute data on the entry bar.** It would remove the entry-bar artifact entirely and
  make the forced-1:3 rows meaningful at every resolution. It would not change the native rows.
* **Fees are the binding constraint at {IVS[-1]}, and they are real.** Pre-fee, the daily native
  row earns {gross_last:+.4f}R per trade, which clears the {bar_exp:+.2f}R KEEP floor; post-fee it
  earns {_g(dn['expectancy_post_fee_r'], 4)}R, which does not. Crabel's own 1.40 Sharpe is quoted
  GROSS, so on a like-for-like basis this test's daily row would pass the bar and on a
  what-you-actually-keep basis it does not. Nothing about that is a reason to relax the bar - the
  fees get paid - but it does locate the failure precisely. A cheaper venue or a maker rebate on
  one leg would narrow the gap; the fine-bar rows are short pre-fee too, so they need more than
  cheaper fills.

### Bottom line

Crabel's own rule - no stop, out at the next session's open - **made money post-fee at every
resolution tested** ({", ".join(f"{i} {_g(summary[i]['native']['r_sum_post_fee'], 1)}R" for i in IVS)})
on three crypto perpetuals, over {arm_1st} armed sessions per coin-set at {IVS[0]}. The per-trade
edge is thin ({_g(hn['expectancy_post_fee_r'], 3)}R at {HEADLINE_TF},
{_g(dn['expectancy_post_fee_r'], 3)}R at {IVS[-1]}) and the pre-fee t-statistics
({t_gross_all}) say the entry rule is doing something real, not something random.

**Verdict: INCONCLUSIVE on the native rule at all four resolutions, DISCARD on the forced 1:3 at
all four.** INCONCLUSIVE here does not mean "too few trades" - there are over two thousand per
resolution. It means positive but short of the KEEP bar, and at {IVS[-1]} short by **one test
only**: {_g(dn['expectancy_post_fee_r'], 3)}R per trade against the {bar_exp:+.2f}R floor, with
Sharpe, R-recovery and reward-to-risk all cleared. That is the closest this project has come to a
KEEP so far, and it is still a miss.

Forcing a 1:3 exit onto the rule destroys it ({_g(hf['r_sum_post_fee'], 1)}R at {HEADLINE_TF},
{_g(dn13['r_sum_post_fee'], 1)}R at {IVS[-1]}), and the exit-death check reads "yes" at every
resolution. Some of that damage is the entry-bar artifact rather than the exit itself, which is
why the forced rows are reported with their artifact share attached and are not used to argue
anything about Crabel.

Two things this test cannot settle, and neither should be quietly resolved in the strategy's
favour: whether the missing edge is the missing opening auction, and whether three correlated
coins can express a claim that was measured on 84 weakly correlated markets. His published
Sharpe of {PAPER_SHARPE_FULL:.2f} is a portfolio number and this is not a portfolio. **Crabel's
result stands untouched by this test; what was measured here is the crypto adaptation of it.**""")

    logbook.log_md("\n\n".join(parts))


if __name__ == "__main__":
    main(write="--log" in sys.argv)







