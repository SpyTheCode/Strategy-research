# Strategy #19 SPEC — funding-rate arbitrage (EXCLUDED)

**Status:** EXCLUDED BY PROJECT DESIGN; do not run using the standard directional backtest matrix. Existing `strategy_log.md` explicitly excludes it because it has no directional stop or meaningful R and forced 1:3 is inapplicable.

## 1. THE RULE — source and exact tested interpretation
**Source:** Bybit USDT perpetual funding mechanism documentation (funding rate paid at scheduled funding times). Candidate cash-and-carry: buy spot, short equal-notional perpetual; receive funding when rate is positive. The source describes exchange mechanics, not a complete strategy. No directional stop, no take-profit; close both legs on funding sign reversal or at 30 days, whichever first (proposed rule only).

## 2. EVERY PLACEHOLDER, PRE-DECIDED
1:1 notional, BTC/SOL/XRP only, funding snapshots at actual historical settlement times; entry next available bar open after observed rate; exit at next open after sign turns non-positive or day30. Spot/perp fees and basis/borrow/capital costs require separate historical data. Do not approximate absent historical rates. Sensitivity holding cap 7/30/90 days, funding threshold 0/0.01% per interval.

## 3. STRATEGY-SPECIFIC LOOKAHEAD TRAPS
Funding rate must be the rate observable before that settlement; realized settlement rate cannot trigger a trade before its publication. No future funding schedule/rate interpolation. Spot and perp candles must align by timestamp; avoid using one leg's later close.

## 4. EXACT TEST MATRIX
- [ ] **Do not** run standard 1H/4H/1D directional native/forced 1:3 matrix.
- [ ] Separate carry engine only after funding history, spot/perp prices, and full cost data are available.
- [ ] Report standalone carry returns, basis risk, drawdown, capital use; no project KEEP/DISCARD label.

## 5. EXACT REPORT FORMAT
Standard report headings 1–15 cannot honestly be populated (no R/forced variant). If data later permits, use sections: source/mechanics; placeholder; timestamp audit; coverage; portfolio returns; cashflows; leg attribution; risk; per-coin; execution/fairness; separate conclusion; sensitivity; costs; summary; limitations. Label as an exception, not comparable.

## 6. MISINTERPRETATION RISKS
Positive funding is not guaranteed profit; basis movement can overwhelm carry. Do not invent funding series or feed this to directional `runner`. This exclusion is intentional, not a failure or missing spec.

## 7–15. EXECUTOR LOCKS
Current action: none. Do not append CSV strategy metrics or assign verdict. Revisit only with a dedicated cash-and-carry specification and data pipeline approved by owner.