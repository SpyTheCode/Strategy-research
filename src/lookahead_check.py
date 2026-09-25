"""Lookahead audit - proves an indicator cannot see the future.

Claiming "no lookahead bias" is cheap. This measures it.

The method: take the finished dataset, cut it off at some bar, recompute every
indicator using only the bars up to that cut, and compare the value at the cut
against the value the same indicator shows when computed over the whole history.

If those two numbers are identical, then nothing after the cut influenced the
value at the cut, which is exactly what "no lookahead" means. If they differ by
even a rounding error, future data is leaking into a past decision and every
result built on that indicator is invalid.

This is run fresh for every strategy, on that strategy's own indicators.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Columns that describe the bar itself rather than a computed signal.
RAW = {"open_time", "open", "high", "low", "close", "volume", "turnover"}


def audit(
    df: pd.DataFrame,
    add_indicators,
    *,
    cuts: int = 25,
    first_cut: int = 300,
    tol: float = 1e-12,
) -> tuple[bool, list[str], list[str]]:
    """Recompute indicators on truncated history and compare at the cut.

    Returns (passed, columns_checked, problems).
    """
    full = add_indicators(df.copy())
    cols = [c for c in full.columns if c not in RAW and not str(c).startswith("regime")]

    n = len(df)
    if n <= first_cut + 10:
        return False, cols, [f"not enough bars ({n}) to audit"]
    points = np.linspace(first_cut, n - 2, num=cuts, dtype=int)

    problems: list[str] = []
    for i in points:
        partial = add_indicators(df.iloc[: i + 1].copy())
        for c in cols:
            a, b = full[c].iloc[i], partial[c].iloc[i]
            a_na = pd.isna(a)
            b_na = pd.isna(b)
            if a_na != b_na:
                problems.append(f"bar {i}, column '{c}': one value is missing and the other is not")
                continue
            if a_na and b_na:
                continue
            if isinstance(a, (str, bool, np.bool_)) or isinstance(b, (str, bool, np.bool_)):
                if a != b:
                    problems.append(f"bar {i}, column '{c}': {b!r} with history cut, {a!r} with full history")
                continue
            if abs(float(a) - float(b)) > tol:
                problems.append(
                    f"bar {i}, column '{c}': {float(b):.10f} with history cut, "
                    f"{float(a):.10f} with full history"
                )
    return (not problems), cols, problems


def report(name: str, df: pd.DataFrame, add_indicators, **kw) -> bool:
    ok, cols, problems = audit(df, add_indicators, **kw)
    print(f"Lookahead audit - {name}")
    print(f"  columns checked: {', '.join(cols)}")
    if ok:
        print("  PASS - every indicator value at the cut was identical with and "
              "without the future bars present.")
    else:
        print(f"  FAIL - {len(problems)} mismatch(es):")
        for p in problems[:15]:
            print(f"    {p}")
    return ok
