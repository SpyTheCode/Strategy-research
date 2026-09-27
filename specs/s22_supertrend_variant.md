# Strategy #22 SPEC — Supertrend (7, 3) robustness variant

**Status:** proposed candidate; deliberately distinguish from already-tested #8 Supertrend(10,3).

## 1. THE RULE — source and exact tested interpretation
**Source:** Olivier Seban's Supertrend indicator (commonly attributed to Seban; canonical implementation varies). Test trend-following: long when close crosses above the active final upper band; short when close crosses below active final lower band. Native reverse on direction flip. No independent TP; initial stop is active Supertrend line.

## 2. EVERY PLACEHOLDER, PRE-DECIDED
ATR length 7, multiplier 3; Wilder ATR; midpoint=(H+L)/2; basic bands midpoint ±3ATR; final bands carry forward unless prior close crosses prior final band; initialize direction up after 7 bars, initial active lower band. Sensitivity ATR length 7/10/14; multiplier 2/3/4 independent. This is an algorithmic convention; record exact recurrence.

## 3. STRATEGY-SPECIFIC LOOKAHEAD TRAPS
Band recurrence references previous final bands and prior close; update only forward. Never use chart-library repainting/retroactive trend flips. Active stop at bar open must be based on prior completed data; current-bar close reversal executes next open. Specify same-bar band-cross behavior explicitly and test it.

## 4. EXACT TEST MATRIX
- [ ] BTC/SOL/XRP × 1H/4H/1D.
- [ ] Supertrend(7,3) native flip and forced 1:3 using same initial stop/risk.
- [ ] ATR 7/10/14; multiplier 2/3/4 independently.
- [ ] audits ×9; verify differs from #8; coverage, context, per-coin, exit-death, logs.

## 5. EXACT REPORT FORMAT
Latest completed 15 headings: source/rule; recurrence/placeholder; lookahead; coverage; pooled results; exit mix; long/short; exit-death; per coin; context; verdict; sensitivity; cost caveats; bottom line; limitations. Compare parameterization to #8 but never merge results.

## 6. MISINTERPRETATION RISKS
Supertrend formulas vary across platforms. Do not silently reuse #8's output/indicator; specify and self-test recurrence. Do not enter retroactively at the band crossing price when rule is close confirmation. Initial R must be actual fill to initial active band.

## 7–15. EXECUTOR LOCKS
Project defaults; warmup 250; no separate TP. Independently test sensitivity values, no best-of selection. Funding/slippage omitted; append after audit and reporting.