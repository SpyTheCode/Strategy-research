# Strategy #17 SPEC — directional movement/ADX system

**Status:** proposed candidate.

## 1. THE RULE — source and exact tested interpretation
**Source:** J. Welles Wilder Jr., *New Concepts in Technical Trading Systems* (1978), Directional Movement System. Buy +DI crossing above −DI with ADX>25; short opposite cross with ADX>25; native exit on opposite DI cross. No TP. Stop 2×ATR(14), project placeholder.

## 2. EVERY PLACEHOLDER, PRE-DECIDED
Wilder smoothing period 14 for TR/+DM/−DM/ADX; ADX threshold 25; stop 2ATR. Sensitivity ADX threshold 20/25/30; period 10/14/20; stop 1.5/2/2.5ATR independently.

## 3. STRATEGY-SPECIFIC LOOKAHEAD TRAPS
Directional movement compares current high/low with previous bar; ties make both +DM/−DM zero. Wilder smoothing initializes from first n values, then recursively updates. ADX has nested warmup; no backfilled full-series initialization. DI cross must be current/previous closed values.

## 4. EXACT TEST MATRIX
- [ ] BTC/SOL/XRP × 1H/4H/1D.
- [ ] period14, ADX>25, stop2ATR, native reverse DI; forced 1:3.
- [ ] periods 10/14/20; threshold 20/25/30; stop sweep independent.
- [ ] audit all nine; per coin, context, coverage, exit-death, log rows.

## 5. EXACT REPORT FORMAT
Use current completed report's 15 sections: source/rule; Wilder arithmetic; lookahead; coverage; results; exit composition; direction split; exit-death; per coin; context; verdict; sensitivity; fees/funding; bottom line; limits.

## 6. MISINTERPRETATION RISKS
ADX measures strength, not direction. Direction is DI ordering/cross. Avoid vendor libraries with inconsistent ADX seeding. State exact seed algorithm in report and tests.

## 7–15. EXECUTOR LOCKS
Project defaults; warmup 3×period+50; 2ATR stop; no target. No selecting threshold based on sample. Funding/slippage absent; append-only.