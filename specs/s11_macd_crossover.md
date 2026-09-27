# Strategy #11 SPEC — MACD line/signal crossover

**Status:** proposed candidate; pinned conventional implementation.

## 1. THE RULE — source and exact tested interpretation
**Source:** Gerald Appel, *The Moving Average Convergence-Divergence Trading Method* (1979). MACD line is 12-EMA minus 26-EMA; signal is 9-EMA of MACD. Source literature describes MACD/signal crossovers but does not define a universal crypto stop/exit. Test long when MACD crosses above signal and close>200-SMA; short on reverse cross and close<200-SMA. Native exit on opposite MACD/signal cross; no separate TP. Initial stop is 2×ATR(14) from next-open fill, project placeholder.

## 2. EVERY PLACEHOLDER, PRE-DECIDED
EMA spans 12/26/9; trend filter 200-SMA; ATR Wilder 14; stop 2 ATR; one position/coin, no pyramiding. Sweep stop 1.5/2/2.5 ATR; MACD fast/slow alternate 8/21 and 12/26 only; 9 signal fixed.

## 3. STRATEGY-SPECIFIC LOOKAHEAD TRAPS
EMA and MACD are recursive causal values; crossover must compare current and prior closed-bar states. Do not use an indicator library that centers/filter-shifts values. ATR stop distance is captured from signal bar and translated to fill price only if specified as absolute signal ATR; freeze stop distance at signal close. No future ATR recalculation for initial stop.

## 4. EXACT TEST MATRIX
- [ ] BTCUSDT/SOLUSDT/XRPUSDT × 1H/4H/1D.
- [ ] Headline 12/26/9, 200-SMA, 2ATR; native + forced 1:3.
- [ ] Stop 1.5/2/2.5ATR; fast/slow pair 8/21 vs 12/26 (signal 9).
- [ ] Audits ×9, context, coverage, per-coin signs, exit-death, both exit CSV rows per timeframe.

## 5. EXACT REPORT FORMAT
Use latest completed report's 15-section heading set, in order: source/rule; placeholders; lookahead audit; coverage; pooled results; exit/holding composition; direction split; exit-death; per-coin; context/fairness; verdict; sensitivities; costs; bottom line; limits. Include the full matrix and exact source-vs-adaptation statement.

## 6. MISINTERPRETATION RISKS
MACD cross is not equivalent to MACD histogram crossing zero when a nonstandard signal line is used. Do not enter at crossover close; fill next open. Avoid look-ahead by not plotting-shifting for visual alignment.

## 7–15. EXECUTOR LOCKS
Use project defaults in `specs/README.md`; warmup 250 bars; ATR stop risk measured as actual fill-to-stop distance. No TP. Run each sensitivity independently, never optimize. Report no funding/slippage as modelled; append only after checks pass.