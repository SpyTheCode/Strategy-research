# Strategy #20 SPEC — ATR channel breakout

**Status:** proposed candidate.

## 1. THE RULE — source and exact tested interpretation
**Source:** J. Welles Wilder Jr., *New Concepts in Technical Trading Systems* (1978), Volatility System / ATR-based stops. Pinned rule adaptation: enter long when close exceeds prior 20-bar high; short below prior 20-bar low. Initial stop 2×ATR(20); native exit on opposite 10-bar channel. No profit target.

## 2. EVERY PLACEHOLDER, PRE-DECIDED
Entry 20, exit 10, ATR20 Wilder, stop2ATR. No pyramiding. Sensitivity entry 10/20/55; exit 5/10/20; stop 1.5/2/2.5ATR independently.

## 3. STRATEGY-SPECIFIC LOOKAHEAD TRAPS
Prior channel excludes current bar and must be shifted. ATR uses completed bars only, initial distance frozen. Breakout based on close, not intrabar touch. Opposite exit channel likewise prior bars only.

## 4. EXACT TEST MATRIX
- [ ] BTC/SOL/XRP × 1H/4H/1D; 20/10/2ATR headline.
- [ ] native opposite channel, forced 1:3.
- [ ] entry 10/20/55; exit 5/10/20; stop 1.5/2/2.5ATR separately.
- [ ] audit ×9; coverage, context, per-coin, exit-death, logs.

## 5. EXACT REPORT FORMAT
Use latest completed 15-section format: source/rule; parameters; audit; coverage; pooled results; exit composition; side split; exit-death; per coin; context; verdict; sensitivity; funding/cost; bottom line; limits.

## 6. MISINTERPRETATION RISKS
This resembles Turtle systems but is not a claim of Turtle rules; source attribution is Wilder ATR only. Do not conflate close breakout with resting stop order. 2ATR is initial risk, not continuously trailing unless separately tested.

## 7–15. EXECUTOR LOCKS
Project defaults; warmup 250; no TP. Independent sweeps, no optimization. Funding/slippage omitted, append-only.