# Strategy #15 SPEC — CCI zero-line trend system

**Status:** proposed candidate.

## 1. THE RULE — source and exact tested interpretation
**Source:** Donald Lambert, “Commodity Channel Index: Tool for Trading Cyclical Trends,” *Commodities* (1980). CCI identifies cyclical extremes; it does not uniquely prescribe a universal crypto stop/exit. Pinned test: long when CCI(20) crosses above +100; short crossing below -100; native exit on opposite zero-line cross. No TP. Stop 2×ATR(20) at entry, project convention.

## 2. EVERY PLACEHOLDER, PRE-DECIDED
Typical price=(H+L+C)/3; SMA20 typical-price; mean deviation over 20; CCI divisor 0.015. Signal ±100 crossing, zero-cross exit. Stop 2 ATR20. Sensitivity entry threshold ±80/±100/±120; stop 1.5/2/2.5 ATR independently.

## 3. STRATEGY-SPECIFIC LOOKAHEAD TRAPS
Mean deviation is rolling absolute deviation from current window SMA, not full-sample mean. Crossings compare current and previous CCI. Do not evaluate current bar's high/low as pre-known. ATR frozen for initial stop.

## 4. EXACT TEST MATRIX
- [ ] BTC/SOL/XRP × 1H/4H/1D.
- [ ] CCI20 ±100 crossing, zero-cross native exit, 2ATR stop; native + forced 1:3.
- [ ] threshold 80/100/120; stop 1.5/2/2.5ATR independent.
- [ ] all audits, context, coverage, per-coin, exit-death, logs.

## 5. EXACT REPORT FORMAT
Latest report's 15 sections: source/rule; parameters; CCI audit traps; coverage; pooled results; exits; side split; exit-death; per coin; context; verdict; sensitivities; fees; bottom line; limitations.

## 6. MISINTERPRETATION RISKS
CCI ±100 extreme cross entry is this spec's declared implementation, not a source-mandated standalone strategy. Do not call a mere CCI level state a crossing. Do not claim stop/exit sourced from Lambert.

## 7–15. EXECUTOR LOCKS
Use project defaults, 250-bar warmup. No TP. Keep test adaptation distinctions prominent and sensitivity independent. Append only after all checks.