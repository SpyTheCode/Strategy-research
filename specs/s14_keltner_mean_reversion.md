# Strategy #14 SPEC — Keltner channel reversion

**Status:** proposed candidate; distinct from #5 Keltner breakout.

## 1. THE RULE — source and exact tested interpretation
**Source:** Chester Keltner, *How to Make Money in Commodities* (1960); modern EMA/ATR construction associated with Linda Bradford Raschke. Test close below lower channel then long; close above upper then short. Center-line close is native exit. No target. Initial stop 2×ATR(20) from fill is a declared placeholder.

## 2. EVERY PLACEHOLDER, PRE-DECIDED
EMA center 20, ATR Wilder 20, multiplier 2.0. Entry outside close; no requirement to re-enter channel; one position. Sweep multiplier 1.5/2/2.5; stop 1.5/2/2.5 ATR independent. Do not combine Keltner definitions.

## 3. STRATEGY-SPECIFIC LOOKAHEAD TRAPS
Use EMA/ATR available at close; signal fills next open. Center and bands are not shifted forward. Freeze risk ATR at signal time; no revised initial stop. Avoid using intrabar breach if rule is close-confirmed.

## 4. EXACT TEST MATRIX
- [ ] 3 coins × 1H/4H/1D; 20/20/2 headline.
- [ ] native centerline exit + forced 1:3.
- [ ] channel multiplier 1.5/2/2.5; stop 1.5/2/2.5 ATR independently.
- [ ] audits ×9, coverage/context, per-coin, exit-death, logs.

## 5. EXACT REPORT FORMAT
Use latest completed 15-section format: source/rule; definition/placeholder; audit; coverage; pooled table; exit composition; side split; exit-death; per coin; context; verdicts; sensitivities; costs; bottom line; limitations. Contrast with #5 breakout as distinct entry/exit hypothesis.

## 6. MISINTERPRETATION RISKS
Do not substitute #5's close-outside breakout entry. Do not enter on intrabar touch when the tested rule says close beyond channel. Centerline exit is next-open after close signal.

## 7–15. EXECUTOR LOCKS
Project defaults; warmup 250; stop=2ATR frozen at signal/fill convention; no TP. Independent sensitivity sweeps, no best-parameter selection. Funding/slippage excluded.