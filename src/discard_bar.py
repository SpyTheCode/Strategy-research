"""The discard bar - one place, applied identically to every strategy.

Nothing in here is a judgement call made per strategy. It is a fixed ruler.
Each exit variant (native, forced-1:3) is scored separately and can land on a
different verdict, which is the point: a strategy can have a good entry and a
bad exit.

Every threshold below is measured AFTER Bybit fees.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DiscardBar:
    # --- Gate: is there enough evidence to judge at all? -------------------
    min_trades: int = 30

    # --- KEEP requires every one of these ---------------------------------
    keep_expectancy_r: float = 0.10      # each trade nets at least 0.10 of what it risked
    keep_sharpe: float = 0.70
    keep_r_recovery: float = 1.50        # total R earned >= 1.5x the worst R drawdown
    keep_win_margin: float = 0.02        # forced-1:3 only: clear its OWN fee breakeven by 2pp
    keep_rr_native: float = 1.50         # native only; winners >= 1.5x average loser

    # --- DISCARD if any one of these is true ------------------------------
    discard_expectancy_r: float = 0.0    # loses money, or exactly breaks even
    discard_sharpe: float = 0.30
    discard_r_recovery: float = 0.50     # never earned back half its worst hole


BAR = DiscardBar()


def _ok(value: float) -> bool:
    return value is not None and np.isfinite(value)


def breakeven_win_rate(fee_cost_r: float) -> float:
    """Win rate a 1:3 system needs just to break even, given its own fee bill.

    A winner pays +3R minus fees, a loser costs -1R minus fees, so expectancy is
    4w - 1 - c where c is the average round-trip fee measured in risk units.
    Setting that to zero gives w = (1 + c) / 4.

    This matters because c is not a constant: a tight stop on an hourly chart
    makes 1R small, so the same percentage fee eats a far larger share of it.
    Measured on this project's data, c runs about 0.02R on daily bars and up to
    0.18R on hourly bars - which moves breakeven from roughly 25.5% to 29.6%.
    A single fixed win-rate threshold would therefore be too lax on fast
    timeframes and too harsh on slow ones, so the bar is derived per run.
    """
    c = fee_cost_r if _ok(fee_cost_r) else 0.0
    return (1.0 + c) / 4.0


def verdict(m: dict, exit_variant: str, bar: DiscardBar = BAR) -> tuple[str, str]:
    """Return (KEEP | DISCARD | INCONCLUSIVE, plain-English reason)."""
    n = m.get("trades", 0)
    if n < bar.min_trades:
        return (
            "INCONCLUSIVE",
            f"only {n} trades (need {bar.min_trades}); too few to tell skill from luck",
        )

    exp = m.get("expectancy_post_fee_r", float("nan"))
    shp = m.get("sharpe_post_fee", float("nan"))
    rec = m.get("r_recovery", float("nan"))
    wr = m.get("win_rate", float("nan"))
    rr = m.get("rr_achieved", float("nan"))
    fee = m.get("avg_fee_cost_r", float("nan"))

    fails: list[str] = []
    if _ok(exp) and exp <= bar.discard_expectancy_r:
        fails.append(f"post-fee expectancy {exp:+.3f}R per trade is not positive")
    if _ok(shp) and shp < bar.discard_sharpe:
        fails.append(f"post-fee Sharpe {shp:.2f} below {bar.discard_sharpe}")
    if _ok(rec) and rec < bar.discard_r_recovery:
        fails.append(f"earned only {rec:.2f}x its worst drawdown")
    if fails:
        return "DISCARD", "; ".join(fails)

    misses: list[str] = []
    if not (_ok(exp) and exp >= bar.keep_expectancy_r):
        misses.append(f"expectancy {exp:+.3f}R < {bar.keep_expectancy_r:+.2f}R")
    if not (_ok(shp) and shp >= bar.keep_sharpe):
        misses.append(f"Sharpe {shp:.2f} < {bar.keep_sharpe}")
    if not (_ok(rec) and rec >= bar.keep_r_recovery):
        misses.append(f"R-recovery {rec:.2f} < {bar.keep_r_recovery}")
    if exit_variant == "forced-1:3":
        need = breakeven_win_rate(fee) + bar.keep_win_margin
        if not (_ok(wr) and wr >= need):
            misses.append(
                f"win rate {wr:.1%} < {need:.1%} needed to clear its own fee bill"
                f" (fees cost {fee:.3f}R per trade)"
            )
    else:
        if not (_ok(rr) and rr >= bar.keep_rr_native):
            misses.append(f"achieved RR {rr:.2f} < {bar.keep_rr_native}")

    if not misses:
        return "KEEP", (
            f"{exp:+.3f}R per trade, Sharpe {shp:.2f}, "
            f"earned {rec:.2f}x its worst drawdown over {n} trades"
        )
    return "INCONCLUSIVE", "positive but short of the KEEP bar: " + "; ".join(misses)


EXIT_DEATH_GAP_R = 0.15   # a gap this big is worth more than the whole KEEP bar


def exit_death(native: dict, forced: dict) -> tuple[str, str]:
    """Is the result decided by the exit rules rather than by the entry signal?

    Same entry, same 1R, only the exit differs - so any difference between the
    two runs is attributable to the exit alone. Two ways that counts as the exit
    being decisive:

      * the two exits disagree on the SIGN of the edge - one makes money and the
        other loses it. The entry cannot be both good and bad, so the exit is
        what decided the outcome.
      * they agree on the sign but differ by at least 0.15R per trade, which is
        larger than the entire +0.10R KEEP requirement. An exit choice worth
        more than the bar itself is the dominant factor.

    Returns ("yes"|"no", plain-English diagnosis).
    """
    a = native.get("expectancy_post_fee_r", float("nan"))
    b = forced.get("expectancy_post_fee_r", float("nan"))
    na, nb = native.get("trades", 0), forced.get("trades", 0)

    if not (_ok(a) and _ok(b)) or min(na, nb) == 0:
        return "n/a", "one of the two runs produced no completed trades, so they cannot be compared"

    gap = b - a
    better = "forced 1:3" if gap > 0 else "native"
    worse = "native" if gap > 0 else "forced 1:3"

    if (a > 0) != (b > 0):
        return "yes", (
            f"the exit flips the sign of the edge: native {a:+.3f}R per trade vs "
            f"forced 1:3 {b:+.3f}R. Identical entries, so the entry signal is not "
            f"what decided this - the {worse} exit is. The edge, such as it is, "
            f"lives in the {better} exit."
        )
    if abs(gap) >= EXIT_DEATH_GAP_R:
        return "yes", (
            f"both exits agree on direction but differ by {abs(gap):.3f}R per trade "
            f"(native {a:+.3f}R vs forced 1:3 {b:+.3f}R), which is larger than the "
            f"entire +0.10R KEEP requirement. The {better} exit is doing more work "
            f"than the entry signal."
        )
    return "no", (
        f"the two exits land within {abs(gap):.3f}R per trade of each other "
        f"(native {a:+.3f}R vs forced 1:3 {b:+.3f}R), so the result is driven by "
        f"the entry signal rather than by the choice of exit"
    )


def describe() -> str:
    """The bar, in words, for the write-up."""
    b = BAR
    return (
        f"Gate: fewer than {b.min_trades} trades -> INCONCLUSIVE.\n"
        f"KEEP needs all of: post-fee expectancy >= {b.keep_expectancy_r:+.2f}R per trade; "
        f"post-fee Sharpe >= {b.keep_sharpe}; total R >= {b.keep_r_recovery}x worst R drawdown; "
        f"and (forced-1:3) win rate >= its own fee breakeven (1+c)/4 plus "
        f"{b.keep_win_margin:.0%}, or (native) achieved RR >= {b.keep_rr_native}:1.\n"
        f"DISCARD on any of: post-fee expectancy <= {b.discard_expectancy_r:+.2f}R; "
        f"post-fee Sharpe < {b.discard_sharpe}; total R < {b.discard_r_recovery}x worst R drawdown.\n"
        "Anything in between -> INCONCLUSIVE."
    )
