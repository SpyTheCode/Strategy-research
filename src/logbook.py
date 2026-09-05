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

# The column list the project owner specified, plus max_drawdown_r. The extra
# column is there because drawdown as a percentage depends on how much we chose
# to risk per trade (1%), while drawdown in risk units does not - and the
# discard bar's R-recovery test is computed from it, so it has to be auditable.
COLUMNS = [
    "strategy",
    "coins",
    "timeframes",
    "exit_type",
    "trades",
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
    tested_on: str | None = None,
) -> None:
    """Append one run to strategy_log.csv. `m` is a metrics() dict."""
    ensure_headers()
    wr = m.get("win_rate")
    row = [
        strategy,
        coins,
        timeframes,
        exit_type,
        m.get("trades", 0),
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
