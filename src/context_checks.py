"""Context checks - the questions that decide whether a result MEANS anything.

A verdict says whether a strategy made money. These say whether the test that
produced it was a fair test. All four are generic, so every strategy gets them.

  1. Is the measured edge distinguishable from luck?  A losing result needs no
     defence, but a positive one does, and the honest yardstick is how large the
     average is compared with how noisy the individual trades were.
  2. Is the stop wider than a single candle?  If 1R is smaller than a typical
     candle's range, most trades resolve inside one bar, where plain OHLC cannot
     say whether the stop or the target came first. The engine resolves that
     ambiguity against us on purpose, so a too-tight stop does not test the
     strategy - it tests the tie-break rule.
  3. How many trades really did resolve on their first candle?  The direct
     measurement of the same worry.
  4. Do the two exit variants actually trade the same entries?  They share the
     entry rule, but an open position blocks the next signal, so a different
     exit can shift the realised set. The exit-death comparison is only as valid
     as this overlap is high.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import bybit_data as bd
from harness import Trade

# Below this, "same entries, only the exit differs" stops being a fair claim.
MIN_OVERLAP = 0.85


def _t_stat(values: np.ndarray) -> float:
    """Mean divided by its own standard error, or nan when there is no spread.

    A sample where every trade returned the SAME R - every forced trade stopped
    out for exactly -1R, say - has a standard deviation of zero, and floating
    point leaves a residue near 1e-16 instead of a clean zero. Dividing by that
    residue produces a t of about 1e17, which reads as overwhelming evidence when
    what it really means is "there was no variation to measure at all". Any
    spread that tiny relative to the mean is treated as no spread.
    """
    m = float(values.mean())
    sd = float(values.std(ddof=1))
    if not np.isfinite(sd) or sd <= abs(m) * 1e-9:
        return float("nan")
    return m / (sd / np.sqrt(len(values)))


def _fmt_t(t: float) -> str:
    return f"{t:+.2f}" if np.isfinite(t) else "n/a, every trade identical"


def significance(trades: list[Trade]) -> dict:
    """Mean per-trade R with its own noise level, pre-fee and post-fee.

    t is the mean divided by its standard error. As a rough reading: below 2 the
    average is inside the range that pure chance would produce anyway.
    """
    g = np.array([t.gross_r for t in trades if np.isfinite(t.gross_r)])
    n = np.array([t.net_r for t in trades if np.isfinite(t.net_r)])
    if len(g) < 2:
        return {"n": len(g), "gross_mean": float("nan"), "gross_std": float("nan"),
                "t_gross": float("nan"), "net_mean": float("nan"), "t_net": float("nan")}
    return {
        "n": len(g),
        "gross_mean": float(g.mean()),
        "gross_std": float(g.std(ddof=1)),
        "t_gross": _t_stat(g),
        "net_mean": float(n.mean()),
        "t_net": _t_stat(n),
    }


def median_candle_range_pct(symbol: str, interval: str) -> float:
    """Median (high - low) / close, as a percentage. How big one candle usually is."""
    df = bd.drop_forming_bar(bd.load(symbol, interval), interval)
    return float(((df["high"] - df["low"]) / df["close"]).median() * 100.0)


def stop_vs_candle(coins, intervals, stop_pct: float) -> dict:
    """{(coin, interval): (median candle range %, stop as a multiple of it)}."""
    out = {}
    for symbol in coins:
        for interval in intervals:
            rng = median_candle_range_pct(symbol, interval)
            out[(symbol, interval)] = (rng, stop_pct / rng if rng > 0 else float("nan"))
    return out


def first_bar_share(trades: list[Trade]) -> float:
    """Fraction of trades that ended on the very first candle they were held.

    bars_held counts candles SURVIVED, so 0 means the trade opened and closed
    inside one candle - the case where the intrabar tie-break decides the result
    instead of the strategy.
    """
    if not trades:
        return float("nan")
    return float(sum(1 for t in trades if t.bars_held == 0) / len(trades))


def entry_overlap(a: list[Trade], b: list[Trade]) -> float:
    """Share of entry timestamps the two variants have in common."""
    sa = {(t.direction, t.entry_time) for t in a}
    sb = {(t.direction, t.entry_time) for t in b}
    union = sa | sb
    return float(len(sa & sb) / len(union)) if union else float("nan")


def summarise(res: dict, coins, intervals, stop_pct: float | None = None) -> dict:
    """Everything above, keyed by timeframe, ready to print or log."""
    out: dict = {}
    for interval in intervals:
        nat = res["trades"][(interval, "native")]
        f13 = res["trades"][(interval, "forced-1:3")]
        row = {
            "sig_native": significance(nat),
            "sig_forced": significance(f13),
            "first_bar_native": first_bar_share(nat),
            "first_bar_forced": first_bar_share(f13),
            "overlap": entry_overlap(nat, f13),
        }
        if stop_pct is not None:
            row["stop_vs_candle"] = {
                s: stop_vs_candle([s], [interval], stop_pct)[(s, interval)] for s in coins
            }
        out[interval] = row
    return out


def text_block(ctx: dict, intervals, stop_pct: float | None = None) -> str:
    """The same information as plain lines, for the terminal and the log."""
    lines = []
    for interval in intervals:
        c = ctx[interval]
        lines.append(f"{interval}:")
        for lab, key in [("native", "sig_native"), ("forced-1:3", "sig_forced")]:
            s = c[key]
            lines.append(
                f"  {lab:<11} {s['n']:>5} trades | pre-fee {s['gross_mean']:+.4f}R/trade "
                f"(spread {s['gross_std']:.2f}R, t = {_fmt_t(s['t_gross'])}) | "
                f"post-fee {s['net_mean']:+.4f}R/trade (t = {_fmt_t(s['t_net'])})"
            )
        lines.append(
            f"  resolved inside their first candle: native "
            f"{c['first_bar_native']:.0%}, forced-1:3 {c['first_bar_forced']:.0%}"
        )
        flag = "" if c["overlap"] >= MIN_OVERLAP else "  <-- TOO LOW to compare exits fairly"
        lines.append(f"  the two variants share {c['overlap']:.1%} of their entries{flag}")
        if stop_pct is not None and "stop_vs_candle" in c:
            bits = ", ".join(
                f"{s} candle {rng:.2f}% (stop = {mult:.1f}x)"
                for s, (rng, mult) in c["stop_vs_candle"].items()
            )
            lines.append(f"  a {stop_pct:.1f}% stop vs a typical candle: {bits}")
    return "\n".join(lines)
