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
