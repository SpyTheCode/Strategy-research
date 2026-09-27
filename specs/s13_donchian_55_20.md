# Strategy #13 SPEC — Turtle 55-day breakout, System 2

**Status:** proposed candidate; deliberately distinct from tested #7 System 1.

## 1. THE RULE — source and exact tested interpretation
**Source:** Curtis Faith, *Way of the Turtle* (2007), describing original Turtle System 2. Enter long on 55-day high breakout or short on 55-day low breakout; exit at opposite 20-day channel. Initial stop 2N where N=20-day ATR. No fixed profit target; no pyramiding in this project test.

## 2. EVERY PLACEHOLDER, PRE-DECIDED
Convert days to bars: 1H 24 bars/day, 4H 6, 1D 1. Entry uses prior 55 completed bars (exclude signal bar); exit uses prior 20 completed bars. N=20-day Wilder ATR converted to bars. Stop 2N fixed at entry. Sensitivity: entry 40/55/80 days, exit 10/20/30 days independently; stop 1.5/2/2.5N. Headline always 55/20/2N.

## 3. STRATEGY-SPECIFIC LOOKAHEAD TRAPS
Donchian extrema must be shifted one bar: today's high cannot set a breakout that today's close is tested against. Exit channel excludes current bar. N uses only past/current completed OHLC and is frozen at fill. Convert day windows by fixed mapping, never use calendar-future bars.

## 4. EXACT TEST MATRIX
- [ ] BTC/SOL/XRP × 1H/4H/1D; headline 55/20/2N.
- [ ] native opposite channel vs forced 1:3, shared same entry and initial risk.
- [ ] entry 40/55/80; exit 10/20/30; stop 1.5/2/2.5N independent sweeps.
- [ ] audit ×9; per-coin, context, coverage, exit-death; CSV 6 rows.

## 5. EXACT REPORT FORMAT
Latest completed report's 15 headings: source/rule; placeholders; lookahead; coverage; pooled results; exit mix/holding; long/short; exit-death; per-coin; context; verdict; sensitivities; fees/funding; bottom line; limitations. Explicitly compare #7 without combining results.

## 6. MISINTERPRETATION RISKS
Do not reuse #7's System 1 20-day entry/10-day exit or skip rule; this is System 2. Do not include current bar in channels. No pyramiding in this controlled test; call out departure from full Turtle portfolio rules.

## 7–15. EXECUTOR LOCKS
Project defaults; warmup = max(55-day bars + ATR warmup, 250); stop distance 2N at entry. No TP. Sensitivities are separate, no grid tuning. Funding unmodelled; append only after audit.