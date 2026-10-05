"""Strategy #14 - Keltner channel mean reversion (specs/s14_keltner_mean_reversion.md).

THE RULE (spec section 1, exact tested interpretation)
  Channels: EMA20 of close, plus/minus 2.0 x Wilder ATR(20).
  LONG  when the closed bar's close is BELOW the lower band.
  SHORT when the closed bar's close is ABOVE the upper band.
  Spec section 2 fixes the reading: "Entry outside close; no requirement to
  re-enter channel" - a STATE, not a cross. The engine fills it at the next
  bar's open and blocks re-fires while a position is open, so a run of bars
  outside the band enters once and re-enters only after the exit.
  Native exit: center-line close (close back beyond the EMA on the closed bar,
  filled at the next open). No target. Hard stop = 2 x ATR(20), frozen at
  signal time, expressed the engine's way (see stop fraction below).

Distinct from #5 Keltner BREAKOUT on purpose: #5 buys strength (close above
the upper rail -> long). #14 fades the extreme (close below the lower rail ->
long). Same channel drawing, opposite hypothesis.

Shared-indicator reuse (declared, per the task's reuse rule): the channel
itself is s05_keltner_breakout.add_indicators called with ma_len=20,
atr_bars=20, mult=headline 2.0, wilder=True - the parameter set the #14 spec
specifies. Only its channel columns (kc_mid/kc_atr/kc_up/kc_lo) are consumed;
none of #5's breakout, risk or exit logic is imported.

Stop mechanics, declared up front: the spec's stop is "2 x ATR(20) from fill",
a declared placeholder. The frozen engine's Signal accepts either an absolute
price level or a fraction of the fill (stop_frac), resolved AT the fill. An
absolute distance from an as-yet-unknown fill is not expressible without
editing the engine, so the stop is carried as
    stop_frac = 2 x ATR(signal bar) / close(signal bar)
and the engine computes stop = fill x (1 - dir x stop_frac). For a normal
fill that equals 2 x ATR_sig; a gap between signal close and fill scales the
distance by fill/close_sig. The ATR is frozen at the signal bar; the initial
stop is never revised. This is the engine's established ATR-stop convention
(s08_fastpath) and is listed as placeholder 1 in the report.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from harness import ExitPlan, Signal
import s05_keltner_breakout as s05

# Spec section 2 placeholders, pre-decided; executor lock (sections 7-15):
# warmup 250, stop = 2 ATR frozen at signal, no take-profit.
EMA_LEN = 20
ATR_BARS = 20
MULT = 2.0
STOP_ATR_MULT = 2.0
WARMUP = 250


def add_indicators(
    df: pd.DataFrame,
    *,
    ma_len: int = EMA_LEN,
    atr_bars: int = ATR_BARS,
    mult: float = MULT,
    stop_atr: float = STOP_ATR_MULT,
) -> pd.DataFrame:
    """Channel (reused, parameters confirmed against the spec) + #14's own columns.

    Every column is built from bar i and earlier. The signals are states read
    on a CLOSED bar and filled at the next open, so no column needs shifting:
    nothing here is ever tested against the bar that produced it.
    """
    out = s05.add_indicators(df, ma_len=ma_len, atr_bars=atr_bars, mult=mult, wilder=True)

    close = out["close"].to_numpy()
    up = out["kc_up"].to_numpy()
    lo = out["kc_lo"].to_numpy()
    atr = out["kc_atr"].to_numpy()

    ok = np.isfinite(atr) & (atr > 0) & (close > 0)
    # Mean-reversion STATES on the closed bar (spec section 2). NaN rails
    # compare False on their own; the finite guard also blanks unwarmed bars.
    out["s14_long_sig"] = ok & np.isfinite(lo) & (close < lo)
    out["s14_short_sig"] = ok & np.isfinite(up) & (close > up)
    # Frozen stop fraction: 2 x ATR(signal bar) / close(signal bar). The engine
    # multiplies it by the fill price, per the Signal.stop_frac contract.
    with np.errstate(divide="ignore", invalid="ignore"):
        out["s14_stop_frac"] = np.where(ok, stop_atr * atr / close, np.nan)
    return out


def entry(df: pd.DataFrame):
    """Fires on the closed bar whenever the state holds; engine fills next open.

    Fires on EVERY bar the state holds - the engine blocks re-fires while a
    position is open, which is the spec's "no requirement to re-enter channel"
    combined with its one-position lock. The stop fraction is frozen here, at
    signal time, and carries no information about the next bar.
    """
    long_sig = df["s14_long_sig"].to_numpy()
    short_sig = df["s14_short_sig"].to_numpy()
    frac = df["s14_stop_frac"].to_numpy()

    def fn(_d: pd.DataFrame, i: int) -> Signal | None:
        f = frac[i]
        if not np.isfinite(f) or f <= 0:
            return None
        if long_sig[i]:
            return Signal(direction=1, stop_frac=float(f))
        if short_sig[i]:
            return Signal(direction=-1, stop_frac=float(f))
        return None

    return fn


def native_exit(df: pd.DataFrame):
    """The source's own exit: center-line close, plus the frozen hard stop.

    The center-line test is a closed-bar decision queued to the next open, so
    it reads the unshifted channel - knowing bar i's close when deciding on
    bar i's close is legitimate. The stop is the trade's initial_stop, frozen
    at signal time per the spec's "no revised initial stop" lock.
    """
    mid = df["kc_mid"].to_numpy()
    close = df["close"].to_numpy()

    def fn(_d: pd.DataFrame, i: int, trade) -> ExitPlan:
        plan = ExitPlan(stop_level=float(trade.initial_stop))
        m = mid[i]
        if np.isfinite(m):
            back_inside = (close[i] >= m) if trade.direction > 0 else (close[i] <= m)
            if back_inside:
                plan.close_exit = True
                plan.reason = "center-line"
        return plan

    return fn


def warmup_for(_interval: str) -> int:
    """Executor lock (spec sections 7-15): project default warmup, 250 bars.

    The same bar count on every timeframe - the spec states it as a bar count,
    not calendar days. 250 covers EMA20, Wilder ATR20 and the reporting-only
    regime label (100-bar average plus 20-bar slope) with room to spare.
    """
    return WARMUP

