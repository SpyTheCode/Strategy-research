# Strategy log

Plain-English write-up of every strategy tested, one section per strategy per
exit type. Append-only: nothing is edited or removed once written, including
results that failed, because a record of what did *not* work is the main output
of this project.

Every money figure in this file is **after Bybit fees** unless a line explicitly
says "pre-fee". Fees applied: taker 0.055% on entry and on exit (maker 0.02% is
used only where a strategy genuinely rests a limit order).

## How to read a section

- **Native exit** — the exit the original source actually describes.
- **Forced 1:3** — the same entry, but exited by a fixed 1-risk-unit stop, a
  3-risk-unit target, and a time limit, whichever comes first.
- **R** — one R is the money risked between entry and the initial stop. +3R means
  a win three times the size of the planned loss. Using R instead of dollars lets
  a $50 trade and a $5,000 trade be compared on the same scale.
- **Exit-death flag** — `yes` when the two exit styles disagree so strongly that
  the strategy's result is decided by its exit rules rather than by its entry
  signal.
- **Verdict** — KEEP / DISCARD / INCONCLUSIVE, from the fixed discard bar. Each
  exit variant is judged on its own and the two verdicts are never merged.

## Test setup used for every strategy

| Item | Value |
|---|---|
| Data source | Bybit v5 public market API (`/v5/market/kline`, category=linear), cached to Parquet |
| Coins | BTCUSDT (large-cap trend), SOLUSDT (high-beta alt), XRPUSDT (chop/range) |
| Timeframes | 1H, 4H, 1D |
| Fees | taker 0.055% per side; maker 0.02% only where a limit order genuinely rests |
| Position sizing | 1% of starting equity risked per trade, never compounded |
| Fill rule | a signal from a closed bar fills at the **next** bar's open |
| Intrabar tie | if one candle contains both stop and target, the **stop** is assumed hit first |
| Gap rule | a bar opening beyond the stop fills at that open, not at the stop |
| Forced-1:3 time limit | 30 bars — **PLACEHOLDER, not a validated optimum** (see below) |
| Unfinished trades | a position still open when the data ends is discarded, not valued at the last price |
| Not modelled | funding payments (charged every 8h on perps) and slippage — see caveat below |

## Placeholder values — flagged, not proven

Some numbers in this project are conventions chosen to get a test running, not
values shown by evidence to be correct. They are listed here and re-flagged in
every write-up that depends on them, so that no result is ever read as more
settled than it is.

| Placeholder | Value used | Status |
|---|---|---|
| Forced-1:3 time limit | 30 bars (~1.25 days on 1H, ~5 days on 4H, ~1 month on 1D) | **Unvalidated placeholder.** Approved as a starting convention, explicitly not a proven optimum. Chosen so the holding horizon scales with the chart rather than being one fixed number that is absurd on two of three timeframes. Never tuned, never optimised. If a strategy's verdict turns out to hinge on it, that is stated in that strategy's write-up. |

Any strategy-specific placeholder (an undisclosed stop-loss percentage, an
indicator length the source kept behind a paywall) is flagged the same way inside
that strategy's own section.

## Funding cost — standing rule

Funding is charged or paid every 8 hours on Bybit perpetuals and is **not
modelled** anywhere in this project. For strategies that close out within a bar
or two this is a rounding error. For strategies that hold for multiple days it is
a real, recurring cost that these results do not contain.

Affected strategies are flagged individually in their write-ups. Expected to be
affected: Dual Momentum, TSMOM, Crabel's stretch, and any other multi-day holder.

**The rule:** if a multi-day-holding strategy earns a KEEP, that KEEP is
**provisional and must not be treated as final**. Work stops there and the
missing funding cost is raised for review first, because on a multi-day hold it
is large enough to change the verdict.

## The discard bar (approved, applied unchanged from here on)

Judged separately for each exit variant. The two verdicts are never merged.

**Gate:** fewer than 30 trades → INCONCLUSIVE, whatever the numbers say.

**KEEP requires all four:**
1. Post-fee expectancy ≥ **+0.10R** per trade.
2. Post-fee Sharpe ≥ **0.70**.
3. Total post-fee R ≥ **1.5×** the worst drawdown measured in R.
4. Reward test, matched to the exit: *forced-1:3* — win rate ≥ its own measured
   fee breakeven `(1+c)/4` **plus 2 percentage points**, where `c` is that run's
   average round-trip fee in R; *native* — average winner ≥ **1.5×** average loser.

**DISCARD on any one of:**
1. Post-fee expectancy ≤ **0.00R**.
2. Post-fee Sharpe < **0.30**.
3. Total post-fee R < **0.5×** worst R drawdown.

**Anything else → INCONCLUSIVE** ("not proven either way", never "failed").

Validated before use against deliberately meaningless coin-flip entries on all
nine data sets: 8 of 9 runs returned DISCARD, and the one run that got lucky
(+0.213R per trade) was correctly held at INCONCLUSIVE by the Sharpe test (0.36)
and the drawdown test (1.01×). No coin flip could reach KEEP.


**Excluded cost caveat.** The fee schedule supplied for this project covers
exchange commission only. Bybit perpetuals also charge or pay funding every 8
hours, and real fills slip. Neither is invented here. For strategies that hold
positions for many hours or days, funding is a real cost that these results do
not contain, and that is stated again in each affected write-up.

---

# Excluded by design (not tested)

These two were found during the research step and are deliberately left out of
the backtest loop, not discarded on evidence. They are recorded here so the
research list stays complete.

### #19 Funding-rate arbitrage
A market-neutral carry trade: hold spot, short the perpetual, and collect the
funding payment. It has no directional stop and no reward-to-risk ratio in the
sense this project uses, because there is no directional risk being taken — the
profit is a stream of small funding payments, not a win several times the size of
a planned loss. There is nothing for a 1:3 test to measure. **Status: excluded by
design, untested.**

### #21 RSI(2) mean reversion
Buys extreme short-term oversold readings and exits on a small bounce. Its
documented edge is the mirror image of what this project is looking for: a high
win rate paired with a reward far *smaller* than the risk, and occasional large
losses. Forcing a 3-risk-unit target onto it would not be a fair test of the
strategy, it would be a different strategy. **Status: excluded by design,
untested.**

---
---

# Master verdict index - every cell this project has ever scored

One row per strategy x timeframe x exit variant. Nothing is merged, averaged or
re-judged: every number below is copied from that strategy's own results table and
every verdict is the one the fixed discard bar returned. Eight strategies, **58
cells** - the complete decision universe, KEEP and INCONCLUSIVE and DISCARD together.

Coverage is the **shortest coin window** in each pooled run, which is the binding
floor rather than the average. Bitcoin's history on this venue begins March 2020,
XRP May 2021, Solana October 2021, so a pooled row is never three equal thirds.
Every money figure is **post-fee**. `t` is the post-fee t-statistic - the average
trade divided by its own standard error; below about 2 the average sits inside the
range random noise would produce anyway.

Strategy #8 was run three times (2026-09-05, 2026-09-12, 2026-09-22) as the rule was
rebuilt; the rows below are the **final** run, and the two earlier runs are preserved
unchanged further down. Strategy #4's 1D forced-1:3 t-statistic is -3325.97 because
every one of its 2095 trades resolved identically (0.0% win rate) and the standard
error is effectively zero - a degenerate cell, not a typo.

## The decision universe

| Strategy | TF | Exit | Trades | Coverage (yr) | R/trade | Sharpe | R-recovery | RR | t | Verdict | Primary reason |
|---|---|---|---|---|---|---|---|---|---|---|---|
| #1 Bollinger Band Reversion (short only) | 1H | native | 1054 | 4.87 | -0.046 | -0.39 | -0.59 | 1.17 | -1.17 | **DISCARD** | post-fee expectancy -0.046R is not positive |
| #1 Bollinger Band Reversion (short only) | 1H | forced-1:3 | 1054 | 4.87 | -0.002 | -0.02 | -0.04 | 1.57 | -0.05 | **DISCARD** | post-fee expectancy -0.002R is not positive |
| #1 Bollinger Band Reversion (short only) | 4H | native | 290 | 4.80 | -0.230 | -0.80 | -0.99 | 2.66 | -2.30 | **DISCARD** | post-fee expectancy -0.230R is not positive |
| #1 Bollinger Band Reversion (short only) | 4H | forced-1:3 | 294 | 4.80 | -0.126 | -0.47 | -1.03 | 2.36 | -1.34 | **DISCARD** | post-fee expectancy -0.126R is not positive |
| #1 Bollinger Band Reversion (short only) | 1D | native | 57 | 4.34 | -0.206 | -0.18 | -0.45 | 8.17 | -0.50 | **DISCARD** | post-fee expectancy -0.206R is not positive |
| #1 Bollinger Band Reversion (short only) | 1D | forced-1:3 | 61 | 4.34 | -0.334 | -0.69 | -0.97 | 2.79 | -1.68 | **DISCARD** | post-fee expectancy -0.334R is not positive |
| #2 Dual Momentum (absolute leg + Bitcoin switch) | 1H | native | 123 | 4.80 | +0.971 | 0.62 | 6.39 | 5.33 | +1.83 | **INCONCLUSIVE** | Sharpe 0.62 < 0.70 |
| #2 Dual Momentum (absolute leg + Bitcoin switch) | 1H | forced-1:3 | 357 | 4.80 | +0.014 | 0.18 | 0.65 | 1.06 | +0.58 | **DISCARD** | post-fee Sharpe 0.18 < 0.30 |
| #2 Dual Momentum (absolute leg + Bitcoin switch) | 4H | native | 134 | 4.80 | +0.859 | 0.58 | 5.03 | 4.67 | +1.70 | **INCONCLUSIVE** | Sharpe 0.58 < 0.70 |
| #2 Dual Momentum (absolute leg + Bitcoin switch) | 4H | forced-1:3 | 360 | 4.80 | +0.074 | 0.52 | 1.41 | 1.45 | +1.58 | **INCONCLUSIVE** | expectancy +0.074R < +0.10R; Sharpe 0.52 < 0.70; recovery 1.41 < 1.50 |
| #2 Dual Momentum (absolute leg + Bitcoin switch) | 1D | native | 141 | 4.56 | +0.807 | 0.67 | 5.43 | 4.56 | +1.80 | **INCONCLUSIVE** | Sharpe 0.67 < 0.70 |
| #2 Dual Momentum (absolute leg + Bitcoin switch) | 1D | forced-1:3 | 163 | 4.56 | +0.144 | 0.47 | 1.15 | 1.98 | +1.19 | **INCONCLUSIVE** | Sharpe 0.47 < 0.70; recovery 1.15 < 1.50 |
| #3 AdaptiveTrend (momentum + monthly Sharpe gate + ATR trail) | 1H | native | 702 | 4.79 | +0.090 | 0.46 | 0.84 | 2.13 | +1.20 | **INCONCLUSIVE** | expectancy +0.090R < +0.10R; Sharpe 0.46 < 0.70; recovery 0.84 < 1.50 |
| #3 AdaptiveTrend (momentum + monthly Sharpe gate + ATR trail) | 1H | forced-1:3 | 672 | 4.79 | -0.023 | -0.18 | -0.22 | 1.30 | -0.49 | **DISCARD** | post-fee expectancy -0.023R is not positive |
| #3 AdaptiveTrend (momentum + monthly Sharpe gate + ATR trail) | 4H | native | 389 | 4.79 | +0.098 | 0.38 | 1.32 | 2.11 | +1.15 | **INCONCLUSIVE** | expectancy +0.098R < +0.10R; Sharpe 0.38 < 0.70; recovery 1.32 < 1.50 |
| #3 AdaptiveTrend (momentum + monthly Sharpe gate + ATR trail) | 4H | forced-1:3 | 352 | 4.79 | -0.030 | -0.17 | -0.25 | 1.52 | -0.44 | **DISCARD** | post-fee expectancy -0.030R is not positive |
| #3 AdaptiveTrend (momentum + monthly Sharpe gate + ATR trail) | 6H | native | 317 | 4.79 | +0.077 | 0.35 | 0.91 | 1.95 | +0.89 | **INCONCLUSIVE** | expectancy +0.077R < +0.10R; Sharpe 0.35 < 0.70; recovery 0.91 < 1.50 |
| #3 AdaptiveTrend (momentum + monthly Sharpe gate + ATR trail) | 6H | forced-1:3 | 279 | 4.79 | +0.044 | 0.21 | 0.51 | 1.57 | +0.57 | **DISCARD** | post-fee Sharpe 0.21 < 0.30 |
| #3 AdaptiveTrend (momentum + monthly Sharpe gate + ATR trail) | 1D | native | 154 | 4.56 | +0.060 | 0.15 | 0.52 | 2.34 | +0.48 | **DISCARD** | post-fee Sharpe 0.15 < 0.30 |
| #3 AdaptiveTrend (momentum + monthly Sharpe gate + ATR trail) | 1D | forced-1:3 | 131 | 4.56 | +0.027 | 0.09 | 0.18 | 1.45 | +0.24 | **DISCARD** | post-fee Sharpe 0.09 < 0.30; recovery 0.18 < 0.50 |
| #4 Crabel Opening Range Breakout ("the stretch") | 1H | native | 2251 | 4.84 | +0.033 | 0.48 | 2.49 | 1.44 | +1.48 | **INCONCLUSIVE** | expectancy +0.033R < +0.10R; Sharpe 0.48 < 0.70; RR 1.44 < 1.50 |
| #4 Crabel Opening Range Breakout ("the stretch") | 1H | forced-1:3 | 1595 | 4.84 | -0.013 | -0.16 | -0.34 | 1.37 | -0.48 | **DISCARD** | post-fee expectancy -0.013R is not positive |
| #4 Crabel Opening Range Breakout ("the stretch") | 4H | native | 2244 | 4.83 | +0.037 | 0.55 | 2.85 | 1.46 | +1.70 | **INCONCLUSIVE** | expectancy +0.037R < +0.10R; Sharpe 0.55 < 0.70; RR 1.46 < 1.50 |
| #4 Crabel Opening Range Breakout ("the stretch") | 4H | forced-1:3 | 1253 | 4.83 | -0.166 | -1.47 | -0.97 | 1.78 | -4.18 | **DISCARD** | post-fee expectancy -0.166R is not positive |
| #4 Crabel Opening Range Breakout ("the stretch") | 6H | native | 2232 | 4.81 | +0.039 | 0.57 | 2.93 | 1.47 | +1.75 | **INCONCLUSIVE** | expectancy +0.039R < +0.10R; Sharpe 0.57 < 0.70; RR 1.47 < 1.50 |
| #4 Crabel Opening Range Breakout ("the stretch") | 6H | forced-1:3 | 1221 | 4.81 | -0.341 | -2.98 | -0.99 | 2.01 | -8.52 | **DISCARD** | post-fee expectancy -0.341R is not positive |
| #4 Crabel Opening Range Breakout ("the stretch") | 1D | native | 2094 | 4.56 | +0.071 | 1.03 | 5.60 | 1.62 | +3.14 | **INCONCLUSIVE** | expectancy +0.071R < +0.10R - the ONLY gate it misses |
| #4 Crabel Opening Range Breakout ("the stretch") | 1D | forced-1:3 | 2095 | 4.56 | -1.031 | -17.18 | -1.00 | n/a (0.0% win) | -3325.97 | **DISCARD** | post-fee expectancy -1.031R is not positive; every trade identical |
| #5 Keltner Channel breakout | 1H | native | 5745 | 4.87 | -0.054 | -1.92 | -0.88 | 1.97 | -6.24 | **DISCARD** | post-fee expectancy -0.054R is not positive |
| #5 Keltner Channel breakout | 1H | forced-1:3 | 3239 | 4.87 | +0.018 | 0.24 | 0.79 | 1.70 | +0.74 | **DISCARD** | post-fee Sharpe 0.24 < 0.30 |
| #5 Keltner Channel breakout | 4H | native | 1482 | 4.82 | +0.011 | 0.22 | 0.94 | 2.25 | +0.66 | **DISCARD** | post-fee Sharpe 0.22 < 0.30 |
| #5 Keltner Channel breakout | 4H | forced-1:3 | 832 | 4.82 | +0.107 | 0.72 | 3.34 | 1.76 | +2.11 | **KEEP** | clears every gate; PROVISIONAL - funding at base rate takes +0.107R to +0.088R |
| #5 Keltner Channel breakout | 6H | native | 961 | 4.79 | +0.046 | 0.70 | 3.61 | 2.48 | +1.93 | **INCONCLUSIVE** | expectancy +0.046R < +0.10R; Sharpe 0.70 < 0.70 |
| #5 Keltner Channel breakout | 6H | forced-1:3 | 570 | 4.79 | +0.078 | 0.47 | 1.62 | 1.82 | +1.29 | **INCONCLUSIVE** | expectancy +0.078R < +0.10R; Sharpe 0.47 < 0.70 |
| #5 Keltner Channel breakout | 1D | native | 218 | 4.48 | +0.154 | 0.86 | 6.12 | 3.20 | +2.17 | **KEEP** | clears every gate; survives funding at base rate (+0.147R) |
| #5 Keltner Channel breakout | 1D | forced-1:3 | 127 | 4.48 | +0.118 | 0.34 | 0.92 | 2.20 | +0.87 | **INCONCLUSIVE** | Sharpe 0.34 < 0.70; recovery 0.92 < 1.50 |
| #6 Ichimoku Cloud trend trading | 1H | native | 3843 | 4.87 | +0.118 | 0.42 | 1.70 | 3.72 | +1.16 | **INCONCLUSIVE** | Sharpe 0.42 < 0.70 |
| #6 Ichimoku Cloud trend trading | 1H | forced-1:3 | 4670 | 4.87 | -0.046 | -0.74 | -0.66 | 1.62 | -2.18 | **DISCARD** | post-fee expectancy -0.046R is not positive |
| #6 Ichimoku Cloud trend trading | 4H | native | 902 | 4.82 | +0.300 | 0.81 | 4.86 | 3.72 | +2.13 | **KEEP** | clears every gate; PROVISIONAL - funding at base rate takes +0.300R to +0.247R |
| #6 Ichimoku Cloud trend trading | 4H | forced-1:3 | 1122 | 4.82 | +0.095 | 0.77 | 3.41 | 1.76 | +2.16 | **INCONCLUSIVE** | expectancy +0.095R < +0.10R - the ONLY gate it misses |
| #6 Ichimoku Cloud trend trading | 6H | native | 594 | 4.79 | +0.317 | 0.64 | 3.74 | 4.22 | +1.61 | **INCONCLUSIVE** | Sharpe 0.64 < 0.70 |
| #6 Ichimoku Cloud trend trading | 6H | forced-1:3 | 745 | 4.79 | +0.064 | 0.45 | 1.40 | 1.73 | +1.22 | **INCONCLUSIVE** | expectancy +0.064R < +0.10R; Sharpe 0.45 < 0.70; recovery 1.40 < 1.50 |
| #6 Ichimoku Cloud trend trading | 1D | native | 144 | 4.48 | +1.027 | 0.59 | 5.79 | 7.25 | +1.47 | **INCONCLUSIVE** | Sharpe 0.59 < 0.70 |
| #6 Ichimoku Cloud trend trading | 1D | forced-1:3 | 182 | 4.48 | +0.051 | 0.19 | 0.41 | 1.96 | +0.46 | **DISCARD** | post-fee Sharpe 0.19 < 0.30; recovery 0.41 < 0.50 |
| #7 Turtle/Donchian 20-day breakout (System 1, no pyramiding) | 1H | native | 237 | 4.83 | +0.444 | 0.80 | 6.85 | 3.66 | +2.04 | **KEEP** | clears every gate; PROVISIONAL - funding at base rate takes +0.444R to +0.399R |
| #7 Turtle/Donchian 20-day breakout (System 1, no pyramiding) | 1H | forced-1:3 | 624 | 4.83 | +0.098 | 1.16 | 7.02 | 1.55 | +3.54 | **INCONCLUSIVE** | expectancy +0.098R < +0.10R - the ONLY gate it misses |
| #7 Turtle/Donchian 20-day breakout (System 1, no pyramiding) | 4H | native | 220 | 4.83 | +0.550 | 0.75 | 9.21 | 3.79 | +1.87 | **KEEP** | clears every gate; PROVISIONAL - funding at base rate takes +0.550R to +0.503R |
| #7 Turtle/Donchian 20-day breakout (System 1, no pyramiding) | 4H | forced-1:3 | 386 | 4.83 | +0.144 | 0.96 | 5.28 | 1.65 | +2.67 | **KEEP** | clears every gate; PROVISIONAL - funding at base rate takes +0.144R to +0.130R |
| #7 Turtle/Donchian 20-day breakout (System 1, no pyramiding) | 6H | native | 219 | 4.81 | +0.509 | 0.70 | 9.10 | 3.83 | +1.75 | **INCONCLUSIVE** | Sharpe 0.70 < 0.70 - the ONLY gate it misses |
| #7 Turtle/Donchian 20-day breakout (System 1, no pyramiding) | 6H | forced-1:3 | 340 | 4.81 | +0.198 | 1.12 | 5.80 | 1.74 | +3.05 | **KEEP** | clears every gate; PROVISIONAL - funding at base rate takes +0.198R to +0.180R |
| #7 Turtle/Donchian 20-day breakout (System 1, no pyramiding) | 1D | native | 188 | 4.56 | +0.537 | 0.69 | 8.49 | 3.48 | +1.67 | **INCONCLUSIVE** | Sharpe 0.69 < 0.70 - the ONLY gate it misses |
| #7 Turtle/Donchian 20-day breakout (System 1, no pyramiding) | 1D | forced-1:3 | 208 | 4.56 | +0.182 | 0.62 | 2.27 | 2.06 | +1.65 | **INCONCLUSIVE** | Sharpe 0.62 < 0.70 - the ONLY gate it misses |
| #8 Supertrend (10, 3) | 1H | native | 3394 | 4.88 | +0.222 | 0.69 | 3.07 | 2.07 | +2.12 | **INCONCLUSIVE** | Sharpe 0.69 < 0.70 - the ONLY gate it misses |
| #8 Supertrend (10, 3) | 1H | forced-1:3 | 3346 | 4.88 | -0.123 | -1.40 | -0.93 | 2.24 | -4.22 | **DISCARD** | post-fee expectancy -0.123R is not positive |
| #8 Supertrend (10, 3) | 4H | native | 850 | 4.87 | +0.798 | 0.89 | 9.20 | 2.66 | +2.40 | **KEEP** | clears every gate; survives funding at base rate (+0.691R) |
| #8 Supertrend (10, 3) | 4H | forced-1:3 | 841 | 4.87 | +0.037 | 0.21 | 0.71 | 2.44 | +0.63 | **DISCARD** | post-fee Sharpe 0.21 < 0.30 |
| #8 Supertrend (10, 3) | 1D | native | 139 | 4.75 | +2.145 | 0.62 | 5.31 | 4.73 | +1.57 | **INCONCLUSIVE** | Sharpe 0.62 < 0.70 - the ONLY gate it misses |
| #8 Supertrend (10, 3) | 1D | forced-1:3 | 140 | 4.75 | +0.210 | 0.53 | 2.92 | 2.75 | +1.36 | **INCONCLUSIVE** | Sharpe 0.53 < 0.70 - the ONLY gate it misses |


## Verdict counts

| Verdict | Cells | Share | Strategies with at least one |
|---|---|---|---|
| **KEEP** | 8 | 13.8% | #5 (2), #6 (1), #7 (4), #8 (1) |
| **INCONCLUSIVE** | 27 | 46.6% | #2, #3, #4, #5, #6, #7, #8 |
| **DISCARD** | 23 | 39.7% | #1, #2, #3, #4, #5, #6, #8 |
| **Total** | **58** | 100% | 8 strategies |

The count reconciles with the row count above: 58 cells. Two strategies hold the
extremes - **#1 is the only strategy with zero non-DISCARD cells** (all six fail),
and **#7 is the only strategy with zero DISCARD cells** (four KEEP, four
INCONCLUSIVE). No strategy earned a KEEP on a forced-1:3 exit alone without also
having a positive native exit; #5's 4H forced-1:3 is the closest thing, and it is
provisional on funding.

## Gate evidence for the 50 non-KEEP cells

KEEP needs: 30+ trades, expectancy >= +0.10R, Sharpe >= 0.70, R-recovery >= 1.50,
and (native) achieved RR >= 1.50 or (forced-1:3) win rate >= its own fee-breakeven
+ 2pp. DISCARD is **any one** of: expectancy <= +0.00R, Sharpe < 0.30, R-recovery
< 0.50. A cell that clears every DISCARD floor but misses any KEEP floor is
INCONCLUSIVE - it is positive evidence that is not yet strong enough to act on.

**The 23 DISCARD cells** - the first DISCARD gate each one trips:

| # | Strategy | TF / Exit | Failing metric | Actual | Discard gate | Result | Also failing |
|---|---|---|---|---|---|---|---|
| 1 | #1 | 1H native | expectancy | -0.046R | > +0.00R | FAIL | Sharpe -0.39 < 0.30; recovery -0.59 < 0.50 |
| 2 | #1 | 1H forced-1:3 | expectancy | -0.002R | > +0.00R | FAIL | Sharpe -0.02 < 0.30; recovery -0.04 < 0.50 |
| 3 | #1 | 4H native | expectancy | -0.230R | > +0.00R | FAIL | Sharpe -0.80 < 0.30; recovery -0.99 < 0.50 |
| 4 | #1 | 4H forced-1:3 | expectancy | -0.126R | > +0.00R | FAIL | Sharpe -0.47 < 0.30; recovery -1.03 < 0.50 |
| 5 | #1 | 1D native | expectancy | -0.206R | > +0.00R | FAIL | Sharpe -0.18 < 0.30; recovery -0.45 < 0.50 |
| 6 | #1 | 1D forced-1:3 | expectancy | -0.334R | > +0.00R | FAIL | Sharpe -0.69 < 0.30; recovery -0.97 < 0.50 |
| 7 | #2 | 1H forced-1:3 | Sharpe | 0.18 | >= 0.30 | FAIL | none - expectancy +0.014R and recovery 0.79 both clear their floors |
| 8 | #3 | 1H forced-1:3 | expectancy | -0.023R | > +0.00R | FAIL | Sharpe -0.18 < 0.30; recovery -0.22 < 0.50 |
| 9 | #3 | 4H forced-1:3 | expectancy | -0.030R | > +0.00R | FAIL | Sharpe -0.17 < 0.30; recovery -0.25 < 0.50 |
| 10 | #3 | 6H forced-1:3 | Sharpe | 0.21 | >= 0.30 | FAIL | none - expectancy +0.044R and recovery 0.51 both clear their floors |
| 11 | #3 | 1D native | Sharpe | 0.15 | >= 0.30 | FAIL | none - expectancy +0.060R and recovery 0.52 both clear their floors |
| 12 | #3 | 1D forced-1:3 | Sharpe | 0.09 | >= 0.30 | FAIL | recovery 0.18 < 0.50 |
| 13 | #4 | 1H forced-1:3 | expectancy | -0.013R | > +0.00R | FAIL | Sharpe -0.16 < 0.30; recovery -0.34 < 0.50 |
| 14 | #4 | 4H forced-1:3 | expectancy | -0.166R | > +0.00R | FAIL | Sharpe -1.47 < 0.30; recovery -0.97 < 0.50 |
| 15 | #4 | 6H forced-1:3 | expectancy | -0.341R | > +0.00R | FAIL | Sharpe -2.98 < 0.30; recovery -0.99 < 0.50 |
| 16 | #4 | 1D forced-1:3 | expectancy | -1.031R | > +0.00R | FAIL | Sharpe -17.18 < 0.30; recovery -1.00 < 0.50 |
| 17 | #5 | 1H native | expectancy | -0.054R | > +0.00R | FAIL | Sharpe -1.92 < 0.30; recovery -0.88 < 0.50 |
| 18 | #5 | 1H forced-1:3 | Sharpe | 0.24 | >= 0.30 | FAIL | none - expectancy +0.018R and recovery 0.79 both clear their floors |
| 19 | #5 | 4H native | Sharpe | 0.22 | >= 0.30 | FAIL | none - expectancy +0.011R and recovery 0.94 both clear their floors |
| 20 | #6 | 1H forced-1:3 | expectancy | -0.046R | > +0.00R | FAIL | Sharpe -0.74 < 0.30; recovery -0.66 < 0.50 |
| 21 | #6 | 1D forced-1:3 | Sharpe | 0.19 | >= 0.30 | FAIL | recovery 0.41 < 0.50 |
| 22 | #8 | 1H forced-1:3 | expectancy | -0.123R | > +0.00R | FAIL | Sharpe -1.40 < 0.30; recovery -0.93 < 0.50 |
| 23 | #8 | 4H forced-1:3 | Sharpe | 0.21 | >= 0.30 | FAIL | none - expectancy +0.037R and recovery 0.71 both clear their floors |

**The 27 INCONCLUSIVE cells** - the KEEP gate each one misses:

| # | Strategy | TF / Exit | Missed gate | Actual | KEEP gate | Result | Also missing |
|---|---|---|---|---|---|---|---|
| 1 | #2 | 1H native | Sharpe | 0.62 | >= 0.70 | FAIL | none - expectancy +0.971R, recovery 6.39, RR 5.33 all pass |
| 2 | #2 | 4H native | Sharpe | 0.58 | >= 0.70 | FAIL | none - expectancy +0.859R, recovery 5.03, RR 4.67 all pass |
| 3 | #2 | 4H forced-1:3 | expectancy | +0.074R | >= +0.10R | FAIL | Sharpe 0.52 < 0.70; recovery 1.41 < 1.50 |
| 4 | #2 | 1D native | Sharpe | 0.67 | >= 0.70 | FAIL | none - expectancy +0.807R, recovery 5.43, RR 4.56 all pass |
| 5 | #2 | 1D forced-1:3 | Sharpe | 0.47 | >= 0.70 | FAIL | recovery 1.15 < 1.50 |
| 6 | #3 | 1H native | expectancy | +0.090R | >= +0.10R | FAIL | Sharpe 0.46 < 0.70; recovery 0.84 < 1.50 |
| 7 | #3 | 4H native | expectancy | +0.098R | >= +0.10R | FAIL | Sharpe 0.38 < 0.70; recovery 1.32 < 1.50 |
| 8 | #3 | 6H native | expectancy | +0.077R | >= +0.10R | FAIL | Sharpe 0.35 < 0.70; recovery 0.91 < 1.50 |
| 9 | #4 | 1H native | expectancy | +0.033R | >= +0.10R | FAIL | Sharpe 0.48 < 0.70; RR 1.44 < 1.50 |
| 10 | #4 | 4H native | expectancy | +0.037R | >= +0.10R | FAIL | Sharpe 0.55 < 0.70; RR 1.46 < 1.50 |
| 11 | #4 | 6H native | expectancy | +0.039R | >= +0.10R | FAIL | Sharpe 0.57 < 0.70; RR 1.47 < 1.50 |
| 12 | #4 | 1D native | expectancy | +0.071R | >= +0.10R | FAIL | **nothing else** - Sharpe 1.03, recovery 5.60, RR 1.62, t +3.14 all pass |
| 13 | #5 | 6H native | expectancy | +0.046R | >= +0.10R | FAIL | Sharpe 0.70 < 0.70 |
| 14 | #5 | 6H forced-1:3 | expectancy | +0.078R | >= +0.10R | FAIL | Sharpe 0.47 < 0.70 |
| 15 | #5 | 1D forced-1:3 | Sharpe | 0.34 | >= 0.70 | FAIL | recovery 0.92 < 1.50 |
| 16 | #6 | 1H native | Sharpe | 0.42 | >= 0.70 | FAIL | none - expectancy +0.118R, recovery 1.70, RR 3.72 all pass |
| 17 | #6 | 4H forced-1:3 | expectancy | +0.095R | >= +0.10R | FAIL | **nothing else** - Sharpe 0.77, recovery 3.41, t +2.16 all pass |
| 18 | #6 | 6H native | Sharpe | 0.64 | >= 0.70 | FAIL | none - expectancy +0.317R, recovery 3.74, RR 4.22 all pass |
| 19 | #6 | 6H forced-1:3 | expectancy | +0.064R | >= +0.10R | FAIL | Sharpe 0.45 < 0.70; recovery 1.40 < 1.50 |
| 20 | #6 | 1D native | Sharpe | 0.59 | >= 0.70 | FAIL | none - expectancy +1.027R, recovery 5.79, RR 7.25 all pass |
| 21 | #7 | 1H forced-1:3 | expectancy | +0.098R | >= +0.10R | FAIL | **nothing else** - Sharpe 1.16, recovery 7.02, t +3.54 all pass |
| 22 | #7 | 6H native | Sharpe | 0.70 | >= 0.70 | FAIL | **nothing else** - expectancy +0.509R, recovery 9.10, t +1.75 all pass |
| 23 | #7 | 1D native | Sharpe | 0.69 | >= 0.70 | FAIL | **nothing else** - expectancy +0.537R, recovery 8.49, t +1.67 all pass |
| 24 | #7 | 1D forced-1:3 | Sharpe | 0.62 | >= 0.70 | FAIL | **nothing else** - expectancy +0.182R, recovery 2.27, t +1.65 all pass |
| 25 | #8 | 1H native | Sharpe | 0.69 | >= 0.70 | FAIL | **nothing else** - expectancy +0.222R, recovery 3.07, t +2.12 all pass |
| 26 | #8 | 1D native | Sharpe | 0.62 | >= 0.70 | FAIL | **nothing else** - expectancy +2.145R, recovery 5.31, t +1.57 all pass |
| 27 | #8 | 1D forced-1:3 | Sharpe | 0.53 | >= 0.70 | FAIL | **nothing else** - expectancy +0.210R, recovery 2.92, t +1.36 all pass |

## Borderline calls - where the verdict turned on one number

**Fifteen of the 27 INCONCLUSIVE cells miss exactly one gate**, and twelve of those
fifteen miss it on **Sharpe alone**. Read those twelve and a pattern appears: the
entry is real, the sample is large, and the *only* thing between the cell and a KEEP
is that the equity curve is not smooth enough. That is a statement about variance,
not about direction.

- **#8 1H native is the textbook case.** Post-fee Sharpe **0.69 against a 0.70
  gate** - a thousandth short. Every other criterion passes comfortably: expectancy
  +0.222R per trade (gate +0.10R), R-recovery 3.07 (gate 1.50), RR 2.07 (gate 1.50),
  t = +2.12 (clear of the noise band), 3394 trades over 4.88 years. This cell is
  INCONCLUSIVE for one reason and one only, and the reason is a rounding-width
  shortfall in smoothness.
- **#7 1D native** sits in the same place: Sharpe **0.69** against 0.70, with
  expectancy +0.537R, recovery 8.49 and t = +1.67. **#7 6H native** reads 0.70 in the
  table and is still below the gate, because the unrounded value is marginally under.
- **#6 1D native** is the same story at a different scale: +1.027R per trade, recovery
  5.79, RR 7.25 - a genuinely large edge held back by Sharpe 0.59 on only 144 trades.
  The t-statistic (+1.47) says the sample is not large enough to be confident about
  that edge either.
- **The three expectancy-only misses are the opposite case.** #4 1D native (+0.071R
  vs +0.10R), #6 4H forced-1:3 (+0.095R) and #7 1H forced-1:3 (+0.098R) each clear
  Sharpe, recovery and t comfortably and fail only the expectancy floor - by 0.029R,
  0.005R and 0.002R respectively. Two of those three are within five-thousandths of a
  risk unit of a KEEP.

**One KEEP does not survive its own funding bill.** #5 4H forced-1:3 clears every
gate as measured (+0.107R, Sharpe 0.72, recovery 3.34, t = +2.11), but it holds
positions for about 70 hours across roughly 8.7 funding settlements, and at Bybit's
*base* rate of 0.01% per 8 hours that costs about -0.019R per trade - taking the edge
to **+0.088R, below the +0.10R threshold**. Funding at the base rate alone is enough
to demote this cell, and the base rate is a floor: real funding on these coins has
spent long stretches above it. It is logged as KEEP and flagged provisional, because
that is what the measured numbers say and the funding rule was fixed before the
strategy was run.

**The other seven KEEPs survive funding at the base rate**, though all seven cross
funding stamps by design and are provisional until a funding model exists: #5 1D
native (+0.154R to +0.147R), #6 4H native (+0.300R to +0.247R), #7 1H native (+0.444R
to +0.399R), #7 4H native (+0.550R to +0.503R), #7 4H forced-1:3 (+0.144R to +0.130R),
#7 6H forced-1:3 (+0.198R to +0.180R) and #8 4H native (+0.798R to +0.691R).

## What this index deliberately does not do

It does not merge the two exits on a timeframe into one verdict, because a strategy
can have a good entry and a bad exit and that difference *is* the finding - #4 is the
cleanest example, INCONCLUSIVE on its own exit at all four resolutions and DISCARD on
the forced 1:3 at all four. It does not average across timeframes, because #1's 1H
and 1D cells are not the same question. It does not promote the borderline Sharpe
cells above, because the 0.70 gate was fixed before any of these strategies were
written and a gate that moves to fit the data is not a gate. And it does not
substitute for the sections below: every row here has a full write-up behind it,
including the sensitivity sweeps, exit-death checks and per-coin breakdowns that a
single line of metrics cannot carry.

---

## Strategy #1 — Bollinger Band Reversion (short only)

**Tested:** 2026-09-05 · **Coins:** BTCUSDT, SOLUSDT, XRPUSDT
(Bybit USDT perpetuals) · **Timeframes:** 1H, 4H, 1D · **Direction:** short only ·
**Source's own timeframe:** 4H

### The rules, in plain English

Only ever sell short, and only when the market is already falling. Three things
must line up on a candle that has finished forming:

1. the faster moving average sits below the slower one, so the trend is down;
2. that candle is the **first** one to close above the upper Bollinger band — a
   stretched bounce inside a downtrend, not the tenth candle of a rally. The
   source stresses this: without the "first" condition a strong rally fires entry
   after entry and every one of them stops out;
3. volume on that candle is above its own recent average, so the push is real
   rather than a thin wick.

The trade is then sold short at the **next** candle's open.

Getting out, the source's way: take profit when a candle closes at or below the
**lower** Bollinger band — the full swing from one edge of the range to the other.
Stop loss is a fixed percentage above the entry price. There is no time limit.

Getting out, the forced way (this project's standard comparison): stop at 1R,
target at 3R, and a 30-bar time limit. Identical entries, identical 1R.

### Parameters — every one is a placeholder

The source describes the logic in public but keeps the numbers behind a paywall.
Nothing below was taken from the source; all of it is a stated assumption.

| Parameter | Value used | Where it came from |
|---|---|---|
| Bollinger period | 20 | Bollinger's own canonical default |
| Bollinger std-dev multiplier | 2.0 | Bollinger's own canonical default |
| Fast EMA | 20 | **Placeholder** — source undisclosed |
| Slow EMA | 50 | **Placeholder** — source undisclosed |
| Volume SMA length | 20 | **Placeholder** — source undisclosed |
| Stop loss | 2% from the fill price | **Placeholder** — source undisclosed |
| Warm-up bars skipped | 200 | enough for the slowest indicator to settle |
| Forced-1:3 time limit | 30 bars | project-wide **unvalidated placeholder** |

The stop percentage is the dangerous one. The stop **is** 1R, and 1R is the
denominator of every number in this report, so guessing it wrong rescales
everything. A sensitivity table is included below for that reason.

### How this test differs from the source

| | Source | This test |
|---|---|---|
| Universe | top 30 by market cap, rebuilt monthly (72 pairs appear) | 3 fixed coins |
| Timeframe | 4H only | 1H, 4H, 1D |
| Leverage | 1.5x fixed | irrelevant — R-multiples are scale-invariant |
| Costs | not stated | Bybit taker 0.00055 both legs, always applied |

The universe gap is the big one. A rule that fires rarely per coin becomes a
usable system across 72 coins and a starved one across 3. Fewer trades also means
less diversification, so the pooled equity curve here is bumpier than the
source's by construction. The source's reported ~25% win rate and ~3.5:1 payoff
come from that wide universe and cannot be expected to reproduce on three coins.

### Lookahead check — run fresh on this strategy

Method: recompute every indicator on history that has been cut off at a given
bar, then compare the value at the cut against the value the same indicator shows
when the whole history is present. If future candles were leaking into a past
decision, the two numbers would differ.

Columns checked: bb_lower, bb_mid, bb_upper, ema_medium, ema_short, first_close_above, vol_sma.
Result: **9/9 datasets PASS** at 25 cut points each, to a tolerance of
1e-12. Every indicator value at the cut was identical with and without the future
bars present.

Two structural protections back that up: a signal read from a finished candle is
filled at the **next** candle's open, never at the closing price it was measured
on; and the percentage stop is measured from the actual fill price, not from the
signal candle's close (self-test #9 proves this on hand-built candles).

### How much history these numbers cover

Trade count on its own does not say how long a period a result is drawn from,
so the window is recorded per coin. What is measured is the TRADEABLE window:
the first bar the rule is allowed to act on, after the warmup, through the last
closed bar in the data. The three coins do not start together - Bitcoin's history
on this venue begins in March 2020, XRP in May 2021, Solana in October 2021 - so a
pooled row is not three equal thirds.

Warmup skipped before the first trade: 200 bars on every timeframe. That subtraction costs very
little at 1H and a great deal at 1D, where a warmup bar is a whole day.

| Timeframe | Coin | Window traded | Days | Years | Tradeable bars | Warmup bars |
|---|---|---|---|---|---|---|
| 1H | BTCUSDT | 2020-04-02 to 2026-09-05 | 2346 | 6.42 | 56,311 | 200 |
| 1H | SOLUSDT | 2021-10-23 to 2026-09-05 | 1778 | 4.87 | 42,665 | 200 |
| 1H | XRPUSDT | 2021-05-21 to 2026-09-05 | 1932 | 5.29 | 46,376 | 200 |
| 4H | BTCUSDT | 2020-04-27 to 2026-09-05 | 2321 | 6.36 | 13,929 | 200 |
| 4H | SOLUSDT | 2021-11-17 to 2026-09-05 | 1753 | 4.80 | 10,517 | 200 |
| 4H | XRPUSDT | 2021-06-15 to 2026-09-05 | 1907 | 5.22 | 11,445 | 200 |
| 1D | BTCUSDT | 2020-10-11 to 2026-09-04 | 2154 | 5.90 | 2,155 | 200 |
| 1D | SOLUSDT | 2022-05-03 to 2026-09-04 | 1585 | 4.34 | 1,586 | 200 |
| 1D | XRPUSDT | 2021-11-29 to 2026-09-04 | 1740 | 4.76 | 1,741 | 200 |

Shortest window in this run: SOLUSDT at 1D, 1585 days (4.34 years). Longest: BTCUSDT at 1H, 2346 days (6.42 years).

### Results — three coins pooled per timeframe, after fees

| Timeframe | Exit | Trades | Days BTC | Days SOL | Days XRP | Win% | RR | R (pre-fee) | R (post-fee) | R/trade | Sharpe | Max DD % | Max DD (R) | R-recovery | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1H | native | 1054 | 2346 | 1778 | 1932 | 43.9 | 1.17 | 9.2 | -48.7 | -0.046 | -0.39 | 83.1 | 82.3 | -0.59 | **DISCARD** |
| 1H | forced-1:3 | 1054 | 2346 | 1778 | 1932 | 38.9 | 1.57 | 55.9 | -2.1 | -0.002 | -0.02 | 48.2 | 49.6 | -0.04 | **DISCARD** |
| 4H | native | 290 | 2321 | 1753 | 1907 | 21.4 | 2.66 | -50.7 | -66.7 | -0.230 | -0.80 | 67.1 | 67.1 | -0.99 | **DISCARD** |
| 4H | forced-1:3 | 294 | 2321 | 1753 | 1907 | 26.2 | 2.36 | -21.0 | -37.1 | -0.126 | -0.47 | 36.5 | 36.1 | -1.03 | **DISCARD** |
| 1D | native | 57 | 2154 | 1585 | 1740 | 8.8 | 8.17 | -8.6 | -11.7 | -0.206 | -0.18 | 22.9 | 26.3 | -0.45 | **DISCARD** |
| 1D | forced-1:3 | 61 | 2154 | 1585 | 1740 | 18.0 | 2.79 | -17.0 | -20.4 | -0.334 | -0.69 | 21.1 | 20.9 | -0.97 | **DISCARD** |

Pre-fee is shown only so the size of the fee bill is visible. Every verdict is
made on the post-fee column.

### How the trades ended

- 1H native: bb_lower 478, stop 576 — average hold 16.8 bars, fees cost 0.055R per trade, best conditions down/highvol, worst range/lowvol
- 1H forced-1:3: stop 537, target 119, time 398 — average hold 17.3 bars, fees cost 0.055R per trade, best conditions down/highvol, worst range/lowvol
- 4H native: bb_lower 62, stop 228 — average hold 8.7 bars, fees cost 0.055R per trade, best conditions up/lowvol, worst range/highvol
- 4H forced-1:3: stop 214, target 57, time 23 — average hold 7.4 bars, fees cost 0.055R per trade, best conditions up/lowvol, worst up/highvol
- 1D native: bb_lower 5, stop 52 — average hold 3.5 bars, fees cost 0.055R per trade, best conditions down/lowvol, worst range/lowvol
- 1D forced-1:3: stop 50, target 11 — average hold 1.0 bars, fees cost 0.055R per trade, best conditions down/highvol, worst down/lowvol

### Exit-death check

Same entry rule, same 1R distance, only the exit rules differ — so a gap between
the two rows of a timeframe is caused by the exit alone. Entry overlap between the
two variants is 92% at worst (an open position blocks the next signal,
so the realised sets are not quite identical), which is high enough for the
comparison to be fair.

- **1H: exit-death = NO.** the two exits land within 0.044R per trade of each other (native -0.046R vs forced 1:3 -0.002R), so the result is driven by the entry signal rather than by the choice of exit
- **4H: exit-death = NO.** the two exits land within 0.104R per trade of each other (native -0.230R vs forced 1:3 -0.126R), so the result is driven by the entry signal rather than by the choice of exit
- **1D: exit-death = NO.** the two exits land within 0.128R per trade of each other (native -0.206R vs forced 1:3 -0.334R), so the result is driven by the entry signal rather than by the choice of exit

**The answer here is no, on all three timeframes — and that is worth stating
plainly, because it is the opposite of what this project usually finds.** A
previous postmortem on seven consecutive failed systems found the exit to be the
culprit seven times out of seven: indicator-reversal exits produced **zero**
winners in that set, while a fixed take-profit on the identical entries produced
**zero** losers. That is why every strategy here is run twice and the two verdicts
are never collapsed into one.

This strategy does not fit that pattern. Forcing a clean 1:3 onto these entries
does help — it lifts 1H from -0.046R
to -0.002R per trade and 4H from
-0.230R to
-0.126R — but it never gets
the sign to flip, and on 1D it makes things worse. When neither exit can rescue a
set of entries, the entries are what is wrong. There is nothing here for a better
exit to save.

### Where the money actually went

| Timeframe | Exit | Trades | Before fees | Fee bill | After fees |
|---|---|---|---|---|---|
| 1H | native | 1054 | +9.2R | 58.0R | -48.7R |
| 1H | forced-1:3 | 1054 | +55.9R | 57.9R | -2.1R |
| 4H | native | 290 | -50.7R | 16.0R | -66.7R |
| 4H | forced-1:3 | 294 | -21.0R | 16.2R | -37.1R |
| 1D | native | 57 | -8.6R | 3.1R | -11.7R |
| 1D | forced-1:3 | 61 | -17.0R | 3.4R | -20.4R |

The single most important line in this whole report is 1H forced-1:3: it earns
**+55.9R before costs and -2.1R
after them.** The commission bill on 1054 trades is
58R, and that is the entire difference
between a flat line and a losing one. A 2% stop on an hourly chart makes 1R small,
so a fixed percentage fee eats 5.5% of a risk unit every
round trip. This is exactly why the project rule is that post-fee is the only
number that counts.

### Was this a fair test?

```
1H:
  native       1054 trades | pre-fee +0.0088R/trade (spread 1.29R, t = +0.22) | post-fee -0.0462R/trade (t = -1.17)
  forced-1:3   1054 trades | pre-fee +0.0530R/trade (spread 1.36R, t = +1.26) | post-fee -0.0019R/trade (t = -0.05)
  resolved inside their first candle: native 7%, forced-1:3 7%
  the two variants share 96.5% of their entries
  a 2.0% stop vs a typical candle: BTCUSDT candle 0.62% (stop = 3.2x), SOLUSDT candle 1.14% (stop = 1.8x), XRPUSDT candle 0.89% (stop = 2.2x)
4H:
  native        290 trades | pre-fee -0.1748R/trade (spread 1.70R, t = -1.75) | post-fee -0.2299R/trade (t = -2.30)
  forced-1:3    294 trades | pre-fee -0.0713R/trade (spread 1.61R, t = -0.76) | post-fee -0.1263R/trade (t = -1.34)
  resolved inside their first candle: native 20%, forced-1:3 20%
  the two variants share 96.8% of their entries
  a 2.0% stop vs a typical candle: BTCUSDT candle 1.34% (stop = 1.5x), SOLUSDT candle 2.42% (stop = 0.8x), XRPUSDT candle 1.90% (stop = 1.1x)
1D:
  native         57 trades | pre-fee -0.1510R/trade (spread 3.11R, t = -0.37) | post-fee -0.2061R/trade (t = -0.50)
  forced-1:3     61 trades | pre-fee -0.2787R/trade (spread 1.55R, t = -1.40) | post-fee -0.3338R/trade (t = -1.68)
  resolved inside their first candle: native 63%, forced-1:3 66%
  the two variants share 92.3% of their entries
  a 2.0% stop vs a typical candle: BTCUSDT candle 3.70% (stop = 0.5x), SOLUSDT candle 6.44% (stop = 0.3x), XRPUSDT candle 5.03% (stop = 0.4x)
```

Three things to read out of that block:

- **Nothing here is distinguishable from luck, even before costs.** The largest
  t-statistic across all six runs is +1.26; roughly 2 is the bare minimum
  before an average is worth taking seriously. So this is not "a small edge
  destroyed by fees" — the pre-fee edge cannot be shown to exist either.
- **The 1D test is not really a test of the strategy.** A typical daily candle
  moves 3.7% on BTC,
  6.4% on SOL and
  5.0% on XRP, while the stop is only
  2% away and the 3R target only 6% away. Both barriers sit inside one candle, so
  66% of forced-1:3 trades resolved on their first
  bar, where plain candle data cannot say which barrier was touched first. The
  engine always resolves that against us. The 1D verdict below is what the fixed
  bar returns, but it is measuring the tie-break rule as much as the strategy.
- **4H is borderline for the same reason** on SOL, whose typical 4H candle is
  2.42% against a 2% stop. 1H is the
  only timeframe where 1R is comfortably wider than a single candle, and 1H is
  therefore the cleanest of the three results.

### Verdicts — each exit variant scored separately

- **1H / native exit — DISCARD.** post-fee expectancy -0.046R per trade is not positive; post-fee Sharpe -0.39 below 0.3; earned only -0.59x its worst drawdown
- **1H / forced 1:3 — DISCARD.** post-fee expectancy -0.002R per trade is not positive; post-fee Sharpe -0.02 below 0.3; earned only -0.04x its worst drawdown (its own fee-derived breakeven win rate is 26.4%)
- **4H / native exit — DISCARD.** post-fee expectancy -0.230R per trade is not positive; post-fee Sharpe -0.80 below 0.3; earned only -0.99x its worst drawdown
- **4H / forced 1:3 — DISCARD.** post-fee expectancy -0.126R per trade is not positive; post-fee Sharpe -0.47 below 0.3; earned only -1.03x its worst drawdown (its own fee-derived breakeven win rate is 26.4%)
- **1D / native exit — DISCARD.** post-fee expectancy -0.206R per trade is not positive; post-fee Sharpe -0.18 below 0.3; earned only -0.45x its worst drawdown
- **1D / forced 1:3 — DISCARD.** post-fee expectancy -0.334R per trade is not positive; post-fee Sharpe -0.69 below 0.3; earned only -0.97x its worst drawdown (its own fee-derived breakeven win rate is 26.4%)

### Stop-size sensitivity (secondary evidence, not the headline)

The source withheld its stop percentage. This shows what happens at 1%, 2% and
3%. Read it as a check on whether the verdict above is an artefact of a guessed
number, not as an optimisation — nothing here is tuned or selected.

| Stop % | Timeframe | Exit | Trades | Win% | R (post-fee) | R/trade | Sharpe |
|---|---|---|---|---|---|---|---|
| 1% | 1H | native | 1144 | 28.4 | -83.6 | -0.073 | -0.43 |
| 1% | 1H | forced-1:3 | 1151 | 29.7 | -78.2 | -0.068 | -0.48 |
| 1% | 4H | native | 307 | 11.7 | -109.6 | -0.357 | -0.97 |
| 1% | 4H | forced-1:3 | 313 | 21.1 | -85.8 | -0.274 | -1.07 |
| 1% | 1D | native | 60 | 3.3 | -19.1 | -0.318 | -0.22 |
| 1% | 1D | forced-1:3 | 61 | 9.8 | -43.7 | -0.717 | -1.66 |
| 2% | 1H | native | 1054 | 43.9 | -48.7 | -0.046 | -0.39 |
| 2% | 1H | forced-1:3 | 1054 | 38.9 | -2.1 | -0.002 | -0.02 |
| 2% | 4H | native | 290 | 21.4 | -66.7 | -0.230 | -0.80 |
| 2% | 4H | forced-1:3 | 294 | 26.2 | -37.1 | -0.126 | -0.47 |
| 2% | 1D | native | 57 | 8.8 | -11.7 | -0.206 | -0.18 |
| 2% | 1D | forced-1:3 | 61 | 18.0 | -20.4 | -0.334 | -0.69 |
| 3% | 1H | native | 1023 | 52.0 | -55.6 | -0.054 | -0.58 |
| 3% | 1H | forced-1:3 | 1018 | 44.9 | 9.3 | 0.009 | 0.09 |
| 3% | 4H | native | 280 | 30.0 | -46.3 | -0.165 | -0.68 |
| 3% | 4H | forced-1:3 | 283 | 30.0 | -31.4 | -0.111 | -0.46 |
| 3% | 1D | native | 57 | 14.0 | -9.0 | -0.158 | -0.18 |
| 3% | 1D | forced-1:3 | 60 | 20.0 | -14.2 | -0.237 | -0.49 |

Every one of the 18 cells above is a DISCARD. Widening the stop to 3% raises the
win rate (1H forced-1:3 goes from 38.9%
to 44.9%) because a wider stop
is harder to hit, and it does turn 1H forced-1:3 barely positive at
+9.3R total — still a
DISCARD on Sharpe and on drawdown recovery. Tightening it to 1% makes everything
worse. The verdict is not an artefact of the guessed stop size.

### Bottom line

The strategy is a **DISCARD on all three timeframes and on both exit variants**,
and the reason is the entry, not the exit. Both exits were tried, neither works,
and the pre-fee edge cannot be distinguished from chance in the first place.

Two honest caveats attached to that:

1. The parameters are guesses. The source's real EMA lengths, volume period,
   Bollinger settings and stop percentage are paywalled. The stop was probed at
   three values and the answer did not change, but the other four were not.
2. The universe is wrong. The source trades 30 coins rebuilt monthly; this is
   three coins. That is the difference between a rule that fires often enough to
   diversify and one that does not.

**What would change this verdict:** running the same rules across a 30-coin
universe rebuilt monthly, which is the one difference from the source that is both
large and testable. That is a build, not a tweak — it needs cross-sectional data
handling the current runner does not have. Flagged as a possible revisit, not
scheduled.

### Funding cost — flagged, and it does apply here

Bybit charges or pays funding on a perpetual every 8 hours. Measured average holds
on this strategy: 1H holds 16.8 bars = 17 hours = about 2 funding windows; 4H holds
8.7 bars = 35 hours = about 4 funding windows; 1D holds 3.5 bars = 84 hours = about
11 funding windows. Every timeframe here is therefore a multi-window hold and the
standing funding flag applies to all three, not just the slow ones.

*Correction, same day:* the first version of this paragraph said the 1H hold was
"under one funding window". That was wrong — 16.8 hourly bars is 16.8 hours, which
spans about two windows. The figures above are the corrected ones. No result,
verdict or table anywhere in this entry depends on it.

One nuance specific to this strategy: it is **short only**, and a short position
*receives* funding when the rate is positive and pays it when negative. Funding is
therefore not automatically a hidden cost here — it could be a hidden credit. This
project has not measured historical funding rates, so the direction is unknown and
**this omission cannot be claimed to be conservative.**

It does not change anything today: every cell on every timeframe is a DISCARD by a
wide margin, and no KEEP is being claimed. But per the standing rule, if a
short-only or multi-day strategy later comes close to a KEEP, funding must be
resolved before that KEEP is treated as real.

### Also not modelled

Slippage, order-book depth, and whether the 3R target or the lower-band exit was
genuinely fillable at the printed price. Those would all make the numbers worse.
Funding, as above, could go either way.

---

## Strategy #2 — Dual Momentum (Bybit perps), absolute leg + Bitcoin switch

**Tested:** 2026-09-05 · **Coins:** BTCUSDT, SOLUSDT, XRPUSDT
(Bybit USDT perpetuals) · **Timeframes:** 1H, 4H, 1D · **Direction:** long and short ·
**Source's own cadence:** weekly re-rank pinned to Monday, average hold about 13 days

**Source:** [+117% in 4 Years: Dual Momentum on Crypto Futures](https://backtestsnotsignals.substack.com/p/117-in-4-years-dual-momentum-on-crypto)
· sourcing rated **strong** (full performance figures, method described in prose,
author states his own caveats).

### The rules, in plain English

This is a momentum system with a master switch, not a chart-pattern system.

1. **Rank and go long.** Take the trailing N-day return of every coin in the
   universe, **deliberately ignoring the most recent bar**, and buy the strongest
   names. The skipped bar matters: the author reports that without it the whole
   edge disappears.
2. **Go short outright weakness.** Any coin whose plain 8-day return is negative
   is sold short.
3. **The Bitcoin switch sits on top of everything.** If Bitcoin closes below its
   30-day moving average, the entire book is flattened — longs and shorts alike —
   and no new trade is opened.

Getting out, the source's way: there is **no stop and no target**. Positions are
re-examined once a week, on Monday, and held otherwise. A position closes when the
weekly re-check no longer likes it, or when the Bitcoin switch turns off. Average
hold is about 13 days. Risk is handled by position size — smaller size in wilder
coins — and by the switch cutting exposure to zero.

Getting out, the forced way (this project's standard comparison): stop at 1R,
target at 3R, 30-bar time limit. Identical entries, identical 1R.

**What it suits:** a trending market, and specifically a Bitcoin uptrend. It is
built to switch itself off in Bitcoin bear markets rather than to profit from them.

### What could NOT be reproduced, and why that matters

Rule 1 is **cross-sectional** — it ranks twenty coins against each other and buys
the winners. This project trades three coins. Ranking three names is not a small
version of ranking twenty; it is a different rule, so **the ranking leg is not
reproduced at all.**

What **is** reproduced is the other half of "dual" momentum — the absolute test the
source applies on top of its ranking, with the same skipped bar and the same
Bitcoin switch: go long when this coin's own skip-adjusted trailing return is
positive, go short when its 8-day return is negative, stay flat whenever Bitcoin
is below its 30-day average. Everything below is labelled "absolute leg + Bitcoin
switch" for that reason. It is not a verdict on the source's full system.

### Parameters — what the source states, and what is a guess

| Parameter | Value used | Where it came from |
|---|---|---|
| Short-leg window | 8 days | **stated by the source** |
| Bitcoin moving average | 30 days | **stated by the source** |
| Skipped bar | 1 bar | **stated by the source** |
| Re-rank day | Monday | **stated by the source** |
| Long-leg lookback N | 30 days | **placeholder** — the source never gives N. Swept at 8/14/30 below |
| Stop distance | 2.0x a 14-day average daily range | **placeholder** — the source has no stop at all |
| Forced-1:3 time limit | 30 bars | project-wide **unvalidated placeholder** |

Two of those deserve calling out.

**The stop is mine, not the source's.** A stop had to exist because R is the
denominator of every number this project reports, and because an unstopped
perpetual short is unbounded risk nobody would actually trade. It is measured
against a **daily-equivalent** average range rather than the trading bar's range —
a 14-bar range on hourly candles would be a 14-hour stop on a 13-day trade, which
would stop out almost immediately and would measure the stop instead of the
strategy. The consequence is that 1R means the same real risk on all three
timeframes, so the three are comparable. It also happens to be a fair reading of
the source's own risk control: risking a fixed fraction of equity against a
volatility-scaled stop **is** inverse-volatility sizing.

The cost of that choice is visible in the exit mix below: a stop the source does
not have ended 42 of
123 native trades on 1H. That share of the native
result is attributable to my placeholder, not to the source's rule.

### How this test differs from the source

| | Source | This test |
|---|---|---|
| Universe | top 20 by market cap | 3 fixed coins |
| Selection | cross-sectional ranking | not reproduced — absolute momentum only |
| Timeframe | daily data, weekly decisions | 1H, 4H and 1D data, weekly decisions |
| Stop | none | volatility stop, as above |
| Costs | not stated | Bybit taker 0.00055 both legs, always applied |
| Funding | not stated | not modelled — see the funding section |

One structural point about the three timeframes. Because the decision day is pinned
to Monday, all three timeframes get the **same** number of decision points — 336
Monday-00:00 bars on 1H, 4H and 1D alike. So this is not three tests at three
different trade frequencies. It is one decision cadence, examined with three
different resolutions of stop and exit. That is why the trade counts below are
similar across timeframes instead of scaling with bar count.

### Lookahead check — run fresh on this strategy

Method: recompute every indicator on history that has been cut off at a given bar,
then compare the value at the cut against the value the same indicator shows when
the whole history is present. If future candles were leaking into a past decision,
the two numbers would differ.

Columns checked: atr_day, btc_close, btc_ma, btc_on, mom_long, mom_short, rebalance, stop_frac.
Result: **9/9 datasets PASS** at 25 cut points each, to a tolerance of
1e-12.

Three things were specifically dealt with on this strategy, because it is the first
one that reads data from a coin other than the one being traded:

- **Bitcoin's price is injected as raw data before any indicator is built**, so the
  audit truncates it at the same bar as everything else. Had Bitcoin's full history
  been loaded inside the indicator step instead, the audit would have ignored the
  cut and would have quietly stopped testing half the rule while still printing
  PASS. `btc_close` and `btc_on` appear in the checked-columns list above, which is
  the proof that the switch really was audited.
- **Bitcoin's bars are aligned onto the traded coin's timestamps by backward fill**,
  so a decision only ever sees the most recent Bitcoin bar that had already closed.
- **The audit's first cut was moved past the warm-up.** The default first cut sits
  at bar 300, which is inside this strategy's 816-bar hourly warm-up — every
  indicator would still be blank there, and comparing blank to blank would print a
  pass without having tested anything.

On top of that, the two protections that apply to every strategy here: a signal read
from a finished candle is filled at the **next** candle's open, and the momentum
windows are shifted twice on purpose — once for the source's skipped bar, once to
reach the start of the window — so no window ever includes the bar being decided on.

### How much history these numbers cover

Trade count on its own does not say how long a period a result is drawn from,
so the window is recorded per coin. What is measured is the TRADEABLE window:
the first bar the rule is allowed to act on, after the warmup, through the last
closed bar in the data. The three coins do not start together - Bitcoin's history
on this venue begins in March 2020, XRP in May 2021, Solana in October 2021 - so a
pooled row is not three equal thirds.

Warmup skipped before the first trade: 1H 816, 4H 204, 1D 120. That subtraction costs very
little at 1H and a great deal at 1D, where a warmup bar is a whole day.

| Timeframe | Coin | Window traded | Days | Years | Tradeable bars | Warmup bars |
|---|---|---|---|---|---|---|
| 1H | BTCUSDT | 2020-04-28 to 2026-09-05 | 2321 | 6.35 | 55,695 | 816 |
| 1H | SOLUSDT | 2021-11-18 to 2026-09-05 | 1752 | 4.80 | 42,049 | 816 |
| 1H | XRPUSDT | 2021-06-16 to 2026-09-05 | 1907 | 5.22 | 45,760 | 816 |
| 4H | BTCUSDT | 2020-04-28 to 2026-09-05 | 2321 | 6.35 | 13,925 | 204 |
| 4H | SOLUSDT | 2021-11-18 to 2026-09-05 | 1752 | 4.80 | 10,513 | 204 |
| 4H | XRPUSDT | 2021-06-16 to 2026-09-05 | 1907 | 5.22 | 11,441 | 204 |
| 1D | BTCUSDT | 2020-07-23 to 2026-09-04 | 2234 | 6.12 | 2,235 | 120 |
| 1D | SOLUSDT | 2022-02-12 to 2026-09-04 | 1665 | 4.56 | 1,666 | 120 |
| 1D | XRPUSDT | 2021-09-10 to 2026-09-04 | 1820 | 4.98 | 1,821 | 120 |

Shortest window in this run: SOLUSDT at 1D, 1665 days (4.56 years). Longest: BTCUSDT at 4H, 2321 days (6.35 years).

### Results — three coins pooled per timeframe, after fees

| Timeframe | Exit | Trades | Days BTC | Days SOL | Days XRP | Win% | RR | R (pre-fee) | R (post-fee) | R/trade | Sharpe | Max DD % | Max DD (R) | R-recovery | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1H | native | 123 | 2321 | 1752 | 1907 | 37.4 | 5.33 | 121.1 | 119.5 | 0.971 | 0.62 | 7.8 | 18.7 | 6.39 | **INCONCLUSIVE** |
| 1H | forced-1:3 | 357 | 2321 | 1752 | 1907 | 50.7 | 1.06 | 9.5 | 5.1 | 0.014 | 0.18 | 7.4 | 7.9 | 0.65 | **DISCARD** |
| 4H | native | 134 | 2321 | 1752 | 1907 | 37.3 | 4.67 | 116.8 | 115.0 | 0.859 | 0.58 | 9.6 | 22.9 | 5.03 | **INCONCLUSIVE** |
| 4H | forced-1:3 | 360 | 2321 | 1752 | 1907 | 46.4 | 1.45 | 31.0 | 26.5 | 0.074 | 0.52 | 13.0 | 18.8 | 1.41 | **INCONCLUSIVE** |
| 1D | native | 141 | 2234 | 1665 | 1820 | 36.9 | 4.56 | 115.6 | 113.7 | 0.807 | 0.67 | 8.9 | 20.9 | 5.43 | **INCONCLUSIVE** |
| 1D | forced-1:3 | 163 | 2234 | 1665 | 1820 | 38.7 | 1.98 | 25.4 | 23.4 | 0.144 | 0.47 | 14.1 | 20.3 | 1.15 | **INCONCLUSIVE** |

Pre-fee is shown only so the size of the fee bill is visible. Every verdict is made
on the post-fee column.

### How the trades ended

- 1H native: btc_switch_off 65, rerank 16, stop 42 — average hold 452.1 bars (18.8 days), fees cost 0.013R per trade, best conditions up/lowvol, worst down/highvol
- 1H forced-1:3: stop 12, target 2, time 343 — average hold 29.4 bars (1.2 days), fees cost 0.012R per trade, best conditions up/highvol, worst range/lowvol
- 4H native: btc_switch_off 67, rerank 16, stop 51 — average hold 104.0 bars (17.3 days), fees cost 0.013R per trade, best conditions up/lowvol, worst down/lowvol
- 4H forced-1:3: stop 66, target 7, time 287 — average hold 27.2 bars (4.5 days), fees cost 0.012R per trade, best conditions up/highvol, worst range/lowvol
- 1D native: btc_switch_off 65, rerank 24, stop 52 — average hold 16.8 bars (16.8 days), fees cost 0.013R per trade, best conditions up/lowvol, worst up/highvol
- 1D forced-1:3: stop 88, target 26, time 49 — average hold 16.1 bars (16.1 days), fees cost 0.012R per trade, best conditions up/highvol, worst down/lowvol

### The long leg versus the short leg — the source's biggest claim, tested

The source credits its **short** leg with 75% of profits. The academic paper it
cites for authority concludes the **opposite**: that momentum profits come almost
entirely from the long leg while the short leg loses money. Those cannot both be
true, so the two legs were measured separately.

| Timeframe | Exit | Long trades | Long R | Long win% | Short trades | Short R | Short win% |
|---|---|---|---|---|---|---|---|
| 1H | native | 97 | +122.5 | 34.0 | 26 | -3.0 | 50.0 |
| 1H | forced-1:3 | 330 | +5.6 | 50.3 | 27 | -0.5 | 55.6 |
| 4H | native | 104 | +114.9 | 33.7 | 30 | +0.2 | 50.0 |
| 4H | forced-1:3 | 326 | +25.9 | 45.7 | 34 | +0.7 | 52.9 |
| 1D | native | 100 | +106.7 | 28.0 | 41 | +7.0 | 58.5 |
| 1D | forced-1:3 | 132 | +24.3 | 38.6 | 31 | -0.9 | 38.7 |

**The paper wins and the source loses, on this data.** On the native exit the long
leg produced +122.5R on 1H,
+114.9R on 4H and
+106.7R on 1D. The short leg produced
-3.0R, +0.2R
and +7.0R. It is not merely smaller — it is
close to nothing on every timeframe, negative on 1H, and never more than
+7R against a long
leg that produced upwards of
+107R.

There is a mechanical reason, and it is worth understanding because it is a design
flaw in the rule rather than an accident of this data. **The Bitcoin switch only
permits trading while Bitcoin is above its 30-day average.** That is precisely when
altcoins tend to have positive momentum. So the short leg is only ever allowed to
fire in the narrow case of a coin falling *while Bitcoin is rising* — and it is
forbidden in exactly the conditions a short seller wants, because a Bitcoin
downtrend flattens the whole book. The switch and the short leg work against each
other by construction.

Trade counts show the same thing: 97 long trades against
26 short on 1H. The book is roughly
79%
long by trade count. Whatever this strategy is, it is a long-biased trend follower
with a small short appendix, not a balanced long/short book.

### Exit-death check

- **1H: exit-death = YES.** both exits agree on direction but differ by 0.957R per trade (native +0.971R vs forced 1:3 +0.014R), which is larger than the entire +0.10R KEEP requirement. The native exit is doing more work than the entry signal.
- **4H: exit-death = YES.** both exits agree on direction but differ by 0.785R per trade (native +0.859R vs forced 1:3 +0.074R), which is larger than the entire +0.10R KEEP requirement. The native exit is doing more work than the entry signal.
- **1D: exit-death = YES.** both exits agree on direction but differ by 0.663R per trade (native +0.807R vs forced 1:3 +0.144R), which is larger than the entire +0.10R KEEP requirement. The native exit is doing more work than the entry signal.

**Read that flag with care on this strategy — the precondition for it is not met.**
The check is only clean when both variants trade the same entries, and here they
share just 46%–63% of them, against the
85% threshold this project requires. The cause is
structural rather than a bug: the native exit holds a position for
17–19 days,
and an open position blocks the next weekly signal, so the native variant simply
gets fewer chances to enter (123 trades on 1H against
357 for the forced version). The two variants are
therefore not the same entries with different exits; they are different trade sets.

What can still be said, because both readings point the same way: **this strategy's
result lives in its native exit, and forcing a 1:3 onto it takes the result away.**
Per trade, native earned +0.971R on
1H against +0.014R forced,
+0.859R against
+0.074R on 4H, and
+0.807R against
+0.144R on 1D. The achieved
reward-to-risk collapses the same way, from about
5.3:1 native to
1.1:1 forced on 1H.

**This is the opposite of the pattern that motivated this whole project.** A previous
postmortem on seven consecutive failed systems found the exit to be the culprit
seven times out of seven: indicator-reversal exits produced zero winners, while a
fixed take-profit on the identical entries produced zero losers. Strategy #2 inverts
that. Its condition-based exit — hold until the weekly re-check or the Bitcoin switch
says otherwise — is the part that works, and the fixed 3R target is what destroys it.
That is what a genuine trend-following payoff distribution looks like: a low win rate
of about 37% paying about
5.3:1, where capping the winners at 3R
removes the few outliers that fund everything else.

**One caveat that cuts against the forced variant's numbers rather than for them.**
On 1H the forced test barely tests 1:3 at all: of
357 trades, the 3R target was reached
2 times and the 30-bar clock ended
343 of them. With 1R measured against a daily range, 1R is roughly
8–14% of price, so a 3R target sits 25–41% away — unreachable inside
30 hours. The 1H forced-1:3 row is therefore mostly measuring
"hold for 30 hours, then leave", not a 1:3 trade plan. The time limit stays fixed at
30 bars because the ruler does not move between strategies,
but the 1H and 4H forced numbers should be read as a handicapped test rather than a
fair refutation. Only the 1D forced-1:3 column gives the target a realistic chance —
and there it hits 26
times out of 163.

### Where the money actually went

| Timeframe | Exit | Trades | Before fees | Fee bill | After fees |
|---|---|---|---|---|---|
| 1H | native | 123 | +121.1R | 1.7R | +119.5R |
| 1H | forced-1:3 | 357 | +9.5R | 4.4R | +5.1R |
| 4H | native | 134 | +116.8R | 1.8R | +115.0R |
| 4H | forced-1:3 | 360 | +31.0R | 4.4R | +26.5R |
| 1D | native | 141 | +115.6R | 1.8R | +113.7R |
| 1D | forced-1:3 | 163 | +25.4R | 2.0R | +23.4R |

**Fees are not the story on this strategy, and that is itself a finding.** They cost
about 0.013R per round trip, roughly a
hundredth of a risk unit, because 1R here is 8–14% of price and a
0.055% commission
is tiny against that. Contrast Strategy #1, where a 2% stop on hourly candles made
the commission bill the entire difference between flat and losing. A wide stop makes
a strategy fee-insensitive; a tight stop makes fees decisive.

### Was this a fair test?

```
1H:
  native        123 trades | pre-fee +0.9847R/trade (spread 5.88R, t = +1.86) | post-fee +0.9712R/trade (t = +1.83)
  forced-1:3    357 trades | pre-fee +0.0266R/trade (spread 0.47R, t = +1.07) | post-fee +0.0144R/trade (t = +0.58)
  resolved inside their first candle: native 0%, forced-1:3 0%
  the two variants share 46.4% of their entries  <-- TOO LOW to compare exits fairly
4H:
  native        134 trades | pre-fee +0.8720R/trade (spread 5.85R, t = +1.72) | post-fee +0.8586R/trade (t = +1.70)
  forced-1:3    360 trades | pre-fee +0.0860R/trade (spread 0.89R, t = +1.84) | post-fee +0.0737R/trade (t = +1.58)
  resolved inside their first candle: native 1%, forced-1:3 0%
  the two variants share 47.8% of their entries  <-- TOO LOW to compare exits fairly
1D:
  native        141 trades | pre-fee +0.8197R/trade (spread 5.34R, t = +1.82) | post-fee +0.8067R/trade (t = +1.80)
  forced-1:3    163 trades | pre-fee +0.1559R/trade (spread 1.54R, t = +1.29) | post-fee +0.1437R/trade (t = +1.19)
  resolved inside their first candle: native 1%, forced-1:3 1%
  the two variants share 63.3% of their entries  <-- TOO LOW to compare exits fairly
```

| Timeframe | Coin | Measured 1R (% of price) | Typical candle (%) | 1R as a multiple of one candle |
|---|---|---|---|---|
| 1H | BTCUSDT | 8.18% | 0.62% | 13.2x |
| 1H | SOLUSDT | 13.73% | 1.14% | 12.0x |
| 1H | XRPUSDT | 11.54% | 0.89% | 13.0x |
| 4H | BTCUSDT | 8.20% | 1.34% | 6.1x |
| 4H | SOLUSDT | 13.71% | 2.42% | 5.7x |
| 4H | XRPUSDT | 11.54% | 1.90% | 6.1x |
| 1D | BTCUSDT | 8.19% | 3.70% | 2.2x |
| 1D | SOLUSDT | 13.73% | 6.44% | 2.1x |
| 1D | XRPUSDT | 11.56% | 5.03% | 2.3x |

Four things to read out of those blocks:

- **The positive results are not statistically distinguishable from luck.** The
  largest t-statistic anywhere in this test is +1.86, and roughly 2 is the bare
  minimum before an average is worth taking seriously. The native exit's
  +119R on 1H looks impressive as a total,
  but it comes from 123 trades with a spread of
  5.9R per trade. A handful of large winners
  produced most of it. That is normal for trend following and it is also exactly the
  shape that cannot be told apart from chance at this sample size.
- **The intrabar ambiguity problem from Strategy #1 is gone.** At most
  1%
  of forced trades resolved inside their first candle, versus a majority on Strategy
  #1's 1D test. 1R is 2.1x wider than a typical candle at its worst in the
  table above, so the pessimistic stop-wins tie-break almost never had to be applied.
  The daily-equivalent stop did its job.
- **The two exit variants do not trade the same entries** (46%–63%
  overlap against a 85% requirement), for the structural
  reason given above. This weakens the exit-death comparison and is the single largest
  methodological weakness in this entry.
- **The sample is thin in a way trade count hides.** 141
  trades sounds adequate, but they come from 336 Monday decision points across three
  coins over about five years, and the three coins are heavily correlated. The
  effective number of independent bets is far smaller than the trade count suggests.

### Per-coin breakdown — the pooled number is mostly Bitcoin

```
coin      timeframe  exit         trades   win%     RR    R pre   R post  R/trade  Sharpe     DD%    DD R  recov  verdict
-------------------------------------------------------------------------------------------------------------------------
BTCUSDT   1H         native           39   43.6   6.62     64.6     63.9    1.638    0.57     3.1     5.3  12.12  INCONCLUSIVE
BTCUSDT   1H         forced-1:3      153   51.6   1.35     12.7     10.4    0.068    0.59     3.6     3.8   2.75  INCONCLUSIVE
BTCUSDT   4H         native           44   40.9   5.65     61.2     60.4    1.373    0.52     4.0     6.6   9.09  INCONCLUSIVE
BTCUSDT   4H         forced-1:3      157   51.6   1.47     25.6     23.2    0.148    0.82     5.5     7.2   3.21  KEEP
BTCUSDT   1D         native           39   38.5   7.62     71.0     70.3    1.802    0.62     3.7     6.6  10.64  INCONCLUSIVE
BTCUSDT   1D         forced-1:3       58   44.8   2.08     21.5     20.5    0.354    0.68     6.0     7.8   2.65  INCONCLUSIVE
SOLUSDT   1H         native           35   37.1   4.18     26.5     26.1    0.746    0.37     6.5     8.7   3.00  INCONCLUSIVE
SOLUSDT   1H         forced-1:3       97   50.5   0.90     -0.4     -1.3   -0.013   -0.15     3.7     3.8  -0.33  DISCARD
SOLUSDT   4H         native           35   40.0   4.08     30.2     29.9    0.853    0.41     5.5     7.6   3.95  INCONCLUSIVE
SOLUSDT   4H         forced-1:3       97   46.4   1.45      8.4      7.5    0.077    0.39     6.0     6.8   1.11  INCONCLUSIVE
SOLUSDT   1D         native           43   51.2   2.60     31.8     31.4    0.730    0.49     6.1     8.6   3.67  INCONCLUSIVE
SOLUSDT   1D         forced-1:3       51   41.2   2.13     13.8     13.3    0.261    0.55     5.5     6.6   2.00  INCONCLUSIVE
XRPUSDT   1H         native           49   32.7   4.90     30.1     29.5    0.602    0.37     5.8     6.0   4.89  INCONCLUSIVE
XRPUSDT   1H         forced-1:3      107   49.5   0.77     -2.8     -4.0   -0.037   -0.47     4.8     4.8  -0.82  DISCARD
XRPUSDT   4H         native           55   32.7   3.97     25.4     24.8    0.451    0.32     7.2     9.7   2.57  INCONCLUSIVE
XRPUSDT   4H         forced-1:3      106   38.7   1.39     -3.0     -4.2   -0.039   -0.21    10.9    11.2  -0.37  DISCARD
XRPUSDT   1D         native           59   25.4   4.06     12.8     12.1    0.205    0.17    10.2    10.1   1.20  DISCARD
XRPUSDT   1D         forced-1:3       54   29.6   1.70     -9.8    -10.4   -0.193   -0.46    11.9    12.1  -0.86  DISCARD
```

Of the +119R the pooled 1H native test
produced, +64R came
from Bitcoin alone, on 39 trades.
XRP's 1D native cell is an outright DISCARD. Every negative post-fee cell in the whole
per-coin table belongs to SOL or XRP. This is a Bitcoin-uptrend strategy that was
applied to two altcoins, not a rule that worked on three coins independently.

**One per-coin cell scores KEEP: BTCUSDT 4H forced-1:3.** It is reported because nothing gets hidden, and it is explicitly *not* being treated as a KEEP. It is one cell out of 18 per-coin cells; at that count, one cell clearing the bar is what noise alone produces. The pooled verdict for that timeframe and exit is the one that counts, and it is not a KEEP. Picking the single best cell out of 18 is the selection error this project exists to avoid.

### Verdicts — each exit variant scored separately

- **1H / native exit — INCONCLUSIVE.** positive but short of the KEEP bar: Sharpe 0.62 < 0.7
- **1H / forced 1:3 — DISCARD.** post-fee Sharpe 0.18 below 0.3 (its own fee-derived breakeven win rate is 25.3%)
- **4H / native exit — INCONCLUSIVE.** positive but short of the KEEP bar: Sharpe 0.58 < 0.7
- **4H / forced 1:3 — INCONCLUSIVE.** positive but short of the KEEP bar: expectancy +0.074R < +0.10R; Sharpe 0.52 < 0.7; R-recovery 1.41 < 1.5 (its own fee-derived breakeven win rate is 25.3%)
- **1D / native exit — INCONCLUSIVE.** positive but short of the KEEP bar: Sharpe 0.67 < 0.7
- **1D / forced 1:3 — INCONCLUSIVE.** positive but short of the KEEP bar: Sharpe 0.47 < 0.7; R-recovery 1.15 < 1.5 (its own fee-derived breakeven win rate is 25.3%)

Not one cell reaches KEEP at the pooled level. The native exit lands
**INCONCLUSIVE on all three timeframes** for the same reason each time: it makes
money in total but its risk-adjusted return falls short of the bar, and the
per-trade average cannot be separated from noise. The forced 1:3 is a DISCARD on 1H
and INCONCLUSIVE on 4H and 1D.

### Lookback sensitivity (secondary evidence, not the headline)

The source never discloses the long leg's N. This sweeps it at 8, 14 and 30 days.
Read it as a check on whether the verdict above is an artefact of a guessed number,
not as an optimisation — nothing here is tuned or selected.

| Long-leg N | Timeframe | Exit | Trades | Win% | R (post-fee) | R/trade | Sharpe | Verdict |
|---|---|---|---|---|---|---|---|---|
| 8 days | 1H | native | 239 | 38.5 | 107.0 | 0.448 | 0.66 | INCONCLUSIVE |
| 8 days | 1H | forced-1:3 | 417 | 48.7 | 2.1 | 0.005 | 0.07 | DISCARD |
| 8 days | 4H | native | 247 | 37.7 | 59.5 | 0.241 | 0.48 | INCONCLUSIVE |
| 8 days | 4H | forced-1:3 | 425 | 46.4 | 8.3 | 0.020 | 0.16 | DISCARD |
| 8 days | 1D | native | 267 | 39.3 | 51.1 | 0.191 | 0.44 | INCONCLUSIVE |
| 8 days | 1D | forced-1:3 | 190 | 38.9 | 16.3 | 0.086 | 0.31 | INCONCLUSIVE |
| 14 days | 1H | native | 166 | 33.7 | 112.6 | 0.678 | 0.64 | INCONCLUSIVE |
| 14 days | 1H | forced-1:3 | 376 | 50.0 | 5.3 | 0.014 | 0.19 | DISCARD |
| 14 days | 4H | native | 177 | 32.8 | 105.7 | 0.597 | 0.58 | INCONCLUSIVE |
| 14 days | 4H | forced-1:3 | 386 | 45.9 | 18.9 | 0.049 | 0.39 | INCONCLUSIVE |
| 14 days | 1D | native | 194 | 36.1 | 73.1 | 0.377 | 0.51 | INCONCLUSIVE |
| 14 days | 1D | forced-1:3 | 182 | 36.8 | 14.1 | 0.078 | 0.27 | DISCARD |
| 30 days | 1H | native | 123 | 37.4 | 119.5 | 0.971 | 0.62 | INCONCLUSIVE |
| 30 days | 1H | forced-1:3 | 357 | 50.7 | 5.1 | 0.014 | 0.18 | DISCARD |
| 30 days | 4H | native | 134 | 37.3 | 115.0 | 0.859 | 0.58 | INCONCLUSIVE |
| 30 days | 4H | forced-1:3 | 360 | 46.4 | 26.5 | 0.074 | 0.52 | INCONCLUSIVE |
| 30 days | 1D | native | 141 | 36.9 | 113.7 | 0.807 | 0.67 | INCONCLUSIVE |
| 30 days | 1D | forced-1:3 | 163 | 38.7 | 23.4 | 0.144 | 0.47 | INCONCLUSIVE |

**0 of the 18 cells above reach KEEP.** The native exit stays positive at
every value of N on every timeframe, which is a genuine robustness result — the
finding does not depend on my guess. But it is positive-and-INCONCLUSIVE at every
value of N too, so no choice of N rescues it. Shortening N to 8 days roughly doubles
the trade count (239 against
123 on 1H) and cuts the total roughly in
half, which is what you would expect if the longer lookback is selecting stronger
trends rather than merely trading more.

### Bottom line

**INCONCLUSIVE on the native exit across all three timeframes; DISCARD on 1H forced
1:3 and INCONCLUSIVE on 4H and 1D forced 1:3.** No KEEP, and no DISCARD of the
strategy as a whole.

What was actually learned, in order of confidence:

1. **The source's central claim about its short leg does not survive.** The long leg
   produced essentially all of the profit and the short leg produced roughly nothing.
   The academic paper the author cites against himself is the one this data agrees
   with. The Bitcoin switch and the short leg are structurally in conflict.
2. **The strategy's result depends on its native exit, not on a target.** This is the
   first strategy in the project where forcing a clean 1:3 makes things worse rather
   than better, and it is a textbook low-win-rate, high-payoff trend profile.
3. **The pooled result is largely Bitcoin's uptrend.** Both altcoins contributed
   little or negative after fees.
4. **Nothing here is statistically solid.** The best t-statistic is +1.86
   against a minimum of about 2.

Why INCONCLUSIVE rather than DISCARD: the results are positive, robust to the one
parameter that was swept, and short of the bar on risk-adjusted grounds rather than
on direction. Calling that a DISCARD would overstate what was tested — and the
biggest single component of the source's rule, the cross-sectional ranking, was never
tested at all.

**What would change this verdict:** running the real rule on a 20-coin universe with
genuine cross-sectional ranking. That is the same build Strategy #1's write-up flagged
— the runner cannot currently rank a universe — and it is now the second strategy
blocked on it. Worth noting that a wider universe should help this one specifically:
its problem is not a broken rule but too few independent bets, and ranking twenty
coins is how the source gets both more trades and better selection. Flagged as a
possible revisit, not scheduled.

### Funding cost — flagged, and this time the omission is NOT conservative

Bybit charges or pays funding on a perpetual every 8 hours. Measured average holds on
the native exit: 1H holds 452.1 bars = 452 hours = about 57 funding windows; 4H holds 104.0 bars = 416 hours = about 52 funding windows; 1D holds 16.8 bars = 402 hours = about 50 funding windows. So every native trade spans roughly fifty funding windows,
which is far more exposure to funding than Strategy #1 had.

The direction matters here in a way it did not for Strategy #1. That strategy was
short only, and a short *receives* funding when the rate is positive, so the unknown
could have been a hidden credit. **This strategy is long-biased** — about
79%
of trades are longs — and a long *pays* funding when the rate is positive. Worse, the
Bitcoin switch only lets it trade while Bitcoin is above its 30-day average, which is
exactly the condition in which funding rates are usually positive. So the most likely
sign of the unmodelled cost is negative, and **this omission cannot be claimed to be
conservative.**

How much would it take to matter? The table below assumes Bybit's baseline rate of
0.01% per 8-hour window — **an assumption, not a measurement; this
project has not collected historical funding rates:**

| Timeframe | Funding windows per trade | Cost of notional at baseline | Cost in R (1R = 8.2–13.7% of price) | Measured native edge |
|---|---|---|---|---|
| 1H | 57 | 0.57% | 0.041–0.069R | +0.971R |
| 4H | 52 | 0.52% | 0.038–0.064R | +0.859R |
| 1D | 50 | 0.50% | 0.037–0.061R | +0.807R |

At the baseline rate the effect is real but small against the native edge — a few
percent of it. It is not small against the forced-1:3 edge, where it would consume a
meaningful share of it. And the baseline is a floor rather than a typical value: in
strong bull markets, which is exactly when this strategy is long and fully exposed,
funding has run well above baseline for extended stretches.

Per the standing rule: no KEEP is being claimed, so nothing is blocked today. But this
is now on record as a strategy where funding must be measured before any KEEP could be
treated as real — and the native exit sits close enough to the bar that funding could
plausibly decide it.

### Also not modelled

Slippage and order-book depth. Two caveats belong to the source rather than to these
numbers: its universe is the 2026 top-20 applied backwards, which is survivorship bias
in its +117% headline (not in this entry — these three coins were fixed in advance and
all three still trade), and its stated in-sample and held-out windows overlap by a full
year, which undercuts its walk-forward claim.

---

## Strategy #3 — AdaptiveTrend (crypto trend-following), momentum + monthly Sharpe gate + ATR trail

**Tested:** 2026-09-05 · **Coins:** BTCUSDT, SOLUSDT, XRPUSDT
(Bybit USDT perpetuals) · **Timeframes:** 1H, 4H, **6H**, 1D · **Direction:** long and
short · **Source's own cadence:** monthly portfolio rebuild, trailing stop in between

**Source:** *AdaptiveTrend* — an academic preprint on adaptive trend-following in
crypto perpetual futures ([arXiv HTML edition](https://arxiv.org/html/2602.11708v1))
· sourcing rated **strong** (full method in equations, six result tables, its own
ablation study).

**A fourth timeframe was added for this strategy.** Every earlier entry in this log
runs on 1H, 4H and 1D. This source's headline number is on **6-hour bars**, and its
own timeframe table makes the bar size part of the claim, so 6H was added to the data
layer and is tested here. That is why this section has eight rows instead of six.

### The rules, in plain English

Four moving parts, and only two of them are things a chart trader would recognise.

1. **A momentum trigger.** Measure how far price has moved over a fixed lookback.
   Buy when that move is positive by more than a threshold; sell short when it is
   negative by more than a threshold.
2. **A monthly quality screen.** On the first day of each month, ask of each coin:
   over the month just finished, how good was its *risk-adjusted* return — its
   Sharpe ratio? A coin needs at least **1.3** to be allowed on the long side and
   at least **1.7** to be allowed on the short side. This is a pass/fail gate, not
   a beauty contest between coins, which matters: unlike Strategy #2's ranking leg,
   a gate works exactly the same with three coins as with a hundred and fifty, so
   this part IS faithfully reproducible here.
3. **A trailing stop that only ever tightens.** The stop sits a fixed multiple of
   average range below price (2.5 x ATR), and each bar it moves up to follow price
   but never back down. When price trades through it, the position is out. There is
   no take-profit anywhere in the system.
4. **A monthly rebuild.** Positions are reconstructed each month from whichever
   coins still pass the screen, 70% of gross exposure to longs and 30% to shorts.

**Market condition it suits:** sustained trends with expanding volatility, in either
direction. The monthly Sharpe gate is the part that is supposed to keep it out of
chop — a coin that chopped sideways last month has a low Sharpe and is not eligible
this month, regardless of what its raw momentum says.

### What could NOT be reproduced here — and which way each gap biases the result

This is the part that decides how much weight the numbers below can carry, so it
comes before them.

1. **The market-cap filter.** The source screens on market capitalisation first:
   longs may only come from the top 15 coins by cap, shorts only from the bottom of
   the ranking. This project trades three coins and all three are large caps, so
   there is no bottom of a ranking to draw from. **Under the source's own rule, none
   of BTC, SOL or XRP could ever have been a short candidate at all.** Dropping the
   filter therefore makes the short leg tested here *more* permissive than the
   source's, not less. That is the honest direction to declare: it means a poor short
   result here cannot be excused by the filter's absence.
2. **The 70/30 long/short exposure tilt.** This harness risks a fixed 1% of equity
   per trade, so there is no gross-exposure knob for a tilt to turn. The two legs are
   reported separately instead, which shows the same information without inventing a
   portfolio weighting the source did not specify per-trade.
3. **The monthly re-optimisation — deliberately not reproduced.** The source re-fits
   the lookback, the thresholds and the stop multiple every month on recent data, then
   reports the result as out-of-sample. Re-fitting a rule monthly and calling the
   output out-of-sample is curve-fitting, and the source's own ablation table prices
   it exactly: strip the monthly re-fit and Sharpe falls from 2.41 to **1.34**.
   **So the honest comparison target for the fixed-parameter test below is
   1.34, not 2.41.** Every table here compares against both, side by side, so
   the distinction cannot get lost.
4. **Slippage.** Not modelled anywhere in this project. Fees are.
5. **Funding.** Not modelled. Quantified as an illustration at the end, because these
   are multi-day holds and the omission is not small.
6. **Different exchange, universe and window.** The source used Binance Futures,
   150+ perpetuals, Jan 2021 – Dec 2024. This is Bybit, three coins, and history that
   runs to today. Three coins cannot diversify the way 150 can, so the drawdowns here
   are structurally harsher than a 150-coin portfolio's would be.

### Parameters: what the source states, and what had to be guessed

| Parameter | In the source | Used here | Status |
|---|---|---|---|
| Long Sharpe gate (γ_L) | 1.3 | 1.3 | **stated** |
| Short Sharpe gate (γ_S) | 1.7 | 1.7 | **stated** |
| Screen window | "the single preceding month" | 30 days | **stated** |
| Trailing-stop multiple (α) | ≈2.5, flat 2.0–3.5 | 2.5 | **stated** |
| Screen cadence | first trading day of the month | first bar of the month | **stated** |
| Momentum lookback (L) | **never given a value** | 14 days | **GUESS — swept below** |
| Entry threshold (θ) | **never given a value** | 0% | **GUESS — swept below** |
| ATR period (k) | **never given a value** | 14 bars | **GUESS** |
| Number of shorts (K_S) | **never given a value** | not applicable (gate, not ranking) | n/a |

Three of the numbers that decide *when this thing trades at all* are absent from a
paper that reports its Sharpe to two decimal places. That is why the sensitivity
sweeps below are not optional extras — they are the only way to tell whether the
result belongs to the rule or to the guesses.

### The contradiction in the source that had to be resolved

The paper says a coin needs a **Sharpe of at least +1.7 to be a SHORT candidate**.
Read as the coin's own Sharpe that is incoherent: a coin with a strongly positive
risk-adjusted return is trending *up*, and shorting it contradicts the momentum rule
in the very same system. The coherent reading is the Sharpe of the *candidate
position*, so for a short it is the Sharpe of the inverse of the coin's returns —
i.e. the coin's own Sharpe at or below **−1.7**. That is what is traded here. The
literal reading is also **counted** — how many monthly screens it would have
permitted a short on — and reported below, so the choice is visible and measurable
rather than buried in a code comment.

### How 1R is defined here, and why it differs from Strategy #2

1R is 2.5 x ATR **of the trading timeframe**. Strategy #2 normalised its stop to a
daily-equivalent range so its timeframes stayed comparable to each other. Here the
opposite choice is correct: the source's formula explicitly uses the trading
timeframe's ATR, and the source's headline claim is that the 6-hour bar beats the
1-hour and the daily. Normalising the stop across timeframes would erase the exact
effect under test.

The consequence has to be stated plainly: **1R is a different amount of real risk on
each row of the results table** — wider on the daily, narrower on the hourly. The
four timeframes here are therefore NOT directly comparable to one another. Each is
comparable to the source's own number for that timeframe, which is the comparison
that matters.

### Lookahead check, run fresh for this strategy

Three places on this strategy needed care, and each was handled before any number
was produced:

- **The trailing stop.** The level in force during a bar is built from the *previous*
  bar's close and ATR. If it used the current bar's, the stop would be positioned
  using the very price range it is then compared against — the position would appear
  to exit at a level that could only be known after the fact.
- **The monthly screen.** The Sharpe is measured over the window ending one bar
  *before* the month's first bar, sampled only on that first bar, then carried
  forward unchanged. Carrying a value forward can only ever propagate something
  already known.
- **The entry trigger.** It compares this bar's eligibility with the previous bar's,
  so both inputs are closed bars.

Beyond reasoning, this is checked mechanically. The audit recomputes every indicator
on truncated history — as if the run had stopped at that bar — and compares each
value against the one computed with the full history available. Any column that
disagrees was reading the future. **12 of 12 coin x timeframe datasets PASS**, across
all 14 computed columns: `atr, gate_long, gate_short, gate_short_literal, long_entry, long_ok, mom, month_start, short_entry, short_ok, sr_screen, stop_frac, trail_long, trail_short`. Decisions are made on closed bars and
filled at the next bar's open throughout.

### How much history these numbers cover

Trade count on its own does not say how long a period a result is drawn from,
so the window is recorded per coin. What is measured is the TRADEABLE window:
the first bar the rule is allowed to act on, after the warmup, through the last
closed bar in the data. The three coins do not start together - Bitcoin's history
on this venue begins in March 2020, XRP in May 2021, Solana in October 2021 - so a
pooled row is not three equal thirds.

Warmup skipped before the first trade: 1H 864, 4H 216, 6H 144, 1D 120. That subtraction costs very
little at 1H and a great deal at 1D, where a warmup bar is a whole day.

| Timeframe | Coin | Window traded | Days | Years | Tradeable bars | Warmup bars |
|---|---|---|---|---|---|---|
| 1H | BTCUSDT | 2020-04-30 to 2026-09-05 | 2319 | 6.35 | 55,647 | 864 |
| 1H | SOLUSDT | 2021-11-20 to 2026-09-05 | 1750 | 4.79 | 42,001 | 864 |
| 1H | XRPUSDT | 2021-06-18 to 2026-09-05 | 1905 | 5.21 | 45,712 | 864 |
| 4H | BTCUSDT | 2020-04-30 to 2026-09-05 | 2319 | 6.35 | 13,913 | 216 |
| 4H | SOLUSDT | 2021-11-20 to 2026-09-05 | 1750 | 4.79 | 10,501 | 216 |
| 4H | XRPUSDT | 2021-06-18 to 2026-09-05 | 1905 | 5.21 | 11,429 | 216 |
| 6H | BTCUSDT | 2020-04-30 to 2026-09-05 | 2319 | 6.35 | 9,277 | 144 |
| 6H | SOLUSDT | 2021-11-20 to 2026-09-05 | 1750 | 4.79 | 7,002 | 144 |
| 6H | XRPUSDT | 2021-06-18 to 2026-09-05 | 1905 | 5.22 | 7,621 | 144 |
| 1D | BTCUSDT | 2020-07-23 to 2026-09-04 | 2234 | 6.12 | 2,235 | 120 |
| 1D | SOLUSDT | 2022-02-12 to 2026-09-04 | 1665 | 4.56 | 1,666 | 120 |
| 1D | XRPUSDT | 2021-09-10 to 2026-09-04 | 1820 | 4.98 | 1,821 | 120 |

Shortest window in this run: SOLUSDT at 1D, 1665 days (4.56 years). Longest: BTCUSDT at 6H, 2319 days (6.35 years).

### Results — three coins pooled per timeframe, post-fee

Fees: 0.055% taker on entry and on exit. Both variants run off the **same entry
signals** and the **same 1R distance**, so any difference between them is the exit
and nothing else. R = one unit of risk; +1R means the trade made what it was risking.

| Timeframe | Exit | Trades | Days BTC | Days SOL | Days XRP | Win% | RR | R (pre-fee) | R (post-fee) | R/trade | Sharpe | Max DD % | Max DD (R) | R-recovery | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1H | native | 702 | 2319 | 1750 | 1905 | 36.2 | 2.13 | 102.2 | 63.0 | 0.090 | 0.46 | 48.2 | 74.7 | 0.84 | **INCONCLUSIVE** |
| 1H | forced-1:3 | 672 | 2319 | 1750 | 1905 | 42.4 | 1.30 | 22.3 | -15.4 | -0.023 | -0.18 | 59.1 | 71.0 | -0.22 | **DISCARD** |
| 4H | native | 389 | 2319 | 1750 | 1905 | 37.0 | 2.11 | 47.9 | 38.1 | 0.098 | 0.38 | 20.4 | 28.9 | 1.32 | **INCONCLUSIVE** |
| 4H | forced-1:3 | 352 | 2319 | 1750 | 1905 | 38.4 | 1.52 | -1.8 | -10.6 | -0.030 | -0.17 | 36.0 | 42.4 | -0.25 | **DISCARD** |
| 6H | native | 317 | 2319 | 1750 | 1905 | 37.9 | 1.95 | 30.7 | 24.4 | 0.077 | 0.35 | 19.7 | 26.9 | 0.91 | **INCONCLUSIVE** |
| 6H | forced-1:3 | 279 | 2319 | 1750 | 1905 | 40.9 | 1.57 | 17.7 | 12.2 | 0.044 | 0.21 | 19.8 | 23.8 | 0.51 | **DISCARD** |
| 1D | native | 154 | 2234 | 1665 | 1820 | 33.1 | 2.34 | 10.7 | 9.3 | 0.060 | 0.15 | 15.5 | 18.0 | 0.52 | **DISCARD** |
| 1D | forced-1:3 | 131 | 2234 | 1665 | 1820 | 42.0 | 1.45 | 4.7 | 3.5 | 0.027 | 0.09 | 17.3 | 20.0 | 0.18 | **DISCARD** |

**Against the source's own per-timeframe claims.** This is the comparison the source
invites by publishing a timeframe table, so here it is with no cushioning:

| Timeframe | Sharpe here (native) | Source's claim | Source, parameters not re-fitted | Trades/month here | Trades/month in source |
|---|---|---|---|---|---|
| 1H | 0.46 | 1.54 | 1.34 | 10.6 | 847 |
| 4H | 0.38 | 2.08 | 1.34 | 5.9 | 213 |
| 6H | 0.35 | 2.41 | 1.34 | 4.8 | 142 |
| 1D | 0.15 | 1.63 | 1.34 | 2.4 | 41 |

The trade counts alone settle something before the Sharpe column does. The source
reports 142 trades per month on 6H across 150+ perpetuals; that is roughly
one trade per coin per month. Here the rate is 4.8 per month across three coins.
Same *rule*, a fiftieth of the *breadth* — so the portfolio effect that produces the
source's smooth equity curve simply cannot exist in this test, whatever the rule does.

### How the trades ended

- 1H native: rebalance 17, stop 685 — average hold 21.6 bars (0.9 days), fees cost 0.056R per trade, best conditions up/lowvol, worst down/highvol
- 1H forced-1:3: stop 297, target 48, time 327 — average hold 20.8 bars (0.9 days), fees cost 0.056R per trade, best conditions up/lowvol, worst down/highvol
- 4H native: rebalance 22, stop 367 — average hold 18.9 bars (3.1 days), fees cost 0.025R per trade, best conditions down/lowvol, worst down/highvol
- 4H forced-1:3: stop 164, target 29, time 159 — average hold 20.5 bars (3.4 days), fees cost 0.025R per trade, best conditions up/highvol, worst down/highvol
- 6H native: rebalance 33, stop 284 — average hold 17.8 bars (4.4 days), fees cost 0.020R per trade, best conditions up/lowvol, worst down/highvol
- 6H forced-1:3: stop 125, target 26, time 128 — average hold 20.5 bars (5.1 days), fees cost 0.020R per trade, best conditions down/lowvol, worst down/highvol
- 1D native: rebalance 42, stop 112 — average hold 14.7 bars (14.7 days), fees cost 0.009R per trade, best conditions down/lowvol, worst range/lowvol
- 1D forced-1:3: stop 62, target 10, time 59 — average hold 20.4 bars (20.4 days), fees cost 0.009R per trade, best conditions up/highvol, worst range/lowvol

### The long leg against the short leg

Remember the market-cap filter: under the source's own rule none of these three coins
could ever be a short candidate. Everything in the short column is therefore *more*
permissive than the source's short leg, not less.

| Timeframe | Exit | Long trades | Long R | Long win% | Short trades | Short R | Short win% |
|---|---|---|---|---|---|---|---|
| 1H | native | 402 | +10.1 | 31.8 | 300 | +52.8 | 42.0 |
| 1H | forced-1:3 | 372 | -36.7 | 40.3 | 300 | +21.3 | 45.0 |
| 4H | native | 212 | +8.5 | 31.6 | 177 | +29.6 | 43.5 |
| 4H | forced-1:3 | 193 | -19.6 | 34.2 | 159 | +8.9 | 43.4 |
| 6H | native | 168 | +16.1 | 33.3 | 149 | +8.3 | 43.0 |
| 6H | forced-1:3 | 148 | -5.8 | 36.5 | 131 | +18.0 | 45.8 |
| 1D | native | 79 | +10.4 | 25.3 | 75 | -1.1 | 41.3 |
| 1D | forced-1:3 | 68 | +0.8 | 38.2 | 63 | +2.7 | 46.0 |

### The short-gate ambiguity, counted rather than argued about

Both readings of "Sharpe ≥ 1.7 to short" were evaluated on every monthly screen. Only
the coherent one was traded.

| Timeframe | Monthly screens | Coherent reading permits a short | Literal reading permits a short | Both agree |
|---|---|---|---|---|
| 1H | 198 | 59 (30%) | 72 (36%) | 0 |
| 4H | 198 | 60 (30%) | 72 (36%) | 0 |
| 6H | 198 | 59 (30%) | 72 (36%) | 0 |
| 1D | 189 | 59 (31%) | 69 (37%) | 0 |

### Exit-death check — does the edge live in the rule or in the exit?

- **1H: exit-death = YES.** the exit flips the sign of the edge: native +0.090R per trade vs forced 1:3 -0.023R. Identical entries, so the entry signal is not what decided this - the forced 1:3 exit is. The edge, such as it is, lives in the native exit.
- **4H: exit-death = YES.** the exit flips the sign of the edge: native +0.098R per trade vs forced 1:3 -0.030R. Identical entries, so the entry signal is not what decided this - the forced 1:3 exit is. The edge, such as it is, lives in the native exit.
- **6H: exit-death = NO.** the two exits land within 0.033R per trade of each other (native +0.077R vs forced 1:3 +0.044R), so the result is driven by the entry signal rather than by the choice of exit
- **1D: exit-death = NO.** the two exits land within 0.034R per trade of each other (native +0.060R vs forced 1:3 +0.027R), so the result is driven by the entry signal rather than by the choice of exit

The wording of those flags says "identical entries". On this strategy that is only 73%–82% true — see the fairness check below, which is why the flags are indicative rather than conclusive here.

### Was this a fair test?

```
1H:
  native        702 trades | pre-fee +0.1456R/trade (spread 1.99R, t = +1.94) | post-fee +0.0897R/trade (t = +1.20)
  forced-1:3    672 trades | pre-fee +0.0332R/trade (spread 1.22R, t = +0.71) | post-fee -0.0230R/trade (t = -0.49)
  resolved inside their first candle: native 1%, forced-1:3 1%
  the two variants share 82.1% of their entries  <-- TOO LOW to compare exits fairly
4H:
  native        389 trades | pre-fee +0.1231R/trade (spread 1.69R, t = +1.44) | post-fee +0.0980R/trade (t = +1.15)
  forced-1:3    352 trades | pre-fee -0.0051R/trade (spread 1.28R, t = -0.08) | post-fee -0.0302R/trade (t = -0.44)
  resolved inside their first candle: native 1%, forced-1:3 1%
  the two variants share 80.8% of their entries  <-- TOO LOW to compare exits fairly
6H:
  native        317 trades | pre-fee +0.0970R/trade (spread 1.53R, t = +1.13) | post-fee +0.0769R/trade (t = +0.89)
  forced-1:3    279 trades | pre-fee +0.0636R/trade (spread 1.28R, t = +0.83) | post-fee +0.0438R/trade (t = +0.57)
  resolved inside their first candle: native 1%, forced-1:3 1%
  the two variants share 79.4% of their entries  <-- TOO LOW to compare exits fairly
1D:
  native        154 trades | pre-fee +0.0695R/trade (spread 1.56R, t = +0.55) | post-fee +0.0604R/trade (t = +0.48)
  forced-1:3    131 trades | pre-fee +0.0361R/trade (spread 1.28R, t = +0.32) | post-fee +0.0269R/trade (t = +0.24)
  resolved inside their first candle: native 2%, forced-1:3 2%
  the two variants share 73.0% of their entries  <-- TOO LOW to compare exits fairly
```

**The exit-death check's precondition is not met on this strategy.** The two variants share only 73%–82% of their entries, against the 85% floor this project requires before "same entries, only the exit differs" can be claimed. The cause is structural rather than a bug: the native exit has no time limit and the forced variant closes at 30 bars, so the two variants are in the market at different times and become eligible to re-enter at different moments. Read every exit-death flag above as indicative only.

The largest t-statistic on per-trade R anywhere in the grid is **1.94**; roughly 2 is
the minimum before a result is distinguishable from noise, and nothing here reaches it.

### The size of 1R, and what it does to the forced 1:3 test

| Timeframe | Coin | Measured 1R (% of price) | Typical candle (%) | 1R as a multiple of one candle | 3R target sits |
|---|---|---|---|---|---|
| 1H | BTCUSDT | 1.80% | 0.62% | 2.9x | 5% away |
| 1H | SOLUSDT | 3.20% | 1.14% | 2.8x | 10% away |
| 1H | XRPUSDT | 2.51% | 0.89% | 2.8x | 8% away |
| 4H | BTCUSDT | 3.79% | 1.34% | 2.8x | 11% away |
| 4H | SOLUSDT | 6.62% | 2.42% | 2.7x | 20% away |
| 4H | XRPUSDT | 5.39% | 1.90% | 2.8x | 16% away |
| 6H | BTCUSDT | 4.69% | 1.68% | 2.8x | 14% away |
| 6H | SOLUSDT | 8.23% | 2.96% | 2.8x | 25% away |
| 6H | XRPUSDT | 6.64% | 2.35% | 2.8x | 20% away |
| 1D | BTCUSDT | 10.24% | 3.70% | 2.8x | 31% away |
| 1D | SOLUSDT | 17.16% | 6.44% | 2.7x | 51% away |
| 1D | XRPUSDT | 14.45% | 5.03% | 2.9x | 43% away |

This is the mirror image of Strategy #1's problem. There the stop was *narrower* than
a single candle, so the pessimistic intrabar tie-break decided most trades. Here 1R
is **2.7x a typical candle at its smallest**, and measured 1R ranges from 1.80% to
17.16% of price — which puts the forced variant's 3R target between 5% and 51%
away from entry. A move that large inside 30 bars is rare, so the forced-1:3
variant is again a partly handicapped comparison: its time limit, not its target, is
doing most of the deciding. That is a limitation of the standard test applied to a
wide-stop strategy, not evidence about the strategy — and it is the third time in a
row this has shown up, which is itself worth remembering.

### Where the money actually went

| Timeframe | Exit | Trades | Before fees | Fee bill | After fees |
|---|---|---|---|---|---|
| 1H | native | 702 | +102.2R | 39.2R | +63.0R |
| 1H | forced-1:3 | 672 | +22.3R | 37.7R | -15.4R |
| 4H | native | 389 | +47.9R | 9.8R | +38.1R |
| 4H | forced-1:3 | 352 | -1.8R | 8.8R | -10.6R |
| 6H | native | 317 | +30.7R | 6.4R | +24.4R |
| 6H | forced-1:3 | 279 | +17.7R | 5.5R | +12.2R |
| 1D | native | 154 | +10.7R | 1.4R | +9.3R |
| 1D | forced-1:3 | 131 | +4.7R | 1.2R | +3.5R |

### Per-coin breakdown — not pooled

Pooling is where one coin carrying, or sinking, everything would be invisible.

```
coin      timeframe  exit         trades   win%     RR    R pre   R post  R/trade  Sharpe     DD%    DD R  recov  verdict
-------------------------------------------------------------------------------------------------------------------------
BTCUSDT   1H         native          306   37.3   2.78    102.0     79.3    0.259    0.67    21.1    31.3   2.54  INCONCLUSIVE
BTCUSDT   1H         forced-1:3      293   45.4   1.28     30.3      8.6    0.029    0.16    21.3    24.9   0.35  DISCARD
BTCUSDT   4H         native          159   42.8   2.51     56.2     51.0    0.321    0.76     6.9     9.3   5.47  KEEP
BTCUSDT   4H         forced-1:3      146   45.2   1.55     23.6     18.9    0.130    0.47     9.9    12.0   1.58  INCONCLUSIVE
BTCUSDT   6H         native          130   43.8   2.42     43.6     40.2    0.309    0.77     6.5     8.8   4.58  KEEP
BTCUSDT   6H         forced-1:3      115   47.0   1.65     26.5     23.7    0.206    0.65     5.8     6.9   3.44  INCONCLUSIVE
BTCUSDT   1D         native           60   43.3   2.85     20.7     20.0    0.334    0.69     3.9     4.6   4.33  INCONCLUSIVE
BTCUSDT   1D         forced-1:3       54   44.4   1.87     13.8     13.1    0.243    0.49     6.6     7.4   1.78  INCONCLUSIVE
SOLUSDT   1H         native          188   32.4   2.00      3.5     -3.4   -0.018   -0.08    26.3    28.3  -0.12  DISCARD
SOLUSDT   1H         forced-1:3      183   36.6   1.47     -8.8    -15.7   -0.086   -0.43    33.5    35.5  -0.44  DISCARD
SOLUSDT   4H         native          110   33.6   2.02      3.1      1.1    0.010    0.03    15.8    17.9   0.06  DISCARD
SOLUSDT   4H         forced-1:3       95   33.7   1.51    -11.1    -12.8   -0.135   -0.50    21.6    22.2  -0.58  DISCARD
SOLUSDT   6H         native           88   31.8   1.86     -4.2     -5.5   -0.062   -0.17    19.3    21.3  -0.26  DISCARD
SOLUSDT   6H         forced-1:3       76   38.2   1.45     -3.2     -4.3   -0.057   -0.18    16.1    17.5  -0.25  DISCARD
SOLUSDT   1D         native           45   26.7   3.19      3.6      3.3    0.074    0.11     7.3     7.4   0.45  DISCARD
SOLUSDT   1D         forced-1:3       39   43.6   1.21     -1.1     -1.3   -0.034   -0.08     9.3     9.4  -0.14  DISCARD
XRPUSDT   1H         native          208   38.0   1.40     -3.3    -13.0   -0.062   -0.36    27.1    29.1  -0.44  DISCARD
XRPUSDT   1H         forced-1:3      196   43.4   1.20      0.8     -8.4   -0.043   -0.22    28.5    31.3  -0.27  DISCARD
XRPUSDT   4H         native          120   32.5   1.49    -11.4    -14.0   -0.117   -0.60    16.7    17.3  -0.81  DISCARD
XRPUSDT   4H         forced-1:3      111   33.3   1.48    -14.3    -16.8   -0.151   -0.57    20.5    21.3  -0.79  DISCARD
XRPUSDT   6H         native           99   35.4   1.37     -8.6    -10.3   -0.105   -0.47    15.5    16.4  -0.63  DISCARD
XRPUSDT   6H         forced-1:3       88   35.2   1.56     -5.6     -7.1   -0.081   -0.28    11.8    12.0  -0.60  DISCARD
XRPUSDT   1D         native           49   26.5   0.93    -13.7    -14.0   -0.287   -1.27    16.6    17.0  -0.83  DISCARD
XRPUSDT   1D         forced-1:3       38   36.8   1.01     -8.0     -8.3   -0.218   -0.61    13.1    13.4  -0.62  DISCARD
```

### Verdicts, applied to each exit variant separately

- **1H / native exit — INCONCLUSIVE.** positive but short of the KEEP bar: expectancy +0.090R < +0.10R; Sharpe 0.46 < 0.7; R-recovery 0.84 < 1.5
- **1H / forced 1:3 — DISCARD.** post-fee expectancy -0.023R per trade is not positive; post-fee Sharpe -0.18 below 0.3; earned only -0.22x its worst drawdown (its own fee-derived breakeven win rate is 26.4%)
- **4H / native exit — INCONCLUSIVE.** positive but short of the KEEP bar: expectancy +0.098R < +0.10R; Sharpe 0.38 < 0.7; R-recovery 1.32 < 1.5
- **4H / forced 1:3 — DISCARD.** post-fee expectancy -0.030R per trade is not positive; post-fee Sharpe -0.17 below 0.3; earned only -0.25x its worst drawdown (its own fee-derived breakeven win rate is 25.6%)
- **6H / native exit — INCONCLUSIVE.** positive but short of the KEEP bar: expectancy +0.077R < +0.10R; Sharpe 0.35 < 0.7; R-recovery 0.91 < 1.5
- **6H / forced 1:3 — DISCARD.** post-fee Sharpe 0.21 below 0.3 (its own fee-derived breakeven win rate is 25.5%)
- **1D / native exit — DISCARD.** post-fee Sharpe 0.15 below 0.3
- **1D / forced 1:3 — DISCARD.** post-fee Sharpe 0.09 below 0.3; earned only 0.18x its worst drawdown (its own fee-derived breakeven win rate is 25.2%)

### Sensitivity 1 — the momentum lookback the source never states

L is not in the paper. 14 days was the placeholder traded above. If the result only
survives at one setting, the result belongs to the setting.

| Lookback L | Timeframe | Exit | Trades | Win% | R (post-fee) | R/trade | Sharpe | Verdict |
|---|---|---|---|---|---|---|---|---|
| 7 days | 1H | native | 949 | 33.7 | 7.6 | 0.008 | 0.06 | DISCARD |
| 7 days | 1H | forced-1:3 | 920 | 40.0 | -20.5 | -0.022 | -0.19 | DISCARD |
| 7 days | 4H | native | 519 | 35.3 | 60.9 | 0.117 | 0.48 | INCONCLUSIVE |
| 7 days | 4H | forced-1:3 | 478 | 37.2 | -17.3 | -0.036 | -0.23 | DISCARD |
| 7 days | 6H | native | 429 | 35.7 | 28.3 | 0.066 | 0.32 | INCONCLUSIVE |
| 7 days | 6H | forced-1:3 | 376 | 41.5 | 11.4 | 0.030 | 0.17 | DISCARD |
| 7 days | 1D | native | 192 | 32.8 | 7.0 | 0.036 | 0.11 | DISCARD |
| 7 days | 1D | forced-1:3 | 150 | 41.3 | 11.2 | 0.074 | 0.27 | DISCARD |
| 14 days | 1H | native | 702 | 36.2 | 63.0 | 0.090 | 0.46 | INCONCLUSIVE |
| 14 days | 1H | forced-1:3 | 672 | 42.4 | -15.4 | -0.023 | -0.18 | DISCARD |
| 14 days | 4H | native | 389 | 37.0 | 38.1 | 0.098 | 0.38 | INCONCLUSIVE |
| 14 days | 4H | forced-1:3 | 352 | 38.4 | -10.6 | -0.030 | -0.17 | DISCARD |
| 14 days | 6H | native | 317 | 37.9 | 24.4 | 0.077 | 0.35 | INCONCLUSIVE |
| 14 days | 6H | forced-1:3 | 279 | 40.9 | 12.2 | 0.044 | 0.21 | DISCARD |
| 14 days | 1D | native | 154 | 33.1 | 9.3 | 0.060 | 0.15 | DISCARD |
| 14 days | 1D | forced-1:3 | 131 | 42.0 | 3.5 | 0.027 | 0.09 | DISCARD |
| 28 days | 1H | native | 443 | 33.9 | -1.8 | -0.004 | -0.02 | DISCARD |
| 28 days | 1H | forced-1:3 | 441 | 42.2 | -19.8 | -0.045 | -0.29 | DISCARD |
| 28 days | 4H | native | 275 | 36.4 | 8.2 | 0.030 | 0.12 | DISCARD |
| 28 days | 4H | forced-1:3 | 267 | 36.3 | -16.9 | -0.063 | -0.31 | DISCARD |
| 28 days | 6H | native | 234 | 37.2 | 4.5 | 0.019 | 0.08 | DISCARD |
| 28 days | 6H | forced-1:3 | 229 | 41.5 | 7.1 | 0.031 | 0.13 | DISCARD |
| 28 days | 1D | native | 143 | 30.8 | -12.7 | -0.089 | -0.36 | DISCARD |
| 28 days | 1D | forced-1:3 | 126 | 31.0 | -18.0 | -0.143 | -0.50 | DISCARD |

**0 of the 24 lookback x timeframe x exit combinations reach KEEP.**

### Sensitivity 2 — the entry threshold, and state versus cross

Also undisclosed: how far momentum must move before the trade is taken. And one
judgement call of mine that deserves to be tested rather than defended. The paper
states the entry as a *state* ("long while momentum exceeds θ"), but a state condition
combined with a trailing stop re-enters on the bar after every stop-out, which
measures the stop's churn instead of the strategy. The edge-triggered version is what
was traded; the state version is run here so the choice is visible. Both on 6H only,
since these are questions about undisclosed detail rather than about the rule.

| Variant (6H) | Exit | Trades | Win% | R (post-fee) | R/trade | Sharpe | Verdict |
|---|---|---|---|---|---|---|---|
| threshold 0% (traded) | native | 317 | 37.9 | 24.4 | 0.077 | 0.35 | INCONCLUSIVE |
| threshold 0% (traded) | forced-1:3 | 279 | 40.9 | 12.2 | 0.044 | 0.21 | DISCARD |
| threshold 2% | native | 312 | 35.3 | 15.7 | 0.050 | 0.23 | DISCARD |
| threshold 2% | forced-1:3 | 275 | 40.4 | 19.3 | 0.070 | 0.32 | INCONCLUSIVE |
| threshold 5% | native | 261 | 34.9 | 12.7 | 0.049 | 0.23 | DISCARD |
| threshold 5% | forced-1:3 | 248 | 40.7 | 0.0 | 0.000 | 0.00 | DISCARD |
| state-triggered entry | native | 537 | 37.6 | 42.2 | 0.079 | 0.46 | INCONCLUSIVE |
| state-triggered entry | forced-1:3 | 543 | 42.5 | 40.9 | 0.075 | 0.48 | INCONCLUSIVE |

### Bottom line

**0 of 8 tested variants clear the discard bar: none.**

The source's headline is Sharpe 2.41 on 6H. Its own honest comparison row — the same
rule without monthly re-fitting — is 1.34. This test measured **0.35** on 6H with
the native trailing-stop exit, on 317 trades, +24.4R post-fee. The strongest
timeframe here was **1H** (0.46 Sharpe, +63.0R, 702 trades native).

Five things constrain how much any of that means:

- **One coin carried it.** Native exit, counted per timeframe rather than summed across them: BTCUSDT positive on 4 of 4, SOLUSDT positive on 2 of 4, XRPUSDT positive on 0 of 4. BTCUSDT is the strongest of the three. The per-coin table reaches KEEP in 2 places — BTCUSDT 4H native, BTCUSDT 6H native — and pooling those with the other two coins is what turns them into an INCONCLUSIVE. On a three-coin test a single-coin KEEP is a curiosity, not a finding: it is exactly where 22 strategies tested across three instruments will throw up winners by chance.
- **Breadth.** Three coins against 150+. The monthly Sharpe gate is faithfully
  reproduced, but the diversification that turns a modest per-trade edge into a smooth
  equity curve is not available at three coins and never will be.
- **The short leg is more permissive here than in the source**, because the market-cap
  filter that would have excluded all three of these coins from shorting cannot be
  applied. Across the four timeframes the short leg produced +89.7R against the long leg's +45.1R (native exit), losing money on 1 of the 4 timeframes. **So the leg that carried this test is the leg the source's own filter would have forbidden outright on these three coins.** That does not support the source — it means the part of the result that looks best here is the part least connected to what the source actually specifies.
  Longs were 51%–57% of trades across the four timeframes.
- **Guessed parameters.** Three of the numbers governing when it trades are absent
  from the source. The sweeps above are the only evidence about whether the outcome is
  the rule's or the guesses'.
- **Funding is not modelled**, and these are multi-day holds. See below.

Nothing here clears the bar, so nothing needs a funding model to be resolved — the omission cannot rescue a losing result, it can only make it worse.

INCONCLUSIVE rather than DISCARD: 1H native, 4H native, 6H native. What would fix it is more instruments, not more history — this rule takes about one trade per coin per month by construction, so the trade count is bounded by how many coins are in the test, and three is the binding constraint.

### Funding cost — flagged, not modelled

Perpetual futures charge funding every 8 hours. It is **not modelled anywhere in this
project**. The holds here: 1H holds 21.6 bars = about 3 funding windows; 4H holds 18.9 bars = about 9 funding windows; 6H holds 17.8 bars = about 13 funding windows; 1D holds 14.7 bars = about 44 funding windows.

The table below is an *illustration* at Bybit's baseline rate (0.01% per window, the
value the rate sits at when longs and shorts are balanced) — not a measurement of what
funding actually was. Direction matters too: funding is a cost to whichever side is
crowded, so it is not automatically a cost to both legs.

| Timeframe | 8-hour windows per trade | Cost at baseline rate | That cost in R | Edge per trade now |
|---|---|---|---|---|
| 1H | 3 | 0.03% | 0.002–0.015R | +0.090R |
| 4H | 9 | 0.09% | 0.006–0.053R | +0.098R |
| 6H | 13 | 0.13% | 0.008–0.074R | +0.077R |
| 1D | 44 | 0.44% | 0.026–0.245R | +0.060R |

### Also not modelled

Slippage; the market-cap filter (structurally impossible at three coins); the 70/30
exposure tilt; the monthly re-optimisation (deliberately excluded as curve-fitting);
liquidation mechanics; borrow availability on the short leg.

## Strategy #4 - Crabel Opening Range Breakout ("the stretch")

**Tested:** 2026-09-05 · **Coins:** BTCUSDT, SOLUSDT, XRPUSDT ·
**Timeframes:** 1H, 4H, 6H, 1D · **Fees:** taker on both legs (0.055% each), every number below is post-fee ·
**Session boundary:** 00:00 UTC

**Source:** Toby Crabel, *Opening Range Breakout: A Century*, tobycrabel.substack.com, 2025.
This is the originator describing his own rule, which is the best-sourced strategy on the
list so far. Everything in the next section is a direct quotation.

### The rule, in the source's own words

* "Compute the distance, call it the stretch, and place a buy stop that far above the open
  and a sell stop that far below it."
* "The stretch is set at 0.8 times the ten-day range, held the same way throughout this book."
* "Whichever side trades first is the position."
* "There is no protective stop."
* "The trade is held until the next day's open, and exited there."

There is no setup filter and no trend filter in the baseline. Every session gets two orders.
He defends the missing stop rather than merely preferring it: "A stop is a second decision
layered on top of the first one", which would mix entry quality with exit quality and break
comparability across a century of data.

### What the source claims, and what he refuses to claim

Full-period stream-level **Sharpe 1.40**, stated GROSS of commissions and
slippage, on 84 equally weighted futures markets, January 1923 to July 2025. Decade averages
of annual Sharpe: 1970s-1990s above 6 · 2000s 2.92 · 2010s 0.91. 22 of 103 years negative.

He publishes **no win rate and no reward-to-risk on purpose**: "We think in dollars and Sharpe
here, not in percentages of winning trades." So there is no 1:3 claim attached to this
strategy. It is on the list as a documented long-run performer, not as a documented 1:3
system, and the forced-1:3 variant below is this project's imposition, not his.

### What this test could not reproduce, stated before any results

1. **The opening auction.** This is the largest adaptation in the project so far. Crabel's
   edge lives in a pit that closes overnight, gaps, and reopens with an auction that
   concentrates a night of orders into one moment. Crypto never closes. 00:00 UTC is used
   because it is what the exchange's own daily candle uses, but it is a timestamp, not an
   event. If this strategy fails here, "crypto has no opening auction" is a sufficient
   explanation on its own, and the failure does not disprove Crabel.
2. **Eighty-four markets.** His number is a portfolio Sharpe across grains, metals,
   energies, rates and currencies. Three correlated crypto perpetuals cannot reproduce it.
   This is the single largest reason to expect a lower number here, and it is a property of
   the test, not of the rule.
3. **Gross versus post-fee.** His 1.40 pays no commission. Every number here is post-fee at
   Bybit taker rates on both legs, so the comparison is deliberately unfair to this test.
4. **A hundred years.** He has 103 years. This has about six on BTC and less on the others.

### What "the ten-day range" means, which the source never resolves

Two readings are available and they differ by three to four times. **AVG** (the mean of the
last ten daily ranges) is traded as the baseline because it is the only reading that puts the
trigger a plausible distance from the open. **SPAN** (highest high minus lowest low over ten
days) would place the trigger about 14.1% from the open on these coins - measured, not
estimated - and would barely ever fill; it is run as a sensitivity rather than argued about. A third reading - the ten-day mean of the
smaller open-to-high / open-to-low tail, with no 0.8 multiplier - is described by third-party
indicator authors as the 1990 book's definition; I have not read the book, so that reading is
attributed to them and not to Crabel, and it is also run as a sensitivity.

### How 1R was defined here, and why it needed a decision

The source has no stop, so it has no natural risk unit, and every number in this project is
expressed in R. Inventing a stop and calling it Crabel's would misrepresent him. Instead
**1R = one stretch** - the same quantity that defines the entry - used as a measuring stick,
not as an order. The native variant enforces no stop whatsoever, exactly as written. Only the
forced-1:3 variant turns 1R into a real stop, which is what that variant is for.

One arithmetic consequence, stated before the results because it explains them: entry is one
stretch away from the open, so with 1R = one stretch the forced stop lands **exactly on the
session open**. That is a coincidence of the definition, not a choice. 1R = two stretches is
run as a sensitivity, which moves the forced stop onto the opposite trigger - the classic
stop-and-reverse level.

On these coins one stretch is about **4.49% of price**, so the 0.11% round-trip fee is
a small fraction of 1R. That is the opposite of Strategy #1's problem and it is why fee cost
per trade is around 0.031R here instead of a third of the edge.

### Lookahead bias: what was checked, freshly, for this strategy

Every computed column is rebuilt on truncated history - only bars up to and including bar *i*
exist - and compared with the same column computed on the full history. Any column that
changes when the future is removed would fail. **All 9 computed columns passed on every
dataset tested, to 1e-12, at 25 separate cut points.** Three places needed real care:

* **The stretch** is built from daily bars and then lagged one full day, so a bar on day D
  uses days D-10 through D-1 and never its own day.
* **The session open** is the only place in this project where a decision uses the current
  bar's own open. That is legitimate here and nowhere else: an open price is known at the
  instant the bar begins, which is exactly the instant Crabel places his two orders.
* **Session boundaries** are derived from the clock, never by asking "does the next row belong
  to a different day". The row-neighbour version would answer differently on the last bar of
  a truncated frame, and the audit would correctly fail it.

The new execution path deserves its own paragraph, because this strategy needed one. Crabel's
orders rest in the market at prices fixed before the session starts, and they fill intrabar at
their own price. So the engine must ask whether bar *i*'s high or low reached a resting level -
which means it does touch bar *i*'s high and low. That is not a relaxation of the rule. The
strategy is forbidden from using bar *i*'s high or low to DECIDE anything; the engine is
required to use them to fill an order that was already sitting there at a price knowable
before the bar opened. Six new hand-built-candle tests pin that behaviour down, including
filling at the trigger, filling at a worse price when a bar gaps through it, and refusing to
guess when one bar covers both sides.

### How much history these numbers cover

Trade count on its own does not say how long a period a result is drawn from,
so the window is recorded per coin. What is measured is the TRADEABLE window:
the first bar the rule is allowed to act on, after the warmup, through the last
closed bar in the data. The three coins do not start together - Bitcoin's history
on this venue begins in March 2020, XRP in May 2021, Solana in October 2021 - so a
pooled row is not three equal thirds.

Warmup skipped before the first trade: 1H 456, 4H 120, 6H 120, 1D 120. That subtraction costs very
little at 1H and a great deal at 1D, where a warmup bar is a whole day.

| Timeframe | Coin | Window traded | Days | Years | Tradeable bars | Warmup bars |
|---|---|---|---|---|---|---|
| 1H | BTCUSDT | 2020-04-13 to 2026-09-05 | 2336 | 6.39 | 56,055 | 456 |
| 1H | SOLUSDT | 2021-11-03 to 2026-09-05 | 1767 | 4.84 | 42,409 | 456 |
| 1H | XRPUSDT | 2021-06-01 to 2026-09-05 | 1922 | 5.26 | 46,120 | 456 |
| 4H | BTCUSDT | 2020-04-14 to 2026-09-05 | 2335 | 6.39 | 14,009 | 120 |
| 4H | SOLUSDT | 2021-11-04 to 2026-09-05 | 1766 | 4.84 | 10,597 | 120 |
| 4H | XRPUSDT | 2021-06-02 to 2026-09-05 | 1921 | 5.26 | 11,525 | 120 |
| 6H | BTCUSDT | 2020-04-24 to 2026-09-05 | 2325 | 6.37 | 9,301 | 120 |
| 6H | SOLUSDT | 2021-11-14 to 2026-09-05 | 1756 | 4.81 | 7,026 | 120 |
| 6H | XRPUSDT | 2021-06-12 to 2026-09-05 | 1911 | 5.23 | 7,645 | 120 |
| 1D | BTCUSDT | 2020-07-23 to 2026-09-04 | 2234 | 6.12 | 2,235 | 120 |
| 1D | SOLUSDT | 2022-02-12 to 2026-09-04 | 1665 | 4.56 | 1,666 | 120 |
| 1D | XRPUSDT | 2021-09-10 to 2026-09-04 | 1820 | 4.98 | 1,821 | 120 |

Shortest window in this run: SOLUSDT at 1D, 1665 days (4.56 years). Longest: BTCUSDT at 1H, 2336 days (6.39 years).

### Results - three coins pooled per timeframe, every number post-fee

Read the four timeframes as **one test at four execution resolutions**, not as four
independent tests. Nothing about the rule changes with the bar size: the session is always the
UTC day and the triggers are always the day's open plus and minus one stretch. All that changes
is how finely the bars can resolve WHEN a resting order was penetrated. 1H is the headline
because it resolves that most finely.

| Timeframe | Exit | Trades | Days BTC | Days SOL | Days XRP | Win% | RR | R (pre-fee) | R (post-fee) | R/trade | Sharpe | Max DD % | Max DD (R) | R-recovery | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1H | native | 2251 | 2336 | 1767 | 1922 | 43.7 | 1.44 | 143.0 | 73.5 | 0.033 | 0.48 | 19.8 | 29.5 | 2.49 | **INCONCLUSIVE** |
| 1H | forced-1:3 | 1595 | 2336 | 1767 | 1922 | 41.5 | 1.37 | 28.7 | -20.7 | -0.013 | -0.16 | 52.4 | 61.3 | -0.34 | **DISCARD** |
| 4H | native | 2244 | 2335 | 1766 | 1921 | 43.8 | 1.46 | 153.4 | 84.0 | 0.037 | 0.55 | 19.9 | 29.5 | 2.85 | **INCONCLUSIVE** |
| 4H | forced-1:3 | 1253 | 2335 | 1766 | 1921 | 29.9 | 1.78 | -168.7 | -207.7 | -0.166 | -1.47 | 214.6 | 214.4 | -0.97 | **DISCARD** |
| 6H | native | 2232 | 2325 | 1756 | 1911 | 43.8 | 1.47 | 155.5 | 86.4 | 0.039 | 0.57 | 19.9 | 29.5 | 2.93 | **INCONCLUSIVE** |
| 6H | forced-1:3 | 1221 | 2325 | 1756 | 1911 | 22.3 | 2.01 | -378.6 | -416.4 | -0.341 | -2.98 | 407.3 | 419.3 | -0.99 | **DISCARD** |
| 1D | native | 2094 | 2234 | 1665 | 1820 | 44.4 | 1.62 | 213.5 | 148.0 | 0.071 | 1.03 | 11.7 | 26.4 | 5.60 | **INCONCLUSIVE** |
| 1D | forced-1:3 | 2095 | 2234 | 1665 | 1820 | 0.0 | n/a | -2095.0 | -2160.5 | -1.031 | -17.18 | 2183.1 | 2159.4 | -1.00 | **DISCARD** |

**Verdicts, per exit variant, never collapsed:**

* **Native (Crabel's own rule):** 1H INCONCLUSIVE - positive but short of the KEEP bar: expectancy +0.033R < +0.10R; Sharpe 0.48 < 0.7; achieved RR 1.44 < 1.5 · 4H INCONCLUSIVE - positive but short of the KEEP bar: expectancy +0.037R < +0.10R; Sharpe 0.55 < 0.7; achieved RR 1.46 < 1.5 · 6H INCONCLUSIVE - positive but short of the KEEP bar: expectancy +0.039R < +0.10R; Sharpe 0.57 < 0.7; achieved RR 1.47 < 1.5 · 1D INCONCLUSIVE - positive but short of the KEEP bar: expectancy +0.071R < +0.10R
* **Forced 1:3:** 1H DISCARD - post-fee expectancy -0.013R per trade is not positive; post-fee Sharpe -0.16 below 0.3; earned only -0.34x its worst drawdown · 4H DISCARD - post-fee expectancy -0.166R per trade is not positive; post-fee Sharpe -1.47 below 0.3; earned only -0.97x its worst drawdown · 6H DISCARD - post-fee expectancy -0.341R per trade is not positive; post-fee Sharpe -2.98 below 0.3; earned only -0.99x its worst drawdown · 1D DISCARD - post-fee expectancy -1.031R per trade is not positive; post-fee Sharpe -17.18 below 0.3; earned only -1.00x its worst drawdown

KEEP rows: none.

### Where the native rule actually stands against the bar

All four native rows are INCONCLUSIVE, but **not for the same reason at each resolution**, and
the difference matters:

* At 1H, 4H, 6H the native rule misses three of the four KEEP tests - expectancy,
  Sharpe and achieved reward-to-risk.
* At 1D it misses **exactly one**: post-fee expectancy
  0.071R against the +0.10R floor. It clears Sharpe
  (1.03 against 0.70), R-recovery (5.60
  against 1.50) and achieved RR (1.62 against 1.50).

**One prediction of mine was wrong and the result corrected it.** Before running this I expected
a no-stop, fixed-time-exit rule to produce near-symmetric winners and losers, so an achieved RR
near 1.0 that could never clear the 1.50 requirement. Measured RR is 1H 1.44, 4H 1.46, 6H 1.47, 1D 1.62 - it clears the
requirement at 1D. A position with no stop keeps whatever the session gives it, so the
winners run further than the losers even though only about 44% of trades win.
The bar's native RR test is not what blocks this strategy. The +0.10R expectancy floor
is, and it is not close to arbitrary: 0.033R per trade at
1H is a thin edge to run a real book on.

**A caution on reading the four resolutions as a trend.** Per-trade edge rises with bar size
(1H 0.033R, 4H 0.037R, 6H 0.039R, 1D 0.071R), but
the four rows are not the same sample: the warmup floor puts a different start date on each
(6026 armed sessions at 1H against 5722 at 1D), and the coarsest bars
skip the whipsaw sessions that penetrated both triggers on the same day. So this is not
evidence that the rule works better on daily bars.

### Exit-death check - and why it can only be indicative here

1H: yes (the exit flips the sign of the edge: native +0.033R per trade vs forced 1:3 -0.013R. Identical entries, so the entry signal is not what decided this - the forced 1:3 exit is. The edge, such as it is, lives in the native exit.). 4H: yes (the exit flips the sign of the edge: native +0.037R per trade vs forced 1:3 -0.166R. Identical entries, so the entry signal is not what decided this - the forced 1:3 exit is. The edge, such as it is, lives in the native exit.). 6H: yes (the exit flips the sign of the edge: native +0.039R per trade vs forced 1:3 -0.341R. Identical entries, so the entry signal is not what decided this - the forced 1:3 exit is. The edge, such as it is, lives in the native exit.). 1D: yes (the exit flips the sign of the edge: native +0.071R per trade vs forced 1:3 -1.031R. Identical entries, so the entry signal is not what decided this - the forced 1:3 exit is. The edge, such as it is, lives in the native exit.).

The comparison has a measurable weakness on this strategy, and it differs at each end of the
timeframe axis. The project's forced variant carries a 30-bar time limit, which is 30 DAYS at
1D and 7.5 days at 6H, while the native rule holds for part of one session. The two
variants therefore hold for wildly different lengths, block different sessions, and end up
trading different entries: shared entries run 1H 73.5%, 4H 62.3%, 6H 62.1%, 1D 99.9%,
against the 85% minimum needed for "same entries, only the exit
differs" to be a fair claim. On the fine bars the two variants are not comparing exits on a
like-for-like set. At 1D the overlap is fine, but there the forced side is 100% entry-bar
artifact (next section) - so the flag is untrustworthy at both ends of the axis, for two
unrelated reasons. Rather than tune a project-wide constant to flatter one strategy, the forced
variant is re-run with its time limit cut to a single session further down, clearly labelled.

What survives all of that: the two variants disagree on the **sign** of the edge at every
resolution, by a margin far larger than the overlap gap could account for. The edge lives in
Crabel's own exit, which is the one thing this check was built to detect.

### What the resting orders actually did

Every armed session places two stop orders. This table says what became of them, summed over
the three coins. It is the honest denominator: only about a third of armed sessions produce a
trade at all, so the trade counts above are not "one trade per day".

| Timeframe | Exit | Sessions with orders placed | Traded | Neither side reached | Both sides in one bar (skipped) | Blocked by an open trade |
|---|---|---|---|---|---|---|
| 1H | native | 6026 | 2251 (37%) | 3771 (63%) | 1 (0.0%) | 0 (0%) |
| 1H | forced-1:3 | 6026 | 1595 (26%) | 2887 (48%) | 1 (0.0%) | 1540 (26%) |
| 4H | native | 6023 | 2244 (37%) | 3769 (63%) | 7 (0.1%) | 0 (0%) |
| 4H | forced-1:3 | 6023 | 1255 (21%) | 2059 (34%) | 4 (0.1%) | 2704 (45%) |
| 6H | native | 5993 | 2232 (37%) | 3748 (63%) | 10 (0.2%) | 0 (0%) |
| 6H | forced-1:3 | 5993 | 1222 (20%) | 2083 (35%) | 7 (0.1%) | 2679 (45%) |
| 1D | native | 5722 | 2095 (37%) | 3577 (63%) | 50 (0.9%) | 0 (0%) |
| 1D | forced-1:3 | 5722 | 2095 (37%) | 3577 (63%) | 50 (0.9%) | 0 (0%) |

Across all four timeframes, **68 of 23764 armed sessions** were skipped because a
single bar covered both triggers and plain OHLC cannot say which side traded first. Those
sessions are counted and discarded rather than guessed. I expected this to be the main problem
on daily bars and it measurably is not: the stretch is 0.8 of an average day's range on EACH
side, so a bar has to span 1.6 average ranges with the open near its middle.

Two accounting notes, so the table can be checked rather than trusted. First, the four outcome
columns fall 9 sessions short of the armed column in total (1H 3, 4H 3, 6H 3, 1D 0): each coin's
final session was still in progress when the data ended, so it was armed but never reached its
own closing bar and belongs in none of the outcome columns. At 1D a session is a single bar, so
nothing is left unfinished there. Second, "Traded" counts orders that FILLED, while the results
table counts trades that CLOSED - a trade still open when the data runs out is discarded rather
than valued at the last price. That is the whole of the difference between the 2095
filled and 2094 closed on the 1D native row.

### The one real measurement problem, and its exact size

A trade entered part-way through a bar is still tested against the WHOLE of that bar, including
the part that happened before the resting order was penetrated. This project keeps that
pessimism deliberately - it can never flatter a result - but on this strategy it interacts badly
with the forced variant. With 1R = one stretch the forced stop sits exactly on the session open,
and a candle's low is almost always at or below its own open, so the further the bar size is
from the entry moment, the more forced trades are recorded as stopped out on their entry bar.

| Timeframe | Native: died on entry bar | Forced 1:3: died on entry bar | Forced trades stopped out | Reading |
|---|---|---|---|---|
| 1H | 0% | 6% | 519 of 1595 (33%) | most faithful |
| 4H | 0% | 24% | 797 of 1253 (64%) | distorted |
| 6H | 0% | 38% | 914 of 1221 (75%) | heavily distorted |
| 1D | 0% | 100% | 2095 of 2095 (100%) | meaningless for the forced variant |

**Read the forced-1:3 rows on 4H, 6H and 1D as a measurement of the data's resolution, not of
the rule.** At 1D the forced variant is not testing Crabel at all. The native rule has no stop
whatsoever, so it is completely untouched by this at every resolution - which is fortunate,
because the native rule is the one Crabel actually published.

### Against the source's own claim

| | Crabel's published test | This test |
|---|---|---|
| Markets | 84 futures, equally weighted | 3 crypto perpetuals, correlated |
| Period | Jan 1923 - Jul 2025, 103 years | Bybit history, about 6 years |
| Costs | gross, no commission | post-fee, taker both legs |
| Sharpe | 1.40 full period | 1H 0.48, 4H 0.55, 6H 0.57, 1D 1.03 (native, by timeframe) |
| Win rate / RR | not published, on purpose | measured here anyway |
| Best decade | above 6 (1970s-90s) | best resolution here: 1D |
| Worst decade | 0.91 (2010s) | - |

The gap in Sharpe is expected and mostly explained by the portfolio effect: 84 weakly
correlated streams against 3 that mostly move together. This test cannot separate "the rule is
weaker in crypto" from "three coins is not a portfolio".

One like-for-like note, since his figure is gross: pre-fee, the daily native row here earns
+0.1019R per trade and post-fee 0.0707R - so fees consume
about 31% of the raw edge. The harness only
computes Sharpe post-fee, so no pre-fee Sharpe is quoted here rather than estimating one.

### Long leg versus short leg

Crabel's rule is symmetric by design, so an asymmetric result is information about the market
rather than about the rule.

| Timeframe | Exit | Long trades | Long R | Long win% | Short trades | Short R | Short win% |
|---|---|---|---|---|---|---|---|
| 1H | native | 1113 | +140.0 | 49.3 | 1138 | -66.6 | 38.1 |
| 1H | forced-1:3 | 800 | +13.6 | 43.5 | 795 | -34.3 | 39.5 |
| 4H | native | 1106 | +150.6 | 49.5 | 1138 | -66.6 | 38.1 |
| 4H | forced-1:3 | 632 | -108.3 | 29.3 | 621 | -99.4 | 30.6 |
| 6H | native | 1100 | +151.0 | 49.5 | 1132 | -64.6 | 38.3 |
| 6H | forced-1:3 | 613 | -232.5 | 20.6 | 608 | -183.9 | 24.0 |
| 1D | native | 1042 | +172.5 | 49.8 | 1052 | -24.5 | 39.0 |
| 1D | forced-1:3 | 1042 | -1075.6 | 0.0 | 1053 | -1084.8 | 0.0 |

### Sensitivities, on the headline timeframe only

Each row changes exactly one thing. None of these is a tuned parameter: the baseline is the
source's own 0.8 x ten-day range, and everything else exists to show how fragile that choice is.

| Variant (1H) | Exit | Trades | Win% | RR | R (post-fee) | R/trade | Sharpe | Fee cost/trade | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| stretch = 0.8 x mean 10-day range (traded) | native | 2251 | 43.7 | 1.44 | 73.5 | 0.033 | 0.48 | 0.031R | INCONCLUSIVE |
| stretch = 0.8 x mean 10-day range (traded) | forced-1:3 | 1595 | 41.5 | 1.37 | -20.7 | -0.013 | -0.16 | 0.031R | DISCARD |
| stretch = 0.8 x 10-day high-low span | native | 170 | 35.9 | 1.52 | -5.1 | -0.030 | -0.16 | 0.014R | DISCARD |
| stretch = 0.8 x 10-day high-low span | forced-1:3 | 157 | 46.5 | 1.23 | 2.8 | 0.018 | 0.10 | 0.014R | DISCARD |
| stretch = mean 10-day smaller open tail | native | 5740 | 45.7 | 1.07 | -708.3 | -0.123 | -0.87 | 0.112R | DISCARD |
| stretch = mean 10-day smaller open tail | forced-1:3 | 5041 | 17.9 | 2.03 | -2585.3 | -0.513 | -8.83 | 0.113R | DISCARD |
| 1R = 2 x stretch | native | 2251 | 43.7 | 1.44 | 36.7 | 0.016 | 0.48 | 0.015R | INCONCLUSIVE |
| 1R = 2 x stretch | forced-1:3 | 1492 | 46.0 | 1.40 | 58.1 | 0.039 | 0.77 | 0.016R | INCONCLUSIVE |
| only after a narrow-range day (NR7) | native | 276 | 43.5 | 1.18 | -5.9 | -0.021 | -0.19 | 0.031R | DISCARD |
| only after a narrow-range day (NR7) | forced-1:3 | 272 | 42.6 | 1.20 | -12.2 | -0.045 | -0.28 | 0.031R | DISCARD |
| only after a wide-range day (WR7) | native | 384 | 40.1 | 1.51 | 1.6 | 0.004 | 0.03 | 0.030R | DISCARD |
| only after a wide-range day (WR7) | forced-1:3 | 348 | 33.3 | 1.56 | -43.2 | -0.124 | -0.64 | 0.030R | DISCARD |

What the rows mean in words:

* **SPAN** puts the trigger 14.1% from the session open instead of 4.5%, and
  the sample collapses to a small fraction of the baseline's trades. That settles the source's
  ambiguity by arithmetic rather than by argument: SPAN cannot be the reading Crabel traded,
  because it would almost never fill.
* **The tail reading** puts the trigger 1.2% from the open, so it fills constantly and
  pays a round-trip fee on every one of those fills. The fee-cost column is the tell, and the
  result is the worst in the table.
* **1R = 2 x stretch** must leave the native Sharpe unchanged and halve every R, because it
  only rescales the measuring stick. It does. That is a check on my own arithmetic, not a
  result. It does change the forced variant, because the stop moves off the session open.
* **NR7 / WR7 conditioning** is the framework Crabel names but defers to paywalled chapters,
  so N = 7 is this project's placeholder and the comparison is indicative only.

### Forced 1:3 with a fair time limit

The standard forced variant holds up to 30 bars. Cut to one session, it becomes comparable to
the native rule in holding period. This is a fair-comparison exhibit, not a tuned result.

| Timeframe | Forced 1:3, 30-bar limit (standard) | Forced 1:3, one-session limit | R/trade, standard -> one-session |
|---|---|---|---|
| 1H | 1595 trades, -20.7R, Sharpe -0.16 | 1668 trades, -7.5R, Sharpe -0.06 | -0.013R -> -0.004R |
| 4H | 1253 trades, -207.7R, Sharpe -1.47 | 1739 trades, -329.5R, Sharpe -2.71 | -0.166R -> -0.189R |
| 6H | 1221 trades, -416.4R, Sharpe -2.98 | 1789 trades, -621.7R, Sharpe -5.07 | -0.341R -> -0.348R |
| 1D | 2095 trades, -2160.5R, Sharpe -17.18 | 2095 trades, -2160.5R, Sharpe -17.18 | -1.031R -> -1.031R |

It does not rescue the forced variant. At 1H the loss shrinks; at 4H and 6H it gets
worse, because a one-session limit forces more trades to be opened into the same entry-bar stop
problem instead of a few being blocked by an existing position. At 1D the two columns are
identical, since one session is one bar there. The conclusion does not depend on the time limit.

### Per coin, per timeframe, per exit

```
coin      timeframe  exit         trades   win%     RR    R pre   R post  R/trade  Sharpe     DD%    DD R  recov  verdict
-------------------------------------------------------------------------------------------------------------------------
BTCUSDT   1H         native          883   44.3   1.50     80.4     45.5    0.052    0.71    10.6    16.3   2.79  INCONCLUSIVE
BTCUSDT   1H         forced-1:3      630   41.1   1.38     14.9    -10.0   -0.016   -0.14    29.8    34.9  -0.29  DISCARD
BTCUSDT   4H         native          882   44.3   1.51     82.6     47.8    0.054    0.75    10.1    15.7   3.05  INCONCLUSIVE
BTCUSDT   4H         forced-1:3      497   30.6   1.63    -78.1    -97.8   -0.197   -1.26   106.4   106.3  -0.92  DISCARD
BTCUSDT   6H         native          878   44.1   1.52     81.3     46.6    0.053    0.73    10.2    15.7   2.97  INCONCLUSIVE
BTCUSDT   6H         forced-1:3      477   21.8   1.97   -156.9   -175.8   -0.369   -2.25   179.6   185.0  -0.95  DISCARD
BTCUSDT   1D         native          833   44.7   1.66    101.1     68.2    0.082    1.16     9.0    15.7   4.35  INCONCLUSIVE
BTCUSDT   1D         forced-1:3      834    0.0    n/a   -834.0   -866.9   -1.039  -14.73   875.3   865.8  -1.00  DISCARD
SOLUSDT   1H         native          666   46.2   1.17     16.4      1.3    0.002    0.03    14.0    15.6   0.09  DISCARD
SOLUSDT   1H         forced-1:3      460   44.8   1.38     32.1     21.7    0.047    0.45    11.0    12.2   1.78  INCONCLUSIVE
SOLUSDT   4H         native          664   46.2   1.19     18.5      3.4    0.005    0.08    12.2    13.1   0.26  DISCARD
SOLUSDT   4H         forced-1:3      349   32.7   1.94     -4.9    -12.8   -0.037   -0.21    24.1    25.9  -0.49  DISCARD
SOLUSDT   6H         native          659   46.4   1.19     20.7      5.7    0.009    0.14    12.2    13.1   0.44  DISCARD
SOLUSDT   6H         forced-1:3      347   24.2   2.02    -86.5    -94.3   -0.272   -1.60    94.3    93.3  -1.01  DISCARD
SOLUSDT   1D         native          612   47.2   1.39     45.8     31.7    0.052    0.86     8.1     8.1   3.92  INCONCLUSIVE
SOLUSDT   1D         forced-1:3      612    0.0    n/a   -612.0   -626.1   -1.023  -14.58   631.5   625.1  -1.00  DISCARD
XRPUSDT   1H         native          702   40.5   1.66     46.2     26.6    0.038    0.31    17.7    19.0   1.40  INCONCLUSIVE
XRPUSDT   1H         forced-1:3      505   39.0   1.36    -18.3    -32.4   -0.064   -0.55    49.1    50.4  -0.64  DISCARD
XRPUSDT   4H         native          698   40.7   1.69     52.3     32.9    0.047    0.38    17.7    19.0   1.73  INCONCLUSIVE
XRPUSDT   4H         forced-1:3      407   26.8   1.84    -85.7    -97.1   -0.238   -1.49   102.2   110.1  -0.88  DISCARD
XRPUSDT   6H         native          695   40.9   1.69     53.6     34.1    0.049    0.39    17.6    19.0   1.80  INCONCLUSIVE
XRPUSDT   6H         forced-1:3      397   21.2   2.04   -135.1   -146.3   -0.368   -2.27   144.9   149.2  -0.98  DISCARD
XRPUSDT   1D         native          649   41.3   1.82     66.6     48.1    0.074    0.58    11.1    12.0   4.00  INCONCLUSIVE
XRPUSDT   1D         forced-1:3      649    0.0    n/a   -649.0   -667.5   -1.028  -14.22   673.3   666.5  -1.00  DISCARD
```

### Is this distinguishable from luck

```
1H:
  native       2251 trades | pre-fee +0.0635R/trade (spread 1.05R, t = +2.88) | post-fee +0.0326R/trade (t = +1.48)
  forced-1:3   1595 trades | pre-fee +0.0180R/trade (spread 1.09R, t = +0.66) | post-fee -0.0130R/trade (t = -0.48)
  resolved inside their first candle: native 0%, forced-1:3 6%
  the two variants share 73.5% of their entries  <-- TOO LOW to compare exits fairly
  a 4.5% stop vs a typical candle: BTCUSDT candle 0.62% (stop = 7.3x), SOLUSDT candle 1.14% (stop = 3.9x), XRPUSDT candle 0.89% (stop = 5.0x)
4H:
  native       2244 trades | pre-fee +0.0684R/trade (spread 1.04R, t = +3.10) | post-fee +0.0375R/trade (t = +1.70)
  forced-1:3   1253 trades | pre-fee -0.1347R/trade (spread 1.40R, t = -3.39) | post-fee -0.1657R/trade (t = -4.18)
  resolved inside their first candle: native 0%, forced-1:3 24%
  the two variants share 62.3% of their entries  <-- TOO LOW to compare exits fairly
  a 4.5% stop vs a typical candle: BTCUSDT candle 1.34% (stop = 3.3x), SOLUSDT candle 2.42% (stop = 1.9x), XRPUSDT candle 1.90% (stop = 2.4x)
6H:
  native       2232 trades | pre-fee +0.0697R/trade (spread 1.05R, t = +3.15) | post-fee +0.0387R/trade (t = +1.75)
  forced-1:3   1221 trades | pre-fee -0.3101R/trade (spread 1.40R, t = -7.75) | post-fee -0.3410R/trade (t = -8.52)
  resolved inside their first candle: native 0%, forced-1:3 38%
  the two variants share 62.1% of their entries  <-- TOO LOW to compare exits fairly
  a 4.5% stop vs a typical candle: BTCUSDT candle 1.68% (stop = 2.7x), SOLUSDT candle 2.96% (stop = 1.5x), XRPUSDT candle 2.35% (stop = 1.9x)
1D:
  native       2094 trades | pre-fee +0.1019R/trade (spread 1.03R, t = +4.53) | post-fee +0.0707R/trade (t = +3.14)
  forced-1:3   2095 trades | pre-fee -1.0000R/trade (spread 0.00R, t = n/a, every trade identical) | post-fee -1.0312R/trade (t = -3325.97)
  resolved inside their first candle: native 0%, forced-1:3 100%
  the two variants share 99.9% of their entries
  a 4.5% stop vs a typical candle: BTCUSDT candle 3.70% (stop = 1.2x), SOLUSDT candle 6.44% (stop = 0.7x), XRPUSDT candle 5.03% (stop = 0.9x)
```

At 1H the native variant's t-statistic on post-fee per-trade R is **+1.48**
(rough reading: below 2, the average sits inside the range chance alone would produce). Across
the axis, post-fee t runs 1H +1.48, 4H +1.70, 6H +1.75, 1D +3.14 while pre-fee t runs 1H +2.88, 4H +3.10, 6H +3.15, 1D +4.53. **That is the single
most useful line in this write-up:** the entry rule produces an edge that is clearly separable
from noise before costs at every resolution, and fees take it back down to marginal on the fine
bars. Native trade counts are healthy everywhere (1H 2251, 4H 2244, 6H 2232, 1D 2094), so nothing here fails for sample
size, and no native trade at all resolved inside its own first candle - so the intrabar
tie-break never decided a native result.

### 1R against one candle

| Coin | Timeframe | Stretch (= 1R) as % of price | Typical candle range % | 1R in candles |
|---|---|---|---|---|
| BTCUSDT | 1H | 3.22% | 0.62% | 5.2x |
| BTCUSDT | 4H | 3.22% | 1.34% | 2.4x |
| BTCUSDT | 6H | 3.22% | 1.68% | 1.9x |
| BTCUSDT | 1D | 3.22% | 3.70% | 0.9x |
| SOLUSDT | 1H | 5.44% | 1.14% | 4.8x |
| SOLUSDT | 4H | 5.44% | 2.42% | 2.3x |
| SOLUSDT | 6H | 5.44% | 2.96% | 1.8x |
| SOLUSDT | 1D | 5.44% | 6.44% | 0.8x |
| XRPUSDT | 1H | 4.49% | 0.89% | 5.0x |
| XRPUSDT | 4H | 4.49% | 1.90% | 2.4x |
| XRPUSDT | 6H | 4.49% | 2.35% | 1.9x |
| XRPUSDT | 1D | 4.49% | 5.03% | 0.9x |

The contrast with Strategy #1 is the point: there 1R was narrower than a single candle, so the
tie-break rule decided the outcomes. On hourly bars 1R here is 7.3x
a typical BTC candle, which is the healthy direction. But read the 1D rows: one stretch is
0.8 of an average DAY's range, so against a daily candle it is roughly one candle or less - below
1x on two of the three coins. **That is the mechanism behind the entry-bar artifact**, not a
separate problem: a stop one candle away, tested against the whole candle it was opened in, is
guaranteed to be hit. It costs the forced variant everything and the native rule nothing.

### Best and worst conditions

| Timeframe | Exit | Best condition | Worst condition |
|---|---|---|---|
| 1H | native | up/highvol | down/lowvol |
| 1H | forced-1:3 | up/highvol | range/highvol |
| 4H | native | range/highvol | down/lowvol |
| 4H | forced-1:3 | range/highvol | down/lowvol |
| 6H | native | up/highvol | down/lowvol |
| 6H | forced-1:3 | range/lowvol | up/highvol |
| 1D | native | range/lowvol | down/lowvol |
| 1D | forced-1:3 | range/highvol | down/lowvol |

### Funding, flagged not modelled

These are perpetual futures, which charge or pay funding every eight hours. The native rule
holds for part of one session, so a trade crosses roughly one or two funding stamps; the forced
variant's 30-bar limit can hold for weeks at 6H and 1D and would cross dozens. **No funding is
modelled anywhere in this project yet**, per the standing instruction, so the multi-day forced
rows in particular are missing a real cost. Direction matters too: funding is usually paid by
longs in a rising market, and this rule is symmetric, so the two legs would not be affected
equally. This is a flag on the numbers above, not an adjustment to them.

### What would change the verdict

* **A real portfolio.** The claim is a portfolio claim. Running the identical rule on 30-50
  perpetuals instead of 3 is the single change most likely to move the Sharpe, and it tests
  what Crabel actually published rather than a three-coin slice of it.
* **A session boundary that is an event, not a timestamp.** Any hour with a genuine
  concentration of crypto order flow - the CME open, a daily funding stamp, the US equity open
  - would test "opening range breakout" better than midnight UTC does. That is a different
  experiment, not a tuning of this one.
* **Tick or minute data on the entry bar.** It would remove the entry-bar artifact entirely and
  make the forced-1:3 rows meaningful at every resolution. It would not change the native rows.
* **Fees are the binding constraint at 1D, and they are real.** Pre-fee, the daily native
  row earns +0.1019R per trade, which clears the +0.10R KEEP floor; post-fee it
  earns 0.0707R, which does not. Crabel's own 1.40 Sharpe is quoted
  GROSS, so on a like-for-like basis this test's daily row would pass the bar and on a
  what-you-actually-keep basis it does not. Nothing about that is a reason to relax the bar - the
  fees get paid - but it does locate the failure precisely. A cheaper venue or a maker rebate on
  one leg would narrow the gap; the fine-bar rows are short pre-fee too, so they need more than
  cheaper fills.

### Bottom line

Crabel's own rule - no stop, out at the next session's open - **made money post-fee at every
resolution tested** (1H 73.5R, 4H 84.0R, 6H 86.4R, 1D 148.0R)
on three crypto perpetuals, over 6026 armed sessions per coin-set at 1H. The per-trade
edge is thin (0.033R at 1H,
0.071R at 1D) and the pre-fee t-statistics
(1H +2.88, 4H +3.10, 6H +3.15, 1D +4.53) say the entry rule is doing something real, not something random.

**Verdict: INCONCLUSIVE on the native rule at all four resolutions, DISCARD on the forced 1:3 at
all four.** INCONCLUSIVE here does not mean "too few trades" - there are over two thousand per
resolution. It means positive but short of the KEEP bar, and at 1D short by **one test
only**: 0.071R per trade against the +0.10R floor, with
Sharpe, R-recovery and reward-to-risk all cleared. That is the closest this project has come to a
KEEP so far, and it is still a miss.

Forcing a 1:3 exit onto the rule destroys it (-20.7R at 1H,
-2160.5R at 1D), and the exit-death check reads "yes" at every
resolution. Some of that damage is the entry-bar artifact rather than the exit itself, which is
why the forced rows are reported with their artifact share attached and are not used to argue
anything about Crabel.

Two things this test cannot settle, and neither should be quietly resolved in the strategy's
favour: whether the missing edge is the missing opening auction, and whether three correlated
coins can express a claim that was measured on 84 weakly correlated markets. His published
Sharpe of 1.40 is a portfolio number and this is not a portfolio. **Crabel's
result stands untouched by this test; what was measured here is the crypto adaptation of it.**

## Strategy #5 - Keltner Channel breakout

**Tested:** 2026-09-05 · **Coins:** BTCUSDT, SOLUSDT, XRPUSDT ·
**Timeframes:** 1H, 4H, 6H, 1D · **Fees:** taker on both legs (0.055% each), every number below is post-fee unless it is labelled pre-fee ·
**Channel:** EMA(20) middle line, bands at 2 x ATR(10)

**Sourcing: MEDIUM, and weaker than any strategy logged so far.** The source is a short trade description, not a paper, and the two results attached to it come from search-result summaries rather than from reading either methodology - so their fees, position sizing and intrabar tie-break rules are unknown. **Neither cited test was on crypto:** one is US equities on daily bars, the other forex on hourly bars. This entry is therefore NOT a replication of a documented crypto result. It is the first crypto test of a rule documented elsewhere, and it should be read that way.

### The rule, in the source's own words

* TRIGGER: buy when price CLOSES outside the upper Keltner Channel (a moving average with ATR-based bands); sell short on a close below the lower band.
* STOP-LOSS: "back inside the channel / at the opposite band".
* TAKE-PROFIT: "a fixed multiple of the channel width or ATR".
* MARKET CONDITION: trending, expanding volatility.

That is the whole rule as stated. Every number in it is missing.

### What the source claims

| Test | Bars | Win% | RR | Sharpe | Max DD % |
|---|---|---|---|---|---|
| 500 US stocks, daily bars, 2010-2024 (TradeAlgo) | daily | 56 | 2.1 | not stated | not stated |
| forex, 1-hour bars, 2021-2025 (Pineify) | 1-hour | 57.8 | not stated | 1.33 | 12.9 |

Two claims worth keeping in view: a win rate near 56-58%, and a reward-to-risk near 2.1:1. Both are tested directly below.

### What the source does not disclose

Four numbers, and they are the four that define the indicator:

| Not stated | Set to | Why | Tested? |
|---|---|---|---|
| Moving-average length | 20-bar EMA | the value in widest circulation for this indicator | swept (50-bar run below) |
| ATR length | 10 bars | same | swept (Wilder ATR run below) |
| Band multiplier | 2 x ATR | same | swept at 1.5 / 2.0 / 2.5 |
| Take-profit multiple | left out of the native rule | see below | supplied by the forced 1:3, and by the source's own 2.1R |

**The take-profit is not invented.** "A fixed multiple of ATR" with no multiple attached is not a rule, and choosing one would be writing the strategy rather than testing it. So the native exit carries NO target, and this project's second variant - the forced 1:3 - IS the source's fixed-multiple exit, imposed. Both halves of the source's exit are therefore tested, just in different columns: its signal exit natively, its fixed-multiple exit in the forced run. Its own documented 2.1:1 is additionally run as a sensitivity, so the claim itself gets measured.

### The one genuine ambiguity, and how it was resolved

"Back inside the channel / at the opposite band" names two different prices, and the gap between them is the entire risk budget of the trade. Both readings were measured before either was traded:

* **The band just broken** ("back inside the channel", read literally). At entry price sits a hair above it, so 1R is a fraction of one candle - the exact disease Strategy #1 documented, where the engine's deliberately pessimistic intrabar tie-break decides the outcome instead of the strategy.
* **The opposite band**, read literally. That is 2 x 2 x ATR away, so the forced variant's 3R target lands roughly 12 ATR from entry and cannot be reached inside any sane time limit.

Neither is usable as the headline, so the traded reading is declared rather than smuggled: **1R runs from the fill to the channel's middle line** - the average the bands are drawn around, the one level both of the source's phrasings bracket, and about 2 x ATR wide, the same order as every other stop in this log. **Both literal readings are run as sensitivities** and their expectancy reported, because of the four KEEP tests only expectancy depends on this choice; Sharpe, achieved RR and R-recovery are all scale-free.

Both of the source's stop phrasings are then used, each in the role it can actually play:

* "at the opposite band" is a PRICE, so it is the hard stop - a level the candle's low (or high) can reach while the bar is still trading.
* "back inside the channel" is a SIGNAL, so it is the exit decision - the first bar closing back inside the channel ends the trade at the next open.

Because the band moves with price, the second rule behaves as a trailing exit: in a run the upper band keeps rising, and the trade only ends once price falls back under wherever the band has got to. And under the 1R definition above, the opposite-band hard stop sits about 2R away, so a native loser can lose about two units of risk. That is the source's own placement, not a choice made here, and it is why the native rows are read with the exit mix beside them.

### Entry is the first bar outside, not every bar outside

"Price is outside the band" is a state that can persist. Measured across all twelve datasets it persists for **2.5 closes on average** (21,397 bars outside a band, but only 8,479 runs). Traded as a state, the rule re-enters on the bar after every exit while price is still outside, which measures the exit's churn rather than the entry. The bar that FIRST closes outside is what is traded here; the state version is run once as a sensitivity, the same treatment Strategy #3 gave the same question.

### Lookahead bias, checked fresh for this strategy

The check is mechanical, not a promise: every indicator column is recomputed on history truncated at 25 different bars and compared with the value the full-history pass produced at that same bar, to a tolerance of 1e-12. Columns checked: `kc_mid`, `kc_atr`, `kc_up`, `kc_lo`, `kc_up_prev`, `kc_lo_prev`, `out_up`, `out_lo`, `long_entry`, `short_entry`, `kc_risk_long`, `kc_risk_short`. **Result: 12/12 datasets PASS** (three coins x four timeframes).

Two places in this strategy could have leaked, and both were handled explicitly:

* **The hard stop is taken from the PREVIOUS bar's band.** The bands at bar i are built from bar i's close and bar i's own high and low (the true range), so testing bar i's low against a band computed from bar i would be placing a stop inside the candle it is meant to protect against. The stop level in force during a bar is the one that was already on the chart when that bar opened.
* **The entry and the "closed back inside" exit use the CURRENT bar's band, and that is legitimate**, because both are decisions made on a bar that has already closed and filled at the NEXT bar's open. Knowing the close of a bar that has closed is not lookahead.

Independently of the audit: **0 of 13174 fills opened already past their own stop level** - the count of trades that were dead on arrival, which is the other way this kind of rule flatters itself.

### A bug found and fixed before any of these numbers were logged

The first complete run of this strategy was thrown away. The line that turns the state "price is outside the band" into the event "price has just closed outside the band" was written as `state & ~state.shift(1).fillna(False)`, and under this project's pandas version that silently does nothing: shifting a true/false column leaves it as generic objects, and inverting generic objects applies whole-number bit-flipping instead of logical NOT, which returns a non-zero (therefore "true") value for BOTH true and false. The condition collapsed back into the raw state, so the discarded run traded every bar price sat outside the band rather than the first one - a different strategy from the one documented above, with no error message to say so.

What it changed, for the record: the **native rows were bit-identical** either way (the native exit only fires when price closes back INSIDE, so there is no re-entry chance left for a state rule to take), while the forced-1:3 rows all moved, and two verdicts moved with them - 1H forced went from INCONCLUSIVE (3380 trades, +94.1R, Sharpe 0.38) to DISCARD, and 4H forced went from INCONCLUSIVE (891 trades, +86.8R, Sharpe 0.68) to KEEP. Both of those discarded figures are reproducible on demand: the collapsed rule IS the state-entry variant, which appears at 1H in Sensitivity 4 below and was re-measured at 4H to confirm the pair quoted here. **Self-test #16 was added to the engine's test file to fail loudly if this ever returns**, and it also checks the same idiom in the two earlier strategies that depend on it - Strategy #1 and Strategy #3 both already used the safe form, so their logged results are unaffected.

### How much history these numbers cover

Trade count on its own does not say how long a period a result is drawn from,
so the window is recorded per coin. What is measured is the TRADEABLE window:
the first bar the rule is allowed to act on, after the warmup, through the last
closed bar in the data. The three coins do not start together - Bitcoin's history
on this venue begins in March 2020, XRP in May 2021, Solana in October 2021 - so a
pooled row is not three equal thirds.

Warmup skipped before the first trade: 150 bars on every timeframe. That subtraction costs very
little at 1H and a great deal at 1D, where a warmup bar is a whole day.

| Timeframe | Coin | Window traded | Days | Years | Tradeable bars | Warmup bars |
|---|---|---|---|---|---|---|
| 1H | BTCUSDT | 2020-03-31 to 2026-09-05 | 2348 | 6.43 | 56,361 | 150 |
| 1H | SOLUSDT | 2021-10-21 to 2026-09-05 | 1780 | 4.87 | 42,715 | 150 |
| 1H | XRPUSDT | 2021-05-19 to 2026-09-05 | 1934 | 5.30 | 46,426 | 150 |
| 4H | BTCUSDT | 2020-04-19 to 2026-09-05 | 2330 | 6.38 | 13,979 | 150 |
| 4H | SOLUSDT | 2021-11-09 to 2026-09-05 | 1761 | 4.82 | 10,567 | 150 |
| 4H | XRPUSDT | 2021-06-07 to 2026-09-05 | 1916 | 5.24 | 11,495 | 150 |
| 6H | BTCUSDT | 2020-05-01 to 2026-09-05 | 2318 | 6.34 | 9,271 | 150 |
| 6H | SOLUSDT | 2021-11-21 to 2026-09-05 | 1749 | 4.79 | 6,996 | 150 |
| 6H | XRPUSDT | 2021-06-19 to 2026-09-05 | 1904 | 5.21 | 7,615 | 150 |
| 1D | BTCUSDT | 2020-08-22 to 2026-09-04 | 2204 | 6.03 | 2,205 | 150 |
| 1D | SOLUSDT | 2022-03-14 to 2026-09-04 | 1635 | 4.48 | 1,636 | 150 |
| 1D | XRPUSDT | 2021-10-10 to 2026-09-04 | 1790 | 4.90 | 1,791 | 150 |

Shortest window in this run: SOLUSDT at 1D, 1635 days (4.48 years). Longest: BTCUSDT at 1H, 2348 days (6.43 years).

### Results - three coins pooled inside each timeframe, never across them

| Timeframe | Exit | Trades | Days BTC | Days SOL | Days XRP | Win% | RR | R (pre-fee) | R (post-fee) | R/trade | Sharpe | Max DD % | Max DD (R) | R-recovery | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1H | native | 5745 | 2348 | 1780 | 1934 | 27.6 | 1.97 | 8.4 | -307.8 | -0.054 | -1.92 | 318.1 | 350.1 | -0.88 | **DISCARD** |
| 1H | forced-1:3 | 3239 | 2348 | 1780 | 1934 | 37.8 | 1.70 | 243.6 | 59.0 | 0.018 | 0.24 | 39.4 | 75.1 | 0.79 | **DISCARD** |
| 4H | native | 1482 | 2330 | 1761 | 1916 | 32.0 | 2.25 | 55.4 | 15.8 | 0.011 | 0.22 | 13.8 | 16.8 | 0.94 | **DISCARD** |
| 4H | forced-1:3 | 832 | 2330 | 1761 | 1916 | 40.4 | 1.76 | 112.7 | 89.0 | 0.107 | 0.72 | 14.4 | 26.7 | 3.34 | **KEEP** |
| 6H | native | 961 | 2318 | 1749 | 1904 | 33.7 | 2.48 | 64.8 | 44.3 | 0.046 | 0.70 | 11.3 | 12.3 | 3.61 | **INCONCLUSIVE** |
| 6H | forced-1:3 | 570 | 2318 | 1749 | 1904 | 38.6 | 1.82 | 57.2 | 44.5 | 0.078 | 0.47 | 21.0 | 27.5 | 1.62 | **INCONCLUSIVE** |
| 1D | native | 218 | 2204 | 1635 | 1790 | 38.1 | 3.20 | 35.8 | 33.7 | 0.154 | 0.86 | 4.7 | 5.5 | 6.12 | **KEEP** |
| 1D | forced-1:3 | 127 | 2204 | 1635 | 1790 | 35.4 | 2.20 | 16.3 | 15.0 | 0.118 | 0.34 | 14.0 | 16.3 | 0.92 | **INCONCLUSIVE** |

* **1H native** - post-fee expectancy -0.054R per trade is not positive; post-fee Sharpe -1.92 below 0.3; earned only -0.88x its worst drawdown
* **1H forced-1:3** - post-fee Sharpe 0.24 below 0.3
* **4H native** - post-fee Sharpe 0.22 below 0.3
* **4H forced-1:3** - +0.107R per trade, Sharpe 0.72, earned 3.34x its worst drawdown over 832 trades
* **6H native** - positive but short of the KEEP bar: expectancy +0.046R < +0.10R; Sharpe 0.70 < 0.7
* **6H forced-1:3** - positive but short of the KEEP bar: expectancy +0.078R < +0.10R; Sharpe 0.47 < 0.7
* **1D native** - +0.154R per trade, Sharpe 0.86, earned 6.12x its worst drawdown over 218 trades
* **1D forced-1:3** - positive but short of the KEEP bar: Sharpe 0.34 < 0.7; R-recovery 0.92 < 1.5

### How the trades actually ended, and what each route paid

| Timeframe | Exit | How the trades ended (count @ mean net R) | Avg bars held |
|---|---|---|---|
| 1H | native | back inside 5724 @ -0.047R, stop 21 @ -1.815R | 2.5 |
| 1H | forced-1:3 | stop 1596 @ -1.062R, target 407 @ +2.927R, time 1236 @ +0.455R | 18.3 |
| 4H | native | back inside 1480 @ +0.012R, stop 2 @ -1.350R | 2.5 |
| 4H | forced-1:3 | stop 417 @ -1.030R, target 124 @ +2.965R, time 291 @ +0.519R | 17.5 |
| 6H | native | back inside 958 @ +0.052R, stop 3 @ -1.745R | 2.6 |
| 6H | forced-1:3 | stop 288 @ -1.023R, target 83 @ +2.974R, time 199 @ +0.464R | 17.8 |
| 1D | native | back inside 217 @ +0.164R, stop 1 @ -1.928R | 2.8 |
| 1D | forced-1:3 | stop 67 @ -1.011R, target 21 @ +2.987R, time 39 @ +0.512R | 17.0 |

The native exit is a signal exit 99.7% of the time: across the four timeframes the opposite-band hard stop fired only 27 times in 8406 native trades. So the ambiguity over where the source's stop sits barely matters for the native rule in practice - price almost always closes back inside the channel long before it can travel two bands. What that leaves is a very short trade: about 2.5 bars, ending on a signal whose average outcome is a small fraction of 1R either way. The forced-1:3 variant is a different animal - roughly 18 bars, with the 30-bar time limit closing 37% of trades before either barrier is touched.

### Exit-death check - which exit is the edge attached to?

* **1H**: the exit flips the sign of the edge: native -0.054R per trade vs forced 1:3 +0.018R. Identical entries, so the entry signal is not what decided this - the native exit is. The edge, such as it is, lives in the forced 1:3 exit. -> exit-death **yes**
* **4H**: the two exits land within 0.096R per trade of each other (native +0.011R vs forced 1:3 +0.107R), so the result is driven by the entry signal rather than by the choice of exit -> exit-death **no**
* **6H**: the two exits land within 0.032R per trade of each other (native +0.046R vs forced 1:3 +0.078R), so the result is driven by the entry signal rather than by the choice of exit -> exit-death **no**
* **1D**: the two exits land within 0.037R per trade of each other (native +0.154R vs forced 1:3 +0.118R), so the result is driven by the entry signal rather than by the choice of exit -> exit-death **no**

That comparison has a caveat this strategy cannot avoid, and it is reported rather than buried: the two variants do NOT trade the same set of entries. An open position blocks the next signal, and because the native exit lasts about 2.5 bars while the forced one lasts about 18, the forced variant sits out signals the native variant takes. The two share only 58% (1H), 59% (4H), 61% (6H), 60% (1D) of their entries, against this project's 85% floor for calling it a clean like-for-like. So the check is run a second time on ONLY the entries both variants actually took:

| Timeframe | Shared entries | Native R/trade | Native Sharpe | Forced R/trade | Forced Sharpe | Exit-death |
|---|---|---|---|---|---|---|
| 1H | 2692 | -0.047R | -1.21 | +0.018R | 0.24 | **yes** |
| 4H | 696 | +0.027R | 0.42 | +0.107R | 0.72 | **no** |
| 6H | 483 | +0.046R | 0.57 | +0.078R | 0.47 | **no** |
| 1D | 115 | +0.190R | 0.73 | +0.118R | 0.34 | **no** |

### Is any of this separable from luck?

t is the average trade divided by its own standard error. Below about 2, the average sits inside the range random noise would produce anyway.

```
1H:
  native       5745 trades | pre-fee +0.0015R/trade (spread 0.65R, t = +0.17) | post-fee -0.0536R/trade (t = -6.24)
  forced-1:3   3239 trades | pre-fee +0.0752R/trade (spread 1.40R, t = +3.06) | post-fee +0.0182R/trade (t = +0.74)
  resolved inside their first candle: native 0%, forced-1:3 2%
  the two variants share 58.5% of their entries  <-- TOO LOW to compare exits fairly
  a 2.6% stop vs a typical candle: BTCUSDT candle 0.62% (stop = 4.2x), SOLUSDT candle 1.14% (stop = 2.3x), XRPUSDT candle 0.89% (stop = 2.9x)
4H:
  native       1482 trades | pre-fee +0.0374R/trade (spread 0.63R, t = +2.30) | post-fee +0.0106R/trade (t = +0.66)
  forced-1:3    832 trades | pre-fee +0.1354R/trade (spread 1.46R, t = +2.67) | post-fee +0.1070R/trade (t = +2.11)
  resolved inside their first candle: native 0%, forced-1:3 2%
  the two variants share 58.6% of their entries  <-- TOO LOW to compare exits fairly
  a 2.6% stop vs a typical candle: BTCUSDT candle 1.34% (stop = 1.9x), SOLUSDT candle 2.42% (stop = 1.1x), XRPUSDT candle 1.90% (stop = 1.4x)
6H:
  native        961 trades | pre-fee +0.0674R/trade (spread 0.74R, t = +2.81) | post-fee +0.0461R/trade (t = +1.93)
  forced-1:3    570 trades | pre-fee +0.1003R/trade (spread 1.44R, t = +1.66) | post-fee +0.0781R/trade (t = +1.29)
  resolved inside their first candle: native 0%, forced-1:3 2%
  the two variants share 60.6% of their entries  <-- TOO LOW to compare exits fairly
  a 2.6% stop vs a typical candle: BTCUSDT candle 1.68% (stop = 1.5x), SOLUSDT candle 2.96% (stop = 0.9x), XRPUSDT candle 2.35% (stop = 1.1x)
1D:
  native        218 trades | pre-fee +0.1644R/trade (spread 1.05R, t = +2.31) | post-fee +0.1544R/trade (t = +2.17)
  forced-1:3    127 trades | pre-fee +0.1281R/trade (spread 1.53R, t = +0.94) | post-fee +0.1178R/trade (t = +0.87)
  resolved inside their first candle: native 0%, forced-1:3 2%
  the two variants share 59.6% of their entries  <-- TOO LOW to compare exits fairly
  a 2.6% stop vs a typical candle: BTCUSDT candle 3.70% (stop = 0.7x), SOLUSDT candle 6.44% (stop = 0.4x), XRPUSDT candle 5.03% (stop = 0.5x)
```

Both KEEP cells clear that bar: 1D native t = +2.17 and 4H forced-1:3 t = +2.11, post-fee. Note what the 1H native column shows, though - a pre-fee average of +0.0015R that becomes -0.0536R post-fee, with t = -6.24. That is not a strategy losing money; it is a strategy paying its fees, measured with enough trades to be certain of it.

One line in that block needs a caveat: the shared context check measures a single stop width - 2.6%, the median 1R at 1H - against every timeframe's candles, which is why it reads as small on the daily rows. This rule's 1R is drawn from ATR, so it grows with the bar. The per-cell version is the table in the next section, and it is the one to read.

### 1R against one candle

If 1R is smaller than a typical candle, most trades resolve inside a single bar, where plain open/high/low/close cannot say whether the stop or the target came first - and this engine breaks that tie against the trade on purpose. A stop that tight would be testing the tie-break rule, not the strategy. Measured from the fills that actually happened:

| Coin | Timeframe | 1R as % of price | Typical candle range % | 1R in candles |
|---|---|---|---|---|
| BTCUSDT | 1H | 1.80% | 0.62% | 2.9x |
| BTCUSDT | 4H | 3.60% | 1.34% | 2.7x |
| BTCUSDT | 6H | 4.51% | 1.68% | 2.7x |
| BTCUSDT | 1D | 9.74% | 3.70% | 2.6x |
| SOLUSDT | 1H | 3.14% | 1.14% | 2.7x |
| SOLUSDT | 4H | 6.26% | 2.42% | 2.6x |
| SOLUSDT | 6H | 7.76% | 2.96% | 2.6x |
| SOLUSDT | 1D | 16.14% | 6.44% | 2.5x |
| XRPUSDT | 1H | 2.60% | 0.89% | 2.9x |
| XRPUSDT | 4H | 5.30% | 1.90% | 2.8x |
| XRPUSDT | 6H | 6.08% | 2.35% | 2.6x |
| XRPUSDT | 1D | 12.22% | 5.03% | 2.4x |

The middle-line reading gives a stop that is 2.4 to 2.9 typical candles wide in every one of the twelve cells - it scales with the bar because ATR does - and **0% of native trades and 2% of daily forced trades resolved inside their first candle**, so the tie-break is not carrying these results. The literal "band just broken" reading is the counter-example, and it is in the sensitivity table below: 1R shrinks to 0.27-1.21% of price and 76%-79% of forced trades die on their entry bar.

### The source's own two claims, measured

| Test | Bars | Trades | Win% | RR achieved | Sharpe | Max DD % |
|---|---|---|---|---|---|---|
| 500 US stocks, daily bars, 2010-2024 (TradeAlgo) | daily | not stated | 56 | 2.1 | not stated | not stated |
| forex, 1-hour bars, 2021-2025 (Pineify) | 1-hour | not stated | 57.8 | not stated | 1.33 | 12.9 |
| this test, native exit, three crypto perps | 1H | 5745 | 27.6 | 1.97 | -1.92 | 318.1 |
| this test, native exit, three crypto perps | 4H | 1482 | 32.0 | 2.25 | 0.22 | 13.8 |
| this test, native exit, three crypto perps | 6H | 961 | 33.7 | 2.48 | 0.70 | 11.3 |
| this test, native exit, three crypto perps | 1D | 218 | 38.1 | 3.20 | 0.86 | 4.7 |

**The win rate does not survive the move to crypto.** The source's 56-58% becomes 27.6% at 1H and 38.1% at 1D. What replaces it is a bigger average winner: achieved reward-to-risk runs 1.97 to 3.20 against the source's 2.1. The shape of the trade is different from the one described - fewer, larger wins instead of many small ones - which is worth stating plainly, because a trader expecting to be right 57% of the time would abandon this rule in its first bad month. The Sharpe claim (1.33 on hourly forex) is not reproduced on any crypto timeframe; the best native Sharpe here is 0.86 at 1D.

The source's own 2.1:1 target, imposed on the native exit:

| Timeframe | Native, no target (traded) | Native + 2.1R target | RR achieved, no target -> 2.1R target |
|---|---|---|---|
| 1H | 5745 trades, 27.6% win, -307.8R, Sharpe -1.92 | 5745 trades, 27.6% win, -302.4R, Sharpe -2.37 | 1.97 -> 1.98 |
| 4H | 1482 trades, 32.0% win, 15.8R, Sharpe 0.22 | 1482 trades, 32.0% win, 54.7R, Sharpe 0.76 | 2.25 -> 2.57 |
| 6H | 961 trades, 33.7% win, 44.3R, Sharpe 0.70 | 961 trades, 33.8% win, 39.8R, Sharpe 0.74 | 2.48 -> 2.41 |
| 1D | 218 trades, 38.1% win, 33.7R, Sharpe 0.86 | 218 trades, 38.1% win, 27.1R, Sharpe 1.03 | 3.20 -> 2.90 |

Capping the winner at the documented ratio does not rescue the timeframes that were already failing. On the daily rows it is a genuine trade-off rather than a loss: total R falls from 33.7R to 27.1R and per-trade expectancy from +0.154R to +0.124R, while Sharpe RISES from 0.86 to 1.03 - a smoother ride for less money, because the target cuts the long runs that produce both the profit and the lumpiness. The trade count is unchanged on every timeframe, so this is an exit-versus-exit comparison on the same entries.

### Sensitivity 1 - the band multiplier the source never states

| Variant | Timeframe | Exit | Trades | Win% | RR | R (post-fee) | R/trade | Sharpe | R-recovery | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| bands at 1.5 x ATR | 1H | native | 9915 | 25.4 | 2.30 | -604.8 | -0.061 | -2.08 | -0.88 | DISCARD |
| bands at 1.5 x ATR | 1H | forced-1:3 | 5049 | 34.9 | 1.88 | 12.9 | 0.003 | 0.04 | 0.11 | DISCARD |
| bands at 1.5 x ATR | 4H | native | 2419 | 30.1 | 2.69 | 88.1 | 0.036 | 0.63 | 2.79 | INCONCLUSIVE |
| bands at 1.5 x ATR | 4H | forced-1:3 | 1248 | 36.9 | 1.94 | 101.3 | 0.081 | 0.64 | 2.44 | INCONCLUSIVE |
| bands at 1.5 x ATR | 6H | native | 1590 | 31.8 | 2.53 | 66.4 | 0.042 | 0.61 | 3.31 | INCONCLUSIVE |
| bands at 1.5 x ATR | 6H | forced-1:3 | 860 | 35.2 | 2.02 | 51.7 | 0.060 | 0.41 | 1.82 | INCONCLUSIVE |
| bands at 1.5 x ATR | 1D | native | 373 | 33.2 | 3.75 | 75.7 | 0.203 | 0.77 | 7.82 | KEEP |
| bands at 1.5 x ATR | 1D | forced-1:3 | 194 | 38.7 | 2.04 | 31.8 | 0.164 | 0.57 | 2.29 | INCONCLUSIVE |
| bands at 2 x ATR (traded) | 1H | native | 5745 | 27.6 | 1.97 | -307.8 | -0.054 | -1.92 | -0.88 | DISCARD |
| bands at 2 x ATR (traded) | 1H | forced-1:3 | 3239 | 37.8 | 1.70 | 59.0 | 0.018 | 0.24 | 0.79 | DISCARD |
| bands at 2 x ATR (traded) | 4H | native | 1482 | 32.0 | 2.25 | 15.8 | 0.011 | 0.22 | 0.94 | DISCARD |
| bands at 2 x ATR (traded) | 4H | forced-1:3 | 832 | 40.4 | 1.76 | 89.0 | 0.107 | 0.72 | 3.34 | KEEP |
| bands at 2 x ATR (traded) | 6H | native | 961 | 33.7 | 2.48 | 44.3 | 0.046 | 0.70 | 3.61 | INCONCLUSIVE |
| bands at 2 x ATR (traded) | 6H | forced-1:3 | 570 | 38.6 | 1.82 | 44.5 | 0.078 | 0.47 | 1.62 | INCONCLUSIVE |
| bands at 2 x ATR (traded) | 1D | native | 218 | 38.1 | 3.20 | 33.7 | 0.154 | 0.86 | 6.12 | KEEP |
| bands at 2 x ATR (traded) | 1D | forced-1:3 | 127 | 35.4 | 2.20 | 15.0 | 0.118 | 0.34 | 0.92 | INCONCLUSIVE |
| bands at 2.5 x ATR | 1H | native | 2946 | 29.5 | 1.92 | -97.1 | -0.033 | -1.15 | -0.82 | DISCARD |
| bands at 2.5 x ATR | 1H | forced-1:3 | 1899 | 42.5 | 1.60 | 169.5 | 0.089 | 1.00 | 5.00 | INCONCLUSIVE |
| bands at 2.5 x ATR | 4H | native | 771 | 33.1 | 2.32 | 15.0 | 0.019 | 0.41 | 2.12 | INCONCLUSIVE |
| bands at 2.5 x ATR | 4H | forced-1:3 | 506 | 40.5 | 1.79 | 56.3 | 0.111 | 0.64 | 2.60 | INCONCLUSIVE |
| bands at 2.5 x ATR | 6H | native | 511 | 33.3 | 2.38 | 14.8 | 0.029 | 0.32 | 1.31 | INCONCLUSIVE |
| bands at 2.5 x ATR | 6H | forced-1:3 | 354 | 41.2 | 1.74 | 39.9 | 0.113 | 0.56 | 2.17 | INCONCLUSIVE |
| bands at 2.5 x ATR | 1D | native | 122 | 42.6 | 2.59 | 12.8 | 0.105 | 0.82 | 3.73 | KEEP |
| bands at 2.5 x ATR | 1D | forced-1:3 | 81 | 43.2 | 1.59 | 7.7 | 0.095 | 0.27 | 0.85 | DISCARD |

This is the axis that separates the two KEEP cells. **1D native is a KEEP at all 3 multipliers tested** (+0.203R, +0.154R, +0.105R per trade at 1.5x, 2.0x and 2.5x), so it does not depend on the placeholder. **4H forced-1:3 is a KEEP at 1 of the 3** - only at the conventional 2.0x - and lands as INCONCLUSIVE either side of it. That cell is therefore standing on one arbitrary value of an undisclosed parameter, and should be treated as the weaker of the two results regardless of what the table says.

### Sensitivity 2 - all three readings of the source's ambiguous stop

| Variant | Timeframe | Exit | Trades | Win% | RR | 1R as % of price | Died on entry bar | R (post-fee) | R/trade | Sharpe | R-recovery | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1R to the middle line (traded) | 1H | native | 5745 | 27.6 | 1.97 | 2.38% | 0% | -307.8 | -0.054 | -1.92 | -0.88 | DISCARD |
| 1R to the middle line (traded) | 1H | forced-1:3 | 3239 | 37.8 | 1.70 | 2.34% | 2% | 59.0 | 0.018 | 0.24 | 0.79 | DISCARD |
| 1R to the middle line (traded) | 4H | native | 1482 | 32.0 | 2.25 | 4.78% | 0% | 15.8 | 0.011 | 0.22 | 0.94 | DISCARD |
| 1R to the middle line (traded) | 4H | forced-1:3 | 832 | 40.4 | 1.76 | 4.55% | 2% | 89.0 | 0.107 | 0.72 | 3.34 | KEEP |
| 1R to the middle line (traded) | 6H | native | 961 | 33.7 | 2.48 | 5.87% | 0% | 44.3 | 0.046 | 0.70 | 3.61 | INCONCLUSIVE |
| 1R to the middle line (traded) | 6H | forced-1:3 | 570 | 38.6 | 1.82 | 5.65% | 2% | 44.5 | 0.078 | 0.47 | 1.62 | INCONCLUSIVE |
| 1R to the middle line (traded) | 1D | native | 218 | 38.1 | 3.20 | 11.78% | 0% | 33.7 | 0.154 | 0.86 | 6.12 | KEEP |
| 1R to the middle line (traded) | 1D | forced-1:3 | 127 | 35.4 | 2.20 | 11.43% | 2% | 15.0 | 0.118 | 0.34 | 0.92 | INCONCLUSIVE |
| 1R to the opposite band (literal) | 1H | native | 5745 | 27.6 | 1.99 | 4.41% | 0% | -161.8 | -0.028 | -1.85 | -0.88 | DISCARD |
| 1R to the opposite band (literal) | 1H | forced-1:3 | 2903 | 43.1 | 1.39 | 4.25% | 0% | 54.1 | 0.019 | 0.32 | 0.81 | INCONCLUSIVE |
| 1R to the opposite band (literal) | 4H | native | 1482 | 32.0 | 2.30 | 8.87% | 0% | 11.6 | 0.008 | 0.28 | 1.28 | DISCARD |
| 1R to the opposite band (literal) | 4H | forced-1:3 | 736 | 46.3 | 1.42 | 8.42% | 0% | 61.0 | 0.083 | 0.76 | 2.98 | INCONCLUSIVE |
| 1R to the opposite band (literal) | 6H | native | 961 | 33.7 | 2.51 | 10.93% | 0% | 25.6 | 0.027 | 0.71 | 3.80 | INCONCLUSIVE |
| 1R to the opposite band (literal) | 6H | forced-1:3 | 504 | 44.2 | 1.47 | 10.39% | 0% | 31.8 | 0.063 | 0.48 | 1.56 | INCONCLUSIVE |
| 1R to the opposite band (literal) | 1D | native | 218 | 38.1 | 3.23 | 22.16% | 0% | 18.4 | 0.084 | 0.88 | 6.21 | INCONCLUSIVE |
| 1R to the opposite band (literal) | 1D | forced-1:3 | 113 | 42.5 | 1.71 | 22.17% | 1% | 11.3 | 0.100 | 0.39 | 1.39 | INCONCLUSIVE |
| 1R to the band just broken (literal) | 1H | native | 5745 | 27.6 | 1.97 | 0.27% | 0% | -9103.8 | -1.585 | -0.46 | -0.63 | DISCARD |
| 1R to the band just broken (literal) | 1H | forced-1:3 | 5432 | 17.5 | 0.67 | 0.28% | 78% | -14457.2 | -2.661 | -2.27 | -1.00 | DISCARD |
| 1R to the band just broken (literal) | 4H | native | 1482 | 32.0 | 2.70 | 0.54% | 0% | 2463.7 | 1.662 | 0.14 | 0.58 | DISCARD |
| 1R to the band just broken (literal) | 4H | forced-1:3 | 1413 | 19.0 | 0.94 | 0.55% | 76% | -2598.9 | -1.839 | -1.18 | -1.00 | DISCARD |
| 1R to the band just broken (literal) | 6H | native | 961 | 33.7 | 0.78 | 0.71% | 0% | -4917.2 | -5.117 | -0.67 | -0.98 | DISCARD |
| 1R to the band just broken (literal) | 6H | forced-1:3 | 935 | 20.0 | 1.42 | 0.71% | 77% | -950.3 | -1.016 | -2.15 | -0.99 | DISCARD |
| 1R to the band just broken (literal) | 1D | native | 218 | 38.1 | 3.93 | 1.18% | 0% | 1125.5 | 5.163 | 0.56 | 5.71 | INCONCLUSIVE |
| 1R to the band just broken (literal) | 1D | forced-1:3 | 208 | 18.8 | 2.09 | 1.21% | 79% | -120.9 | -0.581 | -1.65 | -0.89 | DISCARD |

The two sane readings differ by a factor of about two in how wide 1R is, and that moves every R-denominated number - but it barely moves the scale-free ones. Native Sharpe, middle line versus opposite band: 1H -1.92 vs -1.85, 4H 0.22 vs 0.28, 6H 0.70 vs 0.71, 1D 0.86 vs 0.88. So the choice between them changes the units the result is quoted in, not whether there is a result. Expectancy is the number to distrust across these rows; Sharpe, achieved RR and R-recovery are the numbers that survive.

The third reading is the one that had to be rejected, and the table shows why rather than asserting it. Read literally, 'back inside the channel' puts the stop on the band the candle just closed a hair beyond, so 1R collapses to 0.27% of price at 1H - a fraction of a single candle. 78% of the forced trades then die on their own entry bar, which means the engine's stop-wins-ties rule is deciding the outcome instead of the strategy, and the expectancies go haywire in both directions (from -5.12R to +5.16R per trade). Those are not results, they are artefacts of an unmeasurably tight stop, and they are printed here so the rejected reading is on the record.

### Sensitivity 4 - one change at a time, 1H only

| Variant (1H) | Exit | Trades | Win% | RR | R (post-fee) | R/trade | Sharpe | Fee cost/trade | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| as traded | native | 5745 | 27.6 | 1.97 | -307.8 | -0.054 | -1.92 | 0.055R | DISCARD |
| as traded | forced-1:3 | 3239 | 37.8 | 1.70 | 59.0 | 0.018 | 0.24 | 0.057R | DISCARD |
| 50-bar middle line instead of 20 | native | 8532 | 23.3 | 2.84 | -291.1 | -0.034 | -1.01 | 0.060R | DISCARD |
| 50-bar middle line instead of 20 | forced-1:3 | 3881 | 37.2 | 1.72 | 39.8 | 0.010 | 0.15 | 0.061R | DISCARD |
| Wilder's ATR instead of a simple mean | native | 5304 | 27.1 | 2.18 | -209.1 | -0.039 | -1.32 | 0.050R | DISCARD |
| Wilder's ATR instead of a simple mean | forced-1:3 | 2943 | 39.3 | 1.71 | 177.7 | 0.060 | 0.77 | 0.052R | INCONCLUSIVE |
| entry as a state, not the first bar outside | native | 5745 | 27.6 | 1.97 | -307.8 | -0.054 | -1.92 | 0.055R | DISCARD |
| entry as a state, not the first bar outside | forced-1:3 | 3380 | 38.5 | 1.68 | 94.1 | 0.028 | 0.38 | 0.056R | INCONCLUSIVE |

Nothing here turns the headline timeframe around: the native exit stays a DISCARD under a slower middle line, under Wilder's ATR, and under the state entry. Two rows are worth reading closely. Wilder's ATR - the smoothing most charting packages actually ship as 'ATR' - moves the forced variant from +59.0R to +177.7R and its Sharpe from 0.24 to 0.77, which is a large swing for a choice the source never made explicit - and it is still not a KEEP. And the native rows are IDENTICAL under the state entry, to the last decimal. That is not a copy-paste; it is structural. The native exit only fires on a bar that closes back INSIDE the channel, and on that bar the state is already false, so there is never a bar on which a state rule could re-enter and an edge rule could not. The forced variant, whose trades outlive the state, does differ - 3239 trades against 3380 - which is the evidence that the two entry rules really are wired differently.

### The source's own market condition, tested: expanding volatility

The source says trending, expanding volatility. Trend is not directly measurable as a filter here without inventing one, but volatility is: every trade is tagged high- or low-volatility by the reporting regime label - a 14-bar ATR as a percentage of price, compared with its own 500-bar median on that timeframe - assigned from data available at entry.

| Timeframe | Exit | High-vol trades | High-vol R | High-vol R/trade | Low-vol trades | Low-vol R | Low-vol R/trade |
|---|---|---|---|---|---|---|---|
| 1H | native | 3176 | -104.8 | -0.033 | 2569 | -203.0 | -0.079 |
| 1H | forced-1:3 | 1660 | -12.8 | -0.008 | 1579 | +71.8 | 0.045 |
| 4H | native | 727 | +8.4 | 0.011 | 755 | +7.4 | 0.010 |
| 4H | forced-1:3 | 370 | +38.8 | 0.105 | 462 | +50.2 | 0.109 |
| 6H | native | 466 | +20.1 | 0.043 | 495 | +24.2 | 0.049 |
| 6H | forced-1:3 | 251 | +22.4 | 0.089 | 319 | +22.1 | 0.069 |
| 1D | native | 104 | +12.7 | 0.122 | 114 | +20.9 | 0.184 |
| 1D | forced-1:3 | 54 | +10.4 | 0.192 | 73 | +4.6 | 0.062 |

**The claim does not hold.** Of the eight cells, 4 earn more per trade in high volatility than in low (1H native, 4H native, 6H forced-1:3, 1D forced-1:3). Both KEEP cells fall on the wrong side of the claim: 1D native earns +0.122R in high volatility against +0.184R in low, and 4H forced-1:3 +0.105R against +0.109R. The reason is mechanical: the bands are drawn from ATR, so when volatility expands the bands widen with it, and price has to travel further to close outside them. The indicator already adapts to volatility, which means an extra volatility filter has little left to select on. The honest reading is that this is not a volatility-expansion strategy on crypto, whatever it is on the instruments the source tested.

### Long leg against short leg

| Timeframe | Exit | Long trades | Long R | Long win% | Short trades | Short R | Short win% |
|---|---|---|---|---|---|---|---|
| 1H | native | 2961 | -118.2 | 27.9 | 2784 | -189.5 | 27.3 |
| 1H | forced-1:3 | 1661 | +75.9 | 38.7 | 1578 | -16.9 | 36.9 |
| 4H | native | 771 | +29.3 | 33.2 | 711 | -13.5 | 30.7 |
| 4H | forced-1:3 | 438 | +70.7 | 41.1 | 394 | +18.3 | 39.6 |
| 6H | native | 525 | +49.4 | 33.3 | 436 | -5.1 | 34.2 |
| 6H | forced-1:3 | 306 | +31.7 | 37.6 | 264 | +12.8 | 39.8 |
| 1D | native | 129 | +32.9 | 42.6 | 89 | +0.8 | 31.5 |
| 1D | forced-1:3 | 74 | +13.8 | 35.1 | 53 | +1.1 | 35.8 |

**Longs carry this strategy and shorts contribute almost nothing.** At 1D native, 129 longs make +32.9R while 89 shorts make +0.8R. At 4H forced-1:3 it is +70.7R against +18.3R. Two things follow. First, the sample behind each KEEP is effectively half the size the trade count suggests, because one leg is doing the work. Second, three coins over a window containing a full bull leg is exactly the setup in which a long-only edge can be an artefact of the era rather than of the rule - the same caveat this log has already recorded against every long-biased result. It is not disqualifying, and it is not proof of an edge either.

### Best and worst conditions, per cell

| Timeframe | Exit | Best condition | Worst condition |
|---|---|---|---|
| 1H | native | up/highvol | down/lowvol |
| 1H | forced-1:3 | up/highvol | range/highvol |
| 4H | native | up/lowvol | down/lowvol |
| 4H | forced-1:3 | up/highvol | down/highvol |
| 6H | native | up/lowvol | down/lowvol |
| 6H | forced-1:3 | up/lowvol | range/lowvol |
| 1D | native | range/lowvol | down/lowvol |
| 1D | forced-1:3 | up/lowvol | range/lowvol |

Read as a description of the sample, not a filter to trade: the labels are assigned for reporting and the buckets are small once split four ways.

### Funding, flagged and not modelled - and it matters to one of the two KEEPs

These are perpetual futures, so a position open across an 8-hour settlement pays or receives funding on top of the fees already charged above. This project does not model funding - the rate is a live, time-varying series and modelling it properly is a separate piece of work - so the standing rule applies: **any KEEP that holds positions across funding stamps is PROVISIONAL until this cost is settled.** Both KEEP cells here do (4H forced-1:3, 1D native), so both are provisional.

What follows is arithmetic on two measured numbers - the average hold from the trade list and the average 1R as a percentage of price - at Bybit's BASE rate of 0.01% per 8 hours. It is a floor, not a forecast: real funding on these coins has spent long stretches well above the base rate, and it can also pay a short.

| Timeframe | Exit | Avg hold | 8h funding stamps crossed | 1R as % of price | Funding at the base rate | R/trade post-fee | Post-fee minus funding |
|---|---|---|---|---|---|---|---|
| 1H | native | 2h | 0.3 | 2.38% | -0.001R | -0.054R | -0.055R |
| 1H | forced-1:3 | 18h | 2.3 | 2.34% | -0.010R | +0.018R | +0.008R |
| 4H | native | 10h | 1.3 | 4.78% | -0.003R | +0.011R | +0.008R |
| 4H | forced-1:3 | 70h | 8.7 | 4.55% | -0.019R | +0.107R | +0.088R **<- KEEP** |
| 6H | native | 16h | 2.0 | 5.87% | -0.003R | +0.046R | +0.043R |
| 6H | forced-1:3 | 107h | 13.3 | 5.65% | -0.024R | +0.078R | +0.055R |
| 1D | native | 68h | 8.5 | 11.78% | -0.007R | +0.154R | +0.147R **<- KEEP** |
| 1D | forced-1:3 | 409h | 51.1 | 11.43% | -0.045R | +0.118R | +0.073R |



**4H forced-1:3** holds about 70 hours, roughly 8.7 funding stamps, which at the base rate is about 0.087% of notional. Against a 1R of 4.55% that is about -0.019R per trade, taking +0.107R to **+0.088R** - **below the +0.10R KEEP threshold.** Funding at the base rate alone is enough to demote this cell to INCONCLUSIVE, and any rate above the base widens the gap.

**1D native** holds about 68 hours, roughly 8.5 funding stamps, which at the base rate is about 0.085% of notional. Against a 1R of 11.78% that is about -0.007R per trade, taking +0.154R to **+0.147R** - still clear of the +0.10R KEEP threshold.

And the direction of the bias runs the wrong way. Funding is positive most of the time on these three coins - longs pay shorts - and the leg split above shows **longs are the leg that earns**. So the trades carrying each KEEP are the trades most likely to pay funding, not receive it; the table's symmetric charge is the optimistic version.

**Status: 1 of the 2 KEEP cells survive the base-rate estimate (1D native), and 1 does not (4H forced-1:3).** Neither is a tradeable conclusion until funding is measured from the actual rate history over the same window rather than assumed at its floor.

### What would change these verdicts

- **Funding measured, not floored.** The single most decisive missing number. Pull Bybit's funding-rate history for the same window and charge each trade its actual stamps. On the evidence above this decides whether 4H forced-1:3 is a KEEP at all, and it can only move the number downwards for a long-biased strategy.
- **More daily bars.** 1D native is the more robust of the two KEEPs but rests on 218 trades across three coins, and its per-coin rows are all INCONCLUSIVE on count alone (96, 75, 47). Adding coins - not a longer history, which does not exist for these listings - is the only honest way to raise that count. Ten more liquid perpetuals would take it to roughly 950 trades and make the per-coin rows readable.
- **The band multiplier held fixed by something other than convention.** 4H forced-1:3 is a KEEP at 2.0x and INCONCLUSIVE at 1.5x and 2.5x. If a source can be found that actually states the multiplier, that row becomes interpretable; until then it is one value of an undisclosed parameter and should be read as fragile.
- **A trend filter, since the source names trending markets.** Not tested here, because the source names the condition without defining it and inventing a definition would be inventing the strategy. A stated filter - price above a long moving average, or the middle line sloping up - would be a legitimate follow-up test rather than a fix.
- **The short leg examined separately.** Shorts contribute close to nothing at every timeframe. Either the rule is long-only in crypto, which should be declared and tested as such, or the sample simply did not contain enough sustained downside. Both readings are live and this window cannot separate them.
- **Slippage.** Entries are market orders at the open of the bar after a volatility expansion, which is where the book is thinnest. Nothing beyond fees is charged for that here. At 1D native the median 1R is 11.8% of price, so slippage is small relative to risk; at 1H, where 1R is 2.4%, it is not negligible and the 1H rows are DISCARDs already.

### Bottom line

The rule as the source describes it - break out on the close, exit when price closes back inside - **loses money at 1H after fees** (-307.8R post-fee from 5745 trades, pre-fee +8.4R), because the exit fires after about 2.5 bars and the trade never gets far enough from the entry to pay for two taker fees. That is the same failure mode as Strategy #1: not a wrong direction, a hold too short to cover its own costs. It improves monotonically as the bar gets longer and becomes a KEEP at 1D (218 trades, +0.154R per trade, Sharpe 0.86, t = +2.17), where the same 2.5-bar hold is two and a half days instead of two and a half hours.

Two cells clear the bar, and they are not equally solid. **1D native** survives every multiplier tested, both sane readings of the stop, and the base-rate funding estimate; its weakness is 218 trades and a long leg doing the work. **4H forced-1:3** clears the bar only at one value of an undisclosed parameter and does not survive base-rate funding. Both are **provisional KEEPs** under the funding rule; on the evidence here the daily row is the one worth carrying forward.

The source's numbers are not reproduced on crypto in any variant: the win rate is 18 to 30 percentage points lower on every timeframe, and what makes the daily rows work is a larger average winner, not accuracy. The claimed market condition is contradicted - the edge is slightly better in LOW volatility, which makes sense for bands that widen with ATR. And neither of the source's own tests was on crypto, so nothing here contradicts them either; this is the first crypto measurement of the rule, not a failed replication.

## Strategy #6 - Ichimoku Cloud trend trading (close beyond the 9/26/52 cloud with the conversion line past the base line, 1R to the far cloud edge, stop trails the cloud)

**Tested:** 2026-09-05 - **Coins:** BTCUSDT+SOLUSDT+XRPUSDT -
**Timeframes:** 1H, 4H, 6H, 1D - **Fees:** taker on both legs (0.055% each), every number below is post-fee -
**Data:** Bybit USDT perpetuals, public REST, forming bar dropped -
**Warmup:** 150 bars per dataset before the first trade is allowed

**Sourcing: MEDIUM, and weaker than Strategy #5's.** The source is a short trade
description, not a paper, and two things #5 at least had are missing. It does not
say what MARKET its 39-58% win rates came from, and it does not say what BAR
SIZE. So there is no like-for-like column to build here: the claim cannot be matched
against this test on market or on timeframe, only on shape. And the claim is a RANGE
rather than a number - the source attributes the spread to "settings", which is what
makes the parameter sweep below mandatory rather than optional. It is the source's own
stated reason its results move.

### The rule, in the source's own words

* **Trigger:** "Price breaks above the cloud with the conversion line crossing above
  the base line (bullish); mirror for shorts."
* **Stop-loss:** "Below the cloud / below the base line."
* **Take-profit:** "Commonly the lagging span or a fixed multiple."
* **Market condition:** "Sustained trends. It's a lagging system and gets chopped up
  in ranges."
* **Documented result:** about 1.5:1 reward-to-risk on win rates ranging
  39-58% "depending on settings" (market and bar size NOT stated (Pineify)).

### What the source does not disclose

Every number the indicator is made of, and the take-profit as well.

| Left undefined | Set to here | Why that value | Swept? |
|---|---|---|---|
| Conversion-line window | 9 bars | Goichi Hosoda's original setting, the chart-package default | yes, whole sets |
| Base-line window | 26 bars | same | yes, whole sets |
| Second cloud edge | 52 bars | same | yes, whole sets |
| Forward displacement | 26 bars | same | yes, whole sets |
| Take-profit multiple | none in the native rule | the source names no multiple | yes - the forced 1:3, and the source's own 1.5:1 |
| Which stop of the two | the far cloud edge | the only one that is always on the correct side of the entry | yes, both readings |

Because the source blames its own spread on settings, the three parameter sets in
Sensitivity 1 are not decoration: they are the source's caveat, measured.

### Why the take-profit could not be taken literally

The source offers two exits and neither one is usable as written.

**The lagging span is not a price you can trade to.** The lagging span is simply the
close, drawn 26 bars in the PAST. So the lagging-span value sitting at bar i on a
chart is the close of bar i+26 - a price that does not exist yet when the decision is
made. Using it as a take-profit level is not a parameter choice, it is time travel,
and it is the single biggest lookahead trap in this indicator. It is therefore not
implemented. The lagging span is not thrown away, though: it has one legitimate use,
as a CONFIRMATION phrased in the only direction that does not consume the future -
is today's close above the close 26 bars ago - and that is run in Sensitivity 4.

**"A fixed multiple" names no multiple,** so it is not a rule. Choosing one would be
writing the strategy instead of testing it. So the native exit carries NO target, and
this project's second variant - the forced 1:3 - IS the source's fixed-multiple exit,
imposed. The source's own documented 1.5:1 is additionally run as a labelled
sensitivity so the claim itself gets measured rather than quoted.

### The stop is a two-way ambiguity, and it was not silently resolved

"Below the cloud / below the base line" names two different prices, and the gap
between them is the entire risk budget of the trade. Both were measured; the traded
one was declared in advance on a structural argument, not on which one scored better.

* **Below the cloud (traded).** For a long, 1R runs from the fill to the BOTTOM of the
  cloud. Entry requires a close above the cloud's TOP, and the bottom is by
  construction at or below the top, so this stop is ALWAYS on the correct side of the
  entry: of 10420 signals across all twelve datasets, 0 had to be discarded for an
  impossible stop.
* **Below the base line (sensitivity).** The base line is a 26-bar midpoint. When price
  breaks out above a cloud drawn from data 26 bars old, the base line can easily sit
  ABOVE the entry, which is not a stop-loss at all but a level already passed. Those
  signals have to be thrown away: the same 10420 signals, of which 853 (8%)
  are unusable under this reading. The count is reported, not hidden.

Of the discard bar's four tests only expectancy depends on this choice; Sharpe,
achieved reward-to-risk and R-recovery are all scale-free. Both readings are scored
in Sensitivity 2.

### The stop trails, and it can also loosen

The cloud is re-read on every bar, so in a run the cloud bottom rises underneath a
long and the stop follows it up: the source's stop is a trailing stop by construction,
not by an added rule. But a cloud bottom can also FALL, and the plain reading of "stop
below the cloud" then puts the stop further away than it was at entry. No ratchet was
added to prevent that, because a ratchet is a rule the source does not contain, and
Strategy #5 set the precedent of letting a source-placed stop be whatever the source
placed. The consequence is that a native loser can lose MORE than one unit of risk,
so it is measured: the worst single native trade on 1H was -12.09R, and
35% of native losers on that timeframe went beyond -1.2R. The full table is below.

### What the native exit actually is

The trailing stop above, and nothing else. The source states no signal exit at all -
its two exits are an unknowable level and an unstated multiple - so a trend system held
until its trailing stop is hit is the honest minimum, and that is the native rule. The
obvious candidate exit, closing the trade when the entry condition stops being true, is
NOT in the source, so it is run as a labelled sensitivity instead of being smuggled
into the headline. The native rule also carries no time limit, which is why the hold
tail is reported: with no target and no clock, a winner runs until the cloud catches it.

**Entry is edge-triggered, not a state.** "Price is above the cloud and the conversion
line is above the base line" is a state that can persist for hundreds of bars. Traded
as a state, the rule re-enters on the bar after every exit while the state holds, which
measures the exit's churn rather than the entry. What is traded is the first bar on
which BOTH conditions hold - which fires on whichever of the source's two events
happens second, since requiring both on the same bar is almost never satisfied. The
state version is Sensitivity 4, the same treatment Strategies #3 and #5 gave the same
question.

### Lookahead bias, checked fresh for this strategy

**The mechanical audit passed on 12 of 12 datasets**, re-deriving every
one of the 14 indicator columns on history truncated at 25 different cut points and
requiring each value to match the full-history value to 1e-12. A single mismatch would
have raised and produced no numbers at all. Beyond the mechanical test, three specific
traps in this indicator were handled by hand:

1. **The displacement is backward in the data, forward on the chart.** The two cloud
   edges are drawn 26 bars to the RIGHT of the bars they were computed from, so the
   cloud a trader can see at bar i was computed from data at bar i-26. That is a shift
   into the PAST and it is legitimate. The un-shifted series is deliberately never used
   for anything: it is the cloud that will be drawn in the future, not today's cloud.
2. **The lagging span was refused as a price.** Covered above - as a take-profit level
   it is the close 26 bars ahead. It appears only as a closed-bar comparison.
3. **Intrabar levels are taken from the previous bar.** The stop is a price the
   candle's own low or high is tested against while the bar is still trading. The base
   line at bar i is built from bar i's own high and low, so testing bar i's low against
   a base line computed from bar i would be placing the stop inside the candle it is
   meant to protect against. Both stop levels are shifted one bar, so there is one rule
   to audit rather than two.

**Fills that opened already past their own stop:** 0 of 12202 across every variant.
The 1R level is fixed on the signal bar and the fill happens at the next bar's open, so
a gap through the level would start a trade already stopped out. Perpetuals trade
continuously, so this should be near zero - but "should be" is not a measurement.

### How much history these numbers cover

Trade count on its own does not say how long a period a result is drawn from,
so the window is recorded per coin. What is measured is the TRADEABLE window:
the first bar the rule is allowed to act on, after the warmup, through the last
closed bar in the data. The three coins do not start together - Bitcoin's history
on this venue begins in March 2020, XRP in May 2021, Solana in October 2021 - so a
pooled row is not three equal thirds.

Warmup skipped before the first trade: 150 bars on every timeframe. That subtraction costs very
little at 1H and a great deal at 1D, where a warmup bar is a whole day.

| Timeframe | Coin | Window traded | Days | Years | Tradeable bars | Warmup bars |
|---|---|---|---|---|---|---|
| 1H | BTCUSDT | 2020-03-31 to 2026-09-05 | 2348 | 6.43 | 56,361 | 150 |
| 1H | SOLUSDT | 2021-10-21 to 2026-09-05 | 1780 | 4.87 | 42,715 | 150 |
| 1H | XRPUSDT | 2021-05-19 to 2026-09-05 | 1934 | 5.30 | 46,426 | 150 |
| 4H | BTCUSDT | 2020-04-19 to 2026-09-05 | 2330 | 6.38 | 13,979 | 150 |
| 4H | SOLUSDT | 2021-11-09 to 2026-09-05 | 1761 | 4.82 | 10,567 | 150 |
| 4H | XRPUSDT | 2021-06-07 to 2026-09-05 | 1916 | 5.24 | 11,495 | 150 |
| 6H | BTCUSDT | 2020-05-01 to 2026-09-05 | 2318 | 6.34 | 9,271 | 150 |
| 6H | SOLUSDT | 2021-11-21 to 2026-09-05 | 1749 | 4.79 | 6,996 | 150 |
| 6H | XRPUSDT | 2021-06-19 to 2026-09-05 | 1904 | 5.21 | 7,615 | 150 |
| 1D | BTCUSDT | 2020-08-22 to 2026-09-04 | 2204 | 6.03 | 2,205 | 150 |
| 1D | SOLUSDT | 2022-03-14 to 2026-09-04 | 1635 | 4.48 | 1,636 | 150 |
| 1D | XRPUSDT | 2021-10-10 to 2026-09-04 | 1790 | 4.90 | 1,791 | 150 |

Shortest window in this run: SOLUSDT at 1D, 1635 days (4.48 years). Longest: BTCUSDT at 1H, 2348 days (6.43 years).

### Results, three coins pooled per timeframe

Both variants share the same entry rule and the same fills; only the exit differs.
"native" is the source's own exit - the trailing cloud stop, no target, no time limit.
"forced-1:3" is this project's standard comparison and is also the source's own
fixed-multiple exit made concrete: a 3R target with a 30-bar time limit.

| Timeframe | Exit | Trades | Days BTC | Days SOL | Days XRP | Win% | RR | R (pre-fee) | R (post-fee) | R/trade | Sharpe | Max DD % | Max DD (R) | R-recovery | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1H | native | 3843 | 2348 | 1780 | 1934 | 23.4 | 3.72 | 1025.3 | 452.9 | 0.118 | 0.42 | 60.0 | 267.2 | 1.70 | **INCONCLUSIVE** |
| 1H | forced-1:3 | 4670 | 2348 | 1780 | 1934 | 36.4 | 1.62 | 317.4 | -215.4 | -0.046 | -0.74 | 162.4 | 324.8 | -0.66 | **DISCARD** |
| 4H | native | 902 | 2330 | 1761 | 1916 | 27.2 | 3.72 | 325.5 | 270.7 | 0.300 | 0.81 | 28.2 | 55.7 | 4.86 | **KEEP** |
| 4H | forced-1:3 | 1122 | 2330 | 1761 | 1916 | 39.9 | 1.76 | 159.2 | 106.3 | 0.095 | 0.77 | 13.7 | 31.2 | 3.41 | **INCONCLUSIVE** |
| 6H | native | 594 | 2318 | 1749 | 1904 | 25.1 | 4.22 | 218.6 | 188.3 | 0.317 | 0.64 | 29.8 | 50.4 | 3.74 | **INCONCLUSIVE** |
| 6H | forced-1:3 | 745 | 2318 | 1749 | 1904 | 39.2 | 1.73 | 78.2 | 48.0 | 0.064 | 0.45 | 28.3 | 34.3 | 1.40 | **INCONCLUSIVE** |
| 1D | native | 144 | 2204 | 1635 | 1790 | 25.0 | 7.25 | 150.8 | 147.9 | 1.027 | 0.59 | 12.6 | 25.5 | 5.79 | **INCONCLUSIVE** |
| 1D | forced-1:3 | 182 | 2204 | 1635 | 1790 | 35.7 | 1.96 | 12.2 | 9.2 | 0.051 | 0.19 | 22.1 | 22.3 | 0.41 | **DISCARD** |

### What the source claims, and what this test measured

The source states neither the market nor the bar size, so this is a comparison of
SHAPE only - there is no like-for-like row to build.

| Test | Market | Bars | Trades | Win% | RR |
|---|---|---|---|---|---|
| The source's claim | not stated | not stated | not stated | 39-58 | 1.5 |
| This test, native exit | BTC/SOL/XRP perps | 1H | 3843 | 23.4 | 3.72 |
| This test, native exit | BTC/SOL/XRP perps | 4H | 902 | 27.2 | 3.72 |
| This test, native exit | BTC/SOL/XRP perps | 6H | 594 | 25.1 | 4.22 |
| This test, native exit | BTC/SOL/XRP perps | 1D | 144 | 25.0 | 7.25 |

Every timeframe comes in BELOW the bottom of the source's range - 23.4% to 27.2% against a claimed
39-58% - and every timeframe comes in far ABOVE its claimed reward-to-risk: 3.72 to
7.25 against 1.5. Those two gaps are the same gap. A win rate and a reward-to-risk are
not independent, and the source's pair implies a take-profit that closes trades early;
this test has no take-profit at all, because the source never says what its multiple is,
so winners run until a trailing stop catches them. Fewer of them survive and the ones
that do are far larger. Sensitivity 3 tests exactly that by imposing the source's own
1.5:1, and it is the right row to read against the claim - not this one.

**On that row the claim's SHAPE reproduces and its profitability does not.** With the
source's own 1.5R target attached, the win rate rises to 37.6-41.6% and achieved RR falls to
1.27-1.59 against the claimed 1.5 - so the pair of numbers the source quotes is reachable on
this market, landing inside the claimed 39-58% band at 3 of the 4 timeframes (1H, 4H, 6H).
What does not come with it is the money: post-fee expectancy is positive at 1 of 4
timeframes (6H), and that variant is DISCARD or INCONCLUSIVE everywhere. The source's
win rate and reward-to-risk are reproducible; they are simply not the part worth having.

### How much risk each trade actually put up

1R here is the distance from the fill to the far cloud edge, which is built from
52 bars of range, so it grows with the bar size rather than staying fixed.

| Coin | Timeframe | 1R as % of price | Typical candle range % | 1R in candles |
|---|---|---|---|---|
| BTCUSDT | 1H | 1.10% | 0.62% | 1.8x |
| BTCUSDT | 4H | 2.43% | 1.34% | 1.8x |
| BTCUSDT | 6H | 2.88% | 1.68% | 1.7x |
| BTCUSDT | 1D | 7.15% | 3.70% | 1.9x |
| SOLUSDT | 1H | 1.92% | 1.14% | 1.7x |
| SOLUSDT | 4H | 4.52% | 2.42% | 1.9x |
| SOLUSDT | 6H | 5.71% | 2.96% | 1.9x |
| SOLUSDT | 1D | 10.54% | 6.44% | 1.6x |
| XRPUSDT | 1H | 1.40% | 0.89% | 1.6x |
| XRPUSDT | 4H | 3.21% | 1.90% | 1.7x |
| XRPUSDT | 6H | 4.47% | 2.35% | 1.9x |
| XRPUSDT | 1D | 7.22% | 5.03% | 1.4x |

Across all 12 coin-timeframe cells 1R runs from 1.4x to 1.9x a typical candle.
That matters because a stop inside one candle is decided by the engine's pessimistic
intrabar tie-break rather than by the strategy - the disease Strategy #1 documented.
Nothing here is anywhere near that thin.

### How the trades ended, and how long they ran

| Timeframe | Exit | How the trades ended (count @ mean net R) | Avg bars | Median bars | 95th pct | Longest |
|---|---|---|---|---|---|---|
| 1H | native | stop 3843 @ +0.118R | 31.6 | 17 | 109 | 280 |
| 1H | forced-1:3 | stop 2321 @ -1.153R, target 658 @ +2.837R, time 1691 @ +0.350R | 16.4 | 16 | 30 | 30 |
| 4H | native | stop 902 @ +0.300R | 33.7 | 20 | 110 | 300 |
| 4H | forced-1:3 | stop 543 @ -1.063R, target 176 @ +2.940R, time 403 @ +0.412R | 16.6 | 16 | 30 | 30 |
| 6H | native | stop 594 @ +0.317R | 33.5 | 21 | 118 | 289 |
| 6H | forced-1:3 | stop 361 @ -1.056R, target 108 @ +2.951R, time 276 @ +0.400R | 17.0 | 17 | 30 | 30 |
| 1D | native | stop 144 @ +1.027R | 32.5 | 20 | 98 | 197 |
| 1D | forced-1:3 | stop 97 @ -1.020R, target 29 @ +2.975R, time 56 @ +0.391R | 15.4 | 12 | 30 | 30 |

### What the loosening stop cost

The stop is re-read from the cloud every bar with no ratchet, so a loss can exceed the
one unit of risk it was sold as. This is the size of that effect.

| Timeframe | Exit | Losers | Mean loser | Losses beyond -1.2R | Share of losers | Worst single trade | Best single trade |
|---|---|---|---|---|---|---|---|
| 1H | native | 2945 | -1.154R | 1018 | 35% | -12.09R | +272.91R |
| 1H | forced-1:3 | 2969 | -0.975R | 412 | 14% | -12.09R | +2.99R |
| 4H | native | 657 | -1.061R | 168 | 26% | -10.43R | +65.50R |
| 4H | forced-1:3 | 674 | -0.922R | 28 | 4% | -1.74R | +2.99R |
| 6H | native | 445 | -1.027R | 93 | 21% | -5.22R | +83.29R |
| 6H | forced-1:3 | 453 | -0.906R | 8 | 2% | -5.09R | +3.00R |
| 1D | native | 108 | -0.967R | 15 | 14% | -2.95R | +80.11R |
| 1D | forced-1:3 | 117 | -0.900R | 0 | 0% | -1.14R | +2.99R |

### How much of the result is a handful of trades

The discard bar does not test this, and on this strategy it is the first thing that
should be checked. A trailing stop with no target and no time limit produces a few
enormous winners - the best single 1H native trade is worth more R than this strategy's
entire 4H, 6H, 1D native columns, each taken on its own - and an average R per trade is
only meaningful if it is not one trade wearing a trench coat.

| Timeframe | Exit | Trades | Total R (post-fee) | Best single trade | Its share of the total | Best five | Their share | Total without the best |
|---|---|---|---|---|---|---|---|---|
| 1H | native | 3843 | +452.9 | +272.91R | 60% | +618.9R | 137% | +180.0R |
| 1H | forced-1:3 | 4670 | -215.4 | +2.99R | -1% | +14.9R | -7% | -218.4R |
| 4H | native | 902 | +270.7 | +65.50R | 24% | +187.1R | 69% | +205.2R |
| 4H | forced-1:3 | 1122 | +106.3 | +2.99R | 3% | +15.0R | 14% | +103.3R |
| 6H | native | 594 | +188.3 | +83.29R | 44% | +187.4R | 100% | +105.0R |
| 6H | forced-1:3 | 745 | +48.0 | +3.00R | 6% | +15.0R | 31% | +45.0R |
| 1D | native | 144 | +147.9 | +80.11R | 54% | +175.3R | 118% | +67.8R |
| 1D | forced-1:3 | 182 | +9.2 | +2.99R | 33% | +15.0R | 162% | +6.2R |

Two notes on reading that table. A share above 100% is not an error: the best five
trades can exceed the net total because everything else in the book is net negative
underneath them. And where the total itself is negative the share is arithmetic noise -
ignore the percentage on those rows and read the R figures instead.

**This is the most important caveat on every native row.** At 1H the single best trade
is 60% of the whole post-fee total, and the best five are 137%; at 1D the best trade
alone is 54% of the total. Strip the single best trade out and the native column still stays
positive on every timeframe, which is the one reassuring part of the table - but the
distribution is the opposite of the steady grind the R-per-trade figures suggest. The
forced variant, which caps every winner at 3R, has no such concentration and also has no
such result, and those two facts are the same fact.

### The source's own claimed condition: sustained trends, chopped up in ranges

This is the one claim in the source that can be checked directly. The regime label is
two halves joined by a slash (trend / volatility); this keeps only the trend half and
pools up-trend with down-trend, because the rule is symmetric and the claim is about
trend, not direction. The label is assigned from a 100-bar average and its own 20-bar
slope, both known at the time of the trade, and it is reporting-only - no trade was
filtered on it.

| Timeframe | Exit | Trending trades | Trending R | Trending R/trade | Range trades | Range R | Range R/trade |
|---|---|---|---|---|---|---|---|
| 1H | native | 2272 | +296.5 | 0.130 | 1571 | +156.5 | 0.100 |
| 1H | forced-1:3 | 3042 | -255.4 | -0.084 | 1628 | +40.0 | 0.025 |
| 4H | native | 544 | +46.5 | 0.086 | 358 | +224.1 | 0.626 |
| 4H | forced-1:3 | 752 | +30.3 | 0.040 | 370 | +75.9 | 0.205 |
| 6H | native | 366 | +35.8 | 0.098 | 228 | +152.5 | 0.669 |
| 6H | forced-1:3 | 497 | +14.7 | 0.030 | 248 | +33.3 | 0.134 |
| 1D | native | 85 | +109.7 | 1.291 | 59 | +38.2 | 0.648 |
| 1D | forced-1:3 | 121 | +1.3 | 0.010 | 61 | +7.9 | 0.130 |

**The source's claim is NOT confirmed.** R per trade is higher in trending conditions in only
2 of the 8 timeframe-and-exit cells (1H native, 1D native), and higher in RANGES in
6 (1H forced-1:3, 4H native, 4H forced-1:3, 6H native, 6H forced-1:3, 1D forced-1:3). The widest contradiction is 6H native, where the range bucket earns
+0.669R per trade against +0.098R in trending conditions - the reverse of what the source says
should happen.

The most likely reason is mechanical rather than damning, and it cuts both ways. The
regime label is assigned AT ENTRY from a 100-bar average and its 20-bar slope, and this
rule is designed to enter BEFORE that average has turned: a breakout from a quiet stretch
is labelled "range" on the bar it fires, and if it then becomes a sustained trend the
profit is still booked against the "range" label. So the split measures what the market
looked like when the trade was taken, not what it did afterwards - which means this test
cannot confirm the source's claim and cannot refute it either. What it does establish is
that the claim gives no usable filter: R per trade is HIGHER in labelled ranges on the
native exit at 2 of the 4 timeframes, so switching this rule off in ranges would have
removed some of its best trades rather than its worst.

### Long leg vs short leg

The rule is symmetric. The market is not: these three coins spent most of the sample in
a long-run uptrend, so a symmetric rule is expected to earn more on the long side.

| Timeframe | Exit | Long trades | Long R | Long win% | Short trades | Short R | Short win% |
|---|---|---|---|---|---|---|---|
| 1H | native | 1926 | +525.8 | 23.3 | 1917 | -72.9 | 23.4 |
| 1H | forced-1:3 | 2349 | -103.3 | 36.2 | 2321 | -112.1 | 36.6 |
| 4H | native | 459 | +289.0 | 25.3 | 443 | -18.3 | 29.1 |
| 4H | forced-1:3 | 553 | +66.8 | 40.0 | 569 | +39.5 | 39.9 |
| 6H | native | 295 | +182.7 | 25.8 | 299 | +5.5 | 24.4 |
| 6H | forced-1:3 | 361 | +26.1 | 37.1 | 384 | +21.9 | 41.1 |
| 1D | native | 65 | +152.1 | 23.1 | 79 | -4.2 | 26.6 |
| 1D | forced-1:3 | 78 | +0.4 | 32.1 | 104 | +8.8 | 38.5 |

The long leg out-earns the short leg in 7 of 8 cells.

### Per coin, per timeframe, per exit

coin      timeframe  exit         trades   win%     RR    R pre   R post  R/trade  Sharpe     DD%    DD R  recov  verdict
-------------------------------------------------------------------------------------------------------------------------
BTCUSDT   1H         native         1459   23.1   3.76    435.1    174.4    0.120    0.32    42.0   157.2   1.11  INCONCLUSIVE
BTCUSDT   1H         forced-1:3     1824   34.9   1.59     80.4   -169.2   -0.093   -1.05   158.5   231.2  -0.73  DISCARD
BTCUSDT   4H         native          358   24.6   4.18    131.1    104.2    0.291    0.53    21.5    35.6   2.93  INCONCLUSIVE
BTCUSDT   4H         forced-1:3      446   38.1   1.70     38.1     12.5    0.028    0.16    20.6    25.2   0.50  DISCARD
BTCUSDT   6H         native          222   21.6   5.42    105.0     92.8    0.418    0.56    15.4    23.9   3.88  INCONCLUSIVE
BTCUSDT   6H         forced-1:3      287   38.3   1.86     37.1     24.8    0.086    0.40    11.3    12.2   2.03  INCONCLUSIVE
BTCUSDT   1D         native           47   29.8   8.86     92.9     91.6    1.949    0.46     6.7    12.8   7.14  INCONCLUSIVE
BTCUSDT   1D         forced-1:3       62   41.9   1.79     10.9      9.7    0.156    0.34     5.6     6.2   1.56  INCONCLUSIVE
SOLUSDT   1H         native         1079   24.8   3.31    202.1     88.3    0.082    0.34    67.1   104.0   0.85  INCONCLUSIVE
SOLUSDT   1H         forced-1:3     1303   39.1   1.69    166.5     63.4    0.049    0.54    20.1    39.8   1.59  INCONCLUSIVE
SOLUSDT   4H         native          249   28.9   3.77    106.3     96.1    0.386    0.74    14.9    31.5   3.05  KEEP
SOLUSDT   4H         forced-1:3      311   43.7   1.86     77.8     67.7    0.218    1.17     8.2    14.5   4.66  KEEP
SOLUSDT   6H         native          158   29.7   3.24     46.9     41.5    0.263    0.52    12.4    14.1   2.94  INCONCLUSIVE
SOLUSDT   6H         forced-1:3      199   41.2   2.02     46.4     41.6    0.209    0.91    10.0    13.0   3.21  KEEP
SOLUSDT   1D         native           36   27.8   5.27     26.2     25.7    0.714    0.47     6.9     8.7   2.94  INCONCLUSIVE
SOLUSDT   1D         forced-1:3       47   36.2   2.41      9.7      9.2    0.195    0.41     8.2     8.4   1.09  INCONCLUSIVE
XRPUSDT   1H         native         1305   22.5   4.03    388.1    190.3    0.146    0.27   101.5   128.1   1.49  DISCARD
XRPUSDT   1H         forced-1:3     1543   36.0   1.58     70.6   -109.5   -0.071   -0.76   112.5   127.4  -0.86  DISCARD
XRPUSDT   4H         native          295   28.8   3.23     88.1     70.3    0.238    0.38    52.8    71.4   0.98  INCONCLUSIVE
XRPUSDT   4H         forced-1:3      365   38.9   1.76     43.3     26.0    0.071    0.39    19.0    22.5   1.16  INCONCLUSIVE
XRPUSDT   6H         native          214   25.2   3.98     66.7     54.0    0.252    0.27    50.8    59.6   0.91  DISCARD
XRPUSDT   6H         forced-1:3      259   38.6   1.40     -5.3    -18.3   -0.071   -0.36    36.2    39.0  -0.47  DISCARD
XRPUSDT   1D         native           61   19.7   6.79     31.7     30.6    0.502    0.27    18.8    18.6   1.64  DISCARD
XRPUSDT   1D         forced-1:3       73   30.1   1.85     -8.4     -9.6   -0.132   -0.36    17.7    17.6  -0.55  DISCARD

### Context checks - is the test fair, and is the result separable from luck

1H:
  native       3843 trades | pre-fee +0.2668R/trade (spread 6.30R, t = +2.62) | post-fee +0.1179R/trade (t = +1.16)
  forced-1:3   4670 trades | pre-fee +0.0680R/trade (spread 1.42R, t = +3.27) | post-fee -0.0461R/trade (t = -2.18)
  resolved inside their first candle: native 11%, forced-1:3 8%
  the two variants share 64.4% of their entries  <-- TOO LOW to compare exits fairly
4H:
  native        902 trades | pre-fee +0.3608R/trade (spread 4.23R, t = +2.56) | post-fee +0.3001R/trade (t = +2.13)
  forced-1:3   1122 trades | pre-fee +0.1418R/trade (spread 1.46R, t = +3.25) | post-fee +0.0947R/trade (t = +2.16)
  resolved inside their first candle: native 9%, forced-1:3 7%
  the two variants share 62.6% of their entries  <-- TOO LOW to compare exits fairly
6H:
  native        594 trades | pre-fee +0.3679R/trade (spread 4.78R, t = +1.87) | post-fee +0.3169R/trade (t = +1.61)
  forced-1:3    745 trades | pre-fee +0.1050R/trade (spread 1.43R, t = +2.01) | post-fee +0.0645R/trade (t = +1.22)
  resolved inside their first candle: native 8%, forced-1:3 6%
  the two variants share 64.0% of their entries  <-- TOO LOW to compare exits fairly
1D:
  native        144 trades | pre-fee +1.0473R/trade (spread 8.40R, t = +1.50) | post-fee +1.0273R/trade (t = +1.47)
  forced-1:3    182 trades | pre-fee +0.0671R/trade (spread 1.49R, t = +0.61) | post-fee +0.0506R/trade (t = +0.46)
  resolved inside their first candle: native 9%, forced-1:3 8%
  the two variants share 62.4% of their entries  <-- TOO LOW to compare exits fairly

The stop-against-candle check is deliberately not printed here. It takes a single 1R
percentage, and on this strategy 1R is not one percentage: it is built from 52 bars of
range, so it runs from 1.40% of price at 1H to several times that on daily bars. The
per-cell version of the same check is the risk table above, which puts every one of the
12 cells between 1.4x and 1.9x a typical candle.

**The overlap line is the one that matters.** The two variants share only 62% to 64% of their
entries, well under the 85% this project asks for before comparing exits. That is not a
bug, it is the native exit having no time limit: while one native trade is still running, the
forced variant has already been stopped or timed out and has taken further entries the
native run never saw. It is also why the exit-death check below is repeated on only the
entries both variants actually took.

### Exit-death check - which exit style the edge depends on

The mandatory check compares the two exits on the full runs. It is reported first
because it is the project's defined test, but on this strategy it is contaminated: an
open position blocks the next signal, the native rule holds until a trailing stop is
hit while the forced variant is capped at 30 bars, so the forced run takes entries the
native run was still holding through. The right-hand columns re-score both variants on
ONLY the entries they both actually took, which isolates the exit from the different
trade population.

| Timeframe | Native R/trade | Forced R/trade | Exit-death | Diagnosis | Shared entries | Native (shared) | Forced (shared) | Exit-death (shared) |
|---|---|---|---|---|---|---|---|
| 1H | +0.118R | -0.046R | **yes** | the exit flips the sign of the edge: native +0.118R per trade vs forced 1:3 -0.046R. Identical entries, so the entry signal is not what decided this - the forced 1:3 exit is. The edge, such as it is, lives in the native exit. | 3030 | +0.129R | -0.072R | **yes** |
| 4H | +0.300R | +0.095R | **yes** | both exits agree on direction but differ by 0.205R per trade (native +0.300R vs forced 1:3 +0.095R), which is larger than the entire +0.10R KEEP requirement. The native exit is doing more work than the entry signal. | 697 | +0.417R | +0.124R | **yes** |
| 6H | +0.317R | +0.064R | **yes** | both exits agree on direction but differ by 0.252R per trade (native +0.317R vs forced 1:3 +0.064R), which is larger than the entire +0.10R KEEP requirement. The native exit is doing more work than the entry signal. | 472 | +0.376R | +0.059R | **yes** |
| 1D | +1.027R | +0.051R | **yes** | both exits agree on direction but differ by 0.977R per trade (native +1.027R vs forced 1:3 +0.051R), which is larger than the entire +0.10R KEEP requirement. The native exit is doing more work than the entry signal. | 118 | +0.592R | +0.104R | **yes** |

### Sensitivity 1 - the whole parameter set, which the source itself blames

The source says its win rate moves with "settings" and never says which. So all four
parameters are moved together as complete sets: Hosoda's original (traded), a slightly
slower set, and the doubling that is commonly recommended for a market that trades 24/7
instead of in daily sessions. Nothing here chose the headline.

| Variant | Timeframe | Exit | Trades | Win% | RR | R (post-fee) | R/trade | Sharpe | R-recovery | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| 9/26/52 disp 26 (Hosoda's original, traded) | 1H | native | 3843 | 23.4 | 3.72 | 452.9 | 0.118 | 0.42 | 1.70 | INCONCLUSIVE |
| 9/26/52 disp 26 (Hosoda's original, traded) | 1H | forced-1:3 | 4670 | 36.4 | 1.62 | -215.4 | -0.046 | -0.74 | -0.66 | DISCARD |
| 9/26/52 disp 26 (Hosoda's original, traded) | 4H | native | 902 | 27.2 | 3.72 | 270.7 | 0.300 | 0.81 | 4.86 | KEEP |
| 9/26/52 disp 26 (Hosoda's original, traded) | 4H | forced-1:3 | 1122 | 39.9 | 1.76 | 106.3 | 0.095 | 0.77 | 3.41 | INCONCLUSIVE |
| 9/26/52 disp 26 (Hosoda's original, traded) | 6H | native | 594 | 25.1 | 4.22 | 188.3 | 0.317 | 0.64 | 3.74 | INCONCLUSIVE |
| 9/26/52 disp 26 (Hosoda's original, traded) | 6H | forced-1:3 | 745 | 39.2 | 1.73 | 48.0 | 0.064 | 0.45 | 1.40 | INCONCLUSIVE |
| 9/26/52 disp 26 (Hosoda's original, traded) | 1D | native | 144 | 25.0 | 7.25 | 147.9 | 1.027 | 0.59 | 5.79 | INCONCLUSIVE |
| 9/26/52 disp 26 (Hosoda's original, traded) | 1D | forced-1:3 | 182 | 35.7 | 1.96 | 9.2 | 0.051 | 0.19 | 0.41 | DISCARD |
| 10/30/60 disp 30 | 1H | native | 3359 | 23.2 | 3.88 | 515.7 | 0.154 | 0.56 | 1.31 | INCONCLUSIVE |
| 10/30/60 disp 30 | 1H | forced-1:3 | 4302 | 36.8 | 1.57 | -220.2 | -0.051 | -0.78 | -0.69 | DISCARD |
| 10/30/60 disp 30 | 4H | native | 816 | 25.6 | 3.66 | 161.6 | 0.198 | 0.49 | 2.40 | INCONCLUSIVE |
| 10/30/60 disp 30 | 4H | forced-1:3 | 1045 | 40.0 | 1.70 | 76.1 | 0.073 | 0.58 | 2.36 | INCONCLUSIVE |
| 10/30/60 disp 30 | 6H | native | 554 | 23.6 | 4.34 | 149.8 | 0.270 | 0.47 | 2.57 | INCONCLUSIVE |
| 10/30/60 disp 30 | 6H | forced-1:3 | 701 | 38.9 | 1.75 | 44.0 | 0.063 | 0.43 | 1.71 | INCONCLUSIVE |
| 10/30/60 disp 30 | 1D | native | 132 | 25.8 | 7.62 | 166.0 | 1.257 | 0.56 | 5.60 | INCONCLUSIVE |
| 10/30/60 disp 30 | 1D | forced-1:3 | 161 | 35.4 | 1.87 | 2.5 | 0.015 | 0.05 | 0.11 | DISCARD |
| 20/60/120 disp 30 (the 24/7-market adjustment) | 1H | native | 2373 | 23.6 | 4.61 | 777.5 | 0.328 | 0.75 | 7.56 | KEEP |
| 20/60/120 disp 30 (the 24/7-market adjustment) | 1H | forced-1:3 | 3056 | 38.6 | 1.44 | -159.1 | -0.052 | -0.74 | -0.71 | DISCARD |
| 20/60/120 disp 30 (the 24/7-market adjustment) | 4H | native | 578 | 23.2 | 5.28 | 239.6 | 0.415 | 0.73 | 4.69 | KEEP |
| 20/60/120 disp 30 (the 24/7-market adjustment) | 4H | forced-1:3 | 744 | 41.5 | 1.51 | 27.4 | 0.037 | 0.30 | 0.60 | DISCARD |
| 20/60/120 disp 30 (the 24/7-market adjustment) | 6H | native | 379 | 21.6 | 5.33 | 121.7 | 0.321 | 0.52 | 2.99 | INCONCLUSIVE |
| 20/60/120 disp 30 (the 24/7-market adjustment) | 6H | forced-1:3 | 491 | 39.3 | 1.71 | 26.5 | 0.054 | 0.36 | 1.45 | INCONCLUSIVE |
| 20/60/120 disp 30 (the 24/7-market adjustment) | 1D | native | 91 | 20.9 | 8.45 | 75.0 | 0.824 | 0.55 | 3.74 | INCONCLUSIVE |
| 20/60/120 disp 30 (the 24/7-market adjustment) | 1D | forced-1:3 | 122 | 36.9 | 1.85 | 5.0 | 0.041 | 0.13 | 0.28 | DISCARD |

### Sensitivity 2 - the two readings of the source's ambiguous stop

* **1R to the far cloud edge (traded):** 10420 signals fired across all twelve datasets, 0 unusable.
* **1R to the base line (literal):** the same 10420 signals, 853 unusable (8%) because the base
  line sits on the wrong side of the entry - a stop already passed is not a stop.

"Died on entry bar" is the share of trades that ended on the very first bar, which is
the tell for a stop too close to the fill to be a strategy decision.

| Variant | Timeframe | Exit | Trades | Win% | RR | 1R as % of price | Died on entry bar | R (post-fee) | R/trade | Sharpe | R-recovery | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1R to the far cloud edge (traded) | 1H | native | 3843 | 23.4 | 3.72 | 1.40% | 11% | 452.9 | 0.118 | 0.42 | 1.70 | INCONCLUSIVE |
| 1R to the far cloud edge (traded) | 1H | forced-1:3 | 4670 | 36.4 | 1.62 | 1.82% | 8% | -215.4 | -0.046 | -0.74 | -0.66 | DISCARD |
| 1R to the far cloud edge (traded) | 4H | native | 902 | 27.2 | 3.72 | 3.18% | 9% | 270.7 | 0.300 | 0.81 | 4.86 | KEEP |
| 1R to the far cloud edge (traded) | 4H | forced-1:3 | 1122 | 39.9 | 1.76 | 4.06% | 7% | 106.3 | 0.095 | 0.77 | 3.41 | INCONCLUSIVE |
| 1R to the far cloud edge (traded) | 6H | native | 594 | 25.1 | 4.22 | 3.98% | 8% | 188.3 | 0.317 | 0.64 | 3.74 | INCONCLUSIVE |
| 1R to the far cloud edge (traded) | 6H | forced-1:3 | 745 | 39.2 | 1.73 | 4.92% | 6% | 48.0 | 0.064 | 0.45 | 1.40 | INCONCLUSIVE |
| 1R to the far cloud edge (traded) | 1D | native | 144 | 25.0 | 7.25 | 7.62% | 9% | 147.9 | 1.027 | 0.59 | 5.79 | INCONCLUSIVE |
| 1R to the far cloud edge (traded) | 1D | forced-1:3 | 182 | 35.7 | 1.96 | 10.43% | 8% | 9.2 | 0.051 | 0.19 | 0.41 | DISCARD |
| 1R to the base line (literal) | 1H | native | 5425 | 26.8 | 2.39 | 1.18% | 16% | -537.5 | -0.099 | -0.58 | -0.62 | DISCARD |
| 1R to the base line (literal) | 1H | forced-1:3 | 5085 | 32.5 | 1.63 | 1.23% | 17% | -914.9 | -0.180 | -2.30 | -0.98 | DISCARD |
| 1R to the base line (literal) | 4H | native | 1312 | 29.1 | 3.28 | 2.51% | 14% | 296.1 | 0.226 | 0.74 | 5.21 | KEEP |
| 1R to the base line (literal) | 4H | forced-1:3 | 1226 | 33.3 | 1.88 | 2.58% | 15% | -56.2 | -0.046 | -0.32 | -0.75 | DISCARD |
| 1R to the base line (literal) | 6H | native | 861 | 30.7 | 2.82 | 3.21% | 13% | 127.6 | 0.148 | 0.58 | 2.77 | INCONCLUSIVE |
| 1R to the base line (literal) | 6H | forced-1:3 | 812 | 34.6 | 1.95 | 3.33% | 14% | 17.9 | 0.022 | 0.14 | 0.43 | DISCARD |
| 1R to the base line (literal) | 1D | native | 206 | 26.2 | 3.46 | 6.27% | 13% | 28.0 | 0.136 | 0.24 | 0.73 | DISCARD |
| 1R to the base line (literal) | 1D | forced-1:3 | 197 | 32.5 | 2.32 | 6.43% | 14% | 15.4 | 0.078 | 0.26 | 0.73 | DISCARD |

### Sensitivity 3 - the source's own documented 1.5:1, imposed as a target

The native rule has no target because the source names no multiple. This adds one: the
source's own 1.5:1. It is a sensitivity, never the traded rule.

| Timeframe | Native, no target (traded) | Native + 1.5R target | RR achieved, no target -> 1.5R target |
|---|---|---|---|
| 1H | 3843 trades, 23.4% win, 452.9R, Sharpe 0.42 | 4732 trades, 39.4% win, -511.0R, Sharpe -2.04 | 3.72 -> 1.27 |
| 4H | 902 trades, 27.2% win, 270.7R, Sharpe 0.81 | 1136 trades, 40.2% win, -16.7R, Sharpe -0.15 | 3.72 -> 1.45 |
| 6H | 594 trades, 25.1% win, 188.3R, Sharpe 0.64 | 753 trades, 41.6% win, 31.8R, Sharpe 0.35 | 4.22 -> 1.52 |
| 1D | 144 trades, 25.0% win, 147.9R, Sharpe 0.59 | 181 trades, 37.6% win, -4.1R, Sharpe -0.11 | 7.25 -> 1.59 |

### Sensitivity 4 - one change at a time, 1H only

Each row changes exactly one thing the source left open, so a reader can see whether the
verdict is a property of the strategy or of a placeholder. The last row is the only
honest use of the lagging span: today's close against the close
26 bars ago, two bars that have both already happened.

| Variant (1H) | Exit | Trades | Win% | RR | R (post-fee) | R/trade | Sharpe | Fee cost/trade | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| as traded | native | 3843 | 23.4 | 3.72 | 452.9 | 0.118 | 0.42 | 0.149R | INCONCLUSIVE |
| as traded | forced-1:3 | 4670 | 36.4 | 1.62 | -215.4 | -0.046 | -0.74 | 0.114R | DISCARD |
| entry as a state, not the first bar the pair turns true | native | 4238 | 22.3 | 3.66 | 216.7 | 0.051 | 0.18 | 0.172R | DISCARD |
| entry as a state, not the first bar the pair turns true | forced-1:3 | 6699 | 36.8 | 1.55 | -363.1 | -0.054 | -1.05 | 0.101R | DISCARD |
| exit added: close when the trigger stops being true | native | 7193 | 25.5 | 2.86 | -78.4 | -0.011 | -0.09 | 0.112R | DISCARD |
| exit added: close when the trigger stops being true | forced-1:3 | 4670 | 36.4 | 1.62 | -215.4 | -0.046 | -0.74 | 0.114R | DISCARD |
| lagging-span confirmation added | native | 3747 | 23.8 | 3.52 | 338.7 | 0.090 | 0.31 | 0.141R | INCONCLUSIVE |
| lagging-span confirmation added | forced-1:3 | 4657 | 36.9 | 1.59 | -201.0 | -0.043 | -0.69 | 0.109R | DISCARD |

### Best and worst conditions, per variant

Reporting-only labels, assigned from data known at the time of each trade.

| Timeframe | Exit | Best condition | Worst condition |
|---|---|---|---|
| 1H | native | down/lowvol | down/highvol |
| 1H | forced-1:3 | range/lowvol | down/lowvol |
| 4H | native | range/highvol | down/lowvol |
| 4H | forced-1:3 | range/lowvol | down/highvol |
| 6H | native | range/highvol | down/highvol |
| 6H | forced-1:3 | range/highvol | up/lowvol |
| 1D | native | up/lowvol | range/highvol |
| 1D | forced-1:3 | down/highvol | up/highvol |

### The discard bar, applied to each exit variant separately

The two exits are never collapsed into one verdict. The thresholds are the project's
standing ones: KEEP needs at least 30 trades, +0.10R per trade, Sharpe
0.70, R-recovery 1.50, and for a native exit an achieved reward-to-risk of at
least 1.50. A count under 30 returns INCONCLUSIVE, not DISCARD.

| Timeframe | Exit | Trades | R/trade | Sharpe | R-recovery | Verdict | Why |
|---|---|---|---|---|---|---|---|
| 1H | native | 3843 | 0.118 | 0.42 | 1.70 | **INCONCLUSIVE** | positive but short of the KEEP bar: Sharpe 0.42 < 0.7 |
| 1H | forced-1:3 | 4670 | -0.046 | -0.74 | -0.66 | **DISCARD** | post-fee expectancy -0.046R per trade is not positive; post-fee Sharpe -0.74 below 0.3; earned only -0.66x its worst drawdown |
| 4H | native | 902 | 0.300 | 0.81 | 4.86 | **KEEP** | +0.300R per trade, Sharpe 0.81, earned 4.86x its worst drawdown over 902 trades |
| 4H | forced-1:3 | 1122 | 0.095 | 0.77 | 3.41 | **INCONCLUSIVE** | positive but short of the KEEP bar: expectancy +0.095R < +0.10R |
| 6H | native | 594 | 0.317 | 0.64 | 3.74 | **INCONCLUSIVE** | positive but short of the KEEP bar: Sharpe 0.64 < 0.7 |
| 6H | forced-1:3 | 745 | 0.064 | 0.45 | 1.40 | **INCONCLUSIVE** | positive but short of the KEEP bar: expectancy +0.064R < +0.10R; Sharpe 0.45 < 0.7; R-recovery 1.40 < 1.5 |
| 1D | native | 144 | 1.027 | 0.59 | 5.79 | **INCONCLUSIVE** | positive but short of the KEEP bar: Sharpe 0.59 < 0.7 |
| 1D | forced-1:3 | 182 | 0.051 | 0.19 | 0.41 | **DISCARD** | post-fee Sharpe 0.19 below 0.3; earned only 0.41x its worst drawdown |

For the forced variant the fee drag has a break-even win rate attached, because a fixed
3R target makes that arithmetic meaningful: 1H needs 27.9%, 4H needs 26.2%, 6H needs 26.0%, 1D needs 25.4%.

### Funding, flagged and not modelled - and on this strategy it is the main event

These are perpetual futures, so a position open across an 8-hour settlement pays or
receives funding on top of the fees already charged above. This project does not model
funding - the rate is a live, time-varying series and modelling it properly is separate
work - so the standing rule applies: **any KEEP that holds positions across funding
stamps is PROVISIONAL until this cost is settled.** This rule holds for tens of bars by
design - the native average is 31.6 bars at 1H and 32.5 bars at 1D - so every
cell crosses stamps, and the KEEP cells (4H native) are provisional by that rule.

What follows is arithmetic on two measured numbers - the average hold and the average 1R
as a percentage of price - at Bybit's BASE rate of 0.01% per 8 hours. It is a floor,
not a forecast: real funding on these coins has spent long stretches well above the base
rate. It can also pay a short.

| Timeframe | Exit | Avg hold | 8h funding stamps crossed | 1R as % of price | Funding at the base rate | R/trade post-fee | Post-fee minus funding |
|---|---|---|---|---|---|---|---|
| 1H | native | 32h | 3.9 | 1.40% | -0.028R | +0.118R | +0.090R |
| 1H | forced-1:3 | 16h | 2.1 | 1.82% | -0.011R | -0.046R | -0.057R |
| 4H | native | 135h | 16.8 | 3.18% | -0.053R | +0.300R | +0.247R **<- KEEP** |
| 4H | forced-1:3 | 67h | 8.3 | 4.06% | -0.020R | +0.095R | +0.074R |
| 6H | native | 201h | 25.2 | 3.98% | -0.063R | +0.317R | +0.254R |
| 6H | forced-1:3 | 102h | 12.7 | 4.92% | -0.026R | +0.064R | +0.039R |
| 1D | native | 780h | 97.5 | 7.62% | -0.128R | +1.027R | +0.899R |
| 1D | forced-1:3 | 369h | 46.2 | 10.43% | -0.044R | +0.051R | +0.006R |

**4H native** holds about 135 hours, roughly 16.8 funding stamps, which at the base rate is about 0.168% of notional. Against a 1R of 3.18% that is about -0.053R per trade, taking +0.300R to **+0.247R** - still clear of the +0.10R KEEP threshold.

And the direction of the bias runs the wrong way. Funding is positive most of the time on
these three coins - longs pay shorts - and the leg split above shows the long leg earning
more in 7 of 8 cells. So the trades carrying the result are the trades most likely to
PAY funding rather than receive it, which makes the table's symmetric charge the optimistic
version.

**Status: 1 of the 1 KEEP cells survive the base-rate estimate (4H native).** None is a tradeable conclusion until funding is measured from the actual rate history
over the same window rather than assumed at its floor.

### What would change these verdicts

- **Funding measured, not floored.** The single most decisive missing number, and more so
  here than on any strategy logged yet: this rule holds positions for days by design, so
  the daily cells cross roughly 98 settlements per trade. Pull Bybit's funding-rate
  history for the same window and charge each trade its actual stamps. It can only move
  the number downwards for a long-biased strategy.
- **More 1D bars.** The daily rows rest on 144 trades across three coins (47, 36, 61
  per coin), which is the thinnest sample in the table. Adding liquid perpetuals - not a
  longer history, which does not exist for these listings - is the only honest way to
  raise that count.
- **A source that states its parameters.** The win rate the source quotes is a range it
  blames on settings, and Sensitivity 1 shows the verdict moving with the settings too.
  Until a source states the four windows, every row here is one arbitrary point in a
  space the source itself says is unstable.
- **A ratchet on the stop, declared as an addition.** The loss tail above exists only
  because the cloud is allowed to fall away from a trade. A one-way trailing stop would
  remove that tail, but it is a rule the source does not contain, so adding it here would
  be writing the strategy. It is the obvious next test, labelled as a departure.
- **Slippage.** Entries are market orders at the open of the bar after a breakout, which
  is where the book is thinnest. Nothing beyond fees is charged for that. At the traded
  reading 1R is 1.4x to 1.9x a typical candle, so slippage is small relative to risk -
  but it is not zero, and it is not modelled.

### Bottom line

The rule as the source describes it - wait for a close beyond the cloud with the
conversion line past the base line, then hold while the cloud trails behind price - is
positive after fees on every timeframe tested: +452.9R from 3843 trades at 1H
(+0.118R per trade, Sharpe 0.42, t = +1.16) and +147.9R from 144 trades at
1D (+1.027R per trade, Sharpe 0.59). Verdicts: 1H native **INCONCLUSIVE**, forced-1:3 **DISCARD**; 4H native **KEEP**, forced-1:3 **INCONCLUSIVE**; 6H native **INCONCLUSIVE**, forced-1:3 **INCONCLUSIVE**; 1D native **INCONCLUSIVE**, forced-1:3 **DISCARD**.

Four things carry more weight than the headline numbers.

**The edge is in the exit, not the entry.** Exit-death fires at every timeframe tested, and
it fires the same way on the matched comparison, where both variants are scored on only the
entries they both took (overlap across the four timeframes bottoms out at 62%, so the
full-run comparison is genuinely a different trade population and the matched one is the
honest read). What the entry produces is a slight directional lean; what turns it into a
result is being allowed to hold. Capping the hold at 30 bars with a 3R target - the
source's own fixed-multiple exit, made concrete - changes the answer, which means this
strategy cannot be traded with a short leash and stay the same strategy.

**Most of the result is a handful of trades.** At 1H the single best trade is 60% of the entire post-fee
total and the best five are 137%; at 1D the best trade alone is 54%. Taking the best trade
out leaves every native timeframe positive, so the edge is not literally one trade - but an
average of +0.118R per trade drawn from a distribution that lopsided is not the steady
grind it reads as, and it is the reason the Sharpe numbers sit far below what the R totals
suggest.

**The source's claim about WHEN it works is not confirmed.** It says this rule wants
sustained trends and gets chopped up in ranges, and R per trade is higher in trending
conditions in only 2 of 8 cells. The regime label is assigned at entry, and this rule enters
before a 100-bar average can have turned, so a breakout that becomes a trend books its
profit under the "range" label - which means the test can neither confirm the claim nor
refute it. What it does settle is that the claim is not a usable filter: trading this rule only
in labelled trends would have removed its best trades at 2 of the 4 timeframes.

**The numbers are honest but the risk is not one unit.** No ratchet was added, so a
falling cloud loosens the stop and the worst native trade at 1H returned -12.09R - not
the -1.00R the R-based tables imply. Read every R figure here as an average over a loss
distribution with a tail, not as a bounded bet.

**And the binding uncertainty is funding, not fees.** A rule that holds 33 daily bars crosses
about 98 settlements per trade. At the base rate alone that is the cost calculated above;
at the rates these coins have actually paid in trending markets it is larger, and it lands
on the long leg, which is the leg that earns. Any KEEP above is PROVISIONAL for that
reason and should not be treated as a real KEEP until the rate history is charged against
each trade.

## Strategy #7 - Turtle/Donchian 20-day breakout, System 1 (enter a new 20-day extreme, 2N stop with N the 20-day ATR, exit on the 10-day channel, no pyramiding)

**Tested:** 2026-09-05 - **Coins:** BTCUSDT+SOLUSDT+XRPUSDT -
**Timeframes:** 1H, 4H, 6H, 1D - **Fees:** taker on both legs (0.055% each), every number below is post-fee -
**Data:** Bybit USDT perpetuals, public REST, forming bar dropped -
**Warmup:** 1H 509 bars, 4H 131 bars, 6H 120 bars, 1D 120 bars (the rule is written in calendar days, so
the warmup is a different number of bars on every timeframe)

**Sourcing: MEDIUM - the rules are verifiable, the results are not.** This is the
weakest outcome claim in the log so far, and the gap is not a detail. The source
describes a real, published, decades-old system tested on 43 futures markets 2007-2025, bar size not stated (RogueQuant),
and it publishes **no per-trade numbers at all**: no win rate, no reward-to-risk, no
Sharpe, no drawdown, no trade count. The single figure it gives is
"$1,147,318 total profit across all 43 markets", which the author himself calls
"completely misleading" - correctly, because a dollar total says nothing without the
capital, the sizing or the span behind it. The per-trade metrics are paywalled.

So unlike Strategy #6 there is no claimed win-rate band to test against. **Nothing in
this section can be matched against the source on outcome, only on shape.** Two further
gaps sit on top of that: the tested market is FUTURES over 2007-2025, not crypto
perpetuals over 2020-2026, and no bar size is named anywhere - though the original is a
daily system, which is why 1D is the headline timeframe here.

### The rule, in the source's own words

* **Trigger:** buy a new 20-day high; sell short a new 20-day low.
* **Stop-loss:** ATR-based, with position size scaled to volatility so that every
  market risks the same amount of money.
* **Take-profit:** exit on a 10-day low (for longs). A trailing channel exit, no fixed target.
* **Market condition:** strong trends. Loses steadily in ranges.
* **Documented result:** $1,147,318 total profit across all 43 markets - and nothing else.

The published Turtle rules fill the gaps the article leaves, and they are quoted here
because they are what was actually implemented. **System 1:** enter on a
20-day channel breakout, stop 2N away where N is the 20-day average true range,
exit on the 10-day channel in the opposite direction, risk about 1% of the account per
unit with the unit size divided by N, and pyramid up to four units at half-N intervals.
**System 2** is the same shape at 55 days in and 20 days out, and is run as Sensitivity 5.

### Where this port departs from the original, declared before any number was produced

| # | The original | What was run here | Why | Measured? |
|---|---|---|---|---|
| 1 | Pyramid up to four units at half-N intervals | **one unit, no pyramiding** | the engine holds one position at a time | no - not implementable here |
| 2 | Unit size = 1% of equity divided by N | fixed 1% of equity risked with the stop 2N away | the same arithmetic reaching the same place | n/a |
| 3 | "20 days" on daily bars | 20 calendar DAYS, converted per timeframe (480 bars at 1H, 120 bars at 4H, 80 bars at 6H, 20 bars at 1D) | the rule is written in days, not bars | yes - Sensitivity 1 |
| 4 | N = 20-day ATR on daily bars | a day-scale range averaged over 20 days, on every timeframe | an hourly ATR would put the stop two candles from the fill | yes - Sensitivity 1 |
| 5 | Buy stop resting above the channel, filled inside the breakout bar | **decide on the closed bar, fill at the next open** | comparability with the six strategies already logged | yes - Sensitivity 3 |

**Departure 1 is the one that matters most, and it cannot be measured away.** Pyramiding
is what turns a Turtle winner into a large winner, and it also multiplies the loss when a
breakout fails after the adds. Every number in this section is therefore a SINGLE UNIT,
and **the system's own documented return profile is not reproducible from it.** That is a
limit of this test, stated plainly, not a finding about the system.

**Departure 4 has a proof rather than an argument.** N is the average true range of the
last 20 DAYS - a daily quantity. Measuring it as an average HOURLY range would put the
2N stop about two hourly candles from the fill, which is not the rule and would be dead on
arrival. So the true range is measured over a rolling day-length window of bars and then
averaged over 20 days of them. At 1D that expression collapses EXACTLY to the plain
20-bar ATR - the original's own N - which was checked directly: the largest difference
between the two series across all three coins on daily bars is 0.0. That collapse is the
test that it is the same quantity and not a new one.

### What the source does not disclose

Everything an outcome claim is made of. This table is unusually short because there is
unusually little to fill it with.

| Left undefined | Set to here | Why that value | Swept? |
|---|---|---|---|
| Bar size | 1D headline, all four reported | the original is a daily system | yes - all four timeframes |
| "20 days": days or bars? | calendar days | the rule is written in days | yes - Sensitivity 1 |
| The stop multiple | 2N | the published Turtle rule states 2N | yes - Sensitivity 4 |
| Long-only or both sides? | both sides | the original traded both, and so does the recovered source | yes - Sensitivity 6 |
| Does the channel exit ratchet? | no | re-reading the channel every bar is what the rule says | yes - Sensitivity 6 |
| Any time limit | none in the native rule | the source names none | yes - the forced 1:3 caps holds at 30 bars |

**Signals dropped:** of 3072 breakout signals across all twelve datasets, 3072 had a
measurable 1R and 0 were discarded because N had not yet formed. Dropping is
counted, not silent.

### How much history these numbers cover

Trade count on its own does not say how long a period a result is drawn from,
so the window is recorded per coin. What is measured is the TRADEABLE window:
the first bar the rule is allowed to act on, after the warmup, through the last
closed bar in the data. The three coins do not start together - Bitcoin's history
on this venue begins in March 2020, XRP in May 2021, Solana in October 2021 - so a
pooled row is not three equal thirds.

Warmup skipped before the first trade: 1H 509, 4H 131, 6H 120, 1D 120. That subtraction costs very
little at 1H and a great deal at 1D, where a warmup bar is a whole day.

| Timeframe | Coin | Window traded | Days | Years | Tradeable bars | Warmup bars |
|---|---|---|---|---|---|---|
| 1H | BTCUSDT | 2020-04-15 to 2026-09-05 | 2333 | 6.39 | 56,002 | 509 |
| 1H | SOLUSDT | 2021-11-05 to 2026-09-05 | 1765 | 4.83 | 42,356 | 509 |
| 1H | XRPUSDT | 2021-06-03 to 2026-09-05 | 1919 | 5.26 | 46,067 | 509 |
| 4H | BTCUSDT | 2020-04-16 to 2026-09-05 | 2333 | 6.39 | 13,998 | 131 |
| 4H | SOLUSDT | 2021-11-05 to 2026-09-05 | 1764 | 4.83 | 10,586 | 131 |
| 4H | XRPUSDT | 2021-06-04 to 2026-09-05 | 1919 | 5.25 | 11,514 | 131 |
| 6H | BTCUSDT | 2020-04-24 to 2026-09-05 | 2325 | 6.37 | 9,301 | 120 |
| 6H | SOLUSDT | 2021-11-14 to 2026-09-05 | 1756 | 4.81 | 7,026 | 120 |
| 6H | XRPUSDT | 2021-06-12 to 2026-09-05 | 1911 | 5.23 | 7,645 | 120 |
| 1D | BTCUSDT | 2020-07-23 to 2026-09-04 | 2234 | 6.12 | 2,235 | 120 |
| 1D | SOLUSDT | 2022-02-12 to 2026-09-04 | 1665 | 4.56 | 1,666 | 120 |
| 1D | XRPUSDT | 2021-09-10 to 2026-09-04 | 1820 | 4.98 | 1,821 | 120 |

Shortest window in this run: SOLUSDT at 1D, 1665 days (4.56 years). Longest: BTCUSDT at 1H, 2333 days (6.39 years).

### Lookahead bias, checked fresh for this strategy

**The mechanical audit passed on 12 of 12 datasets**, re-deriving every one of the
11 indicator columns on history truncated at 25 different cut points and requiring each
value to match the full-history value to 1e-12. A single mismatch would have raised and
produced no numbers at all. The audit was also re-run from scratch on the bar-native scale,
on the resting-order variant and on System 2, because each of those changes how the columns
are computed rather than only how they are used.

Four specific traps in this rule were handled by hand, and one of them the audit
structurally cannot see:

1. **The entry channel excludes the bar it judges.** The 20-day high is the highest high
   of the bars BEFORE the bar being tested, so "a new 20-day high" is this bar's close
   against a level that was already on the chart when the bar opened. Without that shift
   the channel would contain the bar's own high, `close > channel` could never be true,
   and the rule would silently produce no trades at all rather than raise.
2. **The exit channel is shifted for the same reason, and it matters more.** That level is
   tested against the HIGH and LOW of the bar it sits on - it is a stop - so it must be
   knowable before the range it is compared with exists.
3. **N is deliberately NOT shifted, and the audit cannot catch that.** N sizes a decision
   taken at the CLOSE of bar i from bars up to and including bar i, all of which have
   closed. The audit truncates history at the END, so it can prove a value does not depend
   on FUTURE bars; it cannot prove a value is not read too early within its own bar. That
   distinction is argued here rather than left to the machine: N is an input to a
   close-of-bar decision, never a level tested inside a bar.
4. **The two measurements that read the chart after the fact read only closed bars.** The
   "which stop fired" and "execution slippage" tables below rebuild the traded frame and
   look levels up at each trade's recorded entry and exit timestamps. Those timestamps are
   bar open times in both engine paths, and the levels looked up are the shifted channel
   values - so the lookup only ever reads something that was already on the chart when the
   trade happened. In the resting variant both trigger prices and the risk unit are
   shifted one bar, because there they ARE levels tested inside bar i.

**Fills that opened already past their own stop level:** 0 of 2422 across every variant.
The 1R distance is fixed on the signal bar and the fill happens at the next bar's open, so a
gap through the level would start a trade already stopped out. Perpetuals trade continuously,
so this should be near zero - but "should be" is not a measurement.

### Results, three coins pooled per timeframe

Both variants share the same entry rule and the same fills; only the exit differs.
"native" is the source's own exit - the 2N stop and the 10-day channel, whichever price
reaches first, no target and no time limit. "forced-1:3" is this project's standard
comparison: a 3R target with a 30-bar time limit.

| Timeframe | Exit | Trades | Days BTC | Days SOL | Days XRP | Win% | RR | R (pre-fee) | R (post-fee) | R/trade | Sharpe | Max DD % | Max DD (R) | R-recovery | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1H | native | 237 | 2333 | 1765 | 1919 | 34.6 | 3.66 | 108.3 | 105.3 | 0.444 | 0.80 | 8.1 | 15.4 | 6.85 | **KEEP** |
| 1H | forced-1:3 | 624 | 2333 | 1765 | 1919 | 49.8 | 1.55 | 68.8 | 60.9 | 0.098 | 1.16 | 6.1 | 8.7 | 7.02 | **INCONCLUSIVE** |
| 4H | native | 220 | 2333 | 1764 | 1919 | 36.4 | 3.79 | 123.7 | 120.9 | 0.550 | 0.75 | 7.4 | 13.1 | 9.21 | **KEEP** |
| 4H | forced-1:3 | 386 | 2333 | 1764 | 1919 | 46.6 | 1.65 | 60.5 | 55.6 | 0.144 | 0.96 | 7.5 | 10.5 | 5.28 | **KEEP** |
| 6H | native | 219 | 2325 | 1756 | 1911 | 35.2 | 3.83 | 114.2 | 111.4 | 0.509 | 0.70 | 9.1 | 12.2 | 9.10 | **INCONCLUSIVE** |
| 6H | forced-1:3 | 340 | 2325 | 1756 | 1911 | 47.1 | 1.74 | 71.7 | 67.4 | 0.198 | 1.12 | 7.8 | 11.6 | 5.80 | **KEEP** |
| 1D | native | 188 | 2234 | 1665 | 1820 | 37.8 | 3.48 | 103.4 | 101.0 | 0.537 | 0.69 | 8.8 | 11.9 | 8.49 | **INCONCLUSIVE** |
| 1D | forced-1:3 | 208 | 2234 | 1665 | 1820 | 38.9 | 2.06 | 40.4 | 37.9 | 0.182 | 0.62 | 13.1 | 16.7 | 2.27 | **INCONCLUSIVE** |

### What the source claims, and what this test measured

This table is here to show that the comparison cannot be made, not to make it.

| Test | Market | Bars | Trades | Win% | RR | Sharpe | Max DD |
|---|---|---|---|---|---|---|---|
| The source's claim | 43 futures markets, 2007-2025 | not stated | not stated | not stated | not stated | not stated | not stated |
| This test, native exit | BTC/SOL/XRP perps | 1H | 237 | 34.6 | 3.66 | 0.80 | 8.1% |
| This test, native exit | BTC/SOL/XRP perps | 4H | 220 | 36.4 | 3.79 | 0.75 | 7.4% |
| This test, native exit | BTC/SOL/XRP perps | 6H | 219 | 35.2 | 3.83 | 0.70 | 9.1% |
| This test, native exit | BTC/SOL/XRP perps | 1D | 188 | 37.8 | 3.48 | 0.69 | 8.8% |

Every cell in the claim row is "not stated" because the source states nothing. The one
figure it does publish - a dollar total across 43 markets - its own author calls "completely misleading",
and he is right: without the capital, the sizing and the span it is not a result. So this
strategy is the first in the log where **the source's outcome cannot be confirmed or refuted at
all.** What can be checked is the SHAPE the rules imply - a low win rate paid for by a high
reward-to-risk, most of the money in a few very large winners, and losses bounded near the risk
unit - and that shape is what the tables below test.

What can also be checked, and is worth more than the claim, is that this rule is **not a rule
this project chose**. The lengths, the stop multiple and the exit channel are all published,
decades old, and were fixed before the first backtest ran. There is no fitting risk in the
parameters themselves - only in the four places the article left ambiguous, and each of those
is swept below.

### How much risk each trade actually put up

1R is 2N, the published stop distance, and N is a day-scale average true range. So 1R is a
volatility measurement rather than a fixed percentage - which is the whole point of the
original's sizing rule - and it comes out at a similar width on every timeframe, because the
quantity being averaged is a DAY's range regardless of the bar size.

| Coin | Timeframe | 1R as % of price | Typical candle range % | 1R in candles |
|---|---|---|---|---|
| BTCUSDT | 1H | 7.70% | 0.62% | 12.4x |
| BTCUSDT | 4H | 7.30% | 1.34% | 5.4x |
| BTCUSDT | 6H | 7.44% | 1.68% | 4.4x |
| BTCUSDT | 1D | 7.64% | 3.70% | 2.1x |
| SOLUSDT | 1H | 12.62% | 1.14% | 11.0x |
| SOLUSDT | 4H | 12.59% | 2.42% | 5.2x |
| SOLUSDT | 6H | 12.56% | 2.96% | 4.2x |
| SOLUSDT | 1D | 12.45% | 6.44% | 1.9x |
| XRPUSDT | 1H | 10.11% | 0.89% | 11.4x |
| XRPUSDT | 4H | 10.43% | 1.90% | 5.5x |
| XRPUSDT | 6H | 10.35% | 2.35% | 4.4x |
| XRPUSDT | 1D | 10.79% | 5.03% | 2.1x |

Across all 12 coin-timeframe cells 1R runs from 1.9x to 12.4x a typical candle. That
matters because a stop inside one candle is decided by the engine's pessimistic intrabar
tie-break rather than by the strategy - the disease Strategy #1 documented. At 1D 1R is about
one daily candle, which is the thinnest cell here and still not in that territory; at 1H it is
tens of candles wide.

### How the trades ended, and how long they ran

The native rule has no target and no clock, so a winner runs until the channel catches
it. The hold tail is reported for that reason, and it is what makes funding the main
uncertainty on this strategy rather than a footnote.

| Timeframe | Exit | How the trades ended (count @ mean net R) | Avg bars | Median bars | 95th pct | Longest |
|---|---|---|---|---|---|---|
| 1H | native | stop 237 @ +0.444R | 359.9 | 273 | 914 | 1819 |
| 1H | forced-1:3 | stop 31 @ -1.013R, target 13 @ +2.980R, time 580 @ +0.092R | 29.0 | 30 | 30 | 30 |
| 4H | native | stop 220 @ +0.550R | 92.4 | 69 | 227 | 467 |
| 4H | forced-1:3 | stop 78 @ -1.013R, target 21 @ +2.980R, time 287 @ +0.251R | 25.9 | 30 | 30 | 30 |
| 6H | native | stop 219 @ +0.509R | 60.8 | 45 | 151 | 312 |
| 6H | forced-1:3 | stop 94 @ -1.012R, target 30 @ +2.981R, time 216 @ +0.339R | 23.8 | 30 | 30 | 30 |
| 1D | native | stop 188 @ +0.537R | 15.0 | 11 | 37 | 77 |
| 1D | forced-1:3 | stop 116 @ -1.012R, target 39 @ +2.985R, time 53 @ +0.734R | 14.7 | 12 | 30 | 30 |

### Which of the two native stops actually fired

The engine records "stop" for any intrabar stop, and BOTH of this rule's exits are
intrabar stops - the fixed 2N floor and the trailing 10-day channel. So the exit mix above
cannot separate them. This table does, by comparing the channel level at the exit bar against
the trade's own initial stop: whichever sits closer to price is the one that was enforced.

| Timeframe | 2N floor fired | Its mean net R | 10-day channel fired | Its mean net R | Channel not formed |
|---|---|---|---|---|---|
| 1H | 55 | -1.013R | 182 | 0.884R | 0 |
| 4H | 52 | -1.012R | 168 | 1.033R | 0 |
| 6H | 52 | -1.012R | 167 | 0.982R | 0 |
| 1D | 46 | -1.013R | 142 | 1.040R | 0 |

At 1D the fixed floor accounts for 24% of native stop exits and the channel for the
rest. Read that with the exit decomposition in Sensitivity 2, which answers the same question
without needing any classification at all - it simply runs each half of the exit on its own.

### Does the fixed floor keep losses near one unit of risk?

The 2N stop is a FIXED level and the 10-day channel exit is re-read every bar, so for a long the
level actually enforced is whichever of the two is HIGHER. Early in a trade that is the 2N
floor; once the channel has climbed above it the channel takes over and the stop trails. That
pairing is the source's own, and its consequence is that a loss should not exceed one unit of
risk except when a bar gaps through the level. Here is whether that held.

| Timeframe | Exit | Losers | Mean loser | Losses beyond -1.2R | Share of losers | Worst single trade | Best single trade |
|---|---|---|---|---|---|---|---|
| 1H | native | 155 | -0.727R | 0 | 0% | -1.03R | +35.36R |
| 1H | forced-1:3 | 313 | -0.363R | 0 | 0% | -1.03R | +3.00R |
| 4H | native | 140 | -0.741R | 0 | 0% | -1.03R | +53.44R |
| 4H | forced-1:3 | 206 | -0.607R | 0 | 0% | -1.03R | +3.00R |
| 6H | native | 142 | -0.729R | 0 | 0% | -1.03R | +53.25R |
| 6H | forced-1:3 | 180 | -0.684R | 0 | 0% | -1.03R | +3.00R |
| 1D | native | 117 | -0.777R | 0 | 0% | -1.03R | +50.47R |
| 1D | forced-1:3 | 127 | -0.952R | 0 | 0% | -1.03R | +2.99R |

### Is the result carried by a handful of trades?

A trend-follower is SUPPOSED to concentrate - the whole design accepts many small losses to
pay for a few very large winners, so a high top-trade share is the rule working, not a
warning. What matters is whether the result survives removing the single best trade, because
that is the difference between a strategy with a fat tail and a strategy that caught one move.

| Timeframe | Exit | Trades | Total R (post-fee) | Best single trade | Its share of the total | Best five | Their share | Total without the best |
|---|---|---|---|---|---|---|---|---|
| 1H | native | 237 | +105.3 | +35.36R | 34% | +89.4R | 85% | +69.9R |
| 1H | forced-1:3 | 624 | +60.9 | +3.00R | 5% | +14.9R | 25% | +57.9R |
| 4H | native | 220 | +120.9 | +53.44R | 44% | +107.1R | 89% | +67.5R |
| 4H | forced-1:3 | 386 | +55.6 | +3.00R | 5% | +15.0R | 27% | +52.6R |
| 6H | native | 219 | +111.4 | +53.25R | 48% | +105.0R | 94% | +58.1R |
| 6H | forced-1:3 | 340 | +67.4 | +3.00R | 4% | +15.0R | 22% | +64.4R |
| 1D | native | 188 | +101.0 | +50.47R | 50% | +103.5R | 102% | +50.6R |
| 1D | forced-1:3 | 208 | +37.9 | +2.99R | 8% | +15.0R | 39% | +34.9R |

The "total without the best" column is the honest test. At 1D the native variant keeps
+50.6R of its +101.0R after the best single trade is deleted, with the best trade alone worth
50% of the total.

### The source's market-condition claim, tested

The source says this system wants strong trends and loses steadily in ranges. That is a
testable claim, and it is the ONE claim in the article specific enough to check. Every trade
is labelled by the regime its entry bar sat in - the project's shared trending / ranging
label, computed from a 100-bar mean and not from anything the strategy knows.

| Timeframe | Exit | Trending trades | Trending R | Trending R/trade | Range trades | Range R | Range R/trade |
|---|---|---|---|---|---|---|---|
| 1H | native | 227 | +95.5 | 0.421 | 10 | +9.7 | 0.971 |
| 1H | forced-1:3 | 605 | +62.5 | 0.103 | 19 | -1.6 | -0.082 |
| 4H | native | 182 | +129.1 | 0.710 | 38 | -8.2 | -0.216 |
| 4H | forced-1:3 | 348 | +51.8 | 0.149 | 38 | +3.8 | 0.101 |
| 6H | native | 127 | +83.7 | 0.659 | 92 | +27.7 | 0.301 |
| 6H | forced-1:3 | 245 | +47.4 | 0.193 | 95 | +20.1 | 0.211 |
| 1D | native | 138 | +54.9 | 0.398 | 50 | +46.1 | 0.922 |
| 1D | forced-1:3 | 151 | +43.2 | 0.286 | 57 | -5.3 | -0.093 |

Of the 8 cells, 5 made more R per trade in trending conditions than in ranging ones.
On the native exit specifically the claim held in ['1H forced-1:3', '4H native', '4H forced-1:3', '6H native', '1D forced-1:3'] of 4 timeframes and failed in ['1H native', '6H forced-1:3', '1D native'];
2 native cells actually did BETTER in ranges. Where it fails, the reason is
usually that a range in this label still contains the multi-week drifts a 20-day channel
trades - the label is not a filter the strategy applied, only a description of the tape.

### Long side versus short side

The original traded both directions and so does this test. One retelling of the system
calls it long-only, which is why the long-only reading is run as a labelled sensitivity
further down rather than argued about here.

| Timeframe | Exit | Long trades | Long R | Long win% | Short trades | Short R | Short win% |
|---|---|---|---|---|---|---|---|
| 1H | native | 120 | +109.7 | 35.8 | 117 | -4.4 | 33.3 |
| 1H | forced-1:3 | 367 | +56.1 | 53.4 | 257 | +4.8 | 44.7 |
| 4H | native | 113 | +120.7 | 35.4 | 107 | +0.2 | 37.4 |
| 4H | forced-1:3 | 224 | +47.4 | 48.2 | 162 | +8.2 | 44.4 |
| 6H | native | 114 | +109.9 | 33.3 | 105 | +1.5 | 37.1 |
| 6H | forced-1:3 | 192 | +60.1 | 49.0 | 148 | +7.3 | 44.6 |
| 1D | native | 99 | +104.0 | 38.4 | 89 | -3.0 | 37.1 |
| 1D | forced-1:3 | 117 | +41.9 | 38.5 | 91 | -4.0 | 39.6 |

The long leg out-earned the short leg in 8 of the 8 cells. Read that against the
span: all three coins spent most of these windows in a rising market, so a long-side
advantage is partly the tape and not only the rule.

### Per coin, so one coin cannot hide behind the pool

coin      timeframe  exit         trades   win%     RR    R pre   R post  R/trade  Sharpe     DD%    DD R  recov  verdict
-------------------------------------------------------------------------------------------------------------------------
BTCUSDT   1H         native           92   37.0   3.43     47.6     46.1    0.501    0.80     5.1     7.3   6.36  KEEP
BTCUSDT   1H         forced-1:3      262   50.4   1.38     23.9     19.7    0.075    0.73     5.9     7.2   2.74  INCONCLUSIVE
BTCUSDT   4H         native           81   40.7   3.35     49.7     48.3    0.597    0.88     4.7     6.9   7.01  KEEP
BTCUSDT   4H         forced-1:3      159   47.2   1.58     24.7     22.1    0.139    0.65     6.9     8.5   2.61  INCONCLUSIVE
BTCUSDT   6H         native           82   39.0   3.29     44.8     43.5    0.530    0.80     5.0     7.2   6.04  KEEP
BTCUSDT   6H         forced-1:3      138   47.8   1.71     31.9     29.7    0.215    0.80     6.7     8.7   3.41  KEEP
BTCUSDT   1D         native           72   41.7   3.04     42.3     41.1    0.571    0.78     3.9     5.2   7.89  KEEP
BTCUSDT   1D         forced-1:3       84   40.5   2.35     29.4     28.1    0.334    0.73     6.4     8.1   3.44  KEEP
SOLUSDT   1H         native           72   33.3   3.42     24.4     23.7    0.330    0.39     5.4     6.1   3.89  INCONCLUSIVE
SOLUSDT   1H         forced-1:3      203   49.8   1.47     18.0     16.2    0.080    0.85     3.5     3.7   4.33  INCONCLUSIVE
SOLUSDT   4H         native           68   33.8   3.22     21.9     21.3    0.314    0.35     6.6     6.8   3.14  INCONCLUSIVE
SOLUSDT   4H         forced-1:3      119   48.7   1.52     17.5     16.4    0.138    0.70     4.9     5.1   3.20  KEEP
SOLUSDT   6H         native           67   34.3   3.35     23.4     22.7    0.339    0.40     6.6     6.8   3.37  INCONCLUSIVE
SOLUSDT   6H         forced-1:3      104   50.0   1.62     22.8     21.9    0.210    0.88     4.6     4.9   4.49  KEEP
SOLUSDT   1D         native           57   38.6   3.00     22.4     21.9    0.384    0.42     5.4     5.7   3.82  INCONCLUSIVE
SOLUSDT   1D         forced-1:3       60   41.7   1.98     14.4     13.9    0.231    0.52     7.6     8.1   1.72  INCONCLUSIVE
XRPUSDT   1H         native           73   32.9   4.19     36.3     35.4    0.485    0.42     6.4     6.9   5.13  INCONCLUSIVE
XRPUSDT   1H         forced-1:3      159   49.1   1.93     26.9     25.1    0.158    0.96     3.6     3.8   6.67  KEEP
XRPUSDT   4H         native           71   33.8   4.93     52.1     51.3    0.722    0.42     6.7     8.4   6.08  INCONCLUSIVE
XRPUSDT   4H         forced-1:3      108   43.5   1.95     18.3     17.1    0.158    0.65     4.9     5.1   3.32  INCONCLUSIVE
XRPUSDT   6H         native           70   31.4   5.07     46.0     45.2    0.645    0.37    11.5    12.1   3.73  INCONCLUSIVE
XRPUSDT   6H         forced-1:3       98   42.9   1.92     17.0     15.9    0.162    0.58     5.7     6.1   2.60  INCONCLUSIVE
XRPUSDT   1D         native           59   32.2   4.68     38.7     38.0    0.644    0.34    13.7    13.7   2.78  INCONCLUSIVE
XRPUSDT   1D         forced-1:3       64   34.4   1.72     -3.4     -4.0   -0.063   -0.16    11.3    11.2  -0.36  DISCARD

### Statistical context checks

1H:
  native        237 trades | pre-fee +0.4568R/trade (spread 3.35R, t = +2.10) | post-fee +0.4441R/trade (t = +2.04)
  forced-1:3    624 trades | pre-fee +0.1103R/trade (spread 0.69R, t = +3.99) | post-fee +0.0977R/trade (t = +3.54)
  resolved inside their first candle: native 0%, forced-1:3 0%
  the two variants share 39.4% of their entries  <-- TOO LOW to compare exits fairly
4H:
  native        220 trades | pre-fee +0.5624R/trade (spread 4.36R, t = +1.91) | post-fee +0.5497R/trade (t = +1.87)
  forced-1:3    386 trades | pre-fee +0.1568R/trade (spread 1.06R, t = +2.90) | post-fee +0.1441R/trade (t = +2.67)
  resolved inside their first candle: native 0%, forced-1:3 1%
  the two variants share 58.3% of their entries  <-- TOO LOW to compare exits fairly
6H:
  native        219 trades | pre-fee +0.5213R/trade (spread 4.31R, t = +1.79) | post-fee +0.5087R/trade (t = +1.75)
  forced-1:3    340 trades | pre-fee +0.2109R/trade (spread 1.20R, t = +3.24) | post-fee +0.1983R/trade (t = +3.05)
  resolved inside their first candle: native 1%, forced-1:3 2%
  the two variants share 65.1% of their entries  <-- TOO LOW to compare exits fairly
1D:
  native        188 trades | pre-fee +0.5500R/trade (spread 4.42R, t = +1.71) | post-fee +0.5375R/trade (t = +1.67)
  forced-1:3    208 trades | pre-fee +0.1944R/trade (spread 1.59R, t = +1.76) | post-fee +0.1821R/trade (t = +1.65)
  resolved inside their first candle: native 6%, forced-1:3 7%
  the two variants share 76.1% of their entries  <-- TOO LOW to compare exits fairly

One caveat specific to this strategy: the entry overlap between the two variants runs from
39% to 76%. Both variants take the same signals, so the overlap should be near total; where
it falls short it is because the native variant has no time limit, so it can still be holding a
trade when a later signal fires and the forced variant - which exits after 30 bars - is
free to take it. That is a real difference in the trade population, not a bookkeeping error, and
it is one reason the two columns are never netted against each other.

### Exit-death check: does the edge depend on the exit style?

This is the mandatory comparison - the source's own exit against the project's forced
1:3 triple-barrier, on identical entries.

| Timeframe | Native R/trade | Forced R/trade | Gap | Flag | What it means |
|---|---|---|---|---|---|
| 1H | 0.444 | 0.098 | 0.346 | yes | both exits agree on direction but differ by 0.346R per trade (native +0.444R vs forced 1:3 +0.098R), which is larger than the entire +0.10R KEEP requirement. The native exit is doing more work than the entry signal. |
| 4H | 0.550 | 0.144 | 0.406 | yes | both exits agree on direction but differ by 0.406R per trade (native +0.550R vs forced 1:3 +0.144R), which is larger than the entire +0.10R KEEP requirement. The native exit is doing more work than the entry signal. |
| 6H | 0.509 | 0.198 | 0.310 | yes | both exits agree on direction but differ by 0.310R per trade (native +0.509R vs forced 1:3 +0.198R), which is larger than the entire +0.10R KEEP requirement. The native exit is doing more work than the entry signal. |
| 1D | 0.537 | 0.182 | 0.355 | yes | both exits agree on direction but differ by 0.355R per trade (native +0.537R vs forced 1:3 +0.182R), which is larger than the entire +0.10R KEEP requirement. The native exit is doing more work than the entry signal. |

The full comparison above pools every trade each variant took, and those populations are not
identical for the reason just given. So the same check is repeated on MATCHED entries only -
the trades both variants took on the same bar in the same direction - where the only difference
left is the exit.

| Timeframe | Matched trades | Native R/trade | Forced R/trade | Gap | Exit-death |
|---|---|---|---|---|---|
| 1H | 226 | 0.444 | 0.078 | 0.366 | yes |
| 4H | 200 | 0.550 | 0.089 | 0.460 | yes |
| 6H | 198 | 0.509 | 0.116 | 0.392 | yes |
| 1D | 140 | 0.610 | 0.166 | 0.444 | yes |

A gap wider than 0.15R either way is flagged as an exit dependency. Read the matched rows as
the cleaner answer: they hold the entries fixed and change only the exit, which is the question
being asked.

### Sensitivity 1: what "20 days" means on an intraday chart

This is the largest of the four ambiguities the article leaves, and no source picks
between the two readings. **Twenty DAYS** converts the rule per timeframe - 480 bars at 1H,
120 at 4H, 80 at 6H, 20 at 1D - and is what was traded, on the precedent set by
Strategies #2, #3 and #4. **Twenty BARS** is what a chart package does when a Donchian-20 is
dropped on an hourly chart: a genuinely different rule, roughly a 20-hour channel, and it is
run here in full.

| Variant | Timeframe | Exit | Trades | Win% | RR | 1R as % of price | R (post-fee) | R/trade | Sharpe | Max DD (R) | Worst trade | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 20 calendar days, converted per timeframe (traded) | 1H | native | 237 | 34.6 | 3.66 | 9.88% | 105.3 | 0.444 | 0.80 | 15.4 | -1.03R | KEEP |
| 20 calendar days, converted per timeframe (traded) | 1H | forced-1:3 | 624 | 49.8 | 1.55 | 9.73% | 60.9 | 0.098 | 1.16 | 8.7 | -1.03R | INCONCLUSIVE |
| 20 calendar days, converted per timeframe (traded) | 4H | native | 220 | 36.4 | 3.79 | 9.80% | 120.9 | 0.550 | 0.75 | 13.1 | -1.03R | KEEP |
| 20 calendar days, converted per timeframe (traded) | 4H | forced-1:3 | 386 | 46.6 | 1.65 | 9.50% | 55.6 | 0.144 | 0.96 | 10.5 | -1.03R | KEEP |
| 20 calendar days, converted per timeframe (traded) | 6H | native | 219 | 35.2 | 3.83 | 9.87% | 111.4 | 0.509 | 0.70 | 12.2 | -1.03R | INCONCLUSIVE |
| 20 calendar days, converted per timeframe (traded) | 6H | forced-1:3 | 340 | 47.1 | 1.74 | 9.82% | 67.4 | 0.198 | 1.12 | 11.6 | -1.03R | KEEP |
| 20 calendar days, converted per timeframe (traded) | 1D | native | 188 | 37.8 | 3.48 | 10.08% | 101.0 | 0.537 | 0.69 | 11.9 | -1.03R | INCONCLUSIVE |
| 20 calendar days, converted per timeframe (traded) | 1D | forced-1:3 | 208 | 38.9 | 2.06 | 10.06% | 37.9 | 0.182 | 0.62 | 16.7 | -1.03R | INCONCLUSIVE |
| 20 bars, whatever a bar happens to be | 1H | native | 4898 | 32.2 | 2.22 | 1.82% | 139.5 | 0.028 | 0.34 | 75.0 | -1.58R | INCONCLUSIVE |
| 20 bars, whatever a bar happens to be | 1H | forced-1:3 | 5029 | 35.9 | 1.83 | 1.86% | 79.8 | 0.016 | 0.24 | 108.2 | -1.70R | DISCARD |
| 20 bars, whatever a bar happens to be | 4H | native | 1193 | 32.9 | 2.67 | 3.76% | 182.2 | 0.153 | 0.87 | 49.1 | -1.15R | KEEP |
| 20 bars, whatever a bar happens to be | 4H | forced-1:3 | 1253 | 38.5 | 1.88 | 3.83% | 131.3 | 0.105 | 0.82 | 42.0 | -1.15R | KEEP |
| 20 bars, whatever a bar happens to be | 6H | native | 796 | 32.0 | 3.33 | 4.71% | 222.4 | 0.279 | 0.81 | 36.1 | -1.08R | KEEP |
| 20 bars, whatever a bar happens to be | 6H | forced-1:3 | 854 | 36.8 | 1.97 | 4.88% | 76.6 | 0.090 | 0.58 | 34.2 | -1.09R | INCONCLUSIVE |
| 20 bars, whatever a bar happens to be | 1D | native | 188 | 37.8 | 3.48 | 10.08% | 101.0 | 0.537 | 0.69 | 11.9 | -1.03R | INCONCLUSIVE |
| 20 bars, whatever a bar happens to be | 1D | forced-1:3 | 208 | 38.9 | 2.06 | 10.06% | 37.9 | 0.182 | 0.62 | 16.7 | -1.03R | INCONCLUSIVE |

The two readings are not variations of one rule; at 1H they are a 20-day channel and a 20-hour
channel. Only the 1D rows are identical by construction, and they are the arithmetic check that
both paths compute the same thing when a bar IS a day.

### Sensitivity 2: which half of the native exit earns

The native exit is two rules at once - the fixed 2N floor and the trailing 10-day channel.
Running each half alone answers what the exit mix cannot: which one the result depends on.
Only the native rows are shown, because the forced-1:3 rows are identical across all three
variants by construction - the forced exit replaces the native exit entirely.

| Variant | Timeframe | Exit | Trades | Win% | RR | 1R as % of price | R (post-fee) | R/trade | Sharpe | Max DD (R) | Worst trade | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2N floor AND 10-day channel (traded) | 1H | native | 237 | 34.6 | 3.66 | 9.88% | 105.3 | 0.444 | 0.80 | 15.4 | -1.03R | KEEP |
| 2N floor AND 10-day channel (traded) | 4H | native | 220 | 36.4 | 3.79 | 9.80% | 120.9 | 0.550 | 0.75 | 13.1 | -1.03R | KEEP |
| 2N floor AND 10-day channel (traded) | 6H | native | 219 | 35.2 | 3.83 | 9.87% | 111.4 | 0.509 | 0.70 | 12.2 | -1.03R | INCONCLUSIVE |
| 2N floor AND 10-day channel (traded) | 1D | native | 188 | 37.8 | 3.48 | 10.08% | 101.0 | 0.537 | 0.69 | 11.9 | -1.03R | INCONCLUSIVE |
| 2N floor only, no channel exit | 1H | native | 27 | 0.0 | n/a | 12.74% | -27.2 | -1.009 | -2.33 | 26.2 | -1.02R | INCONCLUSIVE |
| 2N floor only, no channel exit | 4H | native | 38 | 0.0 | n/a | 12.77% | -38.3 | -1.009 | -2.90 | 37.3 | -1.01R | DISCARD |
| 2N floor only, no channel exit | 6H | native | 24 | 0.0 | n/a | 14.22% | -24.2 | -1.008 | -2.30 | 23.2 | -1.01R | INCONCLUSIVE |
| 2N floor only, no channel exit | 1D | native | 13 | 0.0 | n/a | 14.67% | -13.1 | -1.008 | -1.75 | 12.1 | -1.01R | INCONCLUSIVE |
| 10-day channel only, no 2N floor | 1H | native | 229 | 36.2 | 3.41 | 9.82% | 108.3 | 0.473 | 0.82 | 17.0 | -2.11R | KEEP |
| 10-day channel only, no 2N floor | 4H | native | 211 | 37.9 | 3.53 | 9.69% | 123.5 | 0.585 | 0.76 | 15.6 | -2.10R | KEEP |
| 10-day channel only, no 2N floor | 6H | native | 209 | 37.3 | 3.45 | 9.82% | 113.8 | 0.544 | 0.71 | 12.4 | -2.24R | KEEP |
| 10-day channel only, no 2N floor | 1D | native | 179 | 40.2 | 3.19 | 10.02% | 105.5 | 0.590 | 0.71 | 10.7 | -2.23R | KEEP |

Read these three rows as a decomposition, not as three candidate strategies. "2N floor only, no channel exit"
is a fixed-stop breakout with no way out but the stop, so its winners run until they lose.
"10-day channel only, no 2N floor" keeps 1R defined as 2N - the risk the system intended - but enforces no floor, so
a loss can run past it, which is what its worst-trade column is there to show.
"2N floor AND 10-day channel (traded)" is the source's rule.

### Sensitivity 3: the execution departure, priced

The Turtles rested buy and sell stops at the channel and were filled INSIDE the breakout
bar. This project decides on a closed bar and fills at the next open, which is strictly
worse - it pays away the rest of the breakout bar and any gap after it. Both are run on
identical trigger prices so the cost is measured rather than argued.

| Variant | Timeframe | Exit | Trades | Win% | RR | 1R as % of price | R (post-fee) | R/trade | Sharpe | Max DD (R) | Worst trade | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| decide on the close, fill at the next open (traded) | 1H | native | 237 | 34.6 | 3.66 | 9.88% | 105.3 | 0.444 | 0.80 | 15.4 | -1.03R | KEEP |
| decide on the close, fill at the next open (traded) | 1H | forced-1:3 | 624 | 49.8 | 1.55 | 9.73% | 60.9 | 0.098 | 1.16 | 8.7 | -1.03R | INCONCLUSIVE |
| decide on the close, fill at the next open (traded) | 4H | native | 220 | 36.4 | 3.79 | 9.80% | 120.9 | 0.550 | 0.75 | 13.1 | -1.03R | KEEP |
| decide on the close, fill at the next open (traded) | 4H | forced-1:3 | 386 | 46.6 | 1.65 | 9.50% | 55.6 | 0.144 | 0.96 | 10.5 | -1.03R | KEEP |
| decide on the close, fill at the next open (traded) | 6H | native | 219 | 35.2 | 3.83 | 9.87% | 111.4 | 0.509 | 0.70 | 12.2 | -1.03R | INCONCLUSIVE |
| decide on the close, fill at the next open (traded) | 6H | forced-1:3 | 340 | 47.1 | 1.74 | 9.82% | 67.4 | 0.198 | 1.12 | 11.6 | -1.03R | KEEP |
| decide on the close, fill at the next open (traded) | 1D | native | 188 | 37.8 | 3.48 | 10.08% | 101.0 | 0.537 | 0.69 | 11.9 | -1.03R | INCONCLUSIVE |
| decide on the close, fill at the next open (traded) | 1D | forced-1:3 | 208 | 38.9 | 2.06 | 10.06% | 37.9 | 0.182 | 0.62 | 16.7 | -1.03R | INCONCLUSIVE |
| stop order resting at the channel, filled inside the bar | 1H | native | 263 | 35.4 | 3.67 | 9.82% | 122.9 | 0.467 | 0.83 | 13.0 | -1.20R | KEEP |
| stop order resting at the channel, filled inside the bar | 1H | forced-1:3 | 831 | 48.1 | 1.57 | 9.60% | 70.6 | 0.085 | 1.23 | 7.7 | -1.20R | INCONCLUSIVE |
| stop order resting at the channel, filled inside the bar | 4H | native | 259 | 34.4 | 4.04 | 9.84% | 135.4 | 0.523 | 0.73 | 13.2 | -1.54R | KEEP |
| stop order resting at the channel, filled inside the bar | 4H | forced-1:3 | 495 | 49.1 | 1.61 | 9.69% | 82.5 | 0.167 | 1.29 | 14.0 | -1.54R | KEEP |
| stop order resting at the channel, filled inside the bar | 6H | native | 254 | 35.0 | 4.10 | 9.83% | 140.9 | 0.555 | 0.76 | 12.0 | -1.03R | KEEP |
| stop order resting at the channel, filled inside the bar | 6H | forced-1:3 | 438 | 47.3 | 1.73 | 9.66% | 87.0 | 0.199 | 1.20 | 12.9 | -1.51R | KEEP |
| stop order resting at the channel, filled inside the bar | 1D | native | 243 | 32.9 | 3.96 | 9.86% | 113.8 | 0.468 | 0.64 | 14.1 | -1.28R | INCONCLUSIVE |
| stop order resting at the channel, filled inside the bar | 1D | forced-1:3 | 269 | 38.7 | 2.09 | 9.92% | 51.4 | 0.191 | 0.73 | 12.1 | -1.24R | KEEP |

The two variants do not take the same trades: a resting order fires the moment price touches
the channel, so it enters on bars where the close later fell back inside and the closed-bar
rule never fired at all. To separate the pure execution cost from the different trade
population, the fill price of every trade is compared with the channel level a resting order
would have sat on.

| Execution | Timeframe | Fills measured | Median worse than trigger | Mean | 95th percentile |
|---|---|---|---|---|---|
| decide on the close, fill at the next open (traded) | 1H | 237 | 0.643% | 1.158% | 3.849% |
| decide on the close, fill at the next open (traded) | 4H | 220 | 1.046% | 1.669% | 5.242% |
| decide on the close, fill at the next open (traded) | 6H | 219 | 1.116% | 1.899% | 5.478% |
| decide on the close, fill at the next open (traded) | 1D | 188 | 1.779% | 2.879% | 7.419% |
| stop order resting at the channel, filled inside the bar | 1H | 263 | 0.000% | 0.000% | 0.000% |
| stop order resting at the channel, filled inside the bar | 4H | 259 | 0.000% | 0.000% | 0.000% |
| stop order resting at the channel, filled inside the bar | 6H | 254 | 0.000% | 0.000% | 0.000% |
| stop order resting at the channel, filled inside the bar | 1D | 243 | 0.000% | 0.000% | 0.000% |

A positive number is money paid away versus the trigger. The resting rows are not zero because
a bar can OPEN through a resting stop, in which case the engine fills at the open - the worse
price - exactly as a real stop order would.

### Sensitivity 4: the stop multiple

2N is published, so this is not a parameter search - it is a check that the published number is
not sitting on a cliff. 1N halves the risk unit and 3N raises it by half; because position size
is 1% of equity divided by the stop distance either way, a wider stop does not risk more money
per trade, it takes a smaller position and gives the trade more room.

| Variant | Timeframe | Exit | Trades | Win% | RR | 1R as % of price | R (post-fee) | R/trade | Sharpe | Max DD (R) | Worst trade | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1N stop | 1H | native | 299 | 25.1 | 5.63 | 4.74% | 189.6 | 0.634 | 0.79 | 25.5 | -1.06R | KEEP |
| 1N stop | 1H | forced-1:3 | 661 | 46.3 | 1.54 | 4.87% | 82.8 | 0.125 | 1.00 | 15.3 | -1.07R | KEEP |
| 1N stop | 4H | native | 270 | 25.6 | 6.15 | 4.84% | 212.2 | 0.786 | 0.76 | 20.3 | -1.06R | KEEP |
| 1N stop | 4H | forced-1:3 | 450 | 38.7 | 2.14 | 4.72% | 87.5 | 0.194 | 0.90 | 19.6 | -1.06R | KEEP |
| 1N stop | 6H | native | 262 | 26.0 | 5.95 | 4.93% | 199.7 | 0.762 | 0.74 | 19.7 | -1.06R | KEEP |
| 1N stop | 6H | forced-1:3 | 414 | 39.4 | 2.16 | 4.90% | 96.4 | 0.233 | 0.99 | 16.3 | -1.06R | KEEP |
| 1N stop | 1D | native | 216 | 28.7 | 6.10 | 5.03% | 215.4 | 0.997 | 0.73 | 17.3 | -1.06R | KEEP |
| 1N stop | 1D | forced-1:3 | 290 | 30.0 | 2.83 | 5.03% | 44.5 | 0.153 | 0.53 | 16.9 | -1.06R | INCONCLUSIVE |
| 2N stop (traded) | 1H | native | 237 | 34.6 | 3.66 | 9.88% | 105.3 | 0.444 | 0.80 | 15.4 | -1.03R | KEEP |
| 2N stop (traded) | 1H | forced-1:3 | 624 | 49.8 | 1.55 | 9.73% | 60.9 | 0.098 | 1.16 | 8.7 | -1.03R | INCONCLUSIVE |
| 2N stop (traded) | 4H | native | 220 | 36.4 | 3.79 | 9.80% | 120.9 | 0.550 | 0.75 | 13.1 | -1.03R | KEEP |
| 2N stop (traded) | 4H | forced-1:3 | 386 | 46.6 | 1.65 | 9.50% | 55.6 | 0.144 | 0.96 | 10.5 | -1.03R | KEEP |
| 2N stop (traded) | 6H | native | 219 | 35.2 | 3.83 | 9.87% | 111.4 | 0.509 | 0.70 | 12.2 | -1.03R | INCONCLUSIVE |
| 2N stop (traded) | 6H | forced-1:3 | 340 | 47.1 | 1.74 | 9.82% | 67.4 | 0.198 | 1.12 | 11.6 | -1.03R | KEEP |
| 2N stop (traded) | 1D | native | 188 | 37.8 | 3.48 | 10.08% | 101.0 | 0.537 | 0.69 | 11.9 | -1.03R | INCONCLUSIVE |
| 2N stop (traded) | 1D | forced-1:3 | 208 | 38.9 | 2.06 | 10.06% | 37.9 | 0.182 | 0.62 | 16.7 | -1.03R | INCONCLUSIVE |
| 3N stop | 1H | native | 230 | 36.1 | 3.41 | 14.76% | 71.7 | 0.312 | 0.82 | 10.6 | -1.02R | KEEP |
| 3N stop | 1H | forced-1:3 | 621 | 49.9 | 1.53 | 14.61% | 38.3 | 0.062 | 1.10 | 6.0 | -1.01R | INCONCLUSIVE |
| 3N stop | 4H | native | 212 | 37.7 | 3.55 | 14.61% | 82.1 | 0.387 | 0.76 | 9.8 | -1.01R | KEEP |
| 3N stop | 4H | forced-1:3 | 376 | 47.9 | 1.60 | 14.39% | 37.8 | 0.101 | 0.90 | 8.6 | -1.01R | KEEP |
| 3N stop | 6H | native | 210 | 37.1 | 3.51 | 14.75% | 76.5 | 0.364 | 0.72 | 7.7 | -1.02R | KEEP |
| 3N stop | 6H | forced-1:3 | 325 | 48.0 | 1.59 | 14.68% | 41.1 | 0.126 | 0.90 | 8.8 | -1.02R | KEEP |
| 3N stop | 1D | native | 180 | 40.0 | 3.22 | 15.05% | 70.5 | 0.392 | 0.72 | 7.1 | -1.02R | KEEP |
| 3N stop | 1D | forced-1:3 | 177 | 49.2 | 1.75 | 15.09% | 50.9 | 0.287 | 1.05 | 9.6 | -1.02R | KEEP |

What to look for is monotonicity. If 2N were a lucky value the neighbours would be much worse
than it; if the rule is real, the three rows should trend in one direction and 2N should sit on
that trend rather than above it.

### Sensitivity 5: System 2, the original's slower pair

The published system came in two halves. System 1 is 20 days in and 10 out, which is what was
traded. System 2 is the same shape at 55 days in and 20 out - a slower channel that takes
fewer, larger positions. The Turtles ran both. Running it here costs nothing and doubles the
evidence about whether the shape works at all, independently of the exact lengths.

| Variant | Timeframe | Exit | Trades | Win% | RR | 1R as % of price | R (post-fee) | R/trade | Sharpe | Max DD (R) | Worst trade | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| System 1: 20 in, 10 out (traded) | 1H | native | 237 | 34.6 | 3.66 | 9.88% | 105.3 | 0.444 | 0.80 | 15.4 | -1.03R | KEEP |
| System 1: 20 in, 10 out (traded) | 1H | forced-1:3 | 624 | 49.8 | 1.55 | 9.73% | 60.9 | 0.098 | 1.16 | 8.7 | -1.03R | INCONCLUSIVE |
| System 1: 20 in, 10 out (traded) | 4H | native | 220 | 36.4 | 3.79 | 9.80% | 120.9 | 0.550 | 0.75 | 13.1 | -1.03R | KEEP |
| System 1: 20 in, 10 out (traded) | 4H | forced-1:3 | 386 | 46.6 | 1.65 | 9.50% | 55.6 | 0.144 | 0.96 | 10.5 | -1.03R | KEEP |
| System 1: 20 in, 10 out (traded) | 6H | native | 219 | 35.2 | 3.83 | 9.87% | 111.4 | 0.509 | 0.70 | 12.2 | -1.03R | INCONCLUSIVE |
| System 1: 20 in, 10 out (traded) | 6H | forced-1:3 | 340 | 47.1 | 1.74 | 9.82% | 67.4 | 0.198 | 1.12 | 11.6 | -1.03R | KEEP |
| System 1: 20 in, 10 out (traded) | 1D | native | 188 | 37.8 | 3.48 | 10.08% | 101.0 | 0.537 | 0.69 | 11.9 | -1.03R | INCONCLUSIVE |
| System 1: 20 in, 10 out (traded) | 1D | forced-1:3 | 208 | 38.9 | 2.06 | 10.06% | 37.9 | 0.182 | 0.62 | 16.7 | -1.03R | INCONCLUSIVE |
| System 2: 55 in, 20 out | 1H | native | 108 | 38.0 | 5.03 | 9.27% | 130.1 | 1.205 | 0.60 | 12.1 | -1.03R | INCONCLUSIVE |
| System 2: 55 in, 20 out | 1H | forced-1:3 | 325 | 53.2 | 1.49 | 9.52% | 46.8 | 0.144 | 1.17 | 5.4 | -1.03R | KEEP |
| System 2: 55 in, 20 out | 4H | native | 99 | 38.4 | 5.38 | 9.38% | 129.5 | 1.308 | 0.61 | 10.9 | -1.03R | INCONCLUSIVE |
| System 2: 55 in, 20 out | 4H | forced-1:3 | 197 | 49.7 | 1.69 | 9.38% | 47.3 | 0.240 | 0.97 | 8.3 | -1.02R | KEEP |
| System 2: 55 in, 20 out | 6H | native | 100 | 34.0 | 5.89 | 9.79% | 119.6 | 1.196 | 0.57 | 11.1 | -1.03R | INCONCLUSIVE |
| System 2: 55 in, 20 out | 6H | forced-1:3 | 169 | 49.1 | 1.98 | 9.60% | 57.6 | 0.341 | 1.14 | 12.6 | -1.03R | KEEP |
| System 2: 55 in, 20 out | 1D | native | 83 | 34.9 | 5.94 | 9.94% | 100.5 | 1.211 | 0.57 | 10.4 | -1.02R | INCONCLUSIVE |
| System 2: 55 in, 20 out | 1D | forced-1:3 | 113 | 42.5 | 2.06 | 9.81% | 32.9 | 0.291 | 0.71 | 13.0 | -1.02R | KEEP |

"System 2: 55 in, 20 out" is not a tuning of "System 1: 20 in, 10 out (traded)" - both length pairs are
published, decades old, and were fixed long before this data existed. If both work the shape is
doing the work; if only one works, the lengths are.

### Sensitivity 6: two readings the source leaves open

Run on 1H and 1D only - the densest sample and the headline - because these two variants
test wording, not timeframe behaviour.

**Long-only.** One retelling of this system calls it long-only and then, in the same breath,
lists selling below the 20-day low. The original traded both sides and the recovered source
describes both, so both were traded; this row is the other reading.

**Ratcheted channel exit.** "Exit on a 10-day low" is re-read from scratch every bar, so as
price falls the 10-day low can fall with it and the exit level LOOSENS. A ratchet - holding the
level at its best value - is a rule the source does not contain, and none was added, on the
precedent of Strategies #5 and #6. This row is what adding it would have done.

| Variant | Timeframe | Exit | Trades | Win% | RR | R (post-fee) | R/trade | Sharpe | Max DD (R) | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| as traded | 1H | native | 237 | 34.6 | 3.66 | 105.3 | 0.444 | 0.80 | 15.4 | KEEP |
| as traded | 1H | forced-1:3 | 624 | 49.8 | 1.55 | 60.9 | 0.098 | 1.16 | 8.7 | INCONCLUSIVE |
| as traded | 1D | native | 188 | 37.8 | 3.48 | 101.0 | 0.537 | 0.69 | 11.9 | INCONCLUSIVE |
| as traded | 1D | forced-1:3 | 208 | 38.9 | 2.06 | 37.9 | 0.182 | 0.62 | 16.7 | INCONCLUSIVE |
| long-only, the source's other reading | 1H | native | 120 | 35.8 | 5.15 | 109.7 | 0.914 | 0.87 | 14.5 | KEEP |
| long-only, the source's other reading | 1H | forced-1:3 | 367 | 53.4 | 1.61 | 56.1 | 0.153 | 1.25 | 7.3 | KEEP |
| long-only, the source's other reading | 1D | native | 99 | 38.4 | 4.89 | 104.0 | 1.051 | 0.72 | 13.3 | KEEP |
| long-only, the source's other reading | 1D | forced-1:3 | 121 | 38.8 | 2.49 | 41.0 | 0.339 | 0.86 | 13.2 | KEEP |
| channel exit ratcheted, which the source does NOT say | 1H | native | 237 | 34.6 | 3.66 | 105.3 | 0.444 | 0.80 | 15.4 | KEEP |
| channel exit ratcheted, which the source does NOT say | 1H | forced-1:3 | 624 | 49.8 | 1.55 | 60.9 | 0.098 | 1.16 | 8.7 | INCONCLUSIVE |
| channel exit ratcheted, which the source does NOT say | 1D | native | 188 | 37.8 | 3.48 | 101.0 | 0.537 | 0.69 | 11.9 | INCONCLUSIVE |
| channel exit ratcheted, which the source does NOT say | 1D | forced-1:3 | 208 | 38.9 | 2.06 | 37.9 | 0.182 | 0.62 | 16.7 | INCONCLUSIVE |

The long-only row is a real fork in the reading and it moves the numbers, so it is reported
as a finding about the other reading - not as a verdict on the rule that was actually traded.

The ratcheted row came back **identical to as-traded, to every decimal place printed and on
both timeframes** - same trade count, same win rate, same R. That is not a bug and it is worth
stating plainly: the level this test enforces is already the HIGHER of the channel level and the
fixed 2N floor (the lower, for a short). A ratchet could only ever bind in the narrow case where
the channel level falls back below its own earlier best while still sitting outside the floor -
and across every trade on both timeframes, that case never decided an exit. So the loosening
described above is real in the rule but inert in the results: the fixed floor is already doing
the job a ratchet would have done. Nothing here argues for adding the rule.

### Best and worst conditions, per cell

The regime label is computed from the tape, not from the strategy, so these columns say
which market this rule was paid in - not which market it predicted.

| Timeframe | Exit | Best condition | Worst condition |
|---|---|---|---|
| 1H | native | up/highvol | down/highvol |
| 1H | forced-1:3 | up/highvol | range/highvol |
| 4H | native | up/highvol | range/highvol |
| 4H | forced-1:3 | up/highvol | down/lowvol |
| 6H | native | up/highvol | down/highvol |
| 6H | forced-1:3 | up/highvol | down/lowvol |
| 1D | native | range/lowvol | range/highvol |
| 1D | forced-1:3 | up/lowvol | range/highvol |

### The discard bar, applied to each exit variant separately

The thresholds were fixed before this strategy was written and are the same ones every
strategy in this log is measured against: KEEP needs at least 30 trades, expectancy of at least
+0.10R per trade after fees, Sharpe of at least 0.70, an R-recovery of at least 1.50
(total R divided by the worst drawdown in R), and a win rate at least 2% above the break-even
win rate for the reward-to-risk it achieved. DISCARD is expectancy at or below +0.00R, Sharpe below
0.30, or R-recovery below 0.50. Fewer than 30 trades is INCONCLUSIVE, never DISCARD.

| Timeframe | Exit | Trades | R/trade (post-fee) | Sharpe | R-recovery | Win% | Break-even Win% | Verdict | Why |
|---|---|---|---|---|---|---|---|---|---|
| 1H | native | 237 | 0.444 | 0.80 | 6.85 | 34.6 | - | **KEEP** | +0.444R per trade, Sharpe 0.80, earned 6.85x its worst drawdown over 237 trades |
| 1H | forced-1:3 | 624 | 0.098 | 1.16 | 7.02 | 49.8 | 25.3 | **INCONCLUSIVE** | positive but short of the KEEP bar: expectancy +0.098R < +0.10R |
| 4H | native | 220 | 0.550 | 0.75 | 9.21 | 36.4 | - | **KEEP** | +0.550R per trade, Sharpe 0.75, earned 9.21x its worst drawdown over 220 trades |
| 4H | forced-1:3 | 386 | 0.144 | 0.96 | 5.28 | 46.6 | 25.3 | **KEEP** | +0.144R per trade, Sharpe 0.96, earned 5.28x its worst drawdown over 386 trades |
| 6H | native | 219 | 0.509 | 0.70 | 9.10 | 35.2 | - | **INCONCLUSIVE** | positive but short of the KEEP bar: Sharpe 0.70 < 0.7 |
| 6H | forced-1:3 | 340 | 0.198 | 1.12 | 5.80 | 47.1 | 25.3 | **KEEP** | +0.198R per trade, Sharpe 1.12, earned 5.80x its worst drawdown over 340 trades |
| 1D | native | 188 | 0.537 | 0.69 | 8.49 | 37.8 | - | **INCONCLUSIVE** | positive but short of the KEEP bar: Sharpe 0.69 < 0.7 |
| 1D | forced-1:3 | 208 | 0.182 | 0.62 | 2.27 | 38.9 | 25.3 | **INCONCLUSIVE** | positive but short of the KEEP bar: Sharpe 0.62 < 0.7 |

The two verdicts on a timeframe are never collapsed into one. A strategy can pass on its own
exit and fail on a forced 1:3, and that difference IS the finding - it says the edge lives in the
exit rather than in the entry.

One number on the 1D native row deserves to be read carefully rather than rounded: its Sharpe is
0.69 against a KEEP threshold of 0.70. That is BELOW the bar, not at it, and it is the reason
that cell is not a KEEP. A hair's-breadth miss is still a miss; the threshold was set before the
number existed and is not being moved to accommodate it.

| Timeframe | Exit | Avg hold | 8h funding stamps crossed | 1R as % of price | Funding at the base rate | R/trade post-fee | Post-fee minus funding |
|---|---|---|---|---|---|---|---|
| 1H | native | 360h | 45.0 | 9.88% | -0.046R | +0.444R | +0.399R **<- KEEP** |
| 1H | forced-1:3 | 29h | 3.6 | 9.73% | -0.004R | +0.098R | +0.094R |
| 4H | native | 370h | 46.2 | 9.80% | -0.047R | +0.550R | +0.503R **<- KEEP** |
| 4H | forced-1:3 | 103h | 12.9 | 9.50% | -0.014R | +0.144R | +0.130R **<- KEEP** |
| 6H | native | 365h | 45.6 | 9.87% | -0.046R | +0.509R | +0.462R |
| 6H | forced-1:3 | 143h | 17.8 | 9.82% | -0.018R | +0.198R | +0.180R **<- KEEP** |
| 1D | native | 359h | 44.9 | 10.08% | -0.045R | +0.537R | +0.493R |
| 1D | forced-1:3 | 354h | 44.2 | 10.06% | -0.044R | +0.182R | +0.138R |

**Funding is not modelled, and this strategy is the one where that matters most.**

The 1H native cell reads as a KEEP above. It holds a position for 360 hours on
average, which crosses about 45 funding settlements per trade. At Bybit's base rate of
0.01% per settlement that is roughly 0.05R of cost per trade, against a measured
expectancy of 0.444R. The edge survives the base rate, but the base
rate is a floor: a trend-follower is by definition holding the crowded side of a one-way
market, where funding is usually worse than base. **This KEEP is PROVISIONAL until funding is
modelled properly.**

The 4H native cell reads as a KEEP above. It holds a position for 370 hours on
average, which crosses about 46 funding settlements per trade. At Bybit's base rate of
0.01% per settlement that is roughly 0.05R of cost per trade, against a measured
expectancy of 0.550R. The edge survives the base rate, but the base
rate is a floor: a trend-follower is by definition holding the crowded side of a one-way
market, where funding is usually worse than base. **This KEEP is PROVISIONAL until funding is
modelled properly.**

The 4H forced-1:3 cell reads as a KEEP above. It holds a position for 103 hours on
average, which crosses about 13 funding settlements per trade. At Bybit's base rate of
0.01% per settlement that is roughly 0.01R of cost per trade, against a measured
expectancy of 0.144R. The edge survives the base rate, but the base
rate is a floor: a trend-follower is by definition holding the crowded side of a one-way
market, where funding is usually worse than base. **This KEEP is PROVISIONAL until funding is
modelled properly.**

The 6H forced-1:3 cell reads as a KEEP above. It holds a position for 143 hours on
average, which crosses about 18 funding settlements per trade. At Bybit's base rate of
0.01% per settlement that is roughly 0.02R of cost per trade, against a measured
expectancy of 0.198R. The edge survives the base rate, but the base
rate is a floor: a trend-follower is by definition holding the crowded side of a one-way
market, where funding is usually worse than base. **This KEEP is PROVISIONAL until funding is
modelled properly.**

Per the standing rule, a KEEP on a multi-day holding strategy is not treated as a real KEEP
until funding is priced. The verdicts in the table above are the fee-and-slippage verdicts;
the funding column is the reason none of them is being acted on yet.

### What would change these verdicts

Five things, in the order they would move the numbers most.

1. **Pyramiding.** The single largest departure and the only one that cannot be measured away
   from inside this engine, which holds one position at a time. The Turtles added up to four
   units at half-N intervals, and that is what turns a winner into a large winner - and what
   deepens the loss when a breakout fails after the adds. Every number here is a single unit, so
   the system's own documented return profile is not reproducible from it in either direction.
2. **Funding.** Priced above at the base rate as a floor. On a rule that holds for 15.0 daily
   bars this is not a rounding item, and a proper model needs the historical funding series per
   coin rather than a flat rate.
3. **Execution.** "stop order resting at the channel, filled inside the bar" is the original's own
   execution and "decide on the close, fill at the next open (traded)" is what this project
   trades. Sensitivity 3 measures the gap in R and in percent; at 1D the median fill came in
   1.779% worse than the level a resting order would have sat on. Anyone running
   this for real would rest the stops and should read the resting rows, not the traded ones.
4. **The reading of "20 days".** "20 calendar days, converted per timeframe (traded)" was
   traded; "20 bars, whatever a bar happens to be" is the other reading and is a
   different rule, not a variation. If the two disagree on the intraday timeframes, then those
   timeframes are reporting on a rule choice this project made and the source did not.
5. **More history, and other coins.** The windows here are 2234, 1665, 1820 days for BTC, SOL and XRP
   at 1D. The source tested 43 markets over 18 years. A 20-day channel system takes few
   trades per market per year by design, so the honest way to raise the sample is more markets,
   not more parameter variants on three coins.

### Bottom line

The rule is genuinely old and genuinely published, which makes it the least fitted strategy in
this log - the lengths, the stop multiple and the exit channel were all fixed decades before
this data existed. It is also the strategy with the weakest outcome claim: the article that
prompted the test publishes no per-trade numbers at all, so nothing here could be checked
against it on outcome, only on shape.

On shape it behaves the way a trend-follower should. At 1D the native exit won 37.8% of
188 trades at a reward-to-risk of 3.48, with losses held near one unit of risk - 0% of
losers ran past 1.2R - and the result concentrated in a few large winners. At 1H the same rule
took 237 trades for 0.444R each. Both are the published rule, not a tuned version of it.

The verdicts are in the discard-bar table and are not restated here as a single word, because
there is no single word: each timeframe carries a verdict per exit variant and they differ. What
unifies them is the caveat - the exit that earns is "2N floor AND 10-day channel (traded)", the position
size is one unit where the original used four, and the holding time is long enough that funding
is the largest unpriced number on the page.

---

## Strategy #8 — Supertrend (10, 3)

**Tested:** 2026-09-12 · **Coins:** BTCUSDT+SOLUSDT+XRPUSDT · **Timeframes:** 1H, 4H, 1D

### The rules

Supertrend is a trend-following indicator that builds a trailing stop based on ATR. The line sits below price in an uptrend, above price in a downtrend. When price closes through the line, the indicator flips direction.

- **Entry:** Price closes above the Supertrend line (bullish flip)
- **Exit (native):** Price closes below the Supertrend line (bearish flip)
- **Exit (forced-1:3):** 1R stop, 3R target, 30-bar time limit

**Parameters:** ATR period 10, multiplier 3.0 (standard defaults from the source literature).

**Source:** Olivier Seban (creator). Widely documented across trading education sites.

### Coverage

### How much history these numbers cover

Trade count on its own does not say how long a period a result is drawn from,
so the window is recorded per coin. What is measured is the TRADEABLE window:
the first bar the rule is allowed to act on, after the warmup, through the last
closed bar in the data. The three coins do not start together - Bitcoin's history
on this venue begins in March 2020, XRP in May 2021, Solana in October 2021 - so a
pooled row is not three equal thirds.

Warmup skipped before the first trade: 50 bars on every timeframe. That subtraction costs very
little at 1H and a great deal at 1D, where a warmup bar is a whole day.

| Timeframe | Coin | Window traded | Days | Years | Tradeable bars | Warmup bars |
|---|---|---|---|---|---|---|
| 1H | BTCUSDT | 2020-03-27 to 2026-09-05 | 2352 | 6.44 | 56,461 | 50 |
| 1H | SOLUSDT | 2021-10-17 to 2026-09-05 | 1784 | 4.88 | 42,815 | 50 |
| 1H | XRPUSDT | 2021-05-15 to 2026-09-05 | 1939 | 5.31 | 46,526 | 50 |
| 4H | BTCUSDT | 2020-04-02 to 2026-09-05 | 2346 | 6.42 | 14,079 | 50 |
| 4H | SOLUSDT | 2021-10-23 to 2026-09-05 | 1778 | 4.87 | 10,667 | 50 |
| 4H | XRPUSDT | 2021-05-21 to 2026-09-05 | 1932 | 5.29 | 11,595 | 50 |
| 1D | BTCUSDT | 2020-05-14 to 2026-09-05 | 2305 | 6.31 | 2,306 | 50 |
| 1D | SOLUSDT | 2021-12-04 to 2026-09-05 | 1736 | 4.75 | 1,737 | 50 |
| 1D | XRPUSDT | 2021-07-02 to 2026-09-05 | 1891 | 5.18 | 1,892 | 50 |

Shortest window in this run: SOLUSDT at 1D, 1736 days (4.75 years). Longest: BTCUSDT at 1H, 2352 days (6.44 years).

### Results — post-fee, pooled per timeframe

| Timeframe | Exit | Trades | Days (BTC/SOL/XRP) | Win% | RR | R/trade | Sharpe | Max DD % | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1H | native | 1698 | 2352/1784/1939 | 34.9 | 2.37 | 0.437 | 0.93 | 44.6 | **KEEP** |
| 1H | forced-1:3 | 1697 | 2352/1784/1939 | 28.3 | 2.21 | -0.103 | -0.87 | 153.6 | **DISCARD** |
| 4H | native | 424 | 2346/1778/1932 | 34.2 | 3.93 | 1.625 | 0.95 | 32.3 | **KEEP** |
| 4H | forced-1:3 | 427 | 2346/1778/1932 | 27.9 | 2.58 | -0.004 | -0.02 | 28.5 | **DISCARD** |
| 1D | native | 69 | 2305/1736/1891 | 34.8 | 7.93 | 4.714 | 0.72 | 12.2 | **KEEP** |
| 1D | forced-1:3 | 72 | 2305/1736/1891 | 36.1 | 2.95 | 0.429 | 0.74 | 9.3 | **KEEP** |

### Exit-death check

- **1H: YES.** the exit flips the sign of the edge: native +0.437R per trade vs forced 1:3 -0.103R. Identical entries, so the entry signal is not what decided this - the forced 1:3 exit is. The edge, such as it is, lives in the native exit.
- **4H: YES.** the exit flips the sign of the edge: native +1.625R per trade vs forced 1:3 -0.004R. Identical entries, so the entry signal is not what decided this - the forced 1:3 exit is. The edge, such as it is, lives in the native exit.
- **1D: YES.** both exits agree on direction but differ by 4.285R per trade (native +4.714R vs forced 1:3 +0.429R), which is larger than the entire +0.10R KEEP requirement. The native exit is doing more work than the entry signal.

### Verdicts

- **1H native — KEEP.** +0.437R per trade, Sharpe 0.93, earned 4.39x its worst drawdown over 1698 trades
- **1H forced-1:3 — DISCARD.** post-fee expectancy -0.103R per trade is not positive; post-fee Sharpe -0.87 below 0.3; earned only -0.76x its worst drawdown
- **4H native — KEEP.** +1.625R per trade, Sharpe 0.95, earned 7.45x its worst drawdown over 424 trades
- **4H forced-1:3 — DISCARD.** post-fee expectancy -0.004R per trade is not positive; post-fee Sharpe -0.02 below 0.3; earned only -0.05x its worst drawdown
- **1D native — KEEP.** +4.714R per trade, Sharpe 0.72, earned 10.51x its worst drawdown over 69 trades
- **1D forced-1:3 — KEEP.** +0.429R per trade, Sharpe 0.74, earned 3.00x its worst drawdown over 72 trades

### Bottom line

At least one timeframe / exit combination is a **KEEP**. See the verdict rows above for the breakdown.

---

## Strategy #8 — Supertrend (10, 3)

**Tested:** 2026-09-12 · **Coins:** BTCUSDT+SOLUSDT+XRPUSDT · **Timeframes:** 1H, 4H, 1D

### The rules

Supertrend is a trend-following indicator that builds a trailing stop based on ATR. The line sits below price in an uptrend, above price in a downtrend. When price closes through the line, the indicator flips direction.

- **Entry:** Price closes above the Supertrend line (bullish flip)
- **Exit (native):** Price closes below the Supertrend line (bearish flip)
- **Exit (forced-1:3):** 1R stop, 3R target, 30-bar time limit

**Parameters:** ATR period 10, multiplier 3.0 (standard defaults from the source literature).

**Source:** Olivier Seban (creator). Widely documented across trading education sites.

### Coverage

### How much history these numbers cover

Trade count on its own does not say how long a period a result is drawn from,
so the window is recorded per coin. What is measured is the TRADEABLE window:
the first bar the rule is allowed to act on, after the warmup, through the last
closed bar in the data. The three coins do not start together - Bitcoin's history
on this venue begins in March 2020, XRP in May 2021, Solana in October 2021 - so a
pooled row is not three equal thirds.

Warmup skipped before the first trade: 50 bars on every timeframe. That subtraction costs very
little at 1H and a great deal at 1D, where a warmup bar is a whole day.

| Timeframe | Coin | Window traded | Days | Years | Tradeable bars | Warmup bars |
|---|---|---|---|---|---|---|
| 1H | BTCUSDT | 2020-03-27 to 2026-09-05 | 2352 | 6.44 | 56,461 | 50 |
| 1H | SOLUSDT | 2021-10-17 to 2026-09-05 | 1784 | 4.88 | 42,815 | 50 |
| 1H | XRPUSDT | 2021-05-15 to 2026-09-05 | 1939 | 5.31 | 46,526 | 50 |
| 4H | BTCUSDT | 2020-04-02 to 2026-09-05 | 2346 | 6.42 | 14,079 | 50 |
| 4H | SOLUSDT | 2021-10-23 to 2026-09-05 | 1778 | 4.87 | 10,667 | 50 |
| 4H | XRPUSDT | 2021-05-21 to 2026-09-05 | 1932 | 5.29 | 11,595 | 50 |
| 1D | BTCUSDT | 2020-05-14 to 2026-09-05 | 2305 | 6.31 | 2,306 | 50 |
| 1D | SOLUSDT | 2021-12-04 to 2026-09-05 | 1736 | 4.75 | 1,737 | 50 |
| 1D | XRPUSDT | 2021-07-02 to 2026-09-05 | 1891 | 5.18 | 1,892 | 50 |

Shortest window in this run: SOLUSDT at 1D, 1736 days (4.75 years). Longest: BTCUSDT at 1H, 2352 days (6.44 years).

### Results — post-fee, pooled per timeframe

| Timeframe | Exit | Trades | Days (BTC/SOL/XRP) | Win% | RR | R/trade | Sharpe | Max DD % | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1H | native | 1698 | 2352/1784/1939 | 34.9 | 2.37 | 0.437 | 0.93 | 44.6 | **KEEP** |
| 1H | forced-1:3 | 1697 | 2352/1784/1939 | 28.3 | 2.21 | -0.103 | -0.87 | 153.6 | **DISCARD** |
| 4H | native | 424 | 2346/1778/1932 | 34.2 | 3.93 | 1.625 | 0.95 | 32.3 | **KEEP** |
| 4H | forced-1:3 | 427 | 2346/1778/1932 | 27.9 | 2.58 | -0.004 | -0.02 | 28.5 | **DISCARD** |
| 1D | native | 69 | 2305/1736/1891 | 34.8 | 7.93 | 4.714 | 0.72 | 12.2 | **KEEP** |
| 1D | forced-1:3 | 72 | 2305/1736/1891 | 36.1 | 2.95 | 0.429 | 0.74 | 9.3 | **KEEP** |

### Exit-death check

- **1H: YES.** the exit flips the sign of the edge: native +0.437R per trade vs forced 1:3 -0.103R. Identical entries, so the entry signal is not what decided this - the forced 1:3 exit is. The edge, such as it is, lives in the native exit.
- **4H: YES.** the exit flips the sign of the edge: native +1.625R per trade vs forced 1:3 -0.004R. Identical entries, so the entry signal is not what decided this - the forced 1:3 exit is. The edge, such as it is, lives in the native exit.
- **1D: YES.** both exits agree on direction but differ by 4.285R per trade (native +4.714R vs forced 1:3 +0.429R), which is larger than the entire +0.10R KEEP requirement. The native exit is doing more work than the entry signal.

### Verdicts

- **1H native — KEEP.** +0.437R per trade, Sharpe 0.93, earned 4.39x its worst drawdown over 1698 trades
- **1H forced-1:3 — DISCARD.** post-fee expectancy -0.103R per trade is not positive; post-fee Sharpe -0.87 below 0.3; earned only -0.76x its worst drawdown
- **4H native — KEEP.** +1.625R per trade, Sharpe 0.95, earned 7.45x its worst drawdown over 424 trades
- **4H forced-1:3 — DISCARD.** post-fee expectancy -0.004R per trade is not positive; post-fee Sharpe -0.02 below 0.3; earned only -0.05x its worst drawdown
- **1D native — KEEP.** +4.714R per trade, Sharpe 0.72, earned 10.51x its worst drawdown over 69 trades
- **1D forced-1:3 — KEEP.** +0.429R per trade, Sharpe 0.74, earned 3.00x its worst drawdown over 72 trades

### Bottom line

At least one timeframe / exit combination is a **KEEP**. See the verdict rows above for the breakdown.

## Strategy #8 - Supertrend (10, 3)

**Tested:** 2026-09-22 - **Coins:** BTCUSDT+SOLUSDT+XRPUSDT -
**Timeframes:** 1H, 4H, 1D - **Fees:** taker on both legs (0.055% each), every number below is post-fee -
**Data:** Bybit USDT perpetuals, public REST, forming bar dropped -
**Warmup:** 50 bars per dataset before the first trade is allowed -
**Direction:** long and short

**This entry replaces the shallow one that was here before.** The previous
entry reported a results table and nothing else - no t-statistics, no
concentration, no long/short split, no funding estimate, no lookahead audit
count, no parameter sensitivity, no market-condition breakdown and no entry
overlap. That gap is closed below, and closing it surfaced a second problem:
**the numbers in the previous entry do not reproduce.** See the next section.


### Why the numbers in the previous entry do not reproduce

The run that produced the logged table took only BULLISH flips: 1698
native trades at 1H. The same module run with both directions takes 3394,
which is close to exactly twice as many - the signature of a direction filter
rather than a different indicator. The strategy module as it now stands takes
both directions, so re-running it cannot reproduce the logged counts and cannot
be made to without re-adding a filter the module no longer has.

**Neither reading is the source's, because no source settles it.** The clearest
available description says a bearish flip is "a possible short entry or exit from
long trades" - i.e. both directions - while most retail treatments use the line
only to time a long book. Both are run here: **both directions is what was
traded**, as the literal reading of "flip = trade the new direction", and
long-only is Sensitivity 3, so the numbers the previous entry reported stay on
the page and stay auditable.

The consequence: the previous entry's verdicts are not wrong about the long-only
rule - they reproduce, and Sensitivity 3 reproduces them - but they are not
verdicts about the rule as the literature describes it. **The KEEPs that entry
claimed were long-only KEEPs.** The verdicts in the tables below are for the
both-directions rule, and they are different.

### The rule, as the literature describes it

Supertrend is a trend-following indicator that builds a trailing stop from ATR.
The line sits below price in an uptrend and above it in a downtrend; when price
closes through the line, the indicator flips direction.

* **Entry:** price closes above the Supertrend line (a bullish flip); the mirror
  for shorts.
* **Exit (native):** price closes below the line (a bearish flip). A trailing
  stop, no target, no time limit.
* **Exit (forced-1:3):** 1R stop, 3R target, a 30-bar time
  limit - this project's standard comparison.
* **Parameters:** ATR period 10, multiplier 3.
* **Market condition:** sustained trends; whipsaws in ranges/chop.
* **Documented result:** 50-60% win rate and about 1.5:1 to 3:1 reward-to-risk
  (market and bar size NOT stated (education sites, not Seban)).

**Sourcing: WEAK.** Olivier Seban is credited with the indicator and published no
backtest for it. The outcome claims that circulate come from education sites, not
from the author, and they are marketing copy - from a site whose own footer calls
it educational content and not trading advice. **No market, no bar size, no date
span, no Sharpe, no drawdown and no trade count is stated anywhere.** So the
source comparison below is a comparison of SHAPE only, and even the shape claims
are a vendor's advertisement rather than a measured result.

This is the weakest-sourced strategy in the log, and it is worth being explicit
about what that costs: nothing in this section can be checked against the source
on outcome, and the only shape claims available to check are the ones a vendor
published to sell an indicator. What is measured here is the indicator's own
rule, run honestly.

### What the source does not disclose

Everything an outcome claim is made of.

| Left undefined | Set to here | Why that value | Swept? |
|---|---|---|---|
| The ATR period | 10 | the most widely cited default; some references give 14 |
  yes - Sensitivity 1 |
| The ATR multiplier | 3.0 | the value every source that names one agrees on |
  yes - Sensitivity 2 |
| Long-only or both directions | both | the clearest reference describes both |
  yes - Sensitivity 3 |
| Any take-profit | none in the native rule | the source names no level |
  yes - the forced 1:3 at 30 bars |
| Any time limit | none in the native rule | the source names none |
  n/a - the trailing stop ends every trade |
| The market | BTC/SOL/XRP perpetuals | this project's fixed universe | n/a |

**Signals dropped:** of 4392 flip signals across all nine datasets, 4392
had a measurable 1R and 0 were discarded because ATR had not yet
formed. Dropping is counted, not silent.

### How this port departs from the indicator, declared before any number

| # | The indicator | What was run here | Why | Measured? |
|---|---|---|---|---|
| 1 | The line is a trailing stop, not an order | **1R is fixed at the flip and
  never moves** | the engine needs a fixed risk unit to express every result in R
  | yes - the loss-tail table |
| 2 | Stops sit at the line, or the line plus a buffer | 1R is the ATR distance
  itself | no source gives a rule for the buffer | yes - the 1R table |
| 3 | Flips are taken as they appear | a flip is taken only when the engine is
  flat | one position at a time | no - not implementable here |
| 4 | Close through the line decides | same, and the fill is the next bar's open
  | comparability with the seven strategies already logged | n/a |

**Departure 1 is the important one.** The indicator's line ratchets - in an
uptrend it can only rise - so a real trade's stop tightens as the trend runs and
the trade is closed at whatever the line has climbed to. Here 1R is fixed on the
signal bar, so a native winner is exited by the flip at whatever distance the line
has moved to, and the R-multiple of that exit is measured rather than assumed.
That is the honest way to express a trailing stop in fixed-R units, and the
loss-tail table is what it costs: it is why native losses here run slightly past
one unit of risk.

### How much history these numbers cover

Trade count on its own does not say how long a period a result is drawn from,
so the window is recorded per coin. What is measured is the TRADEABLE window:
the first bar the rule is allowed to act on, after the warmup, through the last
closed bar in the data. The three coins do not start together - Bitcoin's history
on this venue begins in March 2020, XRP in May 2021, Solana in October 2021 - so a
pooled row is not three equal thirds.

Warmup skipped before the first trade: 50 bars on every timeframe. That subtraction costs very
little at 1H and a great deal at 1D, where a warmup bar is a whole day.

| Timeframe | Coin | Window traded | Days | Years | Tradeable bars | Warmup bars |
|---|---|---|---|---|---|---|
| 1H | BTCUSDT | 2020-03-27 to 2026-09-05 | 2352 | 6.44 | 56,461 | 50 |
| 1H | SOLUSDT | 2021-10-17 to 2026-09-05 | 1784 | 4.88 | 42,815 | 50 |
| 1H | XRPUSDT | 2021-05-15 to 2026-09-05 | 1939 | 5.31 | 46,526 | 50 |
| 4H | BTCUSDT | 2020-04-02 to 2026-09-05 | 2346 | 6.42 | 14,079 | 50 |
| 4H | SOLUSDT | 2021-10-23 to 2026-09-05 | 1778 | 4.87 | 10,667 | 50 |
| 4H | XRPUSDT | 2021-05-21 to 2026-09-05 | 1932 | 5.29 | 11,595 | 50 |
| 1D | BTCUSDT | 2020-05-14 to 2026-09-05 | 2305 | 6.31 | 2,306 | 50 |
| 1D | SOLUSDT | 2021-12-04 to 2026-09-05 | 1736 | 4.75 | 1,737 | 50 |
| 1D | XRPUSDT | 2021-07-02 to 2026-09-05 | 1891 | 5.18 | 1,892 | 50 |

Shortest window in this run: SOLUSDT at 1D, 1736 days (4.75 years). Longest: BTCUSDT at 1H, 2352 days (6.44 years).

### Lookahead bias, checked fresh for this strategy

**The mechanical audit passed on 9 of 9 datasets**, re-deriving every
one of the 3 indicator columns on history truncated at 25 different cut
points and requiring each value to match the full-history value to 1e-12. A
single mismatch would have raised and produced no numbers at all. The audit was
also re-run from scratch on each ATR period, each multiplier and the long-only
variant, because each of those changes how the columns are computed rather than
only how they are used.

Three specific traps in this indicator were handled by hand, and one of them the
audit structurally cannot see:

1. **The flip is a close tested against the CURRENT bar's line, and the line is
   recursive in its own past.** The value at bar i must already be known when
   bar i's close is judged against it, and it is: the recursion only ever reads
   bars up to and including i, all of which have closed. The audit truncates
   history at the END, so it can prove no FUTURE bar is consulted; it cannot
   prove a value is not read too early within its own bar. That distinction is
   argued here rather than left to the machine: the level is a close-of-bar
   input, never an intrabar trigger.
2. **The ratchet is one-way by construction.** In an uptrend the line is the
   higher of this bar's lower band and the previous line, so it can never move
   against the trend it is tracking. That is a property of the indicator, not an
   added rule, and it is what makes the native exit a trailing stop.
3. **ATR is a rolling mean, so it lags by half a window.** No shift was added to
   correct for that, because the indicator's own definition uses the unshifted
   ATR; correcting it would be a different indicator.

**Fills that opened already past their own stop level:** 0 of 8710 across
every variant. The 1R distance is a fraction fixed on the signal bar and the fill
happens at the next bar's open, so a gap through the level would start a trade
already stopped out. Perpetuals trade continuously, so this should be near zero -
but "should be" is not a measurement.

### Results, three coins pooled per timeframe

Both variants share the same entry rule, same fills and same 1R; only the
exit differs. "native" is the indicator's own exit - the flip back the other
way, no target and no time limit. "forced-1:3" is this project's standard
comparison.

| Timeframe | Exit | Trades | Days BTC | Days SOL | Days XRP | Win% | RR | R (pre-fee) | R (post-fee) | R/trade | Sharpe | Max DD % | Max DD (R) | R-recovery | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1H | native | 3394 | 2352 | 1784 | 1939 | 35.5 | 2.07 | 1216.1 | 754.9 | 0.222 | 0.69 | 55.6 | 246.0 | 3.07 | **INCONCLUSIVE** |
| 1H | forced-1:3 | 3346 | 2352 | 1784 | 1939 | 27.5 | 2.24 | 44.0 | -410.7 | -0.123 | -1.40 | 342.1 | 442.8 | -0.93 | **DISCARD** |
| 4H | native | 850 | 2346 | 1778 | 1932 | 36.6 | 2.66 | 732.4 | 678.7 | 0.798 | 0.89 | 19.4 | 73.8 | 9.20 | **KEEP** |
| 4H | forced-1:3 | 841 | 2346 | 1778 | 1932 | 30.1 | 2.44 | 83.9 | 31.2 | 0.037 | 0.21 | 26.2 | 44.2 | 0.71 | **DISCARD** |
| 1D | native | 139 | 2305 | 1736 | 1891 | 33.8 | 4.73 | 301.6 | 298.1 | 2.145 | 0.62 | 21.2 | 56.2 | 5.31 | **INCONCLUSIVE** |
| 1D | forced-1:3 | 140 | 2305 | 1736 | 1891 | 32.1 | 2.75 | 32.7 | 29.3 | 0.210 | 0.53 | 8.5 | 10.0 | 2.92 | **INCONCLUSIVE** |

### The discard bar, applied to each exit variant separately

The thresholds were fixed before this strategy was written and are the same ones
every strategy in this log is measured against: KEEP needs at least 30
trades, expectancy of at least +0.10R per trade after
fees, Sharpe of at least 0.70, an R-recovery of at least
1.50 (total R divided by the worst drawdown in R), and a
win rate at least 2% above the break-even win rate for the
reward-to-risk it achieved. DISCARD is expectancy at or below
+0.00R, Sharpe below 0.30, or
R-recovery below 0.50. Fewer than 30 trades
is INCONCLUSIVE, never DISCARD.

| Timeframe | Exit | Trades | R/trade (post-fee) | Sharpe | R-recovery | Win% | Break-even Win% | Verdict | Why |
|---|---|---|---|---|---|---|---|---|---|
| 1H | native | 3394 | 0.222 | 0.69 | 3.07 | 35.5 | - | **INCONCLUSIVE** | positive but short of the KEEP bar: Sharpe 0.69 < 0.7 |
| 1H | forced-1:3 | 3346 | -0.123 | -1.40 | -0.93 | 27.5 | 28.4 | **DISCARD** | post-fee expectancy -0.123R per trade is not positive; post-fee Sharpe -1.40 below 0.3; earned only -0.93x its worst drawdown |
| 4H | native | 850 | 0.798 | 0.89 | 9.20 | 36.6 | - | **KEEP** | +0.798R per trade, Sharpe 0.89, earned 9.20x its worst drawdown over 850 trades |
| 4H | forced-1:3 | 841 | 0.037 | 0.21 | 0.71 | 30.1 | 26.6 | **DISCARD** | post-fee Sharpe 0.21 below 0.3 |
| 1D | native | 139 | 2.145 | 0.62 | 5.31 | 33.8 | - | **INCONCLUSIVE** | positive but short of the KEEP bar: Sharpe 0.62 < 0.7 |
| 1D | forced-1:3 | 140 | 0.210 | 0.53 | 2.92 | 32.1 | 25.6 | **INCONCLUSIVE** | positive but short of the KEEP bar: Sharpe 0.53 < 0.7 |

The two verdicts on a timeframe are never collapsed into one. A strategy can
pass on its own exit and fail on a forced 1:3, and that difference IS the finding
- it says the edge lives in the exit rather than in the entry.

### Is the result distinguishable from luck?

The discard bar does not test this, so it is measured here for every cell: the
mean per-trade R divided by its own standard error, pre-fee and post-fee. As a
rough reading, below 2 the average is inside the range pure chance would produce
anyway.

1H:
  native       3394 trades | pre-fee +0.3583R/trade (spread 6.11R, t = +3.42) | post-fee +0.2224R/trade (t = +2.12)
  forced-1:3   3346 trades | pre-fee +0.0132R/trade (spread 1.68R, t = +0.45) | post-fee -0.1227R/trade (t = -4.22)
  resolved inside their first candle: native 0%, forced-1:3 16%
  the two variants share 98.7% of their entries
4H:
  native        850 trades | pre-fee +0.8616R/trade (spread 9.72R, t = +2.59) | post-fee +0.7984R/trade (t = +2.40)
  forced-1:3    841 trades | pre-fee +0.0997R/trade (spread 1.73R, t = +1.68) | post-fee +0.0371R/trade (t = +0.63)
  resolved inside their first candle: native 0%, forced-1:3 15%
  the two variants share 98.8% of their entries
1D:
  native        139 trades | pre-fee +2.1696R/trade (spread 16.15R, t = +1.58) | post-fee +2.1446R/trade (t = +1.57)
  forced-1:3    140 trades | pre-fee +0.2336R/trade (spread 1.82R, t = +1.52) | post-fee +0.2096R/trade (t = +1.36)
  resolved inside their first candle: native 0%, forced-1:3 21%
  the two variants share 95.9% of their entries

The largest t-statistic across all 6 cells is +2.40. That clears 2, so the average is at least distinguishable from chance.

### How much risk each trade actually put up

1R is the ATR distance at the signal bar, resolved against the actual fill price.
ATR is measured on THIS timeframe's bars, so 1R shrinks with the bar - unlike a
day-scale stop it does not come out at a similar width everywhere. That spread is
the single most important number on this page, because it decides whether the
commission bill is a rounding error or the whole result.

| Coin | Timeframe | 1R as % of price | Typical candle range % | 1R in candles |
|---|---|---|---|---|
| BTCUSDT | 1H | 0.74% | 0.62% | 1.2x |
| BTCUSDT | 4H | 1.53% | 1.34% | 1.1x |
| BTCUSDT | 1D | 3.95% | 3.70% | 1.1x |
| SOLUSDT | 1H | 1.24% | 1.14% | 1.1x |
| SOLUSDT | 4H | 2.64% | 2.42% | 1.1x |
| SOLUSDT | 1D | 6.21% | 6.44% | 1.0x |
| XRPUSDT | 1H | 0.99% | 0.89% | 1.1x |
| XRPUSDT | 4H | 2.08% | 1.90% | 1.1x |
| XRPUSDT | 1D | 5.56% | 5.03% | 1.1x |

Across all 9 coin-timeframe cells 1R runs from 1.0x to 1.2x a typical candle.
Nothing here is inside one candle, so the engine's pessimistic intrabar tie-break
(the stop wins when one candle holds both barriers) is not what is deciding these
results.

### How the trades ended, and how long they ran

| Timeframe | Exit | How the trades ended (count @ mean net R) | Avg bars | Median bars | 95th pct | Longest |
|---|---|---|---|---|---|---|
| 1H | native | supertrend flip bearish 1698 @ +0.437R, supertrend flip bullish 1696 @ +0.007R | 42.9 | 33 | 113 | 359 |
| 1H | forced-1:3 | stop 2389 @ -1.137R, target 763 @ +2.856R, time 194 @ +0.655R | 7.2 | 3 | 30 | 30 |
| 4H | native | supertrend flip bearish 424 @ +1.625R, supertrend flip bullish 426 @ -0.024R | 42.6 | 34 | 110 | 235 |
| 4H | forced-1:3 | stop 582 @ -1.061R, target 206 @ +2.930R, time 53 @ +0.855R | 7.7 | 4 | 30 | 30 |
| 1D | native | supertrend flip bearish 69 @ +4.714R, supertrend flip bullish 70 @ -0.388R | 40.0 | 35 | 97 | 147 |
| 1D | forced-1:3 | stop 94 @ -1.023R, target 41 @ +2.973R, time 5 @ +0.721R | 6.5 | 2 | 26 | 30 |

### Does the trailing stop keep losses near one unit of risk?

The native exit is a flip, not a fixed level, so a loss should sit near one unit
of risk. This is whether it did, and it is the measured cost of the fixed-1R
departure declared above.

| Timeframe | Exit | Losers | Mean loser | Losses beyond -1.2R | Share of losers | Worst single trade | Best single trade |
|---|---|---|---|---|---|---|---|
| 1H | native | 2190 | -2.523R | 1707 | 78% | -48.94R | +81.00R |
| 1H | forced-1:3 | 2426 | -1.125R | 360 | 15% | -2.19R | +2.97R |
| 4H | native | 539 | -2.351R | 417 | 77% | -8.99R | +168.11R |
| 4H | forced-1:3 | 588 | -1.053R | 5 | 1% | -1.24R | +2.98R |
| 1D | native | 92 | -2.290R | 67 | 73% | -16.88R | +137.23R |
| 1D | forced-1:3 | 95 | -1.014R | 0 | 0% | -1.05R | +3.00R |

### Is the result carried by a handful of trades?

A trailing-stop rule with a sub-40% win rate is designed to concentrate: many
small losses paying for a few large winners. What matters is whether the result
survives removing the single best trade, because that is the difference between a
strategy with a fat tail and a strategy that caught one move.

| Timeframe | Exit | Trades | Total R (post-fee) | Best single trade | Its share of the total | Best five | Their share | Total without the best |
|---|---|---|---|---|---|---|---|---|
| 1H | native | 3394 | +754.9 | +81.00R | 11% | +344.0R | 46% | +673.9R |
| 1H | forced-1:3 | 3346 | -410.7 | +2.97R | -1% | +14.9R | -4% | -413.6R |
| 4H | native | 850 | +678.7 | +168.11R | 25% | +489.0R | 72% | +510.6R |
| 4H | forced-1:3 | 841 | +31.2 | +2.98R | 10% | +14.9R | 48% | +28.3R |
| 1D | native | 139 | +298.1 | +137.23R | 46% | +342.8R | 115% | +160.9R |
| 1D | forced-1:3 | 140 | +29.3 | +3.00R | 10% | +15.0R | 51% | +26.4R |

The "total without the best" column is the honest test. At 4H the
native variant keeps +510.6R of its +678.7R after the
best single trade is deleted, with the best trade alone worth 25% of
the total.

### Long side versus short side

The rule is symmetric and the market is not. This is the measurement the previous
entry could not have produced, because it traded long-only.

| Timeframe | Exit | Long trades | Long R | Long win% | Short trades | Short R | Short win% |
|---|---|---|---|---|---|---|---|
| 1H | native | 1698 | +742.3 | 34.9 | 1696 | +12.6 | 36.0 |
| 1H | forced-1:3 | 1678 | -173.2 | 28.4 | 1668 | -237.4 | 26.6 |
| 4H | native | 424 | +688.9 | 34.2 | 426 | -10.3 | 39.0 |
| 4H | forced-1:3 | 420 | +5.9 | 28.3 | 421 | +25.3 | 31.8 |
| 1D | native | 69 | +325.3 | 34.8 | 70 | -27.2 | 32.9 |
| 1D | forced-1:3 | 70 | +33.0 | 37.1 | 70 | -3.6 | 27.1 |

The long leg out-earned the short leg in 5 of the 6 cells.
Counted on the native exit across all three timeframes: 2191 long trades
for +1756.5R against 2192 short trades for -24.9R. So the
trade counts are close to balanced - the rule fires on flips in both directions -
but the money is not: the long side earns essentially all of it and the short side
earns roughly nothing. That is the same long-only bias the recent strategies in
this log showed, and on this rule it is not a filter the strategy applies, it is
what the tape paid a long-biased indicator over 2020-2026.
Read it against the span: all three coins spent most of these windows in a
rising market, so a long-side advantage is partly the tape and not only the rule.

### The source's own claimed condition, tested

The literature says Supertrend wants sustained trends; whipsaws in ranges/chop. Every trade is labelled
by the regime its entry bar sat in - the project's shared trending / ranging
label, computed from a 100-bar mean and not from anything the strategy knows.

| Timeframe | Exit | Trending trades | Trending R | Trending R/trade | Range trades | Range R | Range R/trade |
|---|---|---|---|---|---|---|---|
| 1H | native | 2344 | +177.7 | 0.076 | 1050 | +577.2 | 0.550 |
| 1H | forced-1:3 | 2315 | -481.2 | -0.208 | 1031 | +70.5 | 0.068 |
| 4H | native | 609 | +312.6 | 0.513 | 241 | +366.1 | 1.519 |
| 4H | forced-1:3 | 601 | -14.6 | -0.024 | 240 | +45.8 | 0.191 |
| 1D | native | 104 | +309.4 | 2.975 | 35 | -11.3 | -0.323 |
| 1D | forced-1:3 | 104 | +16.7 | 0.160 | 36 | +12.7 | 0.352 |

Of the 6 cells, 1 made more R per trade in trending
conditions than in ranging ones. Where the claim fails, the reason is usually
that a range in this label still contains the multi-week drifts a Supertrend
rides - the label is not a filter the strategy applied, only a description of the
tape. The best/worst pair per cell is in the next table.

### Best and worst conditions, per cell

The regime label is computed from the tape, not from the strategy, so these
columns say which market this rule was paid in - not which market it
predicted. The literature says Supertrend wants sustained trends and gets
whipsawed in ranges; the best and worst row per cell is that claim, measured.

| Timeframe | Exit | Condition | Trades | R (post-fee) | R/trade | Win% |
|---|---|---|---|---|---|---|
| 1H | native | down/highvol | 583 | -270.1 | -0.463 | 31.0 |
| 1H | native | down/lowvol | 611 | +129.5 | +0.212 | 33.9 |
| 1H | native | range/highvol | 492 | +74.2 | +0.151 | 36.4 |
| 1H | native | range/lowvol | 554 | +510.8 | +0.922 | 39.5 |
| 1H | native | range/unknown | 4 | -7.8 | -1.950 | 0.0 |
| 1H | native | up/highvol | 573 | +132.7 | +0.232 | 35.3 |
| 1H | native | up/lowvol | 577 | +185.6 | +0.322 | 37.4 |
| 1H | forced-1:3 | down/highvol | 580 | -157.9 | -0.272 | 23.1 |
| 1H | forced-1:3 | down/lowvol | 596 | -96.7 | -0.162 | 26.7 |
| 1H | forced-1:3 | range/highvol | 482 | +74.3 | +0.154 | 36.3 |
| 1H | forced-1:3 | range/lowvol | 545 | -3.5 | -0.006 | 31.0 |
| 1H | forced-1:3 | range/unknown | 4 | -0.2 | -0.060 | 25.0 |
| 1H | forced-1:3 | up/highvol | 566 | -177.3 | -0.313 | 21.7 |
| 1H | forced-1:3 | up/lowvol | 573 | -49.3 | -0.086 | 27.7 |
| 4H | native | down/highvol | 145 | +51.4 | +0.354 | 40.0 |
| 4H | native | down/lowvol | 178 | +23.6 | +0.133 | 34.8 |
| 4H | native | range/highvol | 88 | +250.8 | +2.850 | 45.5 |
| 4H | native | range/lowvol | 146 | +127.4 | +0.873 | 32.9 |
| 4H | native | range/unknown | 7 | -12.2 | -1.736 | 14.3 |
| 4H | native | up/highvol | 135 | +28.4 | +0.211 | 40.0 |
| 4H | native | up/lowvol | 151 | +209.2 | +1.385 | 31.8 |
| 4H | forced-1:3 | down/highvol | 144 | -12.1 | -0.084 | 28.5 |
| 4H | forced-1:3 | down/lowvol | 174 | +0.7 | +0.004 | 27.6 |
| 4H | forced-1:3 | range/highvol | 88 | +14.1 | +0.160 | 37.5 |
| 4H | forced-1:3 | range/lowvol | 145 | +39.0 | +0.269 | 34.5 |
| 4H | forced-1:3 | range/unknown | 7 | -7.2 | -1.033 | 0.0 |
| 4H | forced-1:3 | up/highvol | 137 | -17.9 | -0.131 | 26.3 |
| 4H | forced-1:3 | up/lowvol | 146 | +14.7 | +0.101 | 30.8 |
| 1D | native | down/highvol | 18 | -5.0 | -0.276 | 38.9 |
| 1D | native | down/lowvol | 39 | +89.8 | +2.303 | 30.8 |
| 1D | native | range/highvol | 16 | -8.9 | -0.556 | 31.2 |
| 1D | native | range/lowvol | 18 | -9.5 | -0.526 | 38.9 |
| 1D | native | range/unknown | 1 | +7.0 | +7.050 | 100.0 |
| 1D | native | up/highvol | 18 | -22.4 | -1.243 | 11.1 |
| 1D | native | up/lowvol | 29 | +246.9 | +8.514 | 44.8 |
| 1D | forced-1:3 | down/highvol | 18 | +4.0 | +0.223 | 33.3 |
| 1D | forced-1:3 | down/lowvol | 39 | +4.0 | +0.102 | 28.2 |
| 1D | forced-1:3 | range/highvol | 16 | +1.3 | +0.079 | 37.5 |
| 1D | forced-1:3 | range/lowvol | 19 | +8.4 | +0.443 | 36.8 |
| 1D | forced-1:3 | range/unknown | 1 | +3.0 | +2.980 | 100.0 |
| 1D | forced-1:3 | up/highvol | 18 | -10.3 | -0.572 | 11.1 |
| 1D | forced-1:3 | up/lowvol | 29 | +19.0 | +0.656 | 41.4 |

### What the sources claim, and what this test measured

The comparison cannot be made on outcome, only on shape, and the shape claims
are a vendor's.

| Test | Market | Bars | Trades | Win% | RR | Sharpe | Max DD |
|---|---|---|---|---|---|---|---|
| The sources' claim, flip entries | market and bar size NOT stated (education sites, not Seban) | not stated | not stated | 50-60 | 1.5-3.0 | not stated | not stated |
| This test, native exit | BTC/SOL/XRP perps | 1H | 3394 | 35.5 | 2.07 | 0.69 | 55.6% |
| This test, native exit | BTC/SOL/XRP perps | 4H | 850 | 36.6 | 2.66 | 0.89 | 19.4% |
| This test, native exit | BTC/SOL/XRP perps | 1D | 139 | 33.8 | 4.73 | 0.62 | 21.2% |

The sources' win-rate band for flip entries is 50-60%. Every timeframe here comes
in BELOW it: 33.8% to 36.6% native. The same sources claim
65-72% for pullback entries,
which this test does not trade at all - a pullback to the line is a different
entry, and the test here is the flip the indicator actually generates, not the
higher-edge use a vendor sells. On reward-to-risk the relationship inverts:
achieved RR runs 2.07 to 4.73 against a claimed 1.5-3.0, so the
trades that do win are far larger relative to the average loss than the sources
claim, and there are far fewer of them. Those are the same gap seen two ways: no
target means fewer winners and bigger ones.

**The honest summary of the comparison is that there is nothing to compare it
to.** The indicator's creator published no result. The numbers that circulate
come from sites selling indicators and state no market, no bar size and no span,
so they are not a result that could be confirmed or refuted. What is measured
here is the indicator's own rule on three perpetuals over roughly five to six
years.

### Per coin, so one coin cannot hide behind the pool

coin      timeframe  exit         trades   win%     RR    R pre   R post  R/trade  Sharpe     DD%    DD R  recov  verdict
-------------------------------------------------------------------------------------------------------------------------
BTCUSDT   1H         native         1351   34.6   2.03    422.0    180.8    0.134    0.31    43.8   116.6   1.55  INCONCLUSIVE
BTCUSDT   1H         forced-1:3     1329   26.4   2.17    -16.2   -253.8   -0.191   -1.60   237.6   273.1  -0.93  DISCARD
BTCUSDT   4H         native          337   36.2   2.97    368.4    340.9    1.012    0.83    19.4    29.6  11.52  KEEP
BTCUSDT   4H         forced-1:3      332   31.3   2.42     52.5     25.7    0.077    0.32    15.0    20.0   1.28  INCONCLUSIVE
BTCUSDT   1D         native           55   34.5   5.82    167.0    165.2    3.004    0.48     6.4    17.6   9.39  INCONCLUSIVE
BTCUSDT   1D         forced-1:3       55   32.7   2.87     16.4     14.7    0.267    0.44     4.0     4.7   3.10  INCONCLUSIVE
SOLUSDT   1H         native         1001   37.5   2.12    494.1    398.4    0.398    1.05    34.5    75.5   5.27  KEEP
SOLUSDT   1H         forced-1:3      989   29.3   2.30     60.3    -34.4   -0.035   -0.29    57.0    75.3  -0.46  DISCARD
SOLUSDT   4H         native          251   37.1   2.61    199.7    188.3    0.750    0.64    19.7    33.6   5.60  INCONCLUSIVE
SOLUSDT   4H         forced-1:3      247   30.8   2.54     33.8     22.7    0.092    0.37    11.9    15.5   1.46  INCONCLUSIVE
SOLUSDT   1D         native           40   37.5   4.81     84.9     84.2    2.104    0.50    13.8    14.5   5.82  INCONCLUSIVE
SOLUSDT   1D         forced-1:3       40   40.0   2.82     22.3     21.6    0.540    0.82     3.8     4.2   5.17  KEEP
XRPUSDT   1H         native         1042   34.6   2.08    300.0    175.6    0.169    0.37   146.3   253.0   0.69  INCONCLUSIVE
XRPUSDT   1H         forced-1:3     1028   27.1   2.29     -0.1   -122.4   -0.119   -0.99   129.0   139.2  -0.88  DISCARD
XRPUSDT   4H         native          262   36.6   2.35    164.3    149.4    0.570    0.34    43.5    66.6   2.24  INCONCLUSIVE
XRPUSDT   4H         forced-1:3      262   27.9   2.36     -2.4    -17.1   -0.065   -0.28    25.3    28.1  -0.61  DISCARD
XRPUSDT   1D         native           44   29.5   3.73     49.6     48.7    1.107    0.22    45.3    48.5   1.00  DISCARD
XRPUSDT   1D         forced-1:3       45   24.4   2.47     -6.0     -6.9   -0.154   -0.29    16.3    16.7  -0.41  DISCARD

### Exit-death check: does the edge depend on the exit style?

This is the mandatory comparison - the indicator's own exit against the
project's forced 1:3 triple-barrier, on identical entries.

| Timeframe | Native R/trade | Forced R/trade | Gap | Flag | What it means |
|---|---|---|---|---|---|
| 1H | 0.222 | -0.123 | 0.345 | yes | the exit flips the sign of the edge: native +0.222R per trade vs forced 1:3 -0.123R. Identical entries, so the entry signal is not what decided this - the forced 1:3 exit is. The edge, such as it is, lives in the native exit. |
| 4H | 0.798 | 0.037 | 0.761 | yes | both exits agree on direction but differ by 0.761R per trade (native +0.798R vs forced 1:3 +0.037R), which is larger than the entire +0.10R KEEP requirement. The native exit is doing more work than the entry signal. |
| 1D | 2.145 | 0.210 | 1.935 | yes | both exits agree on direction but differ by 1.935R per trade (native +2.145R vs forced 1:3 +0.210R), which is larger than the entire +0.10R KEEP requirement. The native exit is doing more work than the entry signal. |

**Before that flag is trusted, the precondition for it has to be checked.**
The comparison is only clean when both variants trade the same entries, and here
they share 96% to 99% of them against this project's 85%
fairness floor. They CLEAR the floor on 1H, 4H, 1D.
The gap is structural rather than a bookkeeping error: the native rule holds
until the indicator flips back, so an open position blocks the next flip, while
the forced variant is capped at 30 bars and is free to take it. So the two
variants are not the same entries with different exits; they are different
trade populations.

The same check is therefore repeated on MATCHED entries only - the trades both
variants took on the same bar in the same direction - where the only difference
left is the exit.

| Timeframe | Matched trades | Native R/trade | Forced R/trade | Gap | Exit-death |
|---|---|---|---|---|---|
| 1H | 2825 | 0.212 | -0.123 | 0.335 | yes |
| 4H | 729 | 0.814 | 0.041 | 0.772 | yes |
| 1D | 116 | 2.223 | 0.208 | 2.016 | yes |

A gap wider than 0.15R either way is flagged as an exit
dependency. Read the matched rows as the cleaner answer: they hold the entries
fixed and change only the exit, which is the question being asked.

### Sensitivity 1: the ATR period

The literature does not agree on the default. Some references give ATR 10,
others 14; a vendor's guide suggests 7 for scalping and 20 for position trading.
Four values are run here, each changing exactly one thing.

| Variant | Timeframe | Exit | Trades | Win% | RR | 1R as % of price | R (post-fee) | R/trade | Sharpe | Max DD (R) | Worst trade | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ATR 7 | 1H | native | 3452 | 35.4 | 2.05 | 0.98% | 676.1 | 0.196 | 0.61 | 241.4 | -45.01R | INCONCLUSIVE |
| ATR 7 | 1H | forced-1:3 | 3375 | 28.3 | 2.24 | 0.97% | -317.6 | -0.094 | -1.09 | 364.2 | -2.66R | DISCARD |
| ATR 7 | 4H | native | 852 | 36.0 | 2.81 | 2.06% | 706.6 | 0.829 | 1.00 | 74.7 | -8.01R | KEEP |
| ATR 7 | 4H | forced-1:3 | 841 | 30.1 | 2.41 | 2.07% | 23.7 | 0.028 | 0.17 | 55.3 | -1.30R | DISCARD |
| ATR 7 | 1D | native | 133 | 36.1 | 5.75 | 5.21% | 398.7 | 2.998 | 0.72 | 32.1 | -5.19R | KEEP |
| ATR 7 | 1D | forced-1:3 | 133 | 36.8 | 2.64 | 5.19% | 46.1 | 0.347 | 0.84 | 21.0 | -1.07R | KEEP |
| ATR 10 (traded) | 1H | native | 3394 | 35.5 | 2.07 | 0.96% | 754.9 | 0.222 | 0.69 | 246.0 | -48.94R | INCONCLUSIVE |
| ATR 10 (traded) | 1H | forced-1:3 | 3346 | 27.5 | 2.24 | 0.96% | -410.7 | -0.123 | -1.40 | 442.8 | -2.19R | DISCARD |
| ATR 10 (traded) | 4H | native | 850 | 36.6 | 2.66 | 1.99% | 678.7 | 0.798 | 0.89 | 73.8 | -8.99R | KEEP |
| ATR 10 (traded) | 4H | forced-1:3 | 841 | 30.1 | 2.44 | 2.00% | 31.2 | 0.037 | 0.21 | 44.2 | -1.24R | DISCARD |
| ATR 10 (traded) | 1D | native | 139 | 33.8 | 4.73 | 5.05% | 298.1 | 2.145 | 0.62 | 56.2 | -16.88R | INCONCLUSIVE |
| ATR 10 (traded) | 1D | forced-1:3 | 140 | 32.1 | 2.75 | 5.04% | 29.3 | 0.210 | 0.53 | 10.0 | -1.05R | INCONCLUSIVE |
| ATR 14 | 1H | native | 3469 | 34.8 | 2.02 | 0.94% | 459.3 | 0.132 | 0.43 | 222.1 | -56.41R | INCONCLUSIVE |
| ATR 14 | 1H | forced-1:3 | 3434 | 27.4 | 2.25 | 0.94% | -421.9 | -0.123 | -1.48 | 445.0 | -2.32R | DISCARD |
| ATR 14 | 4H | native | 864 | 37.2 | 2.44 | 1.97% | 582.6 | 0.674 | 0.76 | 98.7 | -9.16R | KEEP |
| ATR 14 | 4H | forced-1:3 | 860 | 28.8 | 2.51 | 1.96% | 10.7 | 0.012 | 0.08 | 48.5 | -1.26R | DISCARD |
| ATR 14 | 1D | native | 135 | 35.6 | 3.95 | 5.14% | 243.2 | 1.802 | 0.62 | 33.1 | -15.48R | INCONCLUSIVE |
| ATR 14 | 1D | forced-1:3 | 137 | 32.8 | 2.87 | 5.02% | 37.4 | 0.273 | 0.66 | 10.6 | -1.05R | INCONCLUSIVE |
| ATR 20 | 1H | native | 3416 | 36.0 | 2.00 | 0.94% | 692.3 | 0.203 | 0.67 | 186.1 | -56.85R | INCONCLUSIVE |
| ATR 20 | 1H | forced-1:3 | 3405 | 26.9 | 2.31 | 0.94% | -419.5 | -0.123 | -1.45 | 458.8 | -2.32R | DISCARD |
| ATR 20 | 4H | native | 866 | 37.3 | 2.29 | 1.98% | 470.4 | 0.543 | 0.77 | 78.5 | -16.75R | KEEP |
| ATR 20 | 4H | forced-1:3 | 866 | 29.3 | 2.50 | 1.97% | 25.0 | 0.029 | 0.17 | 66.2 | -1.35R | DISCARD |
| ATR 20 | 1D | native | 135 | 39.3 | 3.53 | 5.33% | 257.4 | 1.906 | 0.68 | 44.9 | -12.16R | INCONCLUSIVE |
| ATR 20 | 1D | forced-1:3 | 138 | 34.8 | 2.83 | 5.28% | 47.1 | 0.341 | 0.82 | 8.7 | -1.05R | KEEP |

What to look for is monotonicity. If ATR 10 (traded) were a lucky value the
neighbours would be much worse than it; if the rule is real, the four rows
should trend in one direction and the traded value should sit on that trend
rather than above it. **Every alternative here is a labelled variant, not a
candidate - nothing below is used to choose the headline.**

### Sensitivity 2: the ATR multiplier

The multiplier is the only other free parameter, and every source that names one
agrees on 3 - though the same sources suggest 2-2.5 for crypto because of its
higher volatility, which is the one asset-class-specific claim available to
test.

| Variant | Timeframe | Exit | Trades | Win% | RR | 1R as % of price | R (post-fee) | R/trade | Sharpe | Max DD (R) | Worst trade | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| multiplier 2 | 1H | native | 6057 | 34.7 | 1.97 | 0.94% | 324.2 | 0.054 | 0.30 | 390.9 | -71.37R | INCONCLUSIVE |
| multiplier 2 | 1H | forced-1:3 | 5646 | 28.0 | 2.24 | 0.94% | -596.6 | -0.106 | -1.57 | 652.2 | -2.92R | DISCARD |
| multiplier 2 | 4H | native | 1504 | 36.7 | 2.26 | 1.98% | 550.2 | 0.366 | 0.83 | 59.0 | -16.61R | KEEP |
| multiplier 2 | 4H | forced-1:3 | 1412 | 30.0 | 2.48 | 1.99% | 65.2 | 0.046 | 0.34 | 71.6 | -1.47R | INCONCLUSIVE |
| multiplier 2 | 1D | native | 249 | 34.5 | 3.73 | 5.35% | 273.0 | 1.096 | 0.66 | 43.0 | -8.46R | INCONCLUSIVE |
| multiplier 2 | 1D | forced-1:3 | 233 | 31.3 | 2.60 | 5.42% | 30.5 | 0.131 | 0.42 | 24.2 | -1.07R | INCONCLUSIVE |
| multiplier 2.5 | 1H | native | 4439 | 35.3 | 2.00 | 0.96% | 569.3 | 0.128 | 0.57 | 300.3 | -48.94R | INCONCLUSIVE |
| multiplier 2.5 | 1H | forced-1:3 | 4293 | 28.0 | 2.23 | 0.96% | -450.4 | -0.105 | -1.34 | 515.3 | -2.19R | DISCARD |
| multiplier 2.5 | 4H | native | 1128 | 36.2 | 2.55 | 1.98% | 685.7 | 0.608 | 0.79 | 111.6 | -16.61R | KEEP |
| multiplier 2.5 | 4H | forced-1:3 | 1099 | 28.8 | 2.47 | 1.99% | -2.8 | -0.003 | -0.02 | 90.4 | -1.31R | DISCARD |
| multiplier 2.5 | 1D | native | 185 | 32.4 | 3.99 | 5.00% | 239.1 | 1.293 | 0.64 | 48.6 | -15.31R | INCONCLUSIVE |
| multiplier 2.5 | 1D | forced-1:3 | 183 | 33.9 | 2.66 | 4.97% | 44.7 | 0.245 | 0.65 | 18.5 | -1.06R | INCONCLUSIVE |
| multiplier 3 (traded) | 1H | native | 3394 | 35.5 | 2.07 | 0.96% | 754.9 | 0.222 | 0.69 | 246.0 | -48.94R | INCONCLUSIVE |
| multiplier 3 (traded) | 1H | forced-1:3 | 3346 | 27.5 | 2.24 | 0.96% | -410.7 | -0.123 | -1.40 | 442.8 | -2.19R | DISCARD |
| multiplier 3 (traded) | 4H | native | 850 | 36.6 | 2.66 | 1.99% | 678.7 | 0.798 | 0.89 | 73.8 | -8.99R | KEEP |
| multiplier 3 (traded) | 4H | forced-1:3 | 841 | 30.1 | 2.44 | 2.00% | 31.2 | 0.037 | 0.21 | 44.2 | -1.24R | DISCARD |
| multiplier 3 (traded) | 1D | native | 139 | 33.8 | 4.73 | 5.05% | 298.1 | 2.145 | 0.62 | 56.2 | -16.88R | INCONCLUSIVE |
| multiplier 3 (traded) | 1D | forced-1:3 | 140 | 32.1 | 2.75 | 5.04% | 29.3 | 0.210 | 0.53 | 10.0 | -1.05R | INCONCLUSIVE |
| multiplier 4 | 1H | native | 2256 | 34.8 | 2.30 | 0.95% | 1002.6 | 0.444 | 0.82 | 302.4 | -45.93R | KEEP |
| multiplier 4 | 1H | forced-1:3 | 2254 | 26.4 | 2.26 | 0.95% | -350.7 | -0.156 | -1.53 | 406.5 | -2.02R | DISCARD |
| multiplier 4 | 4H | native | 579 | 35.1 | 2.90 | 1.99% | 595.0 | 1.028 | 0.81 | 79.4 | -15.00R | KEEP |
| multiplier 4 | 4H | forced-1:3 | 582 | 30.2 | 2.50 | 1.99% | 35.9 | 0.062 | 0.31 | 40.2 | -1.23R | INCONCLUSIVE |
| multiplier 4 | 1D | native | 100 | 36.0 | 5.08 | 5.29% | 326.3 | 3.263 | 0.64 | 38.7 | -5.33R | INCONCLUSIVE |
| multiplier 4 | 1D | forced-1:3 | 103 | 29.1 | 2.73 | 5.28% | 9.1 | 0.088 | 0.19 | 12.0 | -1.05R | DISCARD |

A lower multiplier pulls the line closer to price, so flips fire more often
and 1R narrows; a higher one pushes the line further away, so flips are rarer
and 1R widens. That both directions move the fee bill in R units is why the
sweep matters on a rule this fee-sensitive.

### Sensitivity 3: long-only, the reading the previous entry traded

This is the variant that produced the numbers in the previous entry, and it is
run so those numbers stay auditable rather than being replaced by a different
rule's.

| Variant | Timeframe | Exit | Trades | Win% | RR | 1R as % of price | R (post-fee) | R/trade | Sharpe | Max DD (R) | Worst trade | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| as traded | 1H | native | 3394 | 35.5 | 2.07 | 0.96% | 754.9 | 0.222 | 0.69 | 246.0 | -48.94R | INCONCLUSIVE |
| as traded | 1H | forced-1:3 | 3346 | 27.5 | 2.24 | 0.96% | -410.7 | -0.123 | -1.40 | 442.8 | -2.19R | DISCARD |
| as traded | 4H | native | 850 | 36.6 | 2.66 | 1.99% | 678.7 | 0.798 | 0.89 | 73.8 | -8.99R | KEEP |
| as traded | 4H | forced-1:3 | 841 | 30.1 | 2.44 | 2.00% | 31.2 | 0.037 | 0.21 | 44.2 | -1.24R | DISCARD |
| as traded | 1D | native | 139 | 33.8 | 4.73 | 5.05% | 298.1 | 2.145 | 0.62 | 56.2 | -16.88R | INCONCLUSIVE |
| as traded | 1D | forced-1:3 | 140 | 32.1 | 2.75 | 5.04% | 29.3 | 0.210 | 0.53 | 10.0 | -1.05R | INCONCLUSIVE |
| long-only, the other common reading of the rule | 1H | native | 1698 | 34.9 | 2.37 | 0.93% | 742.3 | 0.437 | 0.93 | 169.1 | -11.45R | KEEP |
| long-only, the other common reading of the rule | 1H | forced-1:3 | 1697 | 28.3 | 2.21 | 0.93% | -174.9 | -0.103 | -0.87 | 230.2 | -2.19R | DISCARD |
| long-only, the other common reading of the rule | 4H | native | 424 | 34.2 | 3.93 | 1.92% | 688.9 | 1.625 | 0.95 | 92.5 | -8.99R | KEEP |
| long-only, the other common reading of the rule | 4H | forced-1:3 | 427 | 27.9 | 2.58 | 1.92% | -1.6 | -0.004 | -0.02 | 33.0 | -1.24R | DISCARD |
| long-only, the other common reading of the rule | 1D | native | 69 | 34.8 | 7.93 | 4.39% | 325.3 | 4.714 | 0.72 | 31.0 | -5.13R | KEEP |
| long-only, the other common reading of the rule | 1D | forced-1:3 | 72 | 36.1 | 2.95 | 4.35% | 30.9 | 0.429 | 0.74 | 10.3 | -1.05R | KEEP |

**The long-only variant is a different rule, and it scores differently.**
With no shorts to take, a bearish flip only ever exits a long, so the trade
population roughly halves and every signal is taken on the bullish side of a
market that rose for most of the window. Read this row as the other reading of
the source, not as a tuned version of what was traded.

| Timeframe | Exit | Avg hold | 8h funding stamps crossed | 1R as % of price | Funding at the base rate | R/trade post-fee | Post-fee minus funding |
|---|---|---|---|---|---|---|---|
| 1H | native | 43h | 5.4 | 0.96% | -0.056R | +0.222R | +0.166R |
| 1H | forced-1:3 | 7h | 0.9 | 0.96% | -0.009R | -0.123R | -0.132R |
| 4H | native | 170h | 21.3 | 1.99% | -0.107R | +0.798R | +0.691R **<- KEEP** |
| 4H | forced-1:3 | 31h | 3.8 | 2.00% | -0.019R | +0.037R | +0.018R |
| 1D | native | 959h | 119.9 | 5.05% | -0.238R | +2.145R | +1.907R |
| 1D | forced-1:3 | 155h | 19.4 | 5.04% | -0.038R | +0.210R | +0.171R |


**Funding is not modelled, and on this rule it is not a footnote.**

The 4H native cell reads as a KEEP above. It holds a position for 170 hours on
average, which crosses about 21 funding settlements per trade. At Bybit's
base rate of 0.01% per settlement that is roughly 0.11R of cost per
trade, against a measured expectancy of 0.798R. The edge survives the base rate, but the base rate is a floor: a
trend-follower is by definition holding the crowded side of a one-way
market, where funding is usually worse than base. **This KEEP is
PROVISIONAL until funding is modelled properly.**

Per the standing rule, a KEEP on a multi-day holding strategy is not
treated as a real KEEP until funding is priced. The verdicts in the table above
are the fee-and-slippage verdicts; the funding column is the reason none of them
is being acted on yet.

### What would change these verdicts

Five things, in the order they would move the numbers most.

1. **The direction reading.** The previous entry's KEEPs were long-only KEEPs;
   the rule as the clearest reference describes it trades both. Sensitivity 3
   keeps both on the page, and the two are not the same strategy.
2. **Funding.** Priced above at the base rate as a floor. The native rule holds
   for 42.6 4H bars on average, so this is not a
   rounding item, and a proper model needs the historical funding series per
   coin rather than a flat rate.
3. **The fixed-1R departure.** The indicator's line ratchets and a fixed 1R does
   not, so a native loss can exceed the one unit of risk it was sold as. The
   loss-tail table measures that; a port that trailed the line instead would
   tighten the stop and cut both the losses and the winners.
4. **The universe.** Three coins is not a market, and a trend-follower on three
   heavily correlated perpetuals has far fewer independent bets than the trade
   count suggests. More coins is the honest way to raise the sample, not more
   parameter variants on three.
5. **The sources' own claims being unfalsifiable.** No market, no bar size, no
   span and no per-trade numbers are stated, so nothing here could be confirmed
   or refuted on outcome. A strategy whose source publishes nothing cannot be
   scored against its source, only against the bar.

### Bottom line

Supertrend is the weakest-sourced strategy in this log and one of the cleanest
rules: two parameters, no discretion, and an exit that is the indicator itself.
The parameters are defaults rather than fits, which is the one thing the sourcing
problem cannot take away.

The cells that clear the bar are **4H native**. Each is a clear of a fixed
quality bar, not a statistical proof: The largest t-statistic anywhere in this run is +2.40, which
clears the ~2.0 that separates an average from chance - but only just,
and only on the one cell the KEEP sits on. That is a weak statistical
claim, not a proven one, and it does not survive removing that cell.
Every KEEP here is also a multi-day hold whose funding
cost is not priced. Read them as PROVISIONAL.

Two things are consistent across every timeframe. The native exit is where the
money is - capping winners at 3R destroys this rule on 1H and 4H, which is the
exit-death finding in a single sentence. And the edge, where it exists, is a
trailing-stop edge rather than an entry edge: the same flips under a fixed 1:3
mostly stop out. Nothing here suggests the entry signal has value on its own.

At 4H the native exit took 850 trades at 0.798R each; at 1H, 3394 trades at 0.222R each.
Both are the indicator's own rule, not a tuned version of it.

## Strategy #9 - Bulkowski's Narrow Range 7 (NR7)

### Source, and the rule exactly as written

Thomas Bulkowski, "NR7", *thepatternsite.com* (Encyclopedia of Chart Patterns). The setup and the
crypto-specific entry are short enough to quote in full:

* Setup: *"The most recent bar must have a smaller high-low price range than the prior six bars
  (seven bars, total)."* The range is **high - low**. He is explicit that it is not true range.
* Breakout: *"A breakout occurs when price closes above the top or below the bottom of the NR7."*
* Entry, for the cryptocurrency test: *"I placed a buy stop a penny above the top of the NR7 and a
  stop loss order a penny below the bottom of the pattern."*
* Exit, the measure rule: *"Measure the height of pattern and add it to the highest price in the
  pattern to get an upward target or subtract it from the lowest low in the pattern to get a
  downward price target."*

This is the next strategy in the lineage started by #4: Crabel names the "narrow range day" as the
conditioning framework for his opening-range breakout and defers its measurement to paywalled
chapters. Bulkowski's NR7 is the standard, fully-published form of that same idea, so it is what
gets tested here instead of a guess at what Crabel left out.

**The rule as tested:** bar D's high-low range is the smallest of the last seven. Before bar D+1
opens, a buy stop sits at bar D's high and a sell stop at bar D's low; whichever fires first is the
trade, and the other end of the pattern is the stop. The exit is the measure rule - the pattern's
own height projected from the entry - which is exactly 1R, making the native exit a symmetric 1:1.

### What is a PLACEHOLDER, never a guess at the source's intent

* **"A penny" above and below the trigger.** Meaningless on a six-figure bitcoin. The traded config
  puts the trigger exactly on bar D's high and low; the offset is run as a sensitivity at 0.1% of
  the bar's range rather than assumed. This is the only free parameter the rule contains.
* **How long unfilled orders rest.** The source says when the breakout is *recognised*, not when
  unexecuted orders are cancelled. The literal reading of *"price closes above the top"* is the
  following bar, so `REST_BARS = 1` is the headline and 2 / 3 bars are sensitivities.
* **N = 7**, because the source is "NR7". NR4 is a separately published pattern and is run as a
  sensitivity, not folded into the headline.

### What this test could NOT reproduce, and what that means

* **The venue and the asset class.** Bulkowski's own result is on 38 cryptocurrencies, but his
  stop-loss and measure-rule percentages come from an equities career. The structural difference
  matters more here than for any other strategy in this project, for the reason in the geometry
  section below.
* **A stop order that is actually resting.** Bybit charges taker fees on both legs of a stop order
  in this test. A maker rebate on the entry leg is the cheapest realistic change, and it is
  reported in the fee section rather than assumed away.
* **The trend conditioning of the source's own result.** He reports the win rate separately in
  uptrends and downtrends; the regime table below is the closest this project has, and it is
  labelled post-fee where his is not.

### Lookahead bias: what was checked, freshly, for this strategy

The runner audits every coin/timeframe input before simulation by rebuilding indicators on truncated
history and comparing with the full-data values; this report also prints a separate BTCUSDT 1H audit.
The displayed audit checked 10 computed columns and passed. Four places needed real care:

* **IS_NR7** compares bar D against the six bars before it and is written ON bar D, so it is a
  closed-bar fact by construction.
* **The triggers and the risk unit** are the most recent narrow bar's own high, low and range,
  carried forward with `where(is_nr7).ffill().shift(1)` - bar *i* reads only bars at or before *i-1*.
* **The "session" is the armed window, not the clock.** NR7's orders rest for bars after a narrow
  bar, which can begin at any hour. The window is therefore derived from IS_NR7 alone, which is closed-
  bar data; it is not aligned to a UTC day.
* **The current bar's high and low** are used by the engine to FILL an order that was already
  sitting there at a pre-bar price, and are never used by the strategy to DECIDE anything. Six
  hand-built-candle tests in the shared resting-order test suite pin that behaviour down, including
  filling at the trigger, filling worse when a bar gaps through it, and refusing to guess when one
  bar covers both sides.

### Results - three coins pooled per timeframe, every number post-fee

The four timeframes are one test at four bar sizes. The rule never changes: seven bars, smallest
range wins, trade the next bar's breakout. Only the bar that carries the definition changes.

| Timeframe | Exit | Trades | Win% | RR | R (pre-fee) | R (post-fee) | R/trade | Sharpe | Max DD % | Max DD (R) | R-recovery | Fee cost/trade | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1H | native | 13031 | 62.3 | 0.62 | 3469.0 | 107.9 | 0.008 | 0.34 | 104.1 | 227.2 | 0.48 | 0.258R | **DISCARD** |
| 1H | forced-1:3 | 10555 | 32.8 | 2.18 | 3221.5 | 585.4 | 0.055 | 1.09 | 86.4 | 162.0 | 3.61 | 0.250R | **INCONCLUSIVE** |
| 4H | native | 3030 | 62.4 | 0.78 | 754.0 | 383.3 | 0.126 | 2.67 | 10.8 | 22.9 | 16.71 | 0.122R | **INCONCLUSIVE** |
| 4H | forced-1:3 | 2557 | 33.1 | 2.54 | 805.8 | 496.4 | 0.194 | 1.92 | 17.2 | 36.9 | 13.47 | 0.121R | **KEEP** |
| 6H | native | 2109 | 63.3 | 0.82 | 563.0 | 353.4 | 0.168 | 2.95 | 6.8 | 12.8 | 27.71 | 0.099R | **INCONCLUSIVE** |
| 6H | forced-1:3 | 1760 | 31.8 | 2.62 | 467.4 | 293.9 | 0.167 | 1.40 | 22.7 | 44.1 | 6.66 | 0.099R | **KEEP** |
| 1D | native | 525 | 68.2 | 0.91 | 191.0 | 164.7 | 0.314 | 2.76 | 4.6 | 6.8 | 24.05 | 0.050R | **INCONCLUSIVE** |
| 1D | forced-1:3 | 447 | 37.1 | 2.79 | 214.5 | 191.5 | 0.428 | 1.70 | 8.5 | 16.1 | 11.87 | 0.052R | **KEEP** |

**Verdicts, per exit variant, never collapsed:**

* **Native (the source's own measure rule):** 1H DISCARD - earned only 0.48x its worst drawdown · 4H INCONCLUSIVE - positive but short of the KEEP bar: achieved RR 0.78 < 1.5 · 6H INCONCLUSIVE - positive but short of the KEEP bar: achieved RR 0.82 < 1.5 · 1D INCONCLUSIVE - positive but short of the KEEP bar: achieved RR 0.91 < 1.5
* **Forced 1:3:** 1H INCONCLUSIVE - positive but short of the KEEP bar: expectancy +0.055R < +0.10R; win rate 32.8% < 33.2% needed to clear its own fee bill (fees cost 0.250R per trade) · 4H KEEP - +0.194R per trade, Sharpe 1.92, earned 13.47x its worst drawdown over 2557 trades · 6H KEEP - +0.167R per trade, Sharpe 1.40, earned 6.66x its worst drawdown over 1760 trades · 1D KEEP - +0.428R per trade, Sharpe 1.70, earned 11.87x its worst drawdown over 447 trades

Exit-death check (does the source's own exit beat a forced 1:3 on the same entries):
1H: no (the two exits land within 0.047R per trade of each other (native +0.008R vs forced 1:3 +0.055R), so the result is driven by the entry signal rather than by the choice of exit) · 4H: no (the two exits land within 0.068R per trade of each other (native +0.126R vs forced 1:3 +0.194R), so the result is driven by the entry signal rather than by the choice of exit) · 6H: no (the two exits land within 0.001R per trade of each other (native +0.168R vs forced 1:3 +0.167R), so the result is driven by the entry signal rather than by the choice of exit) · 1D: no (the two exits land within 0.115R per trade of each other (native +0.314R vs forced 1:3 +0.428R), so the result is driven by the entry signal rather than by the choice of exit).
Rows that read yes: 1H, 4H, 6H, 1D.

The two variants share 1H 82.6%, 4H 86.1%, 6H 84.7%, 1D 85.9% of their entries,
against the 85% minimum for "same entries, only the exit differs" to be
a fair claim. The overlap is short on the fine bars because the two exits hold for different lengths
(a 1:1 measure exit versus a 30-bar triple barrier), so while holding one blocks different armed
sessions for each. The disagreement is in the SIGN of the edge and is far larger than the overlap gap
can account for, which is the comparison the exit-death check exists to make.

### Why the result is what it is: the pattern's own geometry

NR7 is the first strategy in this project whose risk unit is defined as the SMALLEST thing in the
window. Every other strategy measures 1R from a typical or an extreme candle - an ATR, a channel, a
day's range - so 1R is at least as big as a normal bar. Here 1R is required to be *narrower than six
of the last seven bars*. That is not a side effect of the construction; it is the construction.

| Coin | 1R as % of price (1H) | NR7 bars as % of all bars (1H) | 1R as % of price (1D) |
|---|---|---|---|
| BTCUSDT | 0.373% | 17.1% | 1.822% |
| SOLUSDT | 0.719% | 16.2% | 3.721% |
| XRPUSDT | 0.543% | 16.1% | 2.858% |
| Round-trip taker fee | 0.110% of price | | |

The round-trip taker fee is 0.110% of price and the median risk unit is 0.543% of
price, so fees cost roughly **0.26R per trade** at 1H. In this
 pooled sample the native 1H expectancy moves from 0.266R gross to
 0.008R post-fee. Fees materially reduce the edge, but do not erase it
in the pooled 1H mean; the negative BTC row and the weak aggregate Sharpe explain why the quality
verdict can still be DISCARD.

The same fee-to-risk mechanism documented in `discard_bar.py` applies: as 1R gets smaller relative to
the fixed percentage fee, fees consume more R per trade. This is an explanation for the timeframe
pattern, not by itself a complete causal account of the observed coin- and timeframe-level results.

### Concentration - is the edge in one leg or one coin?

NR7 is symmetric by construction: a buy stop above and a sell stop below the same bar. If the market
is genuinely choosing a direction out of consolidation, both legs should carry it.

| Timeframe | Exit | Long trades | Long R | Long win% | Short trades | Short R | Short win% |
|---|---|---|---|---|---|---|---|
| 1H | native | 6598 | -117.3 | 61.0 | 6433 | +225.2 | 63.7 |
| 1H | forced-1:3 | 5379 | -28.5 | 31.4 | 5176 | +613.9 | 34.3 |
| 4H | native | 1585 | +171.6 | 61.5 | 1445 | +211.7 | 63.5 |
| 4H | forced-1:3 | 1341 | +255.0 | 33.0 | 1216 | +241.4 | 33.3 |
| 6H | native | 1061 | +184.1 | 63.7 | 1048 | +169.3 | 63.0 |
| 6H | forced-1:3 | 900 | +205.6 | 33.4 | 860 | +88.3 | 30.1 |
| 1D | native | 255 | +61.8 | 64.7 | 270 | +102.9 | 71.5 |
| 1D | forced-1:3 | 214 | +78.6 | 35.5 | 233 | +113.0 | 38.6 |

At 1H, 6598 long and 6433 short entries split roughly
evenly. The pooled result is not representative of every coin: the per-coin table above shows BTC's
native 1H row is negative while SOL and XRP are positive. Both legs and all coins therefore need to be
read separately; a pooled edge is not evidence of a uniform signal.

### Regime - does it work anywhere?

* **down/highvol:** 2633 trades, +186.8R post-fee
* **down/lowvol:** 2358 trades, -164.9R post-fee
* **range/highvol:** 1362 trades, +107.5R post-fee
* **range/lowvol:** 1712 trades, -7.5R post-fee
* **up/highvol:** 2562 trades, +82.7R post-fee
* **up/lowvol:** 2404 trades, -96.8R post-fee

Best regime: down/highvol. Worst: down/lowvol. The source's own result is conditioned
on trend direction (48% win in an uptrend, 42% in a downtrend) and
is stated gross; these rows are post-fee, so they are not comparable column for column.

### Fees and funding: the binding constraint

Fee cost per trade is **0.258R** native and 0.250R
forced at 1H, against a median 1R of 0.543% of price. The breakeven win rate for the
forced 1:3 at that fee level is **31.2%**, and the measured
win rate is **32.8%** - the forced variant lands essentially on its own fee-breakeven
line, so judge the actual post-fee expectancy and verdict rather than inferring that costs consume
the whole signal. Forced 1:3 verdicts by timeframe: 1H INCONCLUSIVE; 4H KEEP; 6H KEEP; 1D KEEP.

Pre-fee, the entry is doing something: the gross t-statistic is +31.53 at 1H
(1H +31.53 / 4H +14.14 / 6H +12.72 / 1D +8.94 across timeframes). Post-fee it is +0.96 (1H +0.96 / 4H +7.19 / 6H +7.99 / 1D +7.73). The 1H t-statistic
falls sharply after fees; on coarser bars the measured edge remains positive. Statistical evidence is
not by itself proof of a robust or transferable strategy.

### Coverage, and the sensitivities

| Timeframe | Coin | Window traded | Days | Years | Tradeable bars | Warmup bars |
|---|---|---|---|---|---|---|
| 1H | BTCUSDT | 2020-04-03 to 2026-09-05 | 2346 | 6.42 | 56,295 | 216 |
| 1H | SOLUSDT | 2021-10-24 to 2026-09-05 | 1777 | 4.87 | 42,649 | 216 |
| 1H | XRPUSDT | 2021-05-22 to 2026-09-05 | 1932 | 5.29 | 46,360 | 216 |
| 4H | BTCUSDT | 2020-04-14 to 2026-09-05 | 2335 | 6.39 | 14,009 | 120 |
| 4H | SOLUSDT | 2021-11-04 to 2026-09-05 | 1766 | 4.84 | 10,597 | 120 |
| 4H | XRPUSDT | 2021-06-02 to 2026-09-05 | 1921 | 5.26 | 11,525 | 120 |
| 6H | BTCUSDT | 2020-04-24 to 2026-09-05 | 2325 | 6.37 | 9,302 | 120 |
| 6H | SOLUSDT | 2021-11-14 to 2026-09-05 | 1756 | 4.81 | 7,027 | 120 |
| 6H | XRPUSDT | 2021-06-12 to 2026-09-05 | 1911 | 5.23 | 7,646 | 120 |
| 1D | BTCUSDT | 2020-07-23 to 2026-09-05 | 2235 | 6.12 | 2,236 | 120 |
| 1D | SOLUSDT | 2022-02-12 to 2026-09-05 | 1666 | 4.56 | 1,667 | 120 |
| 1D | XRPUSDT | 2021-09-10 to 2026-09-05 | 1821 | 4.99 | 1,822 | 120 | (warmup: 216 1H bars, so
the 100-bar regime average is populated before any trade.)

Sensitivities, headline timeframe, both exits:

| Variant (1H) | Exit | Trades | Win% | RR | R (post-fee) | R/trade | Sharpe | Fee cost/trade | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| N = 7 (traded) | native | 13031 | 62.3 | 0.62 | 107.9 | 0.008 | 0.34 | 0.258R | DISCARD |
| N = 7 (traded) | forced-1:3 | 10555 | 32.8 | 2.18 | 585.4 | 0.055 | 1.09 | 0.250R | INCONCLUSIVE |
| N = 4 (NR4, separately published) | native | 19698 | 60.5 | 0.65 | 8.5 | 0.000 | 0.02 | 0.222R | DISCARD |
| N = 4 (NR4, separately published) | forced-1:3 | 13845 | 32.4 | 2.23 | 752.9 | 0.054 | 1.21 | 0.212R | INCONCLUSIVE |
| N = 10 | native | 9760 | 63.6 | 0.59 | 138.3 | 0.014 | 0.52 | 0.283R | INCONCLUSIVE |
| N = 10 | forced-1:3 | 8256 | 33.3 | 2.12 | 429.8 | 0.052 | 0.93 | 0.278R | INCONCLUSIVE |
| trigger offset = 0.1% of the bar's range | native | 13292 | 60.8 | 0.61 | -344.3 | -0.026 | -1.07 | 0.261R | DISCARD |
| trigger offset = 0.1% of the bar's range | forced-1:3 | 10766 | 32.2 | 2.17 | 312.1 | 0.029 | 0.58 | 0.252R | INCONCLUSIVE |
| orders rest 2 bars | native | 13031 | 62.3 | 0.62 | 107.9 | 0.008 | 0.34 | 0.258R | DISCARD |
| orders rest 2 bars | forced-1:3 | 10555 | 32.8 | 2.18 | 585.4 | 0.055 | 1.09 | 0.250R | INCONCLUSIVE |
| orders rest 3 bars | native | 13031 | 62.3 | 0.62 | 107.9 | 0.008 | 0.34 | 0.258R | DISCARD |
| orders rest 3 bars | forced-1:3 | 10555 | 32.8 | 2.18 | 585.4 | 0.055 | 1.09 | 0.250R | INCONCLUSIVE |

The table is the evidence for the sensitivities; each row uses its own warmup. NR4 and N=10 change
both the frequency and geometry of setups, and the offset changes which breakouts fill. These are
different rules, not independent confirmation of the N=7 headline. The rest-window variants are also
reported as-run. Resting orders for two or three bars produced the same aggregate metrics as one bar
in this run. The execution model tracks one active session state, so the unchanged results should not
be interpreted as evidence that order expiry never matters; the longer-rest variants are not
independent confirmation of the headline result.

### Bottom line

Measured native verdicts by timeframe: 1H DISCARD; 4H INCONCLUSIVE; 6H INCONCLUSIVE; 1D INCONCLUSIVE.
Forced 1:3 verdicts: 1H INCONCLUSIVE; 4H KEEP; 6H KEEP; 1D KEEP. At 1H,
the native strategy records 107.9R post-fee over 13031 pooled trades
(62.3% wins), while forced 1:3 records 585.4R over
10555 trades (32.8% wins). The measured headline native expectancy is
0.008R/trade; the verdict is based on the shared discard criteria,
not a blanket claim that all fees erase all edge.

### Interpretation and limits

Bulkowski reports underperformance against buy-and-hold in his own sample. This backtest does not
calculate a buy-and-hold comparison, so it cannot independently confirm that benchmark claim. Results
vary substantially by timeframe and coin: pooled native verdicts are
1H DISCARD ; 4H INCONCLUSIVE ; 6H INCONCLUSIVE ; 1D INCONCLUSIVE, and forced 1:3 verdicts are
1H INCONCLUSIVE ; 4H KEEP ; 6H KEEP ; 1D KEEP under this project's thresholds.
These labels are screening criteria, not proof of future profitability.

The narrow pattern range makes the fee-to-risk ratio relevant, but does not alone explain the
timeframe/coin differences. A maker-fee scenario or wider stop would be a different execution/risk
model and should be tested explicitly rather than assumed. Coarser bars have positive pooled results
in this sample, but need out-of-sample and execution-resolution checks before being treated as
evidence of a durable effect.

## Strategy #10 - RSI(2) trend-filtered mean reversion

**Tested:** 2026-09-25 - **Coins:** BTCUSDT+SOLUSDT+XRPUSDT - **Timeframes:** 1H, 4H, 1D - **Fees:** Bybit taker 0.055% per side - **Risk:** 1% of starting equity per trade, not compounded

### 1. Rule and source
On a closed bar t: **long** if close[t] > SMA200[t] and RSI(2)[t] < 10; **short** if close[t] < SMA200[t] and RSI(2)[t] > 90. Comparisons are strict, so equality is neither. Entry fills at bar t+1 open and the fixed 2% initial stop is measured from that actual fill (long entry x 0.98, short x 1.02), which defines 1R. **Native exit:** close a long once RSI(2) on a completed bar is strictly above 70 and a short once it is strictly below 30, filled at the next open; the stop stays armed throughout, and there is no reversal on the exit bar - the next position needs its own later qualifying signal. No take-profit, no pyramiding, at most one position per coin per timeframe. **Forced-1:3 variant:** identical entries and identical 1R with a 1R stop, 3R target and 30-bar limit, under the shared engine conventions (the stop wins intrabar ties, a bar that gaps through the stop fills at the open, and a trade still open at the end of the data is discarded rather than marked to the last close).

**Provenance:** the RSI(2) short-term mean-reversion family associated with Larry Connors, *Short Term Trading Strategies That Work* (2008), and Larry Williams, *Long-Term Secrets to Short-Term Trading* (1999). Connors' commonly cited pullback is long-only and exits on a 5-day SMA, so the short mirror, the 70/30 RSI exits and the fixed 2% stop are this test's declared adaptations and are not attributed to that source as canonical. No source performance claim is assumed or reproduced.

### 2. Placeholders and adaptations
- RSI(2): Wilder recursive smoothing (alpha = 1/2, `adjust=False`), needing two close-changes before a value exists; average loss of zero with positive average gain reads 100, and both zero reads 50.
- Trend filter: a contemporaneous, unshifted 200-bar close SMA, requiring all 200 closes.
- Thresholds: entry 10/90, native exit 70/30, every comparison strict.
- Initial stop: fixed 2.0% from the actual next-open fill; no trailing and no recalculation. A project risk convention, not a source parameter.
- Execution: closed-bar decision and next-open fill; taker 0.055% each side; 1% of starting equity risked per trade, not compounded.
- One position per coin per timeframe; no pyramiding; both long and short are traded.
- Warmup is 201 bars on every timeframe, applied identically to the headline and to every sweep.
- The forced 30-bar limit is the project's shared unvalidated convention, not an RSI source parameter.
- Independent sweeps, each a fresh run that never replaces the headline: stop 1%/2%/3%, and entry pair 5/95, 10/90, 15/85 with the 70/30 exit thresholds held fixed.

### 3. Lookahead audit
| Dataset | Columns checked | Result |
|---|---|---|
| BTCUSDT 1D | rsi2, sma200 | PASS |
| BTCUSDT 1H | rsi2, sma200 | PASS |
| BTCUSDT 4H | rsi2, sma200 | PASS |
| SOLUSDT 1D | rsi2, sma200 | PASS |
| SOLUSDT 1H | rsi2, sma200 | PASS |
| SOLUSDT 4H | rsi2, sma200 | PASS |
| XRPUSDT 1D | rsi2, sma200 | PASS |
| XRPUSDT 1H | rsi2, sma200 | PASS |
| XRPUSDT 4H | rsi2, sma200 | PASS |

**9 of 9 datasets passed.** Each indicator value at every cut bar was identical computed on truncated history and on full history.

### 4. Results table
Coins are pooled inside each timeframe; timeframes are never pooled with each other. All money figures are post-fee.

| Timeframe | Exit | Trades | Days/coin | Win% | RR | R pre-fee | R post-fee | R/trade | Sharpe | Max DD % | Max DD R | Verdict |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1H | native | 6789 | BTC 2346d / SOL 1778d / XRP 1932d | 58.7 | 0.62 | 126.1 | -247.3 | -0.036 | -1.36 | 243.0 | 266.8 | **DISCARD** |
| 1H | forced-1:3 | 4700 | BTC 2346d / SOL 1778d / XRP 1932d | 36.5 | 1.70 | 196.3 | -62.2 | -0.013 | -0.20 | 88.9 | 127.5 | **DISCARD** |
| 4H | native | 2083 | BTC 2321d / SOL 1752d / XRP 1907d | 47.6 | 1.01 | 27.1 | -87.4 | -0.042 | -0.50 | 101.6 | 134.8 | **DISCARD** |
| 4H | forced-1:3 | 1807 | BTC 2321d / SOL 1752d / XRP 1907d | 28.7 | 2.52 | 115.1 | 15.8 | 0.009 | 0.07 | 56.6 | 109.2 | **DISCARD** |
| 1D | native | 424 | BTC 2154d / SOL 1585d / XRP 1740d | 26.4 | 2.57 | -2.3 | -25.6 | -0.060 | -0.24 | 55.5 | 58.7 | **DISCARD** |
| 1D | forced-1:3 | 423 | BTC 2154d / SOL 1585d / XRP 1740d | 22.5 | 2.79 | -43.0 | -66.3 | -0.157 | -0.74 | 78.3 | 79.5 | **DISCARD** |

Shortest window in this run: SOLUSDT at 1D, 1585 days (4.34 years). Longest: BTCUSDT at 1H, 2346 days (6.42 years).

### 5. Statistical significance
t is each cell's mean per-trade R divided by its own standard error; roughly 2.0 is the noise threshold, and a negative result needs no such defence.

| Timeframe | Exit | Trades | Pre-fee R/trade | t pre-fee | Post-fee R/trade | t post-fee | vs 2.0 |
|---|---|---:|---:|---:|---:|---:|---|
| 1H | native | 6789 | +0.0186 | 2.04 | -0.0364 | -4.00 | reliably negative, distinguishable from noise |
| 1H | forced-1:3 | 4700 | +0.0418 | 2.00 | -0.0132 | -0.63 | inside the range chance produces |
| 4H | native | 2083 | +0.0130 | 0.50 | -0.0420 | -1.61 | inside the range chance produces |
| 4H | forced-1:3 | 1807 | +0.0637 | 1.58 | +0.0087 | 0.22 | inside the range chance produces |
| 1D | native | 424 | -0.0054 | -0.05 | -0.0604 | -0.61 | inside the range chance produces |
| 1D | forced-1:3 | 423 | -0.1017 | -1.25 | -0.1566 | -1.93 | inside the range chance produces |

### 6. Concentration
How much of each cell's total R rests on one trade and on the best five. A negative total makes the percentage shares directionally meaningless, so read them alongside Total R.

| Timeframe | Exit | Trades | Total R | Best trade | Best 5 trades | Best 5 as % of total |
|---|---|---:|---:|---:|---:|---:|
| 1H | native | 6789 | -247.31 | +6.96 | +27.38 | -11.1 |
| 1H | forced-1:3 | 4700 | -62.17 | +2.95 | +14.73 | -23.7 |
| 4H | native | 2083 | -87.40 | +5.37 | +24.58 | -28.1 |
| 4H | forced-1:3 | 1807 | 15.78 | +2.95 | +14.73 | 93.4 |
| 1D | native | 424 | -25.61 | +18.42 | +52.38 | -204.5 |
| 1D | forced-1:3 | 423 | -66.26 | +2.95 | +14.73 | -22.2 |

### 7. Long/short breakdown
| Timeframe | Exit | Side | Trades | Win% | R post-fee | R/trade, avg bars |
|---|---|---|---:|---:|---:|---|
| 1H | native | long | 3263 | 59.3 | -82.40 | -0.025 (3.9 bars) |
| 1H | native | short | 3526 | 58.1 | -164.91 | -0.047 (4.0 bars) |
| 1H | forced-1:3 | long | 2276 | 36.7 | -36.78 | -0.016 (15.7 bars) |
| 1H | forced-1:3 | short | 2424 | 36.3 | -25.40 | -0.010 (15.9 bars) |
| 4H | native | long | 973 | 44.9 | -104.54 | -0.107 (2.4 bars) |
| 4H | native | short | 1110 | 50.0 | 17.14 | +0.015 (2.7 bars) |
| 4H | forced-1:3 | long | 843 | 26.1 | -85.74 | -0.102 (6.2 bars) |
| 4H | forced-1:3 | short | 964 | 30.9 | 101.53 | +0.105 (7.0 bars) |
| 1D | native | long | 204 | 24.5 | -10.83 | -0.053 (1.1 bars) |
| 1D | native | short | 220 | 28.2 | -14.78 | -0.067 (1.1 bars) |
| 1D | forced-1:3 | long | 205 | 22.0 | -36.26 | -0.177 (1.0 bars) |
| 1D | forced-1:3 | short | 218 | 22.9 | -30.00 | -0.138 (1.3 bars) |

### 8. Exit-death and overlap
The two exits share one entry rule and one 1R, so any difference between them is attributable to the exit alone. Overlap is the share of entry timestamps they have in common; below 85% the comparison is rerun on shared entries only.

**1H.** The two variants share **66.5%** of their entry timestamps. Exit-death: **no** - the two exits land within 0.023R per trade of each other (native -0.036R vs forced 1:3 -0.013R), so the result is driven by the entry signal rather than by the choice of exit

  That is below the 85% floor, so the exit comparison is rerun on the 3853 entry timestamps both variants took: native -0.018R/trade over 4860 completed trades vs forced 1:3 -0.018R/trade over 4505. Exit-death on that shared subset: **no**.

**4H.** The two variants share **85.4%** of their entry timestamps. Exit-death: **yes** - the exit flips the sign of the edge: native -0.042R per trade vs forced 1:3 +0.009R. Identical entries, so the entry signal is not what decided this - the native exit is. The edge, such as it is, lives in the forced 1:3 exit.

**1D.** The two variants share **99.1%** of their entry timestamps. Exit-death: **no** - the two exits land within 0.096R per trade of each other (native -0.060R vs forced 1:3 -0.157R), so the result is driven by the entry signal rather than by the choice of exit

**Exit composition.**

| Timeframe | Exit | Exit reasons | Avg bars held | Avg fee cost R |
|---|---|---|---:|---:|
| 1H | native | rsi_reversion: 4993, stop: 1796 | 4.0 | 0.055 |
| 1H | forced-1:3 | stop: 2569, target: 651, time: 1480 | 15.8 | 0.055 |
| 4H | native | rsi_reversion: 1042, stop: 1041 | 2.6 | 0.055 |
| 4H | forced-1:3 | stop: 1274, target: 435, time: 98 | 6.6 | 0.055 |
| 1D | native | rsi_reversion: 112, stop: 312 | 1.1 | 0.055 |
| 1D | forced-1:3 | stop: 328, target: 95 | 1.1 | 0.055 |

### 9. Funding
Funding is not modelled in any return above. Settlements land every 8 hours on this venue, so holding time is the cost exposure:

| Timeframe | Exit | Avg bars held | Avg holding hours | Est. settlements/trade | Est. funding R/trade @ 0.01%/8h |
|---|---|---:|---:|---:|---:|
| 1H | native | 4.0 | 4.0 | 0.49 | 0.002 |
| 1H | forced-1:3 | 15.8 | 15.8 | 1.98 | 0.010 |
| 4H | native | 2.6 | 10.3 | 1.28 | 0.006 |
| 4H | forced-1:3 | 6.6 | 26.5 | 3.32 | 0.017 |
| 1D | native | 1.1 | 25.9 | 3.24 | 0.016 |
| 1D | forced-1:3 | 1.1 | 26.8 | 3.35 | 0.017 |

The base rate used for that estimate is **0.010% per 8-hour settlement**, an assumed mid-range figure for this venue rather than a rate measured from the data. Position size is 50% of equity because 1% is risked against a 2% stop, which is what converts a percentage settlement into risk units.

KEEP survival assessment: some cells are already profitable after fees, so funding is the difference between a marginal edge and none at all - it would erode any cell that cleared the discard bar on fees alone. Funding is unmodelled, so no verdict in this report is a claim that an edge survives carry costs, and this strategy holds shorts as well as longs, whose true cost is not captured by the fee column alone.

### 10. Parameter sensitivity
Every declared variant, favourable or not. The headline is stop 2% / entry 10/90; nothing here selects or replaces it.

| Variant | Timeframe | Exit | Trades | Win% | R post-fee | R/trade | Sharpe | Verdict |
|---|---|---|---:|---:|---:|---:|---:|---|
| stop 1% | 1H | native | 8227 | 47.8 | -705.7 | -0.086 | -2.20 | DISCARD |
| stop 1% | 1H | forced-1:3 | 6991 | 28.7 | -469.4 | -0.067 | -1.06 | DISCARD |
| stop 1% | 4H | native | 2567 | 31.8 | -276.9 | -0.108 | -0.97 | DISCARD |
| stop 1% | 4H | forced-1:3 | 2501 | 24.8 | -310.8 | -0.124 | -1.14 | DISCARD |
| stop 1% | 1D | native | 464 | 15.7 | -41.7 | -0.090 | -0.27 | DISCARD |
| stop 1% | 1D | forced-1:3 | 464 | 20.3 | -139.0 | -0.300 | -1.51 | DISCARD |
| stop 2% | 1H | native | 6789 | 58.7 | -247.3 | -0.036 | -1.36 | DISCARD |
| stop 2% | 1H | forced-1:3 | 4700 | 36.5 | -62.2 | -0.013 | -0.20 | DISCARD |
| stop 2% | 4H | native | 2083 | 47.6 | -87.4 | -0.042 | -0.50 | DISCARD |
| stop 2% | 4H | forced-1:3 | 1807 | 28.7 | 15.8 | 0.009 | 0.07 | DISCARD |
| stop 2% | 1D | native | 424 | 26.4 | -25.6 | -0.060 | -0.24 | DISCARD |
| stop 2% | 1D | forced-1:3 | 423 | 22.5 | -66.3 | -0.157 | -0.74 | DISCARD |
| stop 3% | 1H | native | 6230 | 61.4 | -134.2 | -0.022 | -1.05 | DISCARD |
| stop 3% | 1H | forced-1:3 | 3890 | 42.3 | -15.3 | -0.004 | -0.07 | DISCARD |
| stop 3% | 4H | native | 1825 | 57.5 | 5.7 | 0.003 | 0.05 | DISCARD |
| stop 3% | 4H | forced-1:3 | 1386 | 33.3 | 68.6 | 0.050 | 0.39 | INCONCLUSIVE |
| stop 3% | 1D | native | 379 | 36.4 | 2.6 | 0.007 | 0.03 | DISCARD |
| stop 3% | 1D | forced-1:3 | 364 | 25.8 | -3.8 | -0.010 | -0.04 | DISCARD |
| entry 5/95 | 1H | native | 3332 | 59.9 | -86.6 | -0.026 | -0.68 | DISCARD |
| entry 5/95 | 1H | forced-1:3 | 2818 | 37.4 | 6.5 | 0.002 | 0.03 | DISCARD |
| entry 5/95 | 4H | native | 1034 | 46.0 | -49.8 | -0.048 | -0.42 | DISCARD |
| entry 5/95 | 4H | forced-1:3 | 967 | 27.5 | -36.9 | -0.038 | -0.24 | DISCARD |
| entry 5/95 | 1D | native | 202 | 27.2 | -7.5 | -0.037 | -0.11 | DISCARD |
| entry 5/95 | 1D | forced-1:3 | 202 | 21.8 | -37.1 | -0.184 | -0.62 | DISCARD |
| entry 10/90 | 1H | native | 6789 | 58.7 | -247.3 | -0.036 | -1.36 | DISCARD |
| entry 10/90 | 1H | forced-1:3 | 4700 | 36.5 | -62.2 | -0.013 | -0.20 | DISCARD |
| entry 10/90 | 4H | native | 2083 | 47.6 | -87.4 | -0.042 | -0.50 | DISCARD |
| entry 10/90 | 4H | forced-1:3 | 1807 | 28.7 | 15.8 | 0.009 | 0.07 | DISCARD |
| entry 10/90 | 1D | native | 424 | 26.4 | -25.6 | -0.060 | -0.24 | DISCARD |
| entry 10/90 | 1D | forced-1:3 | 423 | 22.5 | -66.3 | -0.157 | -0.74 | DISCARD |
| entry 15/85 | 1H | native | 9644 | 58.9 | -400.0 | -0.041 | -1.83 | DISCARD |
| entry 15/85 | 1H | forced-1:3 | 5882 | 36.2 | -49.6 | -0.008 | -0.14 | DISCARD |
| entry 15/85 | 4H | native | 2993 | 47.2 | -194.8 | -0.065 | -0.95 | DISCARD |
| entry 15/85 | 4H | forced-1:3 | 2445 | 27.4 | -63.1 | -0.026 | -0.24 | DISCARD |
| entry 15/85 | 1D | native | 645 | 27.8 | -29.3 | -0.045 | -0.22 | DISCARD |
| entry 15/85 | 1D | forced-1:3 | 636 | 23.9 | -63.0 | -0.099 | -0.55 | DISCARD |

### 11. Market conditions
Each cell split by the project's regime convention (trend/volatility, labelled from already-closed bars and used for reporting only, never for decisions).

| Timeframe | Exit | Regime | Trades | Net R | R/trade |
|---|---|---|---:|---:|---:|
| 1H | native | down/highvol | 1227 | +9.47 | +0.008 |
| 1H | native | down/lowvol | 1214 | -20.35 | -0.017 |
| 1H | native | range/highvol | 926 | -186.35 | -0.201 |
| 1H | native | range/lowvol | 1075 | -122.60 | -0.114 |
| 1H | native | up/highvol | 1192 | +72.06 | +0.060 |
| 1H | native | up/lowvol | 1155 | +0.45 | +0.000 |
| 1H | forced-1:3 | down/highvol | 974 | +24.71 | +0.025 |
| 1H | forced-1:3 | down/lowvol | 713 | +16.68 | +0.023 |
| 1H | forced-1:3 | range/highvol | 716 | -108.68 | -0.152 |
| 1H | forced-1:3 | range/lowvol | 699 | -91.92 | -0.132 |
| 1H | forced-1:3 | up/highvol | 904 | +86.40 | +0.096 |
| 1H | forced-1:3 | up/lowvol | 694 | +10.63 | +0.015 |
| 4H | native | down/highvol | 371 | +56.80 | +0.153 |
| 4H | native | down/lowvol | 385 | +11.84 | +0.031 |
| 4H | native | range/highvol | 263 | -63.97 | -0.243 |
| 4H | native | range/lowvol | 372 | -99.96 | -0.269 |
| 4H | native | up/highvol | 394 | +11.11 | +0.028 |
| 4H | native | up/lowvol | 298 | -3.22 | -0.011 |
| 4H | forced-1:3 | down/highvol | 351 | +33.63 | +0.096 |
| 4H | forced-1:3 | down/lowvol | 305 | +62.31 | +0.204 |
| 4H | forced-1:3 | range/highvol | 248 | -42.84 | -0.173 |
| 4H | forced-1:3 | range/lowvol | 306 | -100.34 | -0.328 |
| 4H | forced-1:3 | up/highvol | 367 | +42.00 | +0.114 |
| 4H | forced-1:3 | up/lowvol | 230 | +21.02 | +0.091 |
| 1D | native | down/highvol | 47 | +8.05 | +0.171 |
| 1D | native | down/lowvol | 117 | -16.43 | -0.140 |
| 1D | native | range/highvol | 43 | +3.52 | +0.082 |
| 1D | native | range/lowvol | 78 | -12.82 | -0.164 |
| 1D | native | up/highvol | 78 | -19.90 | -0.255 |
| 1D | native | up/lowvol | 61 | +11.96 | +0.196 |
| 1D | forced-1:3 | down/highvol | 47 | +2.43 | +0.052 |
| 1D | forced-1:3 | down/lowvol | 115 | -33.33 | -0.290 |
| 1D | forced-1:3 | range/highvol | 43 | -17.36 | -0.404 |
| 1D | forced-1:3 | range/lowvol | 78 | -10.29 | -0.132 |
| 1D | forced-1:3 | up/highvol | 78 | -22.28 | -0.286 |
| 1D | forced-1:3 | up/lowvol | 62 | +14.58 | +0.235 |

### 12. Source comparison
The approved specification supplies no source performance numbers to reproduce, so there is no claimed return, win rate or Sharpe to check these results against. The measured numbers are those in section 4, and the honest statement is that no source comparison is available for this rule as tested.

### 13. Discard-bar verdicts
Every cell is scored against the same fixed bar, applied after fees:

| Timeframe | Exit | Verdict | Criteria met or missed |
|---|---|---|---|
| 1H | native | **DISCARD** | post-fee expectancy -0.036R per trade is not positive; post-fee Sharpe -1.36 below 0.3; earned only -0.93x its worst drawdown.
| 1H | forced-1:3 | **DISCARD** | post-fee expectancy -0.013R per trade is not positive; post-fee Sharpe -0.20 below 0.3; earned only -0.49x its worst drawdown. A 1:3 exit needs 26.4% wins just to cover its own fee bill; this cell measured 36.5%.
| 4H | native | **DISCARD** | post-fee expectancy -0.042R per trade is not positive; post-fee Sharpe -0.50 below 0.3; earned only -0.65x its worst drawdown.
| 4H | forced-1:3 | **DISCARD** | post-fee Sharpe 0.07 below 0.3; earned only 0.14x its worst drawdown. A 1:3 exit needs 26.4% wins just to cover its own fee bill; this cell measured 28.7%.
| 1D | native | **DISCARD** | post-fee expectancy -0.060R per trade is not positive; post-fee Sharpe -0.24 below 0.3; earned only -0.44x its worst drawdown.
| 1D | forced-1:3 | **DISCARD** | post-fee expectancy -0.157R per trade is not positive; post-fee Sharpe -0.74 below 0.3; earned only -0.83x its worst drawdown. A 1:3 exit needs 26.4% wins just to cover its own fee bill; this cell measured 22.5%.

```
Gate: fewer than 30 trades -> INCONCLUSIVE.
KEEP needs all of: post-fee expectancy >= +0.10R per trade; post-fee Sharpe >= 0.7; total R >= 1.5x worst R drawdown; and (forced-1:3) win rate >= its own fee breakeven (1+c)/4 plus 2%, or (native) achieved RR >= 1.5:1.
DISCARD on any of: post-fee expectancy <= +0.00R; post-fee Sharpe < 0.3; total R < 0.5x worst R drawdown.
Anything in between -> INCONCLUSIVE.
```

### 14. Bottom line
Across 3 timeframes x 2 exits (6 cells) the discard bar returns **6x DISCARD**. 4 of 6 cells are profitable before fees, so the entry signal does carry a measurable mean-reversion tendency - but after 0.055% per side against a 2% stop it does not survive as an executable edge on this universe. What would change a verdict: a longer or different sample that lifts a cell's post-fee expectancy past the KEEP bar rather than merely past zero; a validated funding and slippage model rather than an unmodelled one; and out-of-sample confirmation. Nothing here is a live-trading recommendation, and no sweep result was used to reselect the headline.

### 15. Files changed
- `strategy_log.csv`: 67 -> 73 lines (+6 rows, one per timeframe x exit; sweeps add no rows).
- `strategy_log.md`: 5125 -> 5367 lines (+242, this report as one appended section).
- `src/s10_rsi2.py` and `src/run_s10.py`: the strategy and its runner, already on disk.
- Nothing is deleted and no earlier strategy's entry is rewritten; both logs are append-only.

---

## Strategy #11 — MACD Crossover (Gerald Appel, 1979)

**Tested:** 2026-09-27 · **Coins:** BTCUSDT+SOLUSDT+XRPUSDT · **Timeframes:** 1H, 4H, 1D · **Direction:** long and short

### 1. Rule and source
MACD line = 12-EMA − 26-EMA; signal = 9-EMA of the MACD line (standard exponential smoothing, alpha = 2/(span+1), `adjust=False`). On a closed bar t: **long** if the MACD line crosses above the signal line (MACD > signal now, MACD <= signal on the prior bar) AND close[t] > 200-SMA[t]; **short** on the mirror cross below with close[t] < 200-SMA. Entry fills at bar t+1 open. The initial stop is 2 x ATR(14, Wilder) measured as a fraction of the signal bar's close and resolved against the actual next-open fill price, which defines 1R. **Native exit:** close a long when MACD crosses back below the signal line, a short when it crosses back above, filled at the next open; the stop stays armed throughout; no take-profit, no pyramiding, at most one position per coin per timeframe. **Forced-1:3 variant:** identical entries and identical 1R with a 1R stop, 3R target and 30-bar time limit under the shared engine conventions (stop wins intrabar ties, a bar gapping through the stop fills at the open, a trade still open at the end of the data is discarded rather than marked to the last close).

**Provenance:** Gerald Appel, *The Moving Average Convergence-Divergence Trading Method* (1979) - the original source for the indicator and the 12/26/9 parameters. The source describes MACD/signal crossovers on stock data with no universal stop and no crypto-specific exit, so the 2 x ATR(14) stop, the 200-SMA trend filter and the crypto perp execution are this test's declared adaptations, not source canon. No source performance claim is assumed or reproduced.

### 2. Placeholders and adaptations
- MACD 12/26/9: canonical Appel parameters, applied unmodified; EMA smoothing is the standard `span` convention (alpha = 2/(span+1), `adjust=False`).
- Trend filter: a contemporaneous, unshifted 200-bar close SMA - a project addition to keep entries on the side of the longer trend, not a source parameter.
- Initial stop: 2 x ATR(14) (Wilder SMA of true range) as a fraction of the signal bar's close, resolved against the actual next-open fill. A project extrapolation; the source defines no stop.
- Warmup: 250 bars on every timeframe (SMA200 needs 200; margin for EMA/ATR settle-in), applied identically to the headline and every sweep.
- Execution: closed-bar decision and next-open fill; taker 0.055% each side; 1% of starting equity risked per trade, never compounded; one position per coin per timeframe; both long and short traded.
- The forced 30-bar limit is the project's shared unvalidated convention.
- Funding and slippage are not modelled (section 9).
- Independent sweeps, each a fresh run that never replaces the headline: stop 1.5x/2.5x ATR, MACD 8/21 (signal 9 fixed), SMA filter 100 and 300.

### 3. Lookahead-bias audit
The engine's standing rules: a decision on a closed bar fills at the next bar's open, and the stop wins every intrabar tie. Three specific traps checked here: (a) the MACD/signal EMAs are recursive but causal - proven by the end-truncation audit below; (b) a crossover needs the PREVIOUS bar's MACD/signal values, which are also closed-bar reads; (c) the ATR stop distance is captured from the signal bar and only translated to the actual fill price at the next open, so the fill bar's range never touches the stop level. The regime columns used in section 11 are computed from already-closed bars and are never consulted by any decision.

| Dataset | Columns checked | Result |
|---|---|---|
| BTCUSDT 1D | macd_line, macd_signal, sma200, atr | PASS |
| BTCUSDT 1H | macd_line, macd_signal, sma200, atr | PASS |
| BTCUSDT 4H | macd_line, macd_signal, sma200, atr | PASS |
| SOLUSDT 1D | macd_line, macd_signal, sma200, atr | PASS |
| SOLUSDT 1H | macd_line, macd_signal, sma200, atr | PASS |
| SOLUSDT 4H | macd_line, macd_signal, sma200, atr | PASS |
| XRPUSDT 1D | macd_line, macd_signal, sma200, atr | PASS |
| XRPUSDT 1H | macd_line, macd_signal, sma200, atr | PASS |
| XRPUSDT 4H | macd_line, macd_signal, sma200, atr | PASS |

**9 of 9 datasets passed.** Each indicator value at every cut bar (25 cut points per dataset, all past the 250-bar warmup) was identical computed on truncated history and on full history.

Beyond the indicator audit, every completed trade was re-derived from the data: 12175 trades checked; the fill bar had a qualifying same-direction signal on the immediately preceding closed bar in all but 0 cases; the stop sat on the wrong side of the fill in 0 trades; 152 trades exited before entering. First-bar resolutions (where the intrabar tie-break, not the strategy, decides):

- 1H: native 0.0%, forced-1:3 3.0%
- 4H: native 0.0%, forced-1:3 3.1%
- 1D: native 0.0%, forced-1:3 2.1%

### 4. Results table
Coins are pooled inside each timeframe; timeframes are never pooled with each other. All money figures are post-fee; the pre-fee total is shown alongside.

| Timeframe | Exit type | Trades | Days of history per coin (BTC/SOL/XRP) | Win% | Reward:risk achieved | Pre-fee total R | Post-fee total R | R/trade | Sharpe | Max drawdown % | Max DD R | Verdict |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1H | native | 5555 | BTC 2344d / SOL 1776d / XRP 1930d | 31.8 | 2.21 | 490.0 | 78.0 | 0.014 | 0.21 | 48.0 | 123.7 | **DISCARD** |
| 1H | forced-1:3 | 3971 | BTC 2344d / SOL 1776d / XRP 1930d | 36.3 | 1.80 | 358.1 | 68.1 | 0.017 | 0.24 | 40.1 | 72.0 | **DISCARD** |
| 4H | native | 1359 | BTC 2313d / SOL 1744d / XRP 1899d | 32.0 | 2.57 | 168.4 | 124.2 | 0.091 | 0.65 | 24.0 | 36.1 | **INCONCLUSIVE** |
| 4H | forced-1:3 | 958 | BTC 2313d / SOL 1744d / XRP 1899d | 37.5 | 1.80 | 76.0 | 45.3 | 0.047 | 0.34 | 20.0 | 31.7 | **INCONCLUSIVE** |
| 1D | native | 187 | BTC 2105d / SOL 1536d / XRP 1691d | 33.7 | 4.15 | 83.5 | 81.1 | 0.434 | 0.62 | 8.6 | 15.4 | **INCONCLUSIVE** |
| 1D | forced-1:3 | 145 | BTC 2105d / SOL 1536d / XRP 1691d | 38.6 | 1.89 | 18.6 | 16.8 | 0.116 | 0.37 | 10.3 | 12.2 | **INCONCLUSIVE** |

Shortest window in this run: Shortest window in this run: SOLUSDT at 1D, 1536 days (4.21 years). Longest: BTCUSDT at 1H, 2344 days (6.42 years).

### 5. Statistical significance
t is each cell's mean per-trade R divided by its own standard error (the same hand-rolled statistic every other strategy uses); roughly 2.0 is the noise threshold, and a negative result needs no such defence.

| Timeframe | Exit | Trades | Pre-fee R/trade | t pre-fee | Post-fee R/trade | t post-fee | vs ~2.0 |
|---|---|---:|---:|---:|---:|---:|---|
| 1H | native | 5555 | +0.0882 | +4.18 | +0.0140 | +0.67 | inside the range chance produces |
| 1H | forced-1:3 | 3971 | +0.0902 | +3.78 | +0.0172 | +0.72 | inside the range chance produces |
| 4H | native | 1359 | +0.1239 | +2.54 | +0.0914 | +1.87 | inside the range chance produces |
| 4H | forced-1:3 | 958 | +0.0793 | +1.67 | +0.0473 | +1.00 | inside the range chance produces |
| 1D | native | 187 | +0.4463 | +1.54 | +0.4338 | +1.49 | inside the range chance produces |
| 1D | forced-1:3 | 145 | +0.1282 | +0.99 | +0.1161 | +0.90 | inside the range chance produces |

### 6. Concentration
How much of each cell's total R rests on one trade and on the best five. A negative total makes the percentage shares directionally meaningless, so read them alongside Total R.

| Timeframe | Exit | Trades | Total R | Best trade | Best 5 as % of total | Total R ex-best-5 | Profitable ex-best-5? |
|---|---|---:|---:|---:|---:|---:|---|
| 1H | native | 5555 | +78.01 | +19.59 | 113.9 | -10.87 | no |
| 1H | forced-1:3 | 3971 | +68.13 | +2.99 | 21.9 | +53.20 | yes |
| 4H | native | 1359 | +124.20 | +24.46 | 68.5 | +39.06 | yes |
| 4H | forced-1:3 | 958 | +45.28 | +2.99 | 33.0 | +30.34 | yes |
| 1D | native | 187 | +81.11 | +49.59 | 98.0 | +1.65 | yes |
| 1D | forced-1:3 | 145 | +16.83 | +2.99 | 88.8 | +1.88 | yes |

### 7. Long/short breakdown
| Timeframe | Exit | Side | Trades | Win% | R post-fee | R/trade |
|---|---|---|---:|---:|---:|---:|
| 1H | native | long | 2682 | 31.1 | +155.38 | +0.058 |
| 1H | native | short | 2873 | 32.4 | -77.37 | -0.027 |
| 1H | forced-1:3 | long | 1894 | 36.2 | +51.56 | +0.027 |
| 1H | forced-1:3 | short | 2077 | 36.4 | +16.57 | +0.008 |
| 4H | native | long | 637 | 32.0 | +142.57 | +0.224 |
| 4H | native | short | 722 | 32.0 | -18.37 | -0.025 |
| 4H | forced-1:3 | long | 453 | 35.3 | +18.58 | +0.041 |
| 4H | forced-1:3 | short | 505 | 39.4 | +26.70 | +0.053 |
| 1D | native | long | 93 | 32.3 | +67.25 | +0.723 |
| 1D | native | short | 94 | 35.1 | +13.86 | +0.147 |
| 1D | forced-1:3 | long | 72 | 37.5 | +13.97 | +0.194 |
| 1D | forced-1:3 | short | 73 | 39.7 | +2.87 | +0.039 |

### 8. Exit-death and overlap
The two exits share one entry rule and one 1R, so any difference between them is attributable to the exit alone. Overlap is the share of entry timestamps they have in common; below 85% the comparison is rerun on shared entries only.

- **1H: overlap 72.5%, exit-death flag: no.** the two exits land within 0.003R per trade of each other (native +0.014R vs forced 1:3 +0.017R), so the result is driven by the entry signal rather than by the choice of exit
  - Below the 85% floor, so the comparison is rerun on the 4149 entries both exits share: native +0.008R/trade (DISCARD, post-fee Sharpe 0.10 below 0.3; earned only 0.42x its worst drawdown); forced-1:3 +0.017R/trade (DISCARD, post-fee Sharpe 0.24 below 0.3). Shared-entries verdicts: DISCARD / DISCARD.
- **4H: overlap 71.6%, exit-death flag: no.** the two exits land within 0.044R per trade of each other (native +0.091R vs forced 1:3 +0.047R), so the result is driven by the entry signal rather than by the choice of exit
  - Below the 85% floor, so the comparison is rerun on the 997 entries both exits share: native +0.086R/trade (INCONCLUSIVE, positive but short of the KEEP bar: expectancy +0.086R < +0.10R; Sharpe 0.51 < 0.7); forced-1:3 +0.048R/trade (INCONCLUSIVE, positive but short of the KEEP bar: expectancy +0.048R < +0.10R; Sharpe 0.35 < 0.7; R-recovery 1.46 < 1.5). Shared-entries verdicts: INCONCLUSIVE / INCONCLUSIVE.
- **1D: overlap 78.8%, exit-death flag: yes.** both exits agree on direction but differ by 0.318R per trade (native +0.434R vs forced 1:3 +0.116R), which is larger than the entire +0.10R KEEP requirement. The native exit is doing more work than the entry signal.
  - Below the 85% floor, so the comparison is rerun on the 150 entries both exits share: native +0.562R/trade (INCONCLUSIVE, positive but short of the KEEP bar: Sharpe 0.65 < 0.7); forced-1:3 +0.116R/trade (INCONCLUSIVE, positive but short of the KEEP bar: Sharpe 0.37 < 0.7; R-recovery 1.38 < 1.5). Shared-entries verdicts: INCONCLUSIVE / INCONCLUSIVE.

**Exit composition.**

| Timeframe | Exit | Exit reasons | Avg bars held | Avg fee cost R |
|---|---|---|---:|---:|
| 1H | native | macd cross above signal: 2873, macd cross below signal: 2682 | 10.5 | 0.074 |
| 1H | forced-1:3 | stop: 2212, target: 640, time: 1119 | 15.9 | 0.073 |
| 4H | native | macd cross above signal: 722, macd cross below signal: 637 | 10.4 | 0.033 |
| 4H | forced-1:3 | stop: 529, target: 140, time: 289 | 16.4 | 0.032 |
| 1D | native | macd cross above signal: 94, macd cross below signal: 93 | 11.5 | 0.012 |
| 1D | forced-1:3 | stop: 86, target: 23, time: 36 | 15.7 | 0.012 |

### 9. Funding disclosure
Funding is not modelled in any return above. Settlements land every 8 hours on this venue, so holding time is the cost exposure. The stop distance varies per trade (2 x ATR), so the position multiple varies with it: notional = 1R / stop fraction, and a percentage settlement converts to R at that multiple.

| Timeframe | Exit | Avg bars held | Avg holding hours | Settlements/trade | Median stop (% of price) | Est. funding R/trade @ base 0.01% |
|---|---|---:|---:|---:|---:|---:|
| 1H | native | 10.5 | 10.5 | 1.3 | 1.79% | 0.007 |
| 1H | forced-1:3 | 15.9 | 15.9 | 2.0 | 1.82% | 0.011 |
| 4H | native | 10.4 | 41.5 | 5.2 | 3.79% | 0.014 |
| 4H | forced-1:3 | 16.4 | 65.4 | 8.2 | 3.87% | 0.021 |
| 1D | native | 11.5 | 275.0 | 34.4 | 9.28% | 0.037 |
| 1D | forced-1:3 | 15.7 | 377.2 | 47.2 | 9.34% | 0.051 |

No cell in this run reaches the KEEP bar on the measured (fee-only) numbers, so no verdict here has a funding bill that can flip it. For the record: at the base rate of 0.01% per 8-hour settlement the estimated funding cost is the last column of the table above per trade - it would erode any future KEEP that spans settlements, and it cannot rescue a losing cell.

### 10. Parameter sensitivity
Every declared variant, favourable or not, run exactly like the headline. The headline is MACD 12/26/9, 200-SMA filter, 2.0x ATR stop; nothing here selects or replaces it. The signal EMA (9) is held fixed per the specification, which declares fast/slow and stop as the swept parameters.

| Variant | Timeframe | Exit | Trades | Win% | R total | R/trade | Sharpe | Verdict |
|---|---|---|---:|---:|---:|---:|---:|---|
| native | 1H | native | 5555 | 31.8 | 78.0 | 0.014 | 0.21 | **DISCARD** |
| forced-1:3 | 1H | forced-1:3 | 3971 | 36.3 | 68.1 | 0.017 | 0.24 | **DISCARD** |
| native | 4H | native | 1359 | 32.0 | 124.2 | 0.091 | 0.65 | **INCONCLUSIVE** |
| forced-1:3 | 4H | forced-1:3 | 958 | 37.5 | 45.3 | 0.047 | 0.34 | **INCONCLUSIVE** |
| native | 1D | native | 187 | 33.7 | 81.1 | 0.434 | 0.62 | **INCONCLUSIVE** |
| forced-1:3 | 1D | forced-1:3 | 145 | 38.6 | 16.8 | 0.116 | 0.37 | **INCONCLUSIVE** |
| native | 1H | native | 5555 | 31.8 | 104.0 | 0.019 | 0.21 | **DISCARD** |
| forced-1:3 | 1H | forced-1:3 | 4492 | 32.5 | 18.1 | 0.004 | 0.05 | **DISCARD** |
| native | 4H | native | 1359 | 32.0 | 165.6 | 0.122 | 0.65 | **INCONCLUSIVE** |
| forced-1:3 | 4H | forced-1:3 | 1082 | 32.5 | 36.3 | 0.034 | 0.23 | **DISCARD** |
| native | 1D | native | 187 | 33.7 | 108.2 | 0.578 | 0.62 | **INCONCLUSIVE** |
| forced-1:3 | 1D | forced-1:3 | 157 | 35.0 | 22.9 | 0.146 | 0.41 | **INCONCLUSIVE** |
| native | 1H | native | 5555 | 31.8 | 62.4 | 0.011 | 0.21 | **DISCARD** |
| forced-1:3 | 1H | forced-1:3 | 3652 | 39.2 | 70.9 | 0.019 | 0.28 | **DISCARD** |
| native | 4H | native | 1359 | 32.0 | 99.4 | 0.073 | 0.65 | **INCONCLUSIVE** |
| forced-1:3 | 4H | forced-1:3 | 881 | 41.5 | 56.8 | 0.064 | 0.48 | **INCONCLUSIVE** |
| native | 1D | native | 187 | 33.7 | 64.9 | 0.347 | 0.62 | **INCONCLUSIVE** |
| forced-1:3 | 1D | forced-1:3 | 135 | 42.2 | 12.6 | 0.093 | 0.30 | **DISCARD** |
| native | 1H | native | 6888 | 31.8 | -42.6 | -0.006 | -0.12 | **DISCARD** |
| forced-1:3 | 1H | forced-1:3 | 4475 | 37.0 | 96.3 | 0.022 | 0.32 | **INCONCLUSIVE** |
| native | 4H | native | 1624 | 33.6 | 115.0 | 0.071 | 0.65 | **INCONCLUSIVE** |
| forced-1:3 | 4H | forced-1:3 | 1068 | 36.7 | 39.0 | 0.037 | 0.28 | **DISCARD** |
| native | 1D | native | 232 | 36.2 | 53.8 | 0.232 | 0.81 | **KEEP** |
| forced-1:3 | 1D | forced-1:3 | 165 | 33.9 | 1.0 | 0.006 | 0.02 | **DISCARD** |
| native | 1H | native | 5537 | 31.2 | 178.2 | 0.032 | 0.47 | **INCONCLUSIVE** |
| forced-1:3 | 1H | forced-1:3 | 3842 | 35.9 | 66.3 | 0.017 | 0.24 | **DISCARD** |
| native | 4H | native | 1378 | 31.5 | 82.4 | 0.060 | 0.45 | **INCONCLUSIVE** |
| forced-1:3 | 4H | forced-1:3 | 939 | 35.4 | -19.2 | -0.020 | -0.15 | **DISCARD** |
| native | 1D | native | 188 | 32.4 | 14.0 | 0.075 | 0.24 | **DISCARD** |
| forced-1:3 | 1D | forced-1:3 | 138 | 36.2 | -0.5 | -0.003 | -0.01 | **DISCARD** |
| native | 1H | native | 5570 | 31.9 | 17.2 | 0.003 | 0.05 | **DISCARD** |
| forced-1:3 | 1H | forced-1:3 | 4051 | 36.1 | 6.7 | 0.002 | 0.02 | **DISCARD** |
| native | 4H | native | 1379 | 31.9 | 67.0 | 0.049 | 0.37 | **INCONCLUSIVE** |
| forced-1:3 | 4H | forced-1:3 | 990 | 35.9 | 2.3 | 0.002 | 0.02 | **DISCARD** |
| native | 1D | native | 184 | 34.8 | 39.0 | 0.212 | 0.72 | **KEEP** |
| forced-1:3 | 1D | forced-1:3 | 141 | 41.8 | 22.8 | 0.162 | 0.50 | **INCONCLUSIVE** |

### 11. Market conditions
Each cell split by the project's regime convention (trend/volatility, labelled from already-closed bars and used for reporting only, never for decisions). The source's claimed condition is a trending market, entered in the direction of the 200-SMA filter.

| Timeframe | Exit | Regime | Trades | Net R | R/trade |
|---|---|---|---:|---:|---:|
| 1H | native | down/highvol | 963 | +37.84 | +0.039 |
| 1H | native | down/lowvol | 1168 | -47.19 | -0.040 |
| 1H | native | range/highvol | 548 | -58.59 | -0.107 |
| 1H | native | range/lowvol | 787 | -30.53 | -0.039 |
| 1H | native | up/highvol | 899 | +52.32 | +0.058 |
| 1H | native | up/lowvol | 1190 | +124.16 | +0.104 |
| 1H | forced-1:3 | down/highvol | 721 | +37.15 | +0.052 |
| 1H | forced-1:3 | down/lowvol | 801 | +3.26 | +0.004 |
| 1H | forced-1:3 | range/highvol | 418 | -35.42 | -0.085 |
| 1H | forced-1:3 | range/lowvol | 573 | -11.55 | -0.020 |
| 1H | forced-1:3 | up/highvol | 661 | +53.24 | +0.081 |
| 1H | forced-1:3 | up/lowvol | 797 | +21.46 | +0.027 |
| 4H | native | down/highvol | 238 | -24.90 | -0.105 |
| 4H | native | down/lowvol | 335 | +13.34 | +0.040 |
| 4H | native | range/highvol | 94 | -3.47 | -0.037 |
| 4H | native | range/lowvol | 182 | -23.41 | -0.129 |
| 4H | native | up/highvol | 228 | +60.41 | +0.265 |
| 4H | native | up/lowvol | 282 | +102.23 | +0.363 |
| 4H | forced-1:3 | down/highvol | 170 | +6.71 | +0.039 |
| 4H | forced-1:3 | down/lowvol | 212 | +16.66 | +0.079 |
| 4H | forced-1:3 | range/highvol | 77 | -3.01 | -0.039 |
| 4H | forced-1:3 | range/lowvol | 143 | -12.45 | -0.087 |
| 4H | forced-1:3 | up/highvol | 177 | +25.49 | +0.144 |
| 4H | forced-1:3 | up/lowvol | 179 | +11.87 | +0.066 |
| 1D | native | down/highvol | 28 | -2.80 | -0.100 |
| 1D | native | down/lowvol | 52 | +60.04 | +1.155 |
| 1D | native | range/highvol | 11 | -3.86 | -0.351 |
| 1D | native | range/lowvol | 25 | +5.39 | +0.216 |
| 1D | native | up/highvol | 23 | +5.84 | +0.254 |
| 1D | native | up/lowvol | 48 | +16.51 | +0.344 |
| 1D | forced-1:3 | down/highvol | 23 | -1.61 | -0.070 |
| 1D | forced-1:3 | down/lowvol | 40 | -1.42 | -0.035 |
| 1D | forced-1:3 | range/highvol | 10 | -4.30 | -0.430 |
| 1D | forced-1:3 | range/lowvol | 19 | +11.08 | +0.583 |
| 1D | forced-1:3 | up/highvol | 17 | +8.75 | +0.515 |
| 1D | forced-1:3 | up/lowvol | 36 | +4.34 | +0.121 |

### 12. Source comparison
The source is the original inventor's 1979 booklet, which specifies MACD 12/26/9 with signal-line crossovers and makes qualitative claims - that MACD times trend changes and that signal-line crosses catch them early. It publishes no win rate, no reward-to-risk ratio, no Sharpe, and no drawdown figures, and it predates crypto, fees of 0.055% per side, and perp funding entirely. So there is no claimed performance number to reproduce; the only testable source claim is directional. Section 11 checks it: crossover entries do trade with the declared trend (the 200-SMA filter enforces that by construction), and the question this report answers is whether the edge survives costs on this universe - the source gives no basis for any stronger comparison. Sourcing strength: primary and original for the rule, silent on everything this project measures.

### 13. Discard-bar verdicts
Every cell is scored against the same fixed bar, applied after fees:

| Timeframe | Exit | Verdict | Criteria met or missed |
|---|---|---|---|
| 1H | native | **DISCARD** | post-fee Sharpe 0.21 below 0.3. |
| 1H | forced-1:3 | **DISCARD** | post-fee Sharpe 0.24 below 0.3. A 1:3 exit needs 26.8% wins just to cover its own fee bill; this cell measured 36.3%. |
| 4H | native | **INCONCLUSIVE** | positive but short of the KEEP bar: expectancy +0.091R < +0.10R; Sharpe 0.65 < 0.7. |
| 4H | forced-1:3 | **INCONCLUSIVE** | positive but short of the KEEP bar: expectancy +0.047R < +0.10R; Sharpe 0.34 < 0.7; R-recovery 1.43 < 1.5. A 1:3 exit needs 25.8% wins just to cover its own fee bill; this cell measured 37.5%. |
| 1D | native | **INCONCLUSIVE** | positive but short of the KEEP bar: Sharpe 0.62 < 0.7. |
| 1D | forced-1:3 | **INCONCLUSIVE** | positive but short of the KEEP bar: Sharpe 0.37 < 0.7; R-recovery 1.38 < 1.5. A 1:3 exit needs 25.3% wins just to cover its own fee bill; this cell measured 38.6%. |

```
Gate: fewer than 30 trades -> INCONCLUSIVE.
KEEP needs all of: post-fee expectancy >= +0.10R per trade; post-fee Sharpe >= 0.7; total R >= 1.5x worst R drawdown; and (forced-1:3) win rate >= its own fee breakeven (1+c)/4 plus 2%, or (native) achieved RR >= 1.5:1.
DISCARD on any of: post-fee expectancy <= +0.00R; post-fee Sharpe < 0.3; total R < 0.5x worst R drawdown.
Anything in between -> INCONCLUSIVE.
```

### 14. Bottom line
Across 3 timeframes x 2 exits (6 cells) the discard bar returns **4x INCONCLUSIVE, 2x DISCARD**. What would change a verdict: a longer or different sample that lifts a cell's post-fee expectancy past the KEEP bar rather than merely past zero; a validated funding and slippage model rather than an unmodelled one; and out-of-sample confirmation. Nothing here is a live-trading recommendation, and no sweep result was used to reselect the headline.

### 15. Files changed
- `strategy_log.csv`: 73 -> 79 lines (+6 rows, one per timeframe x exit; sweeps add no rows).
- `strategy_log.md`: 5367 -> 5616 lines (+249, this report as one appended section).
- This is a RE-DO of Strategy #11: the earlier five-section stub (logged 2026-09-26 at strategy_log.md lines 5368-5446 and strategy_log.csv rows 74-79) was removed and replaced by this complete report. Strategies #1-#10 are byte-for-byte untouched, and the front-page master verdict index is left as last written for strategies #1-#8.
- `src/s11_macd_crossover.py` and `src/run_s11.py`: the strategy and its runner, already on disk; the runner no longer needs scipy.
- The `master verdict index` front matter was last updated at Strategy #8 and is left untouched, consistent with how #9 and #10 were logged.

---

## Strategy #12 - Parabolic SAR Reversal (J. Welles Wilder Jr., 1978)

**Tested:** 2026-09-27 · **Coins:** BTCUSDT+SOLUSDT+XRPUSDT · **Timeframes:** 1H, 4H, 1D · **Direction:** long and short

### 1. Rule and source
The Parabolic Time/Price System (Wilder 1978). The SAR (stop-and-reverse) level ratchets toward price as a trend extends: SAR = prior SAR + AF x (EP - SAR), where EP is the running extreme of the current trend and AF starts at the step (0.02), rises 0.02 per new extreme, and is capped at 0.20. On a closed bar t: **long** if close[t] crosses above the active SAR (close > SAR[t], close <= SAR on the prior bar); **short** on the mirror cross below. Entry fills at bar t+1 open. **Initial stop:** the signal bar's active SAR, an absolute level that defines 1R against the actual fill price. **Native exit:** the SAR itself - a bar that trades through the SAR stops the trade at the SAR (or at the open if the bar gapped through), and a close on the wrong side of the SAR closes the trade at the next open; no take-profit. **Forced-1:3 variant:** identical entries and identical 1R with a 1R stop, 3R target and 30-bar time limit under the shared engine conventions (stop wins intrabar ties, a trade still open at the end of the data is discarded rather than marked to the last close).

**Initialization (spec section 2):** direction seeded from the first two closed bars (close[1] vs close[0]); initial SAR at the opposite extreme of those two bars, EP at the trend extreme, AF at the step; long SAR clamped below the prior two lows, short SAR above the prior two highs; the seed uses only bars 0-1 and is never backfilled from the full sample.

**Provenance:** J. Welles Wilder Jr., *New Concepts in Technical Trading Systems* (1978), Parabolic Time/Price System - the original source for the indicator and the 0.02/0.02/0.20 parameters. The source's system is stop-and-REVERSE (always in the market); this test requires a fresh close-cross to enter and otherwise stands flat, which is a declared adaptation. No source performance claim is assumed or reproduced.

### 2. Placeholders and adaptations
- AF step 0.02, increment 0.02, max 0.20: canonical Wilder values, applied unmodified (sweeps in section 10).
- Entry requires a fresh close-vs-SAR cross rather than continuous reversal positioning; the reversal leg of the source system executes at the next open under the shared engine, never same-bar (spec section 6).
- Initial stop: the signal bar's active SAR as an absolute price level, resolved against the actual next-open fill. This is source-native (the SAR is the system's stop), not an extrapolation; the 1R risk convention is project scaffolding.
- Warmup: 250 bars on every timeframe (the SAR seed needs only 3 bars, but the shared warmup keeps every strategy comparable), applied identically to the headline and every sweep.
- Execution: closed-bar decision and next-open fill; taker 0.055% each side; 1% of starting equity risked per trade, never compounded; one position per coin per timeframe; both long and short traded.
- The forced 30-bar limit is the project's shared unvalidated convention.
- Funding and slippage are not modelled (section 9).
- Independent sweeps, each a fresh run that never replaces the headline: step 0.01/0.03 (max 0.20 fixed), max AF 0.10/0.30 (step 0.02 fixed).

### 3. Lookahead-bias audit
The engine's standing rules: a decision on a closed bar fills at the next bar's open, and the stop wins every intrabar tie. Three specific traps checked here: (a) the SAR is recursive but causal - every bar's value is a function of closed bars only, seeded from the first two bars and never backfilled - proven by the end-truncation audit below; (b) a fresh cross needs the PREVIOUS bar's SAR and close, both closed-bar reads, and a bar's own high/low updates EP/AF only after that bar closes, so every value a decision reads was knowable when the bar closed; (c) the SAR stop level is captured from the signal bar and translated to the actual fill price at the next open, so the fill bar's range never touches the stop level. The regime columns used in section 11 are computed from already-closed bars and are never consulted by any decision.

| Dataset | Columns checked | Result |
|---|---|---|
| BTCUSDT 1D | sar, sar_stop, sar_valid, sar_dir | PASS |
| BTCUSDT 1H | sar, sar_stop, sar_valid, sar_dir | PASS |
| BTCUSDT 4H | sar, sar_stop, sar_valid, sar_dir | PASS |
| SOLUSDT 1D | sar, sar_stop, sar_valid, sar_dir | PASS |
| SOLUSDT 1H | sar, sar_stop, sar_valid, sar_dir | PASS |
| SOLUSDT 4H | sar, sar_stop, sar_valid, sar_dir | PASS |
| XRPUSDT 1D | sar, sar_stop, sar_valid, sar_dir | PASS |
| XRPUSDT 1H | sar, sar_stop, sar_valid, sar_dir | PASS |
| XRPUSDT 4H | sar, sar_stop, sar_valid, sar_dir | PASS |

**9 of 9 datasets passed.** Each indicator value at every cut bar (25 cut points per dataset, all past the 250-bar warmup) was identical computed on truncated history and on full history.

Beyond the indicator audit, every completed trade was re-derived from the data: 21494 trades checked; the fill bar had a qualifying same-direction SAR cross on the immediately preceding closed bar in all but 0 cases; the stop sat on the wrong side of the fill in 0 trades; 714 trades exited before entering. First-bar resolutions (where the intrabar tie-break, not the strategy, decides):

- 1H: native 3.2%, forced-1:3 3.8%
- 4H: native 2.9%, forced-1:3 3.8%
- 1D: native 2.2%, forced-1:3 4.2%

### 4. Results table
Coins are pooled inside each timeframe; timeframes are never pooled with each other. All money figures are post-fee; the pre-fee total is shown alongside.

| Timeframe | Exit type | Trades | Days of history per coin (BTC/SOL/XRP) | Win% | Reward:risk achieved | Pre-fee total R | Post-fee total R | R/trade | Sharpe | Max drawdown % | Max DD R | Verdict |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1H | native | 11303 | BTC 2344d / SOL 1776d / XRP 1930d | 35.2 | 1.88 | 897.1 | 110.4 | 0.010 | 0.15 | 68.8 | 175.0 | **DISCARD** |
| 1H | forced-1:3 | 5515 | BTC 2344d / SOL 1776d / XRP 1930d | 38.7 | 1.50 | 226.1 | -163.3 | -0.030 | -0.59 | 174.6 | 195.1 | **DISCARD** |
| 4H | native | 2752 | BTC 2313d / SOL 1744d / XRP 1899d | 37.8 | 1.80 | 196.0 | 101.2 | 0.037 | 0.49 | 36.3 | 54.3 | **INCONCLUSIVE** |
| 4H | forced-1:3 | 1332 | BTC 2313d / SOL 1744d / XRP 1899d | 38.3 | 1.59 | 36.4 | -11.1 | -0.008 | -0.08 | 46.1 | 66.7 | **DISCARD** |
| 1D | native | 401 | BTC 2105d / SOL 1536d / XRP 1691d | 37.7 | 2.25 | 57.3 | 52.7 | 0.132 | 0.59 | 12.6 | 17.7 | **INCONCLUSIVE** |
| 1D | forced-1:3 | 191 | BTC 2105d / SOL 1536d / XRP 1691d | 41.4 | 1.51 | 8.6 | 6.4 | 0.034 | 0.15 | 24.4 | 25.0 | **DISCARD** |

Shortest window in this run: Shortest window in this run: SOLUSDT at 1D, 1536 days (4.21 years). Longest: BTCUSDT at 1H, 2344 days (6.42 years).

### 5. Statistical significance
t is each cell's mean per-trade R divided by its own standard error (the same hand-rolled statistic every other strategy uses); roughly 2.0 is the noise threshold, and a negative result needs no such defence.

| Timeframe | Exit | Trades | Pre-fee R/trade | t pre-fee | Post-fee R/trade | t post-fee | vs ~2.0 |
|---|---|---:|---:|---:|---:|---:|---|
| 1H | native | 11303 | +0.0794 | +3.38 | +0.0098 | +0.42 | inside the range chance produces |
| 1H | forced-1:3 | 5515 | +0.0410 | +2.29 | -0.0296 | -1.64 | inside the range chance produces |
| 4H | native | 2752 | +0.0712 | +2.57 | +0.0368 | +1.35 | inside the range chance produces |
| 4H | forced-1:3 | 1332 | +0.0274 | +0.76 | -0.0083 | -0.23 | inside the range chance produces |
| 1D | native | 401 | +0.1430 | +1.50 | +0.1315 | +1.38 | inside the range chance produces |
| 1D | forced-1:3 | 191 | +0.0449 | +0.48 | +0.0338 | +0.36 | inside the range chance produces |

### 6. Concentration
How much of each cell's total R rests on one trade and on the best five. A negative total makes the percentage shares directionally meaningless, so read them alongside Total R.

| Timeframe | Exit | Trades | Total R | Best trade | Best 5 as % of total | Total R ex-best-5 | Profitable ex-best-5? |
|---|---|---:|---:|---:|---:|---:|---|
| 1H | native | 11303 | +110.41 | +165.83 | 376.6 | -305.43 | no |
| 1H | forced-1:3 | 5515 | -163.31 | +2.99 | -9.1 | -178.23 | n/a (negative total) |
| 4H | native | 2752 | +101.25 | +29.63 | 85.7 | +14.52 | yes |
| 4H | forced-1:3 | 1332 | -11.10 | +2.99 | -134.7 | -26.04 | n/a (negative total) |
| 1D | native | 401 | +52.74 | +29.72 | 110.7 | -5.66 | no |
| 1D | forced-1:3 | 191 | +6.45 | +2.99 | 232.0 | -8.51 | no |

### 7. Long/short breakdown
| Timeframe | Exit | Side | Trades | Win% | R post-fee | R/trade |
|---|---|---|---:|---:|---:|---:|
| 1H | native | long | 5652 | 35.2 | +328.62 | +0.058 |
| 1H | native | short | 5651 | 35.3 | -218.22 | -0.039 |
| 1H | forced-1:3 | long | 2739 | 38.9 | -91.00 | -0.033 |
| 1H | forced-1:3 | short | 2776 | 38.4 | -72.30 | -0.026 |
| 4H | native | long | 1375 | 38.0 | +112.47 | +0.082 |
| 4H | native | short | 1377 | 37.5 | -11.22 | -0.008 |
| 4H | forced-1:3 | long | 682 | 38.6 | +11.61 | +0.017 |
| 4H | forced-1:3 | short | 650 | 38.0 | -22.70 | -0.035 |
| 1D | native | long | 201 | 38.3 | +55.91 | +0.278 |
| 1D | native | short | 200 | 37.0 | -3.18 | -0.016 |
| 1D | forced-1:3 | long | 103 | 38.8 | +7.99 | +0.078 |
| 1D | forced-1:3 | short | 88 | 44.3 | -1.54 | -0.018 |

### 8. Exit-death and overlap
The two exits share one entry rule and one 1R, so any difference between them is attributable to the exit alone. Overlap is the share of entry timestamps they have in common; below 85% the comparison is rerun on shared entries only.

- **1H: overlap 52.5%, exit-death flag: yes.** the exit flips the sign of the edge: native +0.010R per trade vs forced 1:3 -0.030R. Identical entries, so the entry signal is not what decided this - the forced 1:3 exit is. The edge, such as it is, lives in the native exit.
  - Below the 85% floor, so the comparison is rerun on the 6373 entries both exits share: native +0.045R/trade (INCONCLUSIVE, positive but short of the KEEP bar: expectancy +0.045R < +0.10R; Sharpe 0.43 < 0.7); forced-1:3 -0.030R/trade (DISCARD, post-fee expectancy -0.030R per trade is not positive; post-fee Sharpe -0.59 below 0.3; earned only -0.84x its worst drawdown). Shared-entries verdicts: INCONCLUSIVE / DISCARD.
- **4H: overlap 52.2%, exit-death flag: yes.** the exit flips the sign of the edge: native +0.037R per trade vs forced 1:3 -0.008R. Identical entries, so the entry signal is not what decided this - the forced 1:3 exit is. The edge, such as it is, lives in the native exit.
  - Below the 85% floor, so the comparison is rerun on the 1539 entries both exits share: native +0.044R/trade (INCONCLUSIVE, positive but short of the KEEP bar: expectancy +0.044R < +0.10R; Sharpe 0.47 < 0.7); forced-1:3 -0.008R/trade (DISCARD, post-fee expectancy -0.008R per trade is not positive; post-fee Sharpe -0.08 below 0.3; earned only -0.17x its worst drawdown). Shared-entries verdicts: INCONCLUSIVE / DISCARD.
- **1D: overlap 51.2%, exit-death flag: no.** the two exits land within 0.098R per trade of each other (native +0.132R vs forced 1:3 +0.034R), so the result is driven by the entry signal rather than by the choice of exit
  - Below the 85% floor, so the comparison is rerun on the 220 entries both exits share: native +0.188R/trade (INCONCLUSIVE, positive but short of the KEEP bar: Sharpe 0.50 < 0.7); forced-1:3 +0.034R/trade (DISCARD, post-fee Sharpe 0.15 below 0.3; earned only 0.26x its worst drawdown). Shared-entries verdicts: INCONCLUSIVE / DISCARD.

**Exit composition.** The native exit reasons here are the engine's: a bar trading through the SAR is a stop at the SAR; a close on the wrong side of the SAR exits at the next open.

| Timeframe | Exit | Exit reasons | Avg bars held | Avg fee cost R |
|---|---|---|---:|---:|
| 1H | native | stop: 11303 | 11.8 | 0.070 |
| 1H | forced-1:3 | stop: 2637, target: 602, time: 2276 | 18.4 | 0.071 |
| 4H | native | stop: 2752 | 11.9 | 0.034 |
| 4H | forced-1:3 | stop: 642, target: 130, time: 560 | 18.8 | 0.036 |
| 1D | native | stop: 401 | 12.2 | 0.011 |
| 1D | forced-1:3 | stop: 92, target: 18, time: 81 | 19.5 | 0.011 |

### 9. Funding disclosure
Funding is not modelled in any return above. Settlements land every 8 hours on this venue, so holding time is the cost exposure. The stop distance varies per trade with the SAR's distance from price, so the position multiple varies with it: notional = 1R / stop fraction, and a percentage settlement converts to R at that multiple. Early-trend SAR distances can be small, which both raises this exposure and is disclosed by the median stop column.

| Timeframe | Exit | Avg bars held | Avg holding hours | Settlements/trade | Median stop (% of price) | Est. funding R/trade @ base 0.01% |
|---|---|---:|---:|---:|---:|---:|
| 1H | native | 11.8 | 11.8 | 1.5 | 2.13% | 0.007 |
| 1H | forced-1:3 | 18.4 | 18.4 | 2.3 | 2.16% | 0.011 |
| 4H | native | 11.9 | 47.8 | 6.0 | 4.43% | 0.013 |
| 4H | forced-1:3 | 18.8 | 75.1 | 9.4 | 4.48% | 0.021 |
| 1D | native | 12.2 | 292.3 | 36.5 | 12.13% | 0.030 |
| 1D | forced-1:3 | 19.5 | 466.8 | 58.4 | 12.34% | 0.047 |

No cell in this run reaches the KEEP bar on the measured (fee-only) numbers, so no verdict here has a funding bill that can flip it. For the record: at the base rate of 0.01% per 8-hour settlement the estimated funding cost is the last column of the table above per trade - it would erode any future KEEP that spans settlements, and it cannot rescue a losing cell.

### 10. Parameter sensitivity
The spec's declared sweeps, favourable or not, each run exactly like the headline: AF step 0.01/0.03 with max 0.20 fixed, and max AF 0.10/0.30 with step 0.02 fixed. The headline is step 0.02 / max 0.20; nothing here selects or replaces it.

| Variant | Timeframe | Exit | Trades | Win% | R total | R/trade | Sharpe | Verdict |
|---|---|---|---:|---:|---:|---:|---:|---|
| headline: step 0.02, max AF 0.20 | 1H | native | 11303 | 35.2 | 110.4 | 0.010 | 0.15 | **DISCARD** |
| headline: step 0.02, max AF 0.20 | 1H | forced-1:3 | 5515 | 38.7 | -163.3 | -0.030 | -0.59 | **DISCARD** |
| headline: step 0.02, max AF 0.20 | 4H | native | 2752 | 37.8 | 101.2 | 0.037 | 0.49 | **INCONCLUSIVE** |
| headline: step 0.02, max AF 0.20 | 4H | forced-1:3 | 1332 | 38.3 | -11.1 | -0.008 | -0.08 | **DISCARD** |
| headline: step 0.02, max AF 0.20 | 1D | native | 401 | 37.7 | 52.7 | 0.132 | 0.59 | **INCONCLUSIVE** |
| headline: step 0.02, max AF 0.20 | 1D | forced-1:3 | 191 | 41.4 | 6.4 | 0.034 | 0.15 | **DISCARD** |
| step 0.01 (max 0.20 fixed) | 1H | native | 6902 | 36.9 | 203.1 | 0.029 | 0.37 | **INCONCLUSIVE** |
| step 0.01 (max 0.20 fixed) | 1H | forced-1:3 | 4223 | 42.1 | -26.0 | -0.006 | -0.12 | **DISCARD** |
| step 0.01 (max 0.20 fixed) | 4H | native | 1698 | 37.3 | 93.3 | 0.055 | 0.54 | **INCONCLUSIVE** |
| step 0.01 (max 0.20 fixed) | 4H | forced-1:3 | 1023 | 42.1 | 48.1 | 0.047 | 0.46 | **INCONCLUSIVE** |
| step 0.01 (max 0.20 fixed) | 1D | native | 243 | 35.0 | 29.6 | 0.122 | 0.49 | **INCONCLUSIVE** |
| step 0.01 (max 0.20 fixed) | 1D | forced-1:3 | 149 | 48.3 | 14.4 | 0.097 | 0.40 | **INCONCLUSIVE** |
| step 0.03 (max 0.20 fixed) | 1H | native | 14980 | 33.6 | -858.2 | -0.057 | -1.19 | **DISCARD** |
| step 0.03 (max 0.20 fixed) | 1H | forced-1:3 | 6387 | 36.5 | -335.1 | -0.052 | -1.07 | **DISCARD** |
| step 0.03 (max 0.20 fixed) | 4H | native | 3656 | 34.6 | -212.4 | -0.058 | -0.79 | **DISCARD** |
| step 0.03 (max 0.20 fixed) | 4H | forced-1:3 | 1534 | 35.1 | -90.6 | -0.059 | -0.63 | **DISCARD** |
| step 0.03 (max 0.20 fixed) | 1D | native | 522 | 38.3 | 79.3 | 0.152 | 0.77 | **KEEP** |
| step 0.03 (max 0.20 fixed) | 1D | forced-1:3 | 221 | 41.2 | 16.1 | 0.073 | 0.31 | **INCONCLUSIVE** |
| max AF 0.10 (step 0.02 fixed) | 1H | native | 10606 | 35.3 | 315.3 | 0.030 | 0.41 | **INCONCLUSIVE** |
| max AF 0.10 (step 0.02 fixed) | 1H | forced-1:3 | 5180 | 39.8 | -72.8 | -0.014 | -0.28 | **DISCARD** |
| max AF 0.10 (step 0.02 fixed) | 4H | native | 2554 | 38.2 | 193.6 | 0.076 | 0.80 | **INCONCLUSIVE** |
| max AF 0.10 (step 0.02 fixed) | 4H | forced-1:3 | 1256 | 38.0 | -15.4 | -0.012 | -0.12 | **DISCARD** |
| max AF 0.10 (step 0.02 fixed) | 1D | native | 375 | 37.9 | 56.5 | 0.151 | 0.60 | **INCONCLUSIVE** |
| max AF 0.10 (step 0.02 fixed) | 1D | forced-1:3 | 182 | 40.1 | 7.6 | 0.042 | 0.18 | **DISCARD** |
| max AF 0.30 (step 0.02 fixed) | 1H | native | 11319 | 35.2 | 96.7 | 0.009 | 0.13 | **DISCARD** |
| max AF 0.30 (step 0.02 fixed) | 1H | forced-1:3 | 5519 | 38.6 | -159.1 | -0.029 | -0.58 | **DISCARD** |
| max AF 0.30 (step 0.02 fixed) | 4H | native | 2752 | 37.8 | 97.6 | 0.035 | 0.47 | **INCONCLUSIVE** |
| max AF 0.30 (step 0.02 fixed) | 4H | forced-1:3 | 1334 | 38.3 | -15.1 | -0.011 | -0.12 | **DISCARD** |
| max AF 0.30 (step 0.02 fixed) | 1D | native | 401 | 37.7 | 53.9 | 0.134 | 0.59 | **INCONCLUSIVE** |
| max AF 0.30 (step 0.02 fixed) | 1D | forced-1:3 | 191 | 41.4 | 6.4 | 0.034 | 0.15 | **DISCARD** |

### 11. Market conditions
Each cell split by the project's regime convention (trend/volatility, labelled from already-closed bars and used for reporting only, never for decisions). The source's claimed condition is a trending market; Wilder designed the parabolic to trail a trend and noted it would lose in sideways congestion.

| Timeframe | Exit | Regime | Trades | Net R | R/trade |
|---|---|---|---:|---:|---:|
| 1H | native | down/highvol | 2196 | +65.84 | +0.030 |
| 1H | native | down/lowvol | 2174 | -96.09 | -0.044 |
| 1H | native | range/highvol | 1081 | -56.60 | -0.052 |
| 1H | native | range/lowvol | 1581 | +88.64 | +0.056 |
| 1H | native | up/highvol | 2089 | -128.36 | -0.061 |
| 1H | native | up/lowvol | 2182 | +236.98 | +0.109 |
| 1H | forced-1:3 | down/highvol | 1157 | -43.51 | -0.038 |
| 1H | forced-1:3 | down/lowvol | 973 | -31.18 | -0.032 |
| 1H | forced-1:3 | range/highvol | 538 | -29.82 | -0.055 |
| 1H | forced-1:3 | range/lowvol | 754 | +1.90 | +0.003 |
| 1H | forced-1:3 | up/highvol | 1080 | -50.95 | -0.047 |
| 1H | forced-1:3 | up/lowvol | 1013 | -9.75 | -0.010 |
| 4H | native | down/highvol | 516 | -5.04 | -0.010 |
| 4H | native | down/lowvol | 587 | +38.43 | +0.065 |
| 4H | native | range/highvol | 231 | -9.05 | -0.039 |
| 4H | native | range/lowvol | 391 | +16.98 | +0.043 |
| 4H | native | up/highvol | 514 | +12.38 | +0.024 |
| 4H | native | up/lowvol | 513 | +47.55 | +0.093 |
| 4H | forced-1:3 | down/highvol | 248 | +38.64 | +0.156 |
| 4H | forced-1:3 | down/lowvol | 274 | -44.37 | -0.162 |
| 4H | forced-1:3 | range/highvol | 110 | -8.72 | -0.079 |
| 4H | forced-1:3 | range/lowvol | 175 | +2.31 | +0.013 |
| 4H | forced-1:3 | up/highvol | 278 | -6.74 | -0.024 |
| 4H | forced-1:3 | up/lowvol | 247 | +7.77 | +0.031 |
| 1D | native | down/highvol | 64 | -7.71 | -0.120 |
| 1D | native | down/lowvol | 98 | +41.57 | +0.424 |
| 1D | native | range/highvol | 35 | -5.78 | -0.165 |
| 1D | native | range/lowvol | 51 | +19.30 | +0.378 |
| 1D | native | up/highvol | 73 | -10.98 | -0.150 |
| 1D | native | up/lowvol | 80 | +16.34 | +0.204 |
| 1D | forced-1:3 | down/highvol | 33 | +0.39 | +0.012 |
| 1D | forced-1:3 | down/lowvol | 38 | +0.87 | +0.023 |
| 1D | forced-1:3 | range/highvol | 20 | -6.89 | -0.344 |
| 1D | forced-1:3 | range/lowvol | 25 | +3.00 | +0.120 |
| 1D | forced-1:3 | up/highvol | 40 | -8.89 | -0.222 |
| 1D | forced-1:3 | up/lowvol | 35 | +17.96 | +0.513 |

### 12. Source comparison
The source is the original inventor's 1978 book, which introduces the Parabolic Time/Price System with the 0.02/0.02/0.20 parameters and makes qualitative claims - that the parabolic trails a trend and reverses the position when the trend ends, and that it should be used with a directional filter (Wilder paired it with DMI/ADX). It publishes no win rate, no reward-to-risk ratio, no Sharpe, and no drawdown figures for any crypto-like instrument, and it predates crypto, fees of 0.055% per side, and perp funding entirely. So there is no claimed performance number to reproduce; the only testable source claims are directional. Section 11 checks the main one: the rule trades with the declared trending condition. Two declared departures from the source are restated here: the source is stop-and-reverse (never flat), while this test enters only on a fresh close-cross and stands flat otherwise; and the source's reversal executes through its own stop level, while the shared engine's reversal leg fills at the next open. Sourcing strength: primary and original for the rule, silent on everything this project measures.

### 13. Discard-bar verdicts
Every cell is scored against the same fixed bar, applied after fees:

| Timeframe | Exit | Verdict | Criteria met or missed |
|---|---|---|---|
| 1H | native | **DISCARD** | post-fee Sharpe 0.15 below 0.3. |
| 1H | forced-1:3 | **DISCARD** | post-fee expectancy -0.030R per trade is not positive; post-fee Sharpe -0.59 below 0.3; earned only -0.84x its worst drawdown. A 1:3 exit needs 26.8% wins just to cover its own fee bill; this cell measured 38.7%. |
| 4H | native | **INCONCLUSIVE** | positive but short of the KEEP bar: expectancy +0.037R < +0.10R; Sharpe 0.49 < 0.7. |
| 4H | forced-1:3 | **DISCARD** | post-fee expectancy -0.008R per trade is not positive; post-fee Sharpe -0.08 below 0.3; earned only -0.17x its worst drawdown. A 1:3 exit needs 25.9% wins just to cover its own fee bill; this cell measured 38.3%. |
| 1D | native | **INCONCLUSIVE** | positive but short of the KEEP bar: Sharpe 0.59 < 0.7. |
| 1D | forced-1:3 | **DISCARD** | post-fee Sharpe 0.15 below 0.3; earned only 0.26x its worst drawdown. A 1:3 exit needs 25.3% wins just to cover its own fee bill; this cell measured 41.4%. |

```
Gate: fewer than 30 trades -> INCONCLUSIVE.
KEEP needs all of: post-fee expectancy >= +0.10R per trade; post-fee Sharpe >= 0.7; total R >= 1.5x worst R drawdown; and (forced-1:3) win rate >= its own fee breakeven (1+c)/4 plus 2%, or (native) achieved RR >= 1.5:1.
DISCARD on any of: post-fee expectancy <= +0.00R; post-fee Sharpe < 0.3; total R < 0.5x worst R drawdown.
Anything in between -> INCONCLUSIVE.
```

### 14. Bottom line
Across 3 timeframes x 2 exits (6 cells) the discard bar returns **4x DISCARD, 2x INCONCLUSIVE**. What would change a verdict: a longer or different sample that lifts a cell's post-fee expectancy past the KEEP bar rather than merely past zero; a validated funding and slippage model rather than an unmodelled one; and out-of-sample confirmation. Nothing here is a live-trading recommendation, and no sweep result was used to reselect the headline.

### 15. Files changed
- `strategy_log.csv`: 79 -> 85 lines (+6 rows, one per timeframe x exit; sweeps add no rows).
- `strategy_log.md`: 5616 -> 5860 lines (+244, this report as one appended section).
- `src/s12_parabolic_sar.py` and `src/run_s12.py`: the strategy and its runner, new on disk this run; no existing file was modified.
- Strategies #1-#11 are byte-for-byte untouched, and the front-page `master verdict index` remains as last written for strategies #1-#8, consistent with how #9-#11 were logged.

