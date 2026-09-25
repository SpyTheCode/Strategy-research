"""Self-tests for the engine.

I wrote the engine, so the engine is exactly where a silent bug would live and
quietly flatter every result. These tests use hand-built candles where the right
answer is known by arithmetic, so a wrong answer is unambiguous.

Run:  .venv\\Scripts\\python.exe src\\selftest.py
"""

from __future__ import annotations

import sys

import pandas as pd

import coverage
import s05_keltner_breakout as s05
import s07_turtle_donchian as s07
from harness import (
    TAKER_FEE_RATE,
    ExitPlan,
    Signal,
    forced_13_exit,
    metrics,
    simulate,
    simulate_resting,
)

FAILURES: list[str] = []


def bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """rows are (open, high, low, close); one bar per hour from a fixed date."""
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["open_time"] = pd.date_range("2024-01-01", periods=len(df), freq="1h", tz="UTC")
    df["volume"] = 1.0
    df["regime"] = "up/lowvol"
    return df


def check(name: str, got, want, tol: float = 1e-9) -> None:
    ok = abs(got - want) <= tol if isinstance(want, float) else got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILURES.append(name)


def entry_once(stop: float, direction: int = 1, at_bar: int = 0):
    """Signal on exactly one bar, so each test has exactly one trade."""
    def fn(df: pd.DataFrame, i: int) -> Signal | None:
        return Signal(direction=direction, stop_price=stop) if i == at_bar else None
    return fn


def hand_net_r(entry: float, exit_px: float, stop: float, direction: int) -> float:
    risk = abs(entry - stop)
    fee = TAKER_FEE_RATE * entry + TAKER_FEE_RATE * exit_px
    return ((exit_px - entry) * direction - fee) / risk


def test_fill_at_next_open() -> None:
    print("\n1. A signal on a closed bar fills at the NEXT bar's open (no lookahead)")
    df = bars([(100, 100, 100, 100), (102, 103, 101, 102), (102, 102, 102, 102)])
    trades = simulate(df, entry_once(99.0), lambda d, i, t: ExitPlan(), warmup=0,
                      time_limit_bars=1)
    check("entry price is bar 1's open, not bar 0's close", trades[0].entry_price, 102.0)
    check("entry timestamp is bar 1", trades[0].entry_time, df["open_time"].iloc[1])


def test_clean_3r_target() -> None:
    print("\n2. Forced 1:3 target hit cleanly -> exactly +3R gross, less fees net")
    df = bars([(100, 100, 100, 100), (100, 106, 99.5, 105), (105, 105, 105, 105)])
    trades = simulate(df, entry_once(99.0), forced_13_exit, warmup=0, time_limit_bars=30)
    t = trades[0]
    check("exit reason", t.exit_reason, "target")
    check("exit price is the 3R level", t.exit_price, 103.0)
    check("gross R", t.gross_r, 3.0)
    check("net R matches hand arithmetic", t.net_r, hand_net_r(100.0, 103.0, 99.0, 1))
    check("fee cost in R", t.fee_cost_r, TAKER_FEE_RATE * (100.0 + 103.0))


def test_stop_wins_ties() -> None:
    print("\n3. One candle touching BOTH stop and target must resolve as the STOP")
    df = bars([(100, 100, 100, 100), (100, 106, 98, 105), (105, 105, 105, 105)])
    trades = simulate(df, entry_once(99.0), forced_13_exit, warmup=0, time_limit_bars=30)
    t = trades[0]
    check("exit reason is stop, not target", t.exit_reason, "stop")
    check("gross R", t.gross_r, -1.0)
    check("net R matches hand arithmetic", t.net_r, hand_net_r(100.0, 99.0, 99.0, 1))


def test_gap_through_stop() -> None:
    print("\n4. A candle that gaps past the stop fills at the open, not at the stop")
    df = bars([(100, 100, 100, 100), (100, 101, 99.5, 100.5), (95, 96, 94, 95), (95, 95, 95, 95)])
    trades = simulate(df, entry_once(99.0), forced_13_exit, warmup=0, time_limit_bars=30)
    t = trades[0]
    check("exit reason", t.exit_reason, "stop")
    check("filled at the gap open of 95, not the 99 stop", t.exit_price, 95.0)
    check("loss is worse than -1R because of the gap", t.gross_r, -5.0)


def test_time_limit() -> None:
    print("\n5. The time limit ends a trade that never reaches stop or target")
    flat = [(100, 100.2, 99.8, 100)] * 6
    df = bars([(100, 100, 100, 100)] + flat)
    trades = simulate(df, entry_once(99.0), forced_13_exit, warmup=0, time_limit_bars=3)
    t = trades[0]
    check("exit reason", t.exit_reason, "time")
    check("bars held", t.bars_held, 3)


def test_short_side() -> None:
    print("\n6. Short trades mirror correctly and still pay fees")
    df = bars([(100, 100, 100, 100), (100, 100.5, 96, 97), (97, 97, 97, 97)])
    trades = simulate(df, entry_once(101.0, direction=-1), forced_13_exit, warmup=0,
                      time_limit_bars=30)
    t = trades[0]
    check("exit reason", t.exit_reason, "target")
    check("3R below entry for a short", t.exit_price, 97.0)
    check("gross R", t.gross_r, 3.0)
    check("net R matches hand arithmetic", t.net_r, hand_net_r(100.0, 97.0, 101.0, -1))


def test_unfinished_trade_dropped() -> None:
    print("\n7. A trade still open when the data ends is discarded, not marked to market")
    df = bars([(100, 100, 100, 100), (100, 100.5, 99.9, 100), (100, 100.5, 99.9, 100)])
    trades = simulate(df, entry_once(99.0), forced_13_exit, warmup=0, time_limit_bars=99)
    check("no completed trades recorded", len(trades), 0)


def test_metrics_arithmetic() -> None:
    print("\n8. Win rate, achieved RR and R-sum add up from the trade list")
    df = bars([(100, 100, 100, 100), (100, 106, 99.5, 105), (105, 105, 105, 105)])
    trades = simulate(df, entry_once(99.0), forced_13_exit, warmup=0, time_limit_bars=30)
    m = metrics(trades, interval="1H")
    check("trade count", m["trades"], 1)
    check("win rate", m["win_rate"], 1.0)
    check("pre-fee R-sum is the clean 3R", m["r_sum_pre_fee"], 3.0)
    check("post-fee R-sum is lower than pre-fee", m["r_sum_post_fee"] < m["r_sum_pre_fee"], True)


def test_stop_frac_uses_real_entry() -> None:
    print("\n9. A percentage stop is measured from the FILL price, not the signal bar's close")
    # Bar 0 closes at 100, bar 1 opens 10% higher at 110. A 2% short stop must
    # sit at 112.2 (2% above the 110 fill), never at 102 (2% above the close).
    df = bars([(100, 100, 100, 100), (110, 111, 109, 110), (109, 109.5, 103, 104),
               (104, 104, 104, 104)])

    def fn(d, i):
        return Signal(direction=-1, stop_frac=0.02) if i == 0 else None

    trades = simulate(df, fn, forced_13_exit, warmup=0, time_limit_bars=30)
    t = trades[0]
    check("entry is bar 1's open", t.entry_price, 110.0)
    check("stop is 2% above the fill, not above the close", t.initial_stop, 112.2)
    check("1R is 2.20, not 2.00", t.risk_per_unit, 2.2000000000000455, tol=1e-6)
    check("3R target reached", t.exit_reason, "target")
    check("gross R", t.gross_r, 3.0, tol=1e-9)


# ---------------------------------------------------------------------------
# Resting stop orders (added for Strategy #4, Crabel's opening range breakout)
# ---------------------------------------------------------------------------

def resting_bars(rows, stretch: float, *, r_mult: float = 1.0, armed: bool = True):
    """Six-hour candles straddling two UTC midnights, with the order levels set.

    Six hours is chosen so four bars make a session and a whole day boundary
    fits in a test that can still be read by eye. The session columns are built
    from the clock exactly as the strategy builds them, so these tests exercise
    the real boundary logic rather than a convenient stand-in.
    """
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["open_time"] = pd.date_range("2024-01-01 18:00", periods=len(df), freq="6h", tz="UTC")
    df["volume"] = 1.0
    df["regime"] = "up/lowvol"
    stamps = pd.DatetimeIndex(df["open_time"])
    day = stamps.normalize()
    step = pd.Timedelta(hours=6)
    df["session_first"] = (stamps == day)
    df["session_last"] = ((stamps + step).normalize() != day)
    df["session_open"] = df.groupby(day)["open"].transform("first")
    df["stretch"] = stretch
    df["buy_trig"] = df["session_open"] + stretch
    df["sell_trig"] = df["session_open"] - stretch
    df["risk_unit"] = r_mult * stretch
    df["armed"] = armed
    return df


def native_orb_exit(df):
    last = df["session_last"].to_numpy()

    def fn(_d, i, _t):
        return ExitPlan(close_exit=bool(last[i]), reason="next open")
    return fn


def test_resting_buy_stop_and_no_stop_loss() -> None:
    print("\n10. A resting buy stop fills at its own price, and the native rule has NO stop")
    # Session opens at 100 with a stretch of 2, so the buy stop rests at 102.
    # Bar 3 then trades down to 95 - far below the 100 measuring stop - and the
    # trade must survive it, because Crabel's rule has no protective stop.
    df = resting_bars([
        (90, 90, 90, 90),            # 18:00 Jan 1, before any tracked session
        (100, 101, 99, 100),         # 00:00 Jan 2, session open 100, no touch
        (100, 103, 99.5, 102),       # 06:00, high 103 penetrates the 102 buy stop
        (102, 104, 95, 103),         # 12:00, deep dip well through the 1R level
        (103, 105, 102, 104),        # 18:00, last bar of the session
        (110, 110, 110, 110),        # 00:00 Jan 3, the next day's open
    ], stretch=2.0)
    stats: dict = {}
    trades = simulate_resting(df, native_orb_exit(df), warmup=0, stats=stats)
    check("exactly one trade", len(trades), 1)
    t = trades[0]
    check("went long", t.direction, 1)
    check("filled at the 102 trigger, not at a later open", t.entry_price, 102.0)
    check("1R measured one stretch below the fill", t.initial_stop, 100.0)
    check("survived the dip to 95 - no stop was enforced", t.exit_reason, "next open")
    check("exited at the next day's open", t.exit_price, 110.0)
    check("gross R", t.gross_r, 4.0)
    check("one session traded", stats["traded"], 1)


def test_resting_sell_stop() -> None:
    print("\n11. The sell stop mirrors it: fills at its own price on the way down")
    df = resting_bars([
        (90, 90, 90, 90),
        (100, 101, 99, 100),         # session open 100, sell stop rests at 98
        (99, 99.5, 97, 97.5),        # low 97 penetrates it
        (97, 98, 96, 96),
        (96, 97, 95, 96),
        (90, 90, 90, 90),            # next day's open
    ], stretch=2.0)
    trades = simulate_resting(df, native_orb_exit(df), warmup=0)
    check("exactly one trade", len(trades), 1)
    t = trades[0]
    check("went short", t.direction, -1)
    check("filled at the 98 trigger", t.entry_price, 98.0)
    check("1R measured one stretch above the fill", t.initial_stop, 100.0)
    check("exited at the next day's open", t.exit_price, 90.0)
    check("gross R", t.gross_r, 4.0)


def test_resting_gap_through_trigger() -> None:
    print("\n12. A bar that opens past a resting stop fills at the OPEN, never at the trigger")
    df = resting_bars([
        (90, 90, 90, 90),
        (100, 101, 99, 100),         # sell stop rests at 98
        (95, 96, 94, 95),            # opens at 95, already through the trigger
        (95, 96, 94, 95),
        (95, 96, 94, 95),
        (95, 95, 95, 95),
    ], stretch=2.0)
    trades = simulate_resting(df, native_orb_exit(df), warmup=0)
    t = trades[0]
    check("filled at the 95 gap open, not the 98 trigger", t.entry_price, 95.0)
    check("which is the worse price for a short", t.entry_price < 98.0, True)


def test_resting_both_triggers_skipped() -> None:
    print("\n13. One bar covering BOTH triggers is skipped and counted, not guessed")
    df = resting_bars([
        (90, 90, 90, 90),
        (100, 101, 99, 100),
        (100, 103, 97, 100),         # covers the 102 buy AND the 98 sell
        (100, 103, 99, 102),         # would have triggered, but the session is closed
        (102, 103, 101, 102),
        (100, 100, 100, 100),
    ], stretch=2.0)
    stats: dict = {}
    trades = simulate_resting(df, native_orb_exit(df), warmup=0, stats=stats)
    check("no trade invented from an unresolvable bar", len(trades), 0)
    check("the ambiguous session is counted", stats["ambiguous"], 1)
    check("and no second entry is taken later in that session", stats["traded"], 0)


def test_resting_one_trade_per_session() -> None:
    print("\n14. One trade per session: a forced stop-out does not re-arm the same day")
    # Also documents the deliberately pessimistic entry-bar rule: the trade is
    # tested against the whole of its entry bar, including the part that
    # happened before the order was penetrated.
    df = resting_bars([
        (90, 90, 90, 90),
        (100, 101, 99, 100),
        (100, 103, 99.5, 100),       # fills long at 102, and the same bar's low
                                     # is below the 100 stop -> stopped out at once
        (100, 105, 99, 104),         # would trigger again; must not
        (104, 105, 103, 104),
        (104, 104, 104, 104),
    ], stretch=2.0)
    stats: dict = {}
    trades = simulate_resting(df, forced_13_exit, warmup=0, time_limit_bars=30, stats=stats)
    check("exactly one trade in the session", len(trades), 1)
    t = trades[0]
    check("stopped out on its entry bar", t.exit_reason, "stop")
    check("bars held is zero", t.bars_held, 0)
    check("loss is exactly 1R gross", t.gross_r, -1.0)
    check("the session is not re-armed", stats["traded"], 1)


def test_resting_session_blocked_and_no_touch() -> None:
    print("\n15. Session accounting: blocked by an open trade, and never touched")
    df = resting_bars([
        (90, 90, 90, 90),
        (100, 101, 99, 100),         # Jan 2 opens 100: buy 102, sell 98
        (100, 103, 102, 103),        # fills long at 102, no stop, no target
        (103, 104, 103, 104),
        (104, 105, 104, 105),        # last bar of Jan 2, forced rule holds on
        (105, 106, 105, 106),        # Jan 3 opens 105 while still long -> blocked
        (106, 107, 106, 107),
        (107, 108, 107, 108),
        (108, 109, 108, 109),        # last bar of Jan 3
        (109, 110, 108.5, 109),      # Jan 4 opens 109: buy 111, sell 107
        (109, 110, 108.5, 109),
        (109, 110, 108.5, 109),
        (109, 110, 108.5, 109),      # last bar of Jan 4, neither level reached
    ], stretch=2.0)
    stats: dict = {}
    trades = simulate_resting(df, forced_13_exit, warmup=0, time_limit_bars=30, stats=stats)
    check("three sessions had orders placed", stats["sessions_armed"], 3)
    check("one traded", stats["traded"], 1)
    check("one was blocked by the trade still running", stats["blocked"], 1)
    check("one saw neither trigger reached", stats["no_touch"], 1)
    check("the forced trade outlived its own session", trades[0].bars_held > 3, True)
    check("and closed at its 3R target on the following day", trades[0].exit_price, 108.0)


def test_first_bar_of_a_state_is_really_the_first_bar() -> None:
    """The "first bar of a state" idiom, which three strategies trade on.

    A state like "price closed outside the band" persists for several bars, and
    every one of those strategies means to trade only the bar that STARTS the
    run. Written as `state & ~state.shift(1).fillna(False)` that silently fails:
    shifting a boolean column leaves object dtype, and `~` on object dtype is
    Python's integer bitwise NOT applied elementwise, giving -1 for False and -2
    for True. Both are truthy, so the whole condition collapses back to `state`
    and the strategy trades every bar of the run instead of the first. The bug is
    invisible - no error, no NaN, just a different strategy. This test fails if
    the collapse ever comes back.
    """
    print("\n16. The first bar of a state is really the first bar of it")
    state = pd.Series([False, True, True, True, False, True])
    broken = state & ~state.shift(1).fillna(False)
    safe = state & ~state.shift(1, fill_value=False)
    check("the unsafe idiom does collapse into the raw state", list(broken), list(state))
    check("the safe idiom keeps a bool column", safe.dtype == bool, True)
    check("and marks only the two run-starts", list(safe),
          [False, True, False, False, False, True])

    # The same check against the real strategy module, on a price path built to
    # sit outside the upper band for a stretch: one ramp, then a flat top.
    close = [100.0] * 200 + [100.0 + 3.0 * k for k in range(1, 41)] + [220.0] * 40
    df = bars([(c, c, c, c) for c in close])
    f = s05.add_indicators(df)
    runs = int(f["out_up"].sum())
    edges = int(f["long_entry"].sum())
    check("the ramp does keep price outside the band for many bars", runs > 10, True)
    check("but far fewer bars are counted as entries", edges < runs, True)
    check("every entry bar is outside the band",
          bool((f["out_up"] | ~f["long_entry"]).all()), True)
    check("and no entry bar follows another outside bar",
          int((f["long_entry"] & f["out_up"].shift(1, fill_value=False)).sum()), 0)


def test_day_scale_n_reduces_to_plain_atr_on_daily_bars() -> None:
    """Strategy #7's N must be the SAME quantity the original Turtles used.

    The original's N is "the average true range of the last twenty days", measured on
    a daily chart - a plain 20-bar ATR. To run that rule on hourly bars, #7 measures
    the true range over a rolling day-length window of bars and averages twenty days
    of them. That is a new expression, and a new expression is exactly where a
    strategy quietly stops being the strategy it claims to be.

    The check that it has not is arithmetic: when a bar IS a day (bars_per_day = 1)
    the day-scale expression must collapse EXACTLY onto the plain 20-bar ATR. If it
    does, the intraday versions are the same quantity measured on finer bars; if it
    does not, they are something else wearing the same name.

    The frame here is hourly, but bpd is passed as 1 explicitly, which is what the
    strategy does on a daily frame. Passing bpd=24 is checked too, to prove the test
    would notice a difference at all rather than passing on any input - which needs
    more than 20*24 bars of history, hence the length.
    """
    print("\n18. Strategy #7's day-scale N collapses onto the plain 20-bar ATR when a bar is a day")
    rows = []
    px = 100.0
    for k in range(600):
        # A deterministic zig-zag with real gaps, so the true range's second and
        # third terms (against the previous close) actually bind on some bars.
        px = px * (1.0 + (0.03 if k % 3 else -0.02))
        rows.append((px, px * 1.02, px * 0.97, px * 1.005))
    df = bars(rows)

    day = s07._day_scale_n(df, s07.N_DAYS, 1)
    plain = s07._true_range(df).rolling(s07.N_DAYS).mean()
    gap = (day - plain).abs().max()
    check("the two series are identical to the last bit at bpd=1", float(gap), 0.0)
    check("and both actually produced numbers rather than all-NaN",
          int(day.notna().sum()) > 50, True)

    wide = s07._day_scale_n(df, s07.N_DAYS, 24)
    check("at bpd=24 the day-scale N is genuinely different, so the test can fail",
          float((wide - plain).abs().max()) > 0.0, True)
    check("and a day-length window measures a wider range than a single bar",
          float(wide.dropna().mean()) > float(plain.dropna().mean()), True)


def test_coverage_reports_the_tradeable_window() -> None:
    """Coverage must report the window the engine could trade, not the file length.

    Reporting the file length would flatter the daily rows badly: a 150-bar warmup
    is six days at 1H and five months at 1D, and a reader comparing "days covered"
    across timeframes would be comparing two different things. This builds a frame
    of known length and checks the window starts exactly `warmup` bars in, and that
    bars, days and years agree with each other.
    """
    print("\n17. Coverage reports the tradeable window, not the file length")
    df = bars([(100.0, 101.0, 99.0, 100.0)] * 500)   # 500 hourly bars
    coverage._CACHE[("TESTUSDT", "1H")] = df

    w = coverage.window("TESTUSDT", "1H", warmup=200)
    check("tradeable bars are the file minus the warmup", w["bars"], 300)
    check("the window starts at the first bar the engine may act on",
          w["start"], df["open_time"].iloc[200])
    check("and ends on the last closed bar", w["end"], df["open_time"].iloc[-1])
    check("days spanned are the hours between those two bars", w["days"], 299 / 24)
    check("years are days over 365.25", w["years"], (299 / 24) / 365.25)

    z = coverage.window("TESTUSDT", "1H", warmup=0)
    check("with no warmup the window is the whole file", z["bars"], 500)
    check("and dropping the warmup lengthens the window", z["days"] > w["days"], True)

    starved = coverage.window("TESTUSDT", "1H", warmup=500)
    check("a warmup that eats the whole file reports no tradeable bars",
          starved["bars"], 0)
    check("and reports no window rather than a fake one", starved["start"], None)


if __name__ == "__main__":
    print("Engine self-tests - hand-built candles, arithmetic answers")
    for fn in [
        test_fill_at_next_open,
        test_clean_3r_target,
        test_stop_wins_ties,
        test_gap_through_stop,
        test_time_limit,
        test_short_side,
        test_unfinished_trade_dropped,
        test_metrics_arithmetic,
        test_stop_frac_uses_real_entry,
        test_resting_buy_stop_and_no_stop_loss,
        test_resting_sell_stop,
        test_resting_gap_through_trigger,
        test_resting_both_triggers_skipped,
        test_resting_one_trade_per_session,
        test_resting_session_blocked_and_no_touch,
        test_first_bar_of_a_state_is_really_the_first_bar,
        test_coverage_reports_the_tradeable_window,
        test_day_scale_n_reduces_to_plain_atr_on_daily_bars,
    ]:
        fn()
    print("\n" + "=" * 62)
    if FAILURES:
        print(f"{len(FAILURES)} CHECK(S) FAILED: {', '.join(FAILURES)}")
        sys.exit(1)
    print("All engine self-tests passed.")
