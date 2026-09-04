# strategies-research

Research and backtesting workspace for crypto trading strategies.

The goal of this project is to take a trading idea, express it as explicit rules,
test those rules against historical price data, and judge honestly whether the
result is a real edge or just noise. Nothing here places live orders.

## Status

Project scaffolding only. No strategies or data pipelines yet.

## Requirements

- Python 3.12 (3.10 or newer works)
- Git

## Setup

The project uses a local virtual environment so its packages stay isolated from
the rest of the machine. It lives in `.venv/` and is **not** committed to Git —
anyone cloning this repo creates their own.

Create it (first time only):

```powershell
python -m venv .venv
```

Activate it (each new terminal session, Windows PowerShell):

```powershell
.\.venv\Scripts\Activate.ps1
```

Your prompt will show `(.venv)` when it is active. To leave it, run `deactivate`.

Once packages are added, install them with:

```powershell
pip install -r requirements.txt
```

## Conventions

- **Secrets stay out of Git.** Exchange or data-provider API keys belong in a
  local `.env` file, which `.gitignore` already excludes.
- **Data stays out of Git.** Downloaded price history goes in `data/`, also
  excluded. Data is re-downloadable; the code that downloads it is what matters.
- **Results are reproducible.** Every backtest should record the symbol,
  timeframe, date range, and parameters that produced it.

## Layout

```
.venv/          local Python environment (ignored by Git)
.gitignore      files Git deliberately does not track
README.md       this file
```

Additional folders will be added as the research work begins.
