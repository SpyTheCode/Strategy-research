"""Calendar coverage: how long a period each cell's numbers are actually drawn from.

Trade count alone does not say how much history a result rests on - 900 trades can
come from six years or from six months, and those are not the same evidence. So every
results table carries the covered window per coin alongside the counts.

The window reported is the TRADEABLE window: the first bar the engine is allowed to
act on (after the strategy's warmup) through the last closed bar in the data. That is
deliberately not the raw file length. Warmups are set per strategy and, for rules
written in calendar days, per timeframe - so the same price file yields a much shorter
tradeable window at 1D, where 200 warmup bars are 200 days, than at 1H, where the same
200 bars are eight days. Reporting the file length instead would make the daily rows
look like they rest on more history than they do.

All twelve datasets are cached Parquet files fetched on 2026-09-05, and every strategy
in the log was run against that same cache, so windows are comparable between
strategies. The closing boundary is the last closed bar at the time of measurement,
which can sit one bar later than the bar an earlier run saw; against windows of 1,600
to 2,400 days that is well below the precision of a day count.
"""

from __future__ import annotations

from typing import Callable, Iterable

import pandas as pd

import bybit_data as bd

DAY = pd.Timedelta(days=1)
YEAR_DAYS = 365.25

# Parquet reads are cheap but not free, and a full log render asks for the same
# twelve frames many times over.
_CACHE: dict[tuple[str, str], pd.DataFrame] = {}


def frame(symbol: str, interval: str) -> pd.DataFrame:
    """The same frame the runner trades: cached candles, forming bar removed."""
    key = (symbol, interval)
    if key not in _CACHE:
        _CACHE[key] = bd.drop_forming_bar(bd.load(symbol, interval), interval)
    return _CACHE[key]


def window(symbol: str, interval: str, warmup: int = 0) -> dict:
    """First tradeable bar -> last closed bar, for one coin on one timeframe."""
    t = frame(symbol, interval)["open_time"]
    if len(t) <= warmup:
        return {"symbol": symbol, "interval": interval, "warmup": warmup,
                "data_start": None, "start": None, "end": None,
                "data_bars": len(t), "bars": 0,
                "days": float("nan"), "years": float("nan")}
    start, end = t.iloc[warmup], t.iloc[-1]
    days = (end - start) / DAY
    return {"symbol": symbol, "interval": interval, "warmup": warmup,
            "data_start": t.iloc[0], "start": start, "end": end,
            "data_bars": len(t), "bars": len(t) - warmup,
            "days": days, "years": days / YEAR_DAYS}


def collect(coins: Iterable[str], intervals: Iterable[str],
            warmup_for: Callable[[str], int]) -> dict:
    """{(interval, coin): window} for every cell a run covers.

    `warmup_for` takes the interval, so a strategy whose warmup is written in
    calendar days reports a different window per timeframe - which is the point.
    """
    return {(iv, c): window(c, iv, warmup_for(iv))
            for iv in intervals for c in coins}


def days_by_coin(cov: dict, interval: str, coins: Iterable[str]) -> dict[str, float]:
    """{coin: tradeable days} for one timeframe - the shape the CSV row wants."""
    return {c: cov[(interval, c)]["days"] for c in coins}


def _d(x) -> str:
    return "" if x is None else str(pd.Timestamp(x).date())


def md_table(cov: dict, coins: Iterable[str], intervals: Iterable[str]) -> str:
    """Markdown table: one row per coin per timeframe, with the window it covers."""
    coins, intervals = list(coins), list(intervals)
    lines = ["| Timeframe | Coin | Window traded | Days | Years | Tradeable bars "
             "| Warmup bars |", "|---|---|---|---|---|---|---|"]
    for iv in intervals:
        for c in coins:
            w = cov[(iv, c)]
            lines.append(
                f"| {iv} | {c} | {_d(w['start'])} to {_d(w['end'])} | "
                f"{w['days']:.0f} | {w['years']:.2f} | {w['bars']:,} | {w['warmup']} |")
    return "\n".join(lines)


def summary_line(cov: dict, coins: Iterable[str], intervals: Iterable[str]) -> str:
    """One sentence naming the shortest and longest window in the whole run."""
    ws = [cov[(iv, c)] for iv in intervals for c in coins]
    ok = [w for w in ws if w["days"] == w["days"]]
    if not ok:
        return "No cell had enough bars to measure a window."
    lo = min(ok, key=lambda w: w["days"])
    hi = max(ok, key=lambda w: w["days"])
    return (f"Shortest window in this run: {lo['symbol']} at {lo['interval']}, "
            f"{lo['days']:.0f} days ({lo['years']:.2f} years). Longest: "
            f"{hi['symbol']} at {hi['interval']}, {hi['days']:.0f} days "
            f"({hi['years']:.2f} years).")


def text_block(cov: dict, coins: Iterable[str], intervals: Iterable[str]) -> str:
    """The section that goes into strategy_log.md next to the results tables."""
    coins, intervals = list(coins), list(intervals)
    ivs = list(dict.fromkeys(intervals))
    warm = {iv: cov[(iv, coins[0])]["warmup"] for iv in ivs}
    varies = len(set(warm.values())) > 1
    warm_txt = (", ".join(f"{iv} {warm[iv]}" for iv in ivs) if varies
                else f"{warm[ivs[0]]} bars on every timeframe")
    return (
        "### How much history these numbers cover\n\n"
        "Trade count on its own does not say how long a period a result is drawn from,\n"
        "so the window is recorded per coin. What is measured is the TRADEABLE window:\n"
        "the first bar the rule is allowed to act on, after the warmup, through the last\n"
        "closed bar in the data. The three coins do not start together - Bitcoin's history\n"
        "on this venue begins in March 2020, XRP in May 2021, Solana in October 2021 - so a\n"
        "pooled row is not three equal thirds.\n\n"
        f"Warmup skipped before the first trade: {warm_txt}. That subtraction costs very\n"
        "little at 1H and a great deal at 1D, where a warmup bar is a whole day.\n\n"
        + md_table(cov, coins, ivs) + "\n\n"
        + summary_line(cov, coins, ivs)
    )
