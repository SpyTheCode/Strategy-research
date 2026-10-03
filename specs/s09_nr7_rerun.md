# Strategy #9 SPEC — NR7 (Bulkowski) — BLIND RE-RUN COPY

**Status:** verbatim copy of the owner's #9 spec, restated here as the authority for
this re-run (`specs/s09_nr7_rerun.md`). This re-run writes NEW files only
(`src/s09_nr7_rerun.py`, `src/run_s09_rerun.py`) and never touches `s09_nr7.py`,
`run_s09.py`, or any prior #9 output. Dry run only: no log append.

=== STRATEGY #9 SPEC: NR7 (Bulkowski) ===
Source: Thomas Bulkowski, "NR7", thepatternsite.com (Encyclopedia of Chart Patterns).
1. Setup: bar D is an NR7 if its range (high minus low, NOT true range) is strictly smaller than the range of each of the six bars before it (seven bars in total). Ties do not qualify.
2. Entry: resting stop orders. Before bar D+1 opens, a buy stop sits at bar D's HIGH and a sell stop at bar D's LOW. Whichever is touched first is the trade. Orders live for REST_BARS = 1 bar (bar D+1 only) in the headline, then are cancelled. Trigger offset = 0 in the headline.
3. Stop: the opposite end of the pattern (bar D's low for a long, bar D's high for a short). That distance is 1R.
4. Native exit: the measure rule. Target = pattern height (bar D's range) added to bar D's high for a long, or subtracted from bar D's low for a short. With offset 0 this is exactly 1R, so native is a symmetric 1:1.
5. Forced 1:3 exit: same stop, 3R target, 30-bar time limit.
6. If bar D+1 touches BOTH the high and the low of bar D: either order ends in a stop, so apply the engine's stop-wins rule and record a 1R loss. Attribute direction to the trigger nearer to bar D+1's open and state that this affects only the long/short split.
7. Fees: taker 0.055% per side on both legs. All other engine rules unchanged (gap through the stop fills at the open, trade open at data-end discarded, stop wins when one candle contains both stop and target).
8. Entries that gap through the trigger: use the engine's existing convention if it has one; otherwise fill at the bar's open and size risk on the actual entry-to-stop distance. State which in section 2.
9. Position handling: use the engine's existing convention and state it.
10. Scope: BTCUSDT, SOLUSDT, XRPUSDT; 1H, 4H, 6H, 1D; full history; pooled coins per timeframe, never pooled timeframes; native versus forced 1:3 for each.
PLACEHOLDERS (section 2): offset 0, REST_BARS 1, N 7, 30-bar limit, double-touch rule, gap-through-entry convention.
SENSITIVITIES (section 10 only, never headline): offset 0.1% of bar D's range; REST_BARS 2 and 3; NR4 in place of NR7.
STEP 0 for #9 only: before writing strategy code, inspect the shared engine and report in plain language whether it can already do resting stop-order entries (a trigger price inside the next bar, first-touch fill). If it cannot, report exactly what is missing, SKIP #9, and go straight on to #10. Do not build engine changes.

=== FINDING (2026-10-03): REST_BARS 2/3 SWEEP IS INERT UNDER THE CURRENT ENGINE ===
The REST_BARS=2 and REST_BARS=3 sensitivity rows are byte-identical to the
headline, and this is structural, not a plumbing bug:

1. A session whose only bar D+1 does NOT touch either trigger is, by that very
   fact, a bar whose range sits strictly inside bar D's range. Its range is
   therefore smaller than all seven bars before it, i.e. bar D+1 is itself NR7.
   So every untouched session is immediately followed by a new narrow bar.
2. The engine (harness.simulate_resting) is a one-session state machine: at
   bar D+2 the new session's session_first re-arms the book with the NEW
   session's triggers, so the old session's extended window never gets a fill
   at its own trigger prices. Verified on BTCUSDT 1H full history: REST=2 and
   REST=3 produce 5094 trades, ZERO of which enter on an extended bar.
3. Accounting artifact of the same collapse: under REST=2 the prior session's
   session_last fires on the same bar the new session re-arms, booking one
   no_touch and leaving the newer session unbucketed. Measured: armed=9668 in
   both runs, but REST=2 buckets sum to 9336 (332 sessions vanish; no_touch
   drops 347 -> 15). Trades are unaffected (entry lists identical).

Consequence: the REST_BARS sensitivity as specified cannot measure order
lifetime on this engine, because an unfilled first bar always hands the next
bar to a fresh session. Fixing this would require overlapping-session support
in the shared engine (used by #4 and #7), which STEP 0 forbids. The sweep rows
are therefore reported as-engine-is with this note attached.