# Strategy #10–#22 execution specifications

These are proposed, fully pinned execution contracts, not an owner-approved
master strategy list. The repository has tested strategies #1–#9, explicitly
excludes #19 and #21 by design, and contains no authoritative definition for
#10–#22. Do not execute a spec whose status says EXCLUDED. Other specs are
research candidates, not claims that their source supports every chosen detail.

All eligible specs inherit the project-wide runner rules: BTCUSDT/SOLUSDT/XRPUSDT;
1H/4H/1D; close-based signal fills next bar open; taker fee 0.055% per side;
1% starting-equity risk per trade, not compounded; worst-case stop-first intrabar
tie; gap-through stop fills at open; discard unresolved end-of-data trades; funding
and slippage unmodelled; pooled coins per timeframe but never pooled timeframes;
native versus shared forced 1:3 exit (1R stop, 3R target, 30-bar limit); mandatory
lookahead audit, context checks, coverage, per-coin results and append-only logs.
These are exact inherited values from `strategy_log.md`, not source parameters.

Every file contains the same 15 report headings/checklist. Where a source does not
prescribe a stop, the spec fixes a test convention and requires it to be labeled
as a placeholder, not attributed to the source. Sweep only the listed values;
never pick a winner and replace the predeclared headline.