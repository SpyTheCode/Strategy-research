# Strategy #16 SPEC — Rate-of-change momentum

**Status:** proposed candidate.

## 1. THE RULE — source and exact tested interpretation
**Source:** Martin J. Pring, *Technical Analysis Explained*, momentum/ROC methods. ROC=(close/close[n]-1)×100; source literature does not settle universal entries/stops. Pinned test: enter long at positive ROC(20) crossing zero, short at negative cross; exit reverse zero cross. No TP. Stop 2×ATR(20) placeholder.

## 2. EVERY PLACEHOLDER, PRE-DECIDED
Lookback 20 bars; threshold 0; ATR20 stop 2×. Sensitivity ROC periods 10/20/50; stop 1.5/2/2.5 ATR. No trend filter, no smoothing.

## 3. STRATEGY-SPECIFIC LOOKAHEAD TRAPS
ROC denominator is exactly close t−n; never use future-indexed shift. Zero crossing requires prior/current values. Signals use closed data, next-open fills; freeze ATR at initial signal.

## 4. EXACT TEST MATRIX
- [ ] BTC/SOL/XRP × 1H/4H/1D; 20-bar headline.
- [ ] native reverse-cross and forced 1:3.
- [ ] ROC periods 10/20/50; stops 1.5/2/2.5ATR independent.
- [ ] audit ×9, per-coin/context/coverage/exit-death and logs.

## 5. EXACT REPORT FORMAT
Latest completed 15 headings: source/rule; pinned calculation; lookahead; coverage; pooled results; exit mix; long/short; exit-death; coin rows; context; verdicts; sensitivity; costs; bottom line; limitations.

## 6. MISINTERPRETATION RISKS
ROC level and ROC change are different indicators; use the defined percentage ROC. Do not enter repeatedly while positive—entry is a crossing event. No source-defined stop exists; state placeholder.

## 7–15. EXECUTOR LOCKS
Project defaults, 250 warmup, stop 2ATR, no TP, no parameter tuning. Funding/slippage omitted. Append only after auditing.