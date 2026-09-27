# Strategy #12 SPEC — Parabolic SAR reversal

**Status:** proposed candidate; canonical indicator parameters pinned.

## 1. THE RULE — source and exact tested interpretation
**Source:** J. Welles Wilder Jr., *New Concepts in Technical Trading Systems* (1978), Parabolic Time/Price System. Follow SAR direction: long when close crosses above SAR, short when close crosses below; reverse on opposite SAR signal. The active SAR is the source stop/reversal level; no independent target.

## 2. EVERY PLACEHOLDER, PRE-DECIDED
Initial acceleration 0.02; increment 0.02; maximum 0.20. Initialize direction from first 2 closed bars; initial SAR opposite extreme of those bars, EP with trend extreme. Clamp long SAR below prior two lows / short SAR above prior two highs. Signal on close crossing prior-known active SAR, fill next open; stop/reversal at active SAR. Sensitivity max AF 0.10/0.20/0.30; step 0.01/0.02/0.03 independently.

## 3. STRATEGY-SPECIFIC LOOKAHEAD TRAPS
SAR is recursively updated and must use prior EP/AF and prior bars. Never seed trend using later extrema; never backfill initial SAR using the full sample. Current bar's high/low may update EP only after close; newly calculated SAR applies no earlier than next bar. Preserve stop-first same-bar ambiguity.

## 4. EXACT TEST MATRIX
- [ ] BTC/SOL/XRP × 1H/4H/1D.
- [ ] AF .02/.02/.20 headline; native SAR reversal + forced 1:3.
- [ ] max AF .10/.20/.30; step .01/.02/.03 independently.
- [ ] all 9 audits, context, coverage, coin splits, exit-death, 6 CSV rows.

## 5. EXACT REPORT FORMAT
Fill the latest completed report's 15 headings: source/rule; exact initialization; lookahead; coverage; results; exit composition; long/short; exit-death; per-coin; context; verdict; parameter sensitivity; costs; bottom line; limitations. State initialization pseudocode and parameter variant explicitly.

## 6. MISINTERPRETATION RISKS
Do not treat SAR as a fixed entry-relative stop: it ratchets and can reverse direction. Avoid applying a bar's newly updated SAR to that same bar's low/high; SAR reversal can gap and must execute at next open under shared runner mechanics.

## 7–15. EXECUTOR LOCKS
Inherited project defaults; warmup 250 bars; no separate target. Test source-native reversal separately from forced 1:3. No parameter selection by best outcome. Fees taker both legs; funding/slippage excluded; log all cells append-only.