# Strategy #9 RE-RUN v2 — NR7, rule 6 applied as written (HEADLINE)

## What changed vs the first re-run (v1), stated first

v1 used the engine's convention for a double-touch session (bar D+1's range
covers BOTH the NR7 high and low): the session produced NO trade and was only
counted in `stats["ambiguous"]`. That looks at the whole bar to drop a session
that must end in a loss — selection by outcome. v2 removes it.

v2 books every double-touch session exactly as `specs/s09_nr7_rerun.md` rule 6
says: enter at the trigger nearer to bar D+1's open, exit at the opposite end
(the stop), a loss of 1R plus taker fees on both legs. This v2 run is the
HEADLINE. v1's numbers appear only as a labeled comparison column
("v1: double-touch skipped").

## How rule 6 is implemented without touching any existing file

1. The shared engine (`harness.simulate_resting`) runs unchanged, exactly as in
   v1, and returns its trades plus `stats["ambiguous"]`.
2. The engine counts an ambiguous session only when it was FLAT with live
   orders (harness.py:382-387: `state == "open" and position is None and
   armed[i] and risk[i] > 0`). So every counted session passes the same
   position gating as any entry, by construction.
3. The engine returns only the count, not the bars. The v2 runner re-derives
   which bars those were by replaying the engine's state machine (lines
   349-436) from the same df columns the strategy already produced
   (buy_trig, sell_trig, armed, risk_unit, session_first, session_last) plus
   the engine's returned trade list for the position timeline. No new
   indicator, no new data, no lookahead.
4. Each re-derived bar is booked as a `harness.Trade`: direction = trigger
   nearer to the bar's open; entry price = worse of that trigger and the open
   (the engine's gap rule, harness.py:392); initial_stop = entry - d*risk_unit
   (the opposite end); exit at the stop the same bar (the bar's range provably
   covers it, so the fill is exactly at the stop) = -1R gross; taker fees on
   both legs through `Trade.net_r`, the same accounting as every other trade.
5. RECONCILIATION: per coin, timeframe and exit, the number of re-derived
   double-touch bars MUST equal the engine's `stats["ambiguous"]`. Any
   mismatch aborts the run loudly. Silent divergence is impossible.

## Unchanged from v1

Triggers, NR7 definition (strict '<' vs all prior six ranges), REST_BARS=1,
offset 0, warmup, one position per session, no re-entry, no reversal,
gap-through-entry rule, stop-first tie rule, taker fees, the Sep 4 2026 cache,
partial final 1H/6H bars not dropped, pooled-coin-per-timeframe reporting,
the discard bar and verdict thresholds, sensitivities, and the lookahead
truncation audit. Both exits (native measure rule, forced-1:3) as in v1.

## Reporting deltas required by the v2 brief

- Trades per cell state how many are double-touch losses; raw win and loss
  counts are printed.
- Concentration AND long/short split are computed for BOTH exits.
- Exit-overlap and shared-entry re-run as in v1 (threshold 85%).
- Per-coin trades and post-fee R per cell.
- Double-touch direction attribution: rule 6's "nearer to bar D+1's open" is
  applied mechanically; the split long/short it produces is reported.

## Known limitation carried over from v1

Funding is a base-rate estimate (a floor, not a measurement), stated wherever
funding numbers appear. Strategy #10 uses market-order entries (simulate, not
simulate_resting) and carries no double-touch skip convention; its re-run
reproduced the original exactly. Only #4 and #9 use the resting-order path and
carry the skip convention.
