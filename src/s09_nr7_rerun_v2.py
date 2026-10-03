"""Strategy #9 RE-RUN v2 - NR7 (Bulkowski), rule 6 applied as written.

The strategy logic is IDENTICAL to v1 (s09_nr7_rerun.py): same NR7 pattern
(strict '<' against all six prior ranges), same resting stops at bar D's
high/low with REST_BARS=1 and offset 0, same 1R = trigger-to-opposite-end,
same native measure rule and same forced-1:3 exit. It is re-exported from
s09_nr7_rerun rather than copied so the two re-runs cannot drift.

The ONLY v2 change is in run_s09_rerun_v2.py: a double-touch session (bar
D+1 covers both triggers) is BOOKED as a trade - entry at the trigger nearer
to the bar's open, exit at the opposite end, -1R gross plus taker fees on
both legs - instead of being skipped per the engine convention. See
specs/s09_nr7_rerun_v2.md. s09_nr7.py and run_s09.py are never opened.
"""

from s09_nr7_rerun import (  # noqa: F401  (re-export, verbatim v1 logic)
    N,
    REST_BARS,
    OFFSET_MULT,
    add_indicators,
    native_exit,
    no_entry,
    warmup_for,
)
