"""Strategy #13 - Turtle 55-day breakout, System 2.

WHAT THE SOURCE SAYS
--------------------
  * Source:       Curtis Faith, *Way of the Turtle* (2007), describing original Turtle System 2.
  * Trigger:      enter long on 55-day high breakout; enter short on 55-day low breakout.
  * Stop-loss:    initial stop 2N away where N is the 20-day Wilder ATR.
  * Take-profit:  exit on opposite 20-day channel (20-day low for long, 20-day high for short).
                  No fixed profit target.
  * Sizing:       1% risk per unit, single position per coin in this benchmark (no pyramiding).
  * System 2 distinction: longer-term partner to System 1 (#7, 20-day breakout / 10-day exit).
                  System 2 takes all breakouts; no skip rule applies.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan, Signal, Trade
import s07_turtle_donchian as s07

ENTRY_DAYS = 55
EXIT_DAYS = 20
N_DAYS = 20
STOP_N = 2.0


def add_indicators(
    df: pd.DataFrame,
    entry_days: int = ENTRY_DAYS,
    exit_days: int = EXIT_DAYS,
    n_days: int = N_DAYS,
    stop_n: float = STOP_N,
    scale: str = s07.SCALE_DAY,
    long_only: bool = False,
    resting: bool = False,
) -> pd.DataFrame:
    """Delegate to s07's parameterized indicator builder with System 2 defaults."""
    return s07.add_indicators(
        df,
        entry_days=entry_days,
        exit_days=exit_days,
        n_days=n_days,
        stop_n=stop_n,
        scale=scale,
        long_only=long_only,
        resting=resting,
    )


def entry(df: pd.DataFrame):
    """Entry trigger on 55-day breakout."""
    return s07.entry(df)


def native_exit(
    df: pd.DataFrame,
    use_2n: bool = True,
    use_channel: bool = True,
    ratchet: bool = False,
    target_r: float | None = None,
):
    """Native exit at opposite 20-day channel or 2N initial stop."""
    return s07.native_exit(
        df,
        use_2n=use_2n,
        use_channel=use_channel,
        ratchet=ratchet,
        target_r=target_r,
    )


def warmup_for(
    interval: str,
    entry_days: int = ENTRY_DAYS,
    n_days: int = N_DAYS,
    scale: str = s07.SCALE_DAY,
) -> int:
    """Warmup bars required before trading."""
    return s07.warmup_for(interval, entry_days=entry_days, n_days=n_days, scale=scale)
