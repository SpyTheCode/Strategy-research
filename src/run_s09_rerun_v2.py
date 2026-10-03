r"""Run Strategy #9 RE-RUN v2 - NR7 (Bulkowski) - double-touch sessions booked.

Usage:  .venv\Scripts\python.exe src/run_s09_rerun_v2.py [--log]

DRY RUN default: nothing is appended to strategy_log.md / strategy_log.csv.
NEW files only; s09_nr7.py, run_s09.py, s10_rsi2.py and run_s10.py are never
opened or touched.

The one departure from v1 (specs/s09_nr7_rerun_v2.md, rule 6): sessions where
BOTH resting orders are touched on the first armed bar (engine "ambiguous",
harness.py:385-387) are booked as 1R-loss trades instead of skipped. The
engine is NOT modified: v2 re-derives those bars by replaying the engine's
state machine on the same df the engine ran on, reconciles the count against
stats["ambiguous"], and aborts on any mismatch.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import bybit_data
import context_checks
import coverage
import discard_bar
import harness
import runner
import s09_nr7_rerun_v2 as s9
import run_s09_rerun as v1
from discard_bar import verdict
from harness import Trade, metrics

NAME = ("#9 RE-RUN v2 NR7 (Bulkowski): stop orders at NR7 high/low, REST_BARS=1, "
        "offset 0; double-touch first bars booked as 1R losses")
IVS = v1.IVS
EXITS = v1.EXITS
DT_REASON = "double-touch 1R"


def _g(x, nd=2):
    return "n/a" if x is None or x != x else f"{x:.{nd}f}"


def _fmt_t(t):
    return "n/a" if t is None or t != t else f"{t:+.2f}"


def make_spec() -> runner.StrategySpec:
    """Same rule parameters as v1; the booking convention lives outside the engine."""
    add_ind = lambda df: s9.add_indicators(df, n=7, rest_bars=1, offset_mult=0.0)
    return runner.StrategySpec(
        name=NAME,
        add_indicators=add_ind,
        entry=s9.no_entry,
        native_exit=s9.native_exit,
        warmup=0,
        warmup_fn=lambda iv: s9.warmup_for(iv),
        resting=True,
        notes=(f"n=7 rest_bars=1 offset_mult=0.0; resting stops at NR7 high/low; "
               "stop = opposite pattern end; native = measure rule (1:1 at "
               "offset 0); one position; double-touch first bars booked as 1R "
               "losses outside the engine (v2)"),
    )


# ---------------------------------------------------------------------------
# Double-touch re-derivation (the v2 departure; engine itself is untouched)
# ---------------------------------------------------------------------------

# harness.py:382-387, quoted verbatim - the branch v2 books outside the engine:
AMBIGUOUS_QUOTE = (
    "harness.py:382-387 (simulate_resting, the only place \"ambiguous\" is set):\n"
    '        if state == "open" and position is None and armed[i] and risk[i] > 0:\n'
    "            hit_buy = hi[i] >= buy[i]\n"
    "            hit_sell = lo[i] <= sell[i]\n"
    "            if hit_buy and hit_sell:\n"
    '                counts["ambiguous"] += 1\n'
    '                state = "ambiguous"'
)


def _occupancy(df: pd.DataFrame, trades: list[Trade], warmup: int,
               stats_traded: int | None = None) -> np.ndarray:
    """Bars on which the engine held a position through step 3 (the entry gate).

    A trade entered at bar e does NOT block its own entry bar: at step 3 of e
    the position was still None (the entry is what step 3 does). A same-bar
    stop/target exit fills at step 4, so the position is held at step 3 of the
    exit bar (entry gate closed there). A pending exit ("time"/"signal"/"close")
    fills at the NEXT bar's open, before the session and entry steps, so the
    exit bar is free.

    The engine DISCARDS a position still open at data end without appending it
    to the returned trades, yet that position still occupies every bar from its
    entry to the last bar. It is invisible in `trades`, so it is re-derived:
    stats["traded"] counts entries, so stats_traded > len(trades) means exactly
    one discard exists, and its entry bar is the first session at/after the
    last booked trade's release where exactly one trigger is touched (a
    double-touch there would have closed the session ambiguous, and then no
    discard could exist).
    """
    n = len(df)
    times = pd.DatetimeIndex(df["open_time"])
    occ = np.zeros(n, dtype=bool)
    for t in trades:
        e = times.get_loc(t.entry_time)
        if t.exit_time is None:
            x = n - 1                      # discarded, still held at the end
        else:
            x = times.get_loc(t.exit_time)
            if t.exit_reason not in ("stop", "target"):
                x -= 1                     # pending exit: released at x's open
        occ[e + 1:x + 1] = True            # own entry bar: position was None at step 3

    if stats_traded is not None and stats_traded > len(trades):
        # The last position never exited: hold everything from its entry bar
        # (exclusive) to data end. Find that entry bar.
        if trades:
            t = trades[-1]
            rel = times.get_loc(t.exit_time)   # exit_time is not None here
            if t.exit_reason not in ("stop", "target"):
                rel -= 1                       # pending exit released at open
        else:
            rel = warmup - 1                   # engine scan starts at warmup
        hi = df["high"].to_numpy(dtype=float)
        lo = df["low"].to_numpy(dtype=float)
        buy = df["buy_trig"].to_numpy(dtype=float)
        sell = df["sell_trig"].to_numpy(dtype=float)
        sf = df["session_first"].to_numpy(dtype=bool)
        armed = df["armed"].to_numpy(dtype=bool)
        risk = df["risk_unit"].to_numpy(dtype=float)
        for i in range(rel + 1, n):
            if not (sf[i] and armed[i] and risk[i] > 0):
                continue
            hb = hi[i] >= buy[i] if np.isfinite(buy[i]) else False
            hs = lo[i] <= sell[i] if np.isfinite(sell[i]) else False
            if hb != hs:                       # exactly one trigger: the entry
                occ[i + 1:] = True
                break
    return occ


def replay_cell(df: pd.DataFrame, warmup: int, trades: list[Trade],
                stats_traded: int | None = None
                ) -> tuple[list[Trade], dict, int]:
    """Replay the engine's state machine (harness.py:349-436) on this df and
    return the double-touch trades to book, replayed session counts, and the
    number of exact open-equidistant ties (booked long by convention).

    The replay never re-enters engine trades: it reproduces the state machine
    to find every bar the engine counted as ambiguous, so the booking can be
    reconciled against stats["ambiguous"] before anything is reported.
    `stats_traded` (the engine's stats["traded"]) lets _occupancy account for a
    final position the engine discarded at data end.
    """
    n = len(df)
    o = df["open"].to_numpy(dtype=float)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    buy = df["buy_trig"].to_numpy(dtype=float)
    sell = df["sell_trig"].to_numpy(dtype=float)
    risk = df["risk_unit"].to_numpy(dtype=float)
    armed = df["armed"].to_numpy(dtype=bool)
    s_first = df["session_first"].to_numpy(dtype=bool)
    s_last = df["session_last"].to_numpy(dtype=bool)
    regimes = (df["regime"].to_numpy(dtype=object) if "regime" in df.columns
               else np.array([""] * n, dtype=object))
    ot = df["open_time"].to_numpy()
    occ = _occupancy(df, trades, warmup, stats_traded)

    state: str | None = None
    counts = {"sessions_armed": 0, "traded": 0, "ambiguous": 0,
              "blocked": 0, "no_touch": 0}
    booked: list[Trade] = []
    ties = 0
    for i in range(warmup, n):
        if s_first[i]:
            if not armed[i]:
                state = None
            elif occ[i]:
                counts["sessions_armed"] += 1
                counts["blocked"] += 1
                state = "blocked"
            else:
                counts["sessions_armed"] += 1
                state = "open"
        if state == "open" and (not occ[i]) and armed[i] and risk[i] > 0:
            hit_buy = hi[i] >= buy[i]
            hit_sell = lo[i] <= sell[i]
            if hit_buy and hit_sell:
                counts["ambiguous"] += 1
                state = "ambiguous"
                # Rule 6: attribute to the trigger nearer the bar's open.
                db, ds = abs(o[i] - buy[i]), abs(o[i] - sell[i])
                d = 1 if db <= ds else -1
                if db == ds:
                    ties += 1
                # Gap rule (harness.py:392): fill at the worse of trigger/open.
                entry_px = float(max(buy[i], o[i]) if d > 0 else min(sell[i], o[i]))
                stop_px = float(entry_px - d * risk[i])
                booked.append(Trade(
                    direction=d, entry_time=ot[i], entry_price=entry_px,
                    initial_stop=stop_px, exit_time=ot[i],
                    exit_price=stop_px, exit_reason=DT_REASON, bars_held=0,
                    regime=str(regimes[i]),
                ))  # taker fees on both legs via Trade defaults
            elif hit_buy or hit_sell:
                counts["traded"] += 1
                state = "traded"
        if s_last[i]:
            if state == "open":
                counts["no_touch"] += 1
            state = None
    return booked, counts, ties


def cell_time_limit(label: str) -> int | None:
    return None if label == "native" else runner.FORCED_TIME_LIMIT


# ---------------------------------------------------------------------------
# v2 result assembly: engine run + booked double-touch trades, reconciled
# ---------------------------------------------------------------------------

def run_v2() -> dict:
    """Engine run exactly as v1, then book each cell's ambiguous sessions.

    Reconciliation is absolute: the replayed per-cell counts must equal the
    engine's stats dict for every key, or the run aborts before any report.
    """
    spec = make_spec()
    res = runner.run(spec, runner.COINS, IVS, audit=True)

    ties_total = 0
    v2 = {"per_cell": {}, "pooled": {}, "trades": {}, "fills": res["fills"],
          "audit": res["audit"], "v1_per_cell": {}, "v1_pooled": {},
          "booked_n": {}, "ties": {}, "recon": {}}

    for iv in IVS:
        warmup = spec.warmup_for(iv)
        pooled = {lab: [] for lab in EXITS}
        for sym in runner.COINS:
            df = runner._prepare(spec, sym, iv)
            for label in EXITS:
                engine_trades = res["trades"][(sym, iv, label)]
                fills = res["fills"][(sym, iv, label)]
                booked, counts, ties = replay_cell(
                    df, warmup, engine_trades, fills.get("traded"))
                # --- reconciliation: replay must equal the engine, or abort --
                for k in ("sessions_armed", "traded", "ambiguous",
                          "blocked", "no_touch"):
                    if counts[k] != fills.get(k):
                        raise RuntimeError(
                            f"RECONCILIATION FAILED {sym} {iv} {label} {k}: "
                            f"replay {counts[k]} != engine {fills.get(k)}")
                merged = sorted(engine_trades + booked,
                                key=lambda t: t.entry_time)
                ties_total += ties
                v2["booked_n"][(sym, iv, label)] = len(booked)
                v2["ties"][(sym, iv, label)] = ties
                v2["recon"][(sym, iv, label)] = counts
                v2["per_cell"][(sym, iv, label)] = metrics(merged, interval=iv)
                v2["v1_per_cell"][(sym, iv, label)] = res["per_cell"][(sym, iv, label)]
                v2["trades"][(sym, iv, label)] = merged
                pooled[label].extend(merged)

        for label in EXITS:
            v2["pooled"][(iv, label)] = metrics(pooled[label], interval=iv)
            v2["v1_pooled"][(iv, label)] = res["pooled"][(iv, label)]
            v2["trades"][(iv, label)] = pooled[label]

    v2["spec"] = spec
    v2["ties_total"] = ties_total
    return v2



# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def v2_summary(v2: dict) -> dict:
    """Verdicts on the v2 pooled metrics, with the v1 verdict kept alongside."""
    out: dict = {}
    for iv in IVS:
        n, f13 = v2["pooled"][(iv, "native")], v2["pooled"][(iv, "forced-1:3")]
        n1, f1 = v2["v1_pooled"][(iv, "native")], v2["v1_pooled"][(iv, "forced-1:3")]
        vn, rn = verdict(n, "native")
        vf, rf = verdict(f13, "forced-1:3")
        v1n, _ = verdict(n1, "native")
        v1f, _ = verdict(f1, "forced-1:3")
        out[iv] = {
            "native": n, "forced-1:3": f13,
            "verdict_native": vn, "reason_native": rn,
            "verdict_forced": vf, "reason_forced": rf,
            "v1_native": n1, "v1_forced": f1,
            "v1_verdict_native": v1n, "v1_verdict_forced": v1f,
        }
    return out


def results_table(v2: dict, summary: dict) -> str:
    HEAD = (f"{'tf':<4} {'exit':<11} {'trades':>6} {'ofDT':>5} {'win%':>6} "
            f"{'W/L':>9} {'R pre':>8} {'R post':>8} {'R/trade':>8} "
            f"{'Sharpe':>7} {'DD%':>6} {'DD R':>7} {'recov':>7} "
            f"{'fee/tr':>7}  verdict")
    lines = [HEAD, "-" * len(HEAD)]
    for iv in IVS:
        for label in EXITS:
            m = v2["pooled"][(iv, label)]
            v = summary[iv]["verdict_native" if label == "native" else "verdict_forced"]
            ts = [t for t in v2["trades"][(iv, label)]
                  if t.exit_price is not None and np.isfinite(t.net_r)]
            net = np.array([t.net_r for t in ts])
            raw_w = int((net > 0).sum())
            raw_l = int((net <= 0).sum())
            dt = sum(1 for t in ts if t.exit_reason == DT_REASON)
            wr = m["win_rate"] * 100 if m["win_rate"] == m["win_rate"] else float("nan")
            rec = m["r_recovery"]
            rec_s = "n/a" if rec != rec else ("inf" if rec == float("inf") else f"{rec:.2f}")
            lines.append(
                f"{iv:<4} {label:<11} {m['trades']:>6} {dt:>5} {wr:>6.1f} "
                f"{raw_w:>4}/{raw_l:<4} {_g(m['r_sum_pre_fee'], 1):>8} "
                f"{_g(m['r_sum_post_fee'], 1):>8} "
                f"{_g(m['expectancy_post_fee_r'], 3):>8} "
                f"{_g(m['sharpe_post_fee']):>7} {_g(m['max_drawdown_pct'], 1):>6} "
                f"{_g(m['max_drawdown_r'], 1):>7} {rec_s:>7} "
                f"{_g(m['avg_fee_cost_r'], 4):>7}  {v}")
        m1n = summary[iv]["v1_native"]
        m1f = summary[iv]["v1_forced"]
        lines.append(
            f"     v1 (DT skipped): native {m1n['trades']} trades, "
            f"R/trade {_g(m1n['expectancy_post_fee_r'], 3)}, "
            f"{summary[iv]['v1_verdict_native']} | forced {m1f['trades']}, "
            f"R/trade {_g(m1f['expectancy_post_fee_r'], 3)}, "
            f"{summary[iv]['v1_verdict_forced']}")
        lines.append("")
    return "\n".join(lines)


def report_intro(v2: dict, summary: dict) -> str:
    L: list[str] = []
    n_audit = len(v2["audit"])
    n_pass = sum(1 for ok, _, _ in v2["audit"].values() if ok)
    amb = {iv: {lab: sum(v2["recon"][(s, iv, lab)]["ambiguous"] for s in runner.COINS)
                for lab in EXITS} for iv in IVS}
    L += [
        "# Strategy #9 RE-RUN v2 - NR7 (Bulkowski), double-touch booked",
        "",
        "## 1. Departure from v1 (read this first)",
        "v1 followed the shared resting engine's convention: a session whose first bar",
        "touched BOTH resting orders produced no trade and was counted in",
        'stats["ambiguous"]. The v2 spec (specs/s09_nr7_rerun_v2.md, rule 6) books each',
        "such session as a 1R-loss trade: direction = the trigger nearer to bar D+1's",
        "open (exact ties - open equidistant - go long; count disclosed below), entry at",
        "the worse of trigger and open (the engine's gap rule, harness.py:392), stop at",
        "1R (the opposite pattern end), exit at the stop the same bar, taker fees on",
        "both legs. The engine was NOT modified. v2 re-derives those bars by replaying",
        "the engine's state machine (harness.py:349-436) on the same prepared data, and",
        "aborts unless the replay reproduces the engine's per-cell session counts",
        'exactly (sessions_armed, traded, ambiguous, blocked, no_touch). The booked',
        'losses carry exit_reason "double-touch 1R" so every figure below can attribute',
        "them.",
        "",
        "Pooled double-touch sessions booked (v1 skipped these):",
        "  " + " | ".join(
            f"{iv}: native {amb[iv]['native']}, forced-1:3 {amb[iv]['forced-1:3']}"
            for iv in IVS),
        f"Exact open-equidistant ties booked long by convention, all cells pooled: "
        f"{v2['ties_total']}.",
        "",
        "## 2. Unchanged from v1",
        "Same rule (N=7 strict '<', REST_BARS=1, offset 0), same engine",
        "(runner.run -> simulate_resting), same fees (taker 0.055% per side, both",
        "legs), same data (Sep 4, 2026 cache, forming bars dropped), same coverage",
        "windows, same coins (BTC/SOL/XRP) and timeframes (1H/4H/6H/1D), same exit",
        "variants (native measure rule 1:1; forced 1:3 with the 30-bar time limit),",
        "same lookahead audit, same discard-bar verdicts. Only the booking of",
        "double-touch sessions differs.",
        "",
        f"## 3. Lookahead audit - {n_pass}/{n_audit} datasets passed",
        "Identical to v1: the shared truncation audit ran before results (audit=True);",
        "a failure would have aborted the run.",
        "",
        v1.DATA_NOTE,
        "",
    ]
    L += ["## 4. Results - coins pooled per timeframe, post-fee", "```",
          results_table(v2, summary), "```",
          "'ofDT' = double-touch 1R losses included in the trade count; W/L are raw",
          "win/loss counts (win = net R > 0, loss = net R <= 0). Timeframes are never",
          "pooled with each other. Per-coin detail is printed after the report.", ""]
    return "\n".join(L)


def report_mid(v2: dict, summary: dict, ctx: dict) -> str:
    L: list[str] = []
    L += ["## 5. Significance - t-test on pooled per-trade R (post-fee), per timeframe"]
    for iv in IVS:
        s = ctx[iv]["sig_native"]
        t = s["t_net"]
        L.append(f"  {iv}: n={s['n']}, post-fee R/trade {s['net_mean']:+.4f}, "
                 f"t={_fmt_t(t)}, {'SIG at 5%' if (t == t and abs(t) >= 1.96) else 'not sig at 5%'}")
    L += ["  (n and t from the shared context_checks significance test, now computed on",
          "   the merged trade list including the booked double-touch losses.)", ""]

    def dt_lines(trades: list) -> str:
        dt = [t for t in trades if t.exit_reason == DT_REASON]
        if not dt:
            return "    double-touch booked: none"
        dl = sum(1 for t in dt if t.direction > 0)
        rs = sum(t.net_r for t in dt)
        return (f"    double-touch booked: {len(dt)} ({dl} long / {len(dt) - dl} short), "
                f"R sum {rs:+.1f} (all -1R gross plus fees)")

    L += ["## 6. Concentration and long/short - BOTH exits, pooled, post-fee"]
    for iv in IVS:
        for label in EXITS:
            trades = v2["trades"][(iv, label)]
            c = v1.concentration(trades)
            b1, b5 = c["best1_pct"], c["best5_pct"]
            # The shared helper returns nan when net R <= 0 (a share of a
            # non-positive pool is undefined); say so instead of printing nan.
            b1s = f"{b1:.1f}%" if b1 == b1 else "n/a (net R <= 0)"
            b5s = f"{b5:.1f}%" if b5 == b5 else "n/a (net R <= 0)"
            L.append(f"  {iv} {label}: best trade {b1s} of net R; "
                     f"best five {b5s}")
            L.append(dt_lines(trades))
            L.append("    long/short (pooled coins):")
            for ln in v1.long_short_lines(trades).splitlines():
                L.append("    " + ln.strip())
    L.append("")

    L += ["## 7. Exit-overlap - do native and forced-1:3 trade the same entries?",
          "Native-vs-forced entry overlap (union base), pooled per timeframe, v2 merged",
          "trades (booked double-touch entries included in both lists where hit):"]
    for iv in IVS:
        ov, m_nat, m_f13 = v1.shared_entry_rerun(v2["trades"][(iv, "native")],
                                                 v2["trades"][(iv, "forced-1:3")])
        line = f"  {iv}: overlap {ov * 100:.1f}%"
        if m_nat is not None:
            line += (f" (<{v1.MIN_OVERLAP * 100:.0f}% -> shared-entry re-run: native "
                     f"n={m_nat['trades']}, R/trade={_g(m_nat['expectancy_post_fee_r'], 3)}, "
                     f"forced n={m_f13['trades']}, R/trade={_g(m_f13['expectancy_post_fee_r'], 3)})")
        L.append(line)
    L.append("")

    L += ["## 8. Funding cost at the base rate (0.01% per 8h, estimate - Bybit rates vary)",
          "  Mean holding time and R of base-rate funding per trade (native, v2 merged):"]
    for iv in IVS:
        f = v1.funding_estimate(v2["trades"][(iv, "native")], iv)
        L.append(f"  {iv}: hold {_g(f['hold_bars'], 1)} bars | "
                 f"funding {_g(f['funding_r'], 4)} R/trade")
    L += ["  (Base rate is a floor, not a measurement; per-trade funding varies by side",
          "  and hour.)", ""]
    return "\n".join(L)


def report_tail(v2: dict, summary: dict, cov_txt: str, per_coin: str, ctx: dict) -> str:
    L: list[str] = []
    L += ["## 9. Per-coin detail (v2 metrics, pooled exit variants)", "```", per_coin, "```",
          "Data coverage per cell (identical to v1):", "```", cov_txt, "```",
          "Per-timeframe significance and entry shares (shared context_checks block,",
          "computed on the v2 merged trade lists):", "```",
          context_checks.text_block(ctx, IVS), "```", ""]
    L += ["## 10. Discard-bar verdict, cell by cell (v2 metrics)", "```"]
    for sym in runner.COINS:
        for iv in IVS:
            for label in EXITS:
                m = v2["per_cell"][(sym, iv, label)]
                vv, why = verdict(m, label)
                L.append(f"  {sym} {iv} {label:<11} {vv:<12} {why}")
    L += ["```", ""]
    L += ["## 11. The engine convention v2 departs from (quoted, verbatim)", "```",
          AMBIGUOUS_QUOTE, "```",
          "Files that call the resting simulator simulate_resting: src/runner.py:131",
          "(the shared runner, used by this re-run), src/run_s04.py:117, and six call",
          "sites in src/selftest.py that pin the engine's behaviour (including the",
          'ambiguous-count check at src/selftest.py:272-274). Every one of them inherits',
          "the skip convention; none of them was modified.",
          ""]

    L += ["## 12. Caveats", "",
          "- Funding floor: section 8 uses the 0.01%/8h base rate; actual Bybit funding",
          "  varies by side and hour, so the true funding cost of longs in uptrends is",
          "  typically worse. The v2 booking does not change this caveat.",
          "- The booked double-touch losses assume the worst reading of the spec (a full",
          "  1R loss on every double-touch first bar). If the true sequence inside the bar",
          "  were knowable, some of those sessions would have been winners; the convention",
          "  is conservative by construction and matches the spec's rule 6.",
          "- Direction on exact open-equidistant ties is long by convention; ties are",
          "  counted in section 1.",
          "- Strategy #10 uses market-order entries and carries no double-touch skip; its",
          "  re-run reproduced the original exactly. No #10 v2 re-run was requested.",
          "- Section 10 sensitivities were not re-run here; v1's sweep numbers keep the",
          "  skip convention and are not v2-comparable.",
          ""]
    L += ["## 13. Bottom line (declarative only)", "```"]
    for iv in IVS:
        for lab in EXITS:
            m = summary[iv][lab]
            short = "native" if lab == "native" else "forced"
            m1 = summary[iv]["v1_" + short]
            vk = "verdict_" + short
            v1k = "v1_verdict_" + short
            L.append(f"  {iv} {lab:<11}: v2 {m['trades']} trades, win "
                     f"{_g(m['win_rate'] * 100, 1)}%, {_g(m['expectancy_post_fee_r'], 3)} R/trade "
                     f"post-fee, Sharpe {_g(m['sharpe_post_fee'])}, {summary[iv][vk]}"
                     f"  [v1: {m1['trades']}, {_g(m1['expectancy_post_fee_r'], 3)}, "
                     f"{summary[iv][v1k]}]")
    L += ["```", "",
          "## 14. Files changed by this v2 re-run",
          "  New: specs/s09_nr7_rerun_v2.md, src/s09_nr7_rerun_v2.py (re-exports v1's",
          "  indicator/entry/exit logic), src/run_s09_rerun_v2.py (this runner).",
          "  No existing file was opened for results, edited, or overwritten; no log",
          "  entries were appended (dry run). s09_nr7.py, run_s09.py, s10_rsi2.py and",
          "  run_s10.py were never opened.", ""]
    return "\n".join(L)


def per_coin_table_v2(v2: dict) -> str:
    lines = [f"{'coin':<9} " + runner.HEAD, "-" * (len(runner.HEAD) + 10)]
    for sym in runner.COINS:
        for iv in IVS:
            for label in EXITS:
                m = v2["per_cell"][(sym, iv, label)]
                v, _ = verdict(m, label)
                lines.append(f"{sym:<9} " + runner._line(iv, label, m, v))
    return "\n".join(lines)


def main() -> None:
    if "--log" in sys.argv:
        print("This re-run is a DRY RUN; --log was requested but nothing is appended "
              "to strategy_log.md/csv by design.")
    v2 = run_v2()
    spec = v2["spec"]
    summary = v2_summary(v2)
    per_coin = per_coin_table_v2(v2)
    cov = coverage.collect(runner.COINS, IVS, spec.warmup_for)
    cov_txt = coverage.md_table(cov, runner.COINS, IVS)
    ctx = context_checks.summarise(v2, runner.COINS, IVS)
    print()
    print(report_intro(v2, summary))
    print(report_mid(v2, summary, ctx))
    print(report_tail(v2, summary, cov_txt, per_coin, ctx))


if __name__ == "__main__":
    main()
