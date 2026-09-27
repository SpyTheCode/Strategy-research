# Strategy #21 SPEC — RSI(2) mean reversion (EXCLUDED)

**Status:** EXCLUDED BY PROJECT DESIGN. Existing `strategy_log.md` explicitly says this high-win/low-reward, tail-loss strategy is not fairly evaluated by forced 1:3 and is not to be tested under the standard matrix. Do not duplicate #10's proposed candidate.

## 1. THE RULE — source and exact tested interpretation
**Source:** Larry Connors, *Short Term Trading Strategies That Work* (2008), RSI(2) methods. The book contains several variants; there is no single rule identified in repository sources. No trading rule is approved for execution under #21. The often-cited long setup (close above 200-SMA, RSI(2)<10; exit above 5-SMA) is not automatically the #21 rule without owner/source-page confirmation.

## 2. EVERY PLACEHOLDER, PRE-DECIDED
No execution placeholders are assigned because status is excluded. If owner reverses exclusion, obtain exact source edition/page and rule before any test; do not infer from the earlier unrun #10 draft. Forced 1:3 remains unsuitable.

## 3. STRATEGY-SPECIFIC LOOKAHEAD TRAPS
If ever revisited: RSI seed/smoothing, current-close timing, 200-SMA and exit SMA alignment; no use of a signal bar close as fill. Exact source variant must be frozen first.

## 4. EXACT TEST MATRIX
- [ ] No backtest; no standard native/forced matrix.
- [ ] No parameter sweeps.
- [ ] No CSV rows or verdict. Require owner approval and a bespoke evaluation design.

## 5. EXACT REPORT FORMAT
Not applicable; do not fabricate the standard 15-section performance report. Preserve this exclusion note and record decision rationale only.

## 6. MISINTERPRETATION RISKS
Do not confuse this excluded #21 with proposed #10. Strategy numbering alone is not evidence that it is approved or that same-named methods are identical.

## 7–15. EXECUTOR LOCKS
Current action: none. Do not execute `src/s10_rsi2.py` as #21, do not write result metrics, and do not change project logs.