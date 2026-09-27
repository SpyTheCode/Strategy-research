# Strategy #10 SPEC — RSI(2) trend-filtered mean reversion (final)

**Status:** Final resolved execution contract; not owner approval to execute. Supersedes any prior #10 spec text. The unrun draft implementation at `src/s10_rsi2.py` informed the resolved rules below; neither that file nor `src/run_s10.py` is itself an authority if it conflicts with this contract.

## 1. THE RULE — exact tested interpretation and provenance

Use RSI(2), a 200-bar simple moving average trend filter, and a 2% fixed initial stop. On a closed bar `t`:

- Enter **long** if `close[t] > SMA200[t]` and `RSI2[t] < 10`.
- Enter **short** if `close[t] < SMA200[t]` and `RSI2[t] > 90`.
- Otherwise do not enter. Equality to either SMA or threshold does not qualify.
- Fill an entry at bar `t+1` open. At fill, set the fixed initial stop 2% from actual fill: long `entry × 0.98`; short `entry × 1.02`. This stop defines initial 1R.
- **Native exit:** after entry, close a long when RSI(2) on a completed bar is strictly greater than 70; close a short when RSI(2) is strictly less than 30. Queue the exit for the next bar open. The stop remains active. Do not reverse directly on an exit condition: any new position must arise from a later qualifying closed-bar entry signal, after the prior position has closed.
- No take-profit. No pyramiding; at most one open position per coin and timeframe. Long and short entries are both part of this resolved test.
- Also run the common forced-1:3 variant on the same entry definition and same initial stop: 1R stop, 3R target, 30-bar time limit, with shared engine stop-first intrabar tie handling, gap-through stop at open, and unresolved end-of-data trades discarded.

**Source/provenance:** The draft's Wilder-smoothed RSI(2), SMA200 trend filter, <10/>90 entry thresholds, >70/<30 RSI exits, and fixed 2% stop are the resolved tested interpretation requested here. Do not represent this combined long/short rule or its 2% stop as a single canonical Connors/Williams source rule: Connors' commonly cited RSI(2) pullback is long-only and uses a 5-day SMA exit; the short mirror, RSI exits, and fixed stop are this test's declared adaptations. The cited source family is Larry Connors, *Short Term Trading Strategies That Work* (2008), and Larry Williams, *Long-Term Secrets to Short-Term Trading* (1999). No source-specific performance claim is assumed.

## 2. EVERY PLACEHOLDER / ADAPTATION — PRE-DECIDED

- RSI: period 2, Wilder recursive smoothing (`alpha=1/2`, `adjust=False`), minimum two changes before a value. If average loss is zero and average gain positive, RSI=100; if both are zero, RSI=50. If average gain is zero and average loss positive, RSI=0 by the RSI formula.
- Trend: contemporaneous, unshifted 200-bar close SMA; strict close-above/below test.
- Entry thresholds: long RSI<10; short RSI>90. Native exit thresholds: long RSI>70; short RSI<30. All comparisons are strict.
- Initial stop: fixed 2.0% from actual next-open fill, project risk convention and not claimed source-authentic. No trailing or recalculation.
- Execution: closed-bar signals fill next open; taker fee 0.055% each side; risk 1% of starting equity per trade, not compounded.
- Position constraint: one position per coin/timeframe; no pyramiding or simultaneous long and short on the same coin/timeframe.
- Sensitivity sweeps, each independent of the headline and of one another: stop 1% / 2% / 3%; entry threshold pair (long oversold / short overbought) 5/95, 10/90, 15/85. Keep native RSI exit thresholds 70/30 fixed for all entry-threshold sweeps. Run all three timeframes and both exits for each variant. Do not select or replace the headline based on sweep results.
- Forced-1:3 30-bar limit is the project's shared unvalidated convention, not an RSI source parameter.

## 3. STRATEGY-SPECIFIC LOOKAHEAD TRAPS

Compute RSI only from close changes through the just-closed bar, causally and recursively; do not use centered windows or full-sample initialization. Compute SMA200 from the current and preceding 199 closes, without future shift. Entry conditions are evaluated only after bar close and filled next open; never use signal-bar high/low to decide entry. Native RSI exit is known only at close and fills next open; the fixed stop remains intrabar-active. Run the project's end-truncation audit by recomputing all indicators on truncated raw history and comparing every indicator value against full-history values at the truncation boundary; report each dataset pass/fail count.

## 4. EXACT TEST MATRIX

- [ ] BTCUSDT, SOLUSDT, XRPUSDT × 1H, 4H, 1D.
- [ ] Headline: long/short entries as Section 1, thresholds 10/90, native RSI exits 70/30, fixed 2% initial stop; native and forced 1:3.
- [ ] Independent stop sensitivity 1/2/3%; independent paired entry-threshold sensitivity 5/95, 10/90, 15/85; all timeframes and both exits.
- [ ] All nine coin/timeframe audit datasets, coverage, pooled-per-timeframe and per-coin results, long/short breakdown, concentration, funding disclosure, market-condition breakdown, exit-death/overlap, t-statistics, source comparison, explicit discard-bar verdicts.
- [ ] Headline log output only after execution is separately authorized and all required reporting is complete; CSV has six rows (3 timeframes × 2 exits). Sensitivity runs do not add headline CSV rows.

## 5. EXACT REPORT FORMAT — 15 required sections

Use these headings in this exact order, satisfying the requested standing report:

1. **Rule and source** — specify entries, initial stop, both exits and provenance before presenting numbers.
2. **Placeholders and adaptations** — list each value, source departure, and convention.
3. **Lookahead audit** — fresh all-nine truncation audit, pass/fail counts and any failures.
4. **Results table** — every timeframe and exit, pooled coins; trades, days per coin, win%, RR, pre/post-fee R, R/trade, Sharpe, max drawdown % and R, verdict.
5. **Statistical significance** — pre/post-fee t-statistics against approximately 2.0 noise threshold.
6. **Concentration** — percentage of return from best trade and best five trades.
7. **Long/short breakdown** — every applicable timeframe/exit cell.
8. **Exit-death and overlap** — entry overlap per timeframe; if below 85%, rerun comparison on shared entries only and report it.
9. **Funding** — holding time, settlements/trade, base-rate estimate and KEEP survival assessment; funding remains unmodelled in headline returns.
10. **Parameter sensitivity** — all declared independent stop and threshold variants, not only favorable results.
11. **Market conditions** — each cell split by the project's market-regime convention.
12. **Source comparison** — source's claimed numbers, if any, versus measured numbers; state unavailable claims plainly and discrepancies directly.
13. **Discard-bar verdicts** — explicit verdict and each criterion passed/failed for every timeframe/exit cell.
14. **Bottom line** — summarize results and what new evidence could change any inconclusive/provisional verdict.
15. **Files changed** — exact paths, line counts before/after, and confirmation nothing was deleted.

## 6. MISINTERPRETATION RISKS

Do not silently revert to the long-only, SMA5-exit source variant: this final spec intentionally includes the draft's short mirror and RSI 70/30 exits. Conversely, do not attribute those adaptations to the cited source as canonical. RSI level tests are not crossing-event tests: entry is a qualifying state on a closed bar; exit is a qualifying state on a later closed bar. Do not use RSI values formed with the entry fill bar's future close. Forced 1:3 is a diagnostic alternate exit, not the native RSI method.

## 7–15. EXECUTOR LOCKS

- Inherit `specs/README.md` project-wide setup: only BTCUSDT/SOLUSDT/XRPUSDT; 1H/4H/1D; taker 0.055% per side; 1% starting-equity risk per trade, not compounded; closed-bar decision / next-open fill; stop-first same-bar tie; gap-through stop at open; discard unresolved end-of-data trades; funding and slippage unmodelled in returns.
- Warmup: 201 bars before the first eligible signal (200 SMA needs 200 closes; RSI computation begins from prior close changes). Apply consistently to headline and every sweep.
- Do not optimize parameters or revise this contract after seeing results. Report negative and inconclusive outcomes as fully as positive outcomes.
- #19 and #21 remain excluded and are not involved in this strategy.
- No backtest, approval, or log append is authorized by this specification edit. Append logs only after separate explicit authorization and result review.