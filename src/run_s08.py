"""Run Strategy #8 - Supertrend, and log it.

Usage:  .venv\\Scripts\\python.exe src\\run_s08.py [--log]
"""

from __future__ import annotations

import sys

import coverage
import logbook
import runner
import s08_supertrend as s08
from discard_bar import exit_death, verdict

NAME = "Supertrend (10, 3)"
COINS_STR = "BTCUSDT+SOLUSDT+XRPUSDT"


def main(write=False):
    spec = runner.StrategySpec(
        name=NAME,
        add_indicators=s08.add_indicators,
        entry=s08.entry,
        native_exit=s08.native_exit,
        warmup=50,
        notes="atr_period=10 multiplier=3",
    )

    # 1. Run simulator (which runs the lookahead audit)
    res = runner.run(spec, runner.COINS, runner.INTERVALS)

    # 2. Coverage
    cov = coverage.collect(runner.COINS, runner.INTERVALS, spec.warmup_for)

    # 3. Summarise
    summary = runner.summarise(spec, res, runner.INTERVALS)

    # 4. Print to terminal
    print("\n=== STRATEGY #8: Supertrend ===\n")
    print("Exit-death check:")
    for i in runner.INTERVALS:
        s = summary[i]
        print(f"  {i}: {s['exit_death'].upper()} — {s['exit_death_diag']}")

    print("\nVerdicts:")
    for i in runner.INTERVALS:
        s = summary[i]
        print(f"  {i} native:      {s['verdict_native']} — {s['reason_native']}")
        bwr = s['breakeven_wr_forced']
        bwr_str = f"{bwr:.1%}" if bwr is not None else "n/a"
        print(f"  {i} forced-1:3:  {s['verdict_forced']} — {s['reason_forced']} "
              f"[breakeven WR {bwr_str}]")

    print(f"\nCoverage: {coverage.summary_line(cov, runner.COINS, runner.INTERVALS)}")

    if write:
        write_logs(spec, res, summary, cov)
        print("\nS8 (Supertrend) logs appended.")
    else:
        print("\n(dry run — pass --log to write)")


def write_logs(spec: runner.StrategySpec, res: dict, summary: dict,
               cov: coverage.Coverage) -> None:
    """Append to both logs."""

    # Build markdown
    def _g(x, nd=2):
        return "n/a" if x is None or x != x else f"{x:.{nd}f}"

    table_rows = ["| Timeframe | Exit | Trades | Days (BTC/SOL/XRP) | Win% | RR | "
                  "R/trade | Sharpe | Max DD % | Verdict |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
    for i in runner.INTERVALS:
        s = summary[i]
        days = coverage.days_by_coin(cov, i, runner.COINS)
        days_str = f"{days['BTCUSDT']:.0f}/{days['SOLUSDT']:.0f}/{days['XRPUSDT']:.0f}"
        for label, vkey in [("native", "verdict_native"),
                            ("forced-1:3", "verdict_forced")]:
            m = s[label]
            table_rows.append(
                f"| {i} | {label} | {m['trades']} | {days_str} "
                f"| {_g(m['win_rate'] * 100, 1)} | {_g(m['rr_achieved'])} "
                f"| {_g(m['expectancy_post_fee_r'], 3)} | {_g(m['sharpe_post_fee'])} "
                f"| {_g(m['max_drawdown_pct'], 1)} | **{s[vkey]}** |"
            )

    exit_death_lines = "\n".join(
        f"- **{i}: {summary[i]['exit_death'].upper()}.** {summary[i]['exit_death_diag']}"
        for i in runner.INTERVALS
    )

    verdict_lines = "\n".join(
        f"- **{i} native — {summary[i]['verdict_native']}.** {summary[i]['reason_native']}\n"
        f"- **{i} forced-1:3 — {summary[i]['verdict_forced']}.** {summary[i]['reason_forced']}"
        for i in runner.INTERVALS
    )

    md = f"""---

## Strategy #8 — Supertrend (10, 3)

**Tested:** {logbook.date.today().isoformat()} · **Coins:** {COINS_STR} · **Timeframes:** {", ".join(runner.INTERVALS)}

### The rules

Supertrend is a trend-following indicator that builds a trailing stop based on ATR. The line sits below price in an uptrend, above price in a downtrend. When price closes through the line, the indicator flips direction.

- **Entry:** Price closes above the Supertrend line (bullish flip)
- **Exit (native):** Price closes below the Supertrend line (bearish flip)
- **Exit (forced-1:3):** 1R stop, 3R target, 30-bar time limit

**Parameters:** ATR period 10, multiplier 3.0 (standard defaults from the source literature).

**Source:** Olivier Seban (creator). Widely documented across trading education sites.

### Coverage

{coverage.text_block(cov, runner.COINS, runner.INTERVALS)}

### Results — post-fee, pooled per timeframe

{chr(10).join(table_rows)}

### Exit-death check

{exit_death_lines}

### Verdicts

{verdict_lines}

### Bottom line

{_bottom_line(summary)}
"""

    # Write markdown
    logbook.log_md(md)

    # Write CSV rows
    for i in runner.INTERVALS:
        for label in ["native", "forced-1:3"]:
            vkey = "verdict_native" if label == "native" else "verdict_forced"
            logbook.log_row(
                strategy=spec.name,
                coins=COINS_STR,
                timeframes=i,
                exit_type=label,
                m=summary[i][label],
                exit_death_flag=summary[i]["exit_death"],
                verdict=summary[i][vkey],
                coverage_days=coverage.days_by_coin(cov, i, runner.COINS),
            )


def _bottom_line(summary: dict) -> str:
    """Generate a plain-English verdict summary."""
    verdicts = {i: (summary[i]['verdict_native'], summary[i]['verdict_forced'])
                for i in runner.INTERVALS}
    keep_count = sum(1 for n, f in verdicts.values() if n == "KEEP" or f == "KEEP")
    inc_count = sum(1 for n, f in verdicts.values()
                    if n == "INCONCLUSIVE" or f == "INCONCLUSIVE")

    if keep_count > 0:
        return (f"At least one timeframe / exit combination is a **KEEP**. "
                f"See the verdict rows above for the breakdown.")
    elif inc_count == len(verdicts) * 2:
        return "All variants are **INCONCLUSIVE** — insufficient trade count."
    else:
        return ("All variants are **DISCARD** or inconclusive. "
                "The strategy does not clear the quality bar on these coins and timeframes.")


if __name__ == "__main__":
    main(write="--log" in sys.argv)
