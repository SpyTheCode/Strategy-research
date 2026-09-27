# Strategy #18 SPEC — Donchian failed-break reversion

**Status:** proposed candidate; distinct from #7 Turtle breakout.

## 1. THE RULE — source and exact tested interpretation
**Source:** Richard Donchian, channel trading methodology as described in *Futures: An Investor's Guide to Trading Financial Futures* (1981); the failed-break reversion is this spec's explicit adaptation, not claimed as his canonical system. Enter short when close breaks above prior 20-bar high then closes back inside within 3 bars; long mirror below prior low and close back inside. Native exit at channel midpoint; no TP. Stop 1×20-bar channel width beyond fill, placeholder.

## 2. EVERY PLACEHOLDER, PRE-DECIDED
Channel 20, failure window 3 bars, midpoint exit; stop distance=prior channel width, fixed at signal; one position. Sweep channel 10/20/55; failure window 1/3/5; stop width 0.5/1/1.5 independently.

## 3. STRATEGY-SPECIFIC LOOKAHEAD TRAPS
Channel high/low excludes current bar; initial breakout and re-entry sequence state must be updated strictly forward. Store breakout direction and bar index; expire after exactly 3 subsequent completed bars; do not retrospectively detect future failure. Signal close re-entry fills next open.

## 4. EXACT TEST MATRIX
- [ ] BTC/SOL/XRP × 1H/4H/1D.
- [ ] N20, 3-bar failure, 1 channel-width stop; native midpoint + forced 1:3.
- [ ] N10/20/55; window1/3/5; stop .5/1/1.5 width independent.
- [ ] audit ×9; context, coverage, sides, coin signs, exit-death, logs.

## 5. EXACT REPORT FORMAT
Latest 15-section format: source versus adaptation; exact state machine; lookahead; coverage; pooled results; exits/holds; side split; exit-death; coin rows; context; verdicts; sensitivities; costs; conclusion; limitations.

## 6. MISINTERPRETATION RISKS
This is not a Donchian breakout. Must not count a close beyond channel as immediate reversion entry. Stop width is frozen; target is none. A signal is one event per breakout episode, not every bar outside.

## 7–15. EXECUTOR LOCKS
Project matrix/defaults; warmup 250; no TP; declare source adaptation. Independent sweeps only. Append logs after successful state-machine audit.