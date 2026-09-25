"""The two log files: one machine-readable row per run, one write-up per run.

Everything that reaches a log goes through here, so every strategy is recorded
in exactly the same shape and nothing gets logged by hand. Both files are
append-only. Nothing is ever rewritten or deleted, including failures.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "strategy_log.csv"
MD_PATH = ROOT / "strategy_log.md"

# The column list the project owner specified, plus max_drawdown_r and the three
# per-coin coverage columns. max_drawdown_r is there because drawdown as a
# percentage depends on how much we chose to risk per trade (1%), while drawdown in
# risk units does not - and the discard bar's R-recovery test is computed from it, so
# it has to be auditable. The days_* columns sit next to `trades` because sample size
# without sample length is not interpretable: the same 900 trades mean something
# different over six years than over six months. They are the TRADEABLE window per
# coin - after warmup, through the last closed bar - so they shrink at 1D, where a
# warmup bar costs a whole day.
COINS_LOGGED = ["BTCUSDT", "SOLUSDT", "XRPUSDT"]
DAY_COLUMNS = [f"days_{c}" for c in COINS_LOGGED]

COLUMNS = [
    "strategy",
    "coins",
    "timeframes",
    "exit_type",
    "trades",
    *DAY_COLUMNS,
    "win_rate_pct",
    "rr_achieved",
    "r_sum_pre_fee",
    "r_sum_post_fee",
    "sharpe_post_fee",
    "max_drawdown_pct",
    "max_drawdown_r",
    "exit_death_flag",
    "verdict",
    "date_tested",
]


def _fmt(x, nd: int = 2) -> str:
    if x is None:
        return ""
    if isinstance(x, float):
        return "" if x != x else f"{x:.{nd}f}"  # x != x catches NaN
    return str(x)


def ensure_headers() -> None:
    if not CSV_PATH.exists():
        with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(COLUMNS)


def log_row(
    *,
    strategy: str,
    coins: str,
    timeframes: str,
    exit_type: str,
    m: dict,
    exit_death_flag: str,
    verdict: str,
    coverage_days: dict | None = None,
    tested_on: str | None = None,
) -> None:
    """Append one run to strategy_log.csv. `m` is a metrics() dict.

    `coverage_days` maps coin -> tradeable days for THIS timeframe, from
    coverage.days_by_coin(). Omitting it leaves those cells blank rather than
    writing a zero, because a blank reads as "not recorded" and a zero reads as
    "no history", which are different claims.
    """
    ensure_headers()
    wr = m.get("win_rate")
    cov = coverage_days or {}
    row = [
        strategy,
        coins,
        timeframes,
        exit_type,
        m.get("trades", 0),
        *[_fmt(cov.get(c), 0) for c in COINS_LOGGED],
        _fmt(wr * 100.0 if isinstance(wr, float) and wr == wr else wr, 1),
        _fmt(m.get("rr_achieved")),
        _fmt(m.get("r_sum_pre_fee")),
        _fmt(m.get("r_sum_post_fee")),
        _fmt(m.get("sharpe_post_fee")),
        _fmt(m.get("max_drawdown_pct")),
        _fmt(m.get("max_drawdown_r")),
        exit_death_flag,
        verdict,
        tested_on or date.today().isoformat(),
    ]
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)


def log_md(text: str) -> None:
    """Append a plain-English section to strategy_log.md."""
    with MD_PATH.open("a", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n\n")
