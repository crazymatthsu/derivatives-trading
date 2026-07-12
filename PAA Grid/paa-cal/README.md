# paa-cal — Standalone PAA / Risk Grid Calculator

A plain-Python (stdlib-only, no pip install needed) sub-project that runs
the same calculations as the Deephaven scripts in
[../deephaven-paa/](../deephaven-paa/), reading mock data from editable CSV
files. Use it to reproduce every number in
[../MOCK-DATA-WALKTHROUGH.md](../MOCK-DATA-WALKTHROUGH.md), debug a
calculation step by step, or fine-tune inputs and see the effect instantly.

Requires Python 3.8+. No dependencies.

## Quick start

```bash
cd paa-cal

# everything: marks & Greeks, trade P&L, PAA, roll-ups, both grids
python3 run_paa.py all

# one report at a time
python3 run_paa.py risk        # T-1 marks + Greeks, live marks, market moves
python3 run_paa.py trades      # intraday new-trade P&L per (book, instrument)
python3 run_paa.py paa         # the attribution table
python3 run_paa.py rollup      # by book / by underlying / firm + summary stats
python3 run_paa.py risk-grid   # Greeks x spot ladder
python3 run_paa.py paa-grid    # attribution x spot ladder

# filter to one instrument or book (great for tracing a single position)
python3 run_paa.py paa-grid --instrument AAPL_C220_DEC26
python3 run_paa.py paa --book DESK1

# also write every report as CSV (open in Excel)
python3 run_paa.py all --csv-out outputs

# point at a different scenario directory
python3 run_paa.py all --inputs my_scenario
```

## Input files (`inputs/`) — edit these to change the scenario

Each file is one data source from the architecture
([../ARCHITECTURE.md](../ARCHITECTURE.md)); the Tier-1 team that owns it in
production is noted:

| File | Owner (production) | Columns |
|---|---|---|
| `instrument.csv` | Operations (security master) | instrument_id, underlying, option_type (CALL/PUT), strike, expiry (YYYY-MM-DD), multiplier, currency |
| `book_position.csv` | Operations (SOD reconciliation) | book, instrument_id, sod_qty (signed) |
| `spot.csv` | Product control (prev) / market data tech (live) | underlying, prev, live |
| `vol.csv` | Product control (prev) / quant team (live) | instrument_id, prev, live |
| `rates.csv` | Product control (prev) / rates team (live) | currency, prev, live |
| `dividends.csv` | Product control (prev) / rates team (live) | underlying, prev, live (continuous div+borrow yield) |
| `fx.csv` | Product control (prev) / market data tech (live) | currency, prev, live (USD per 1 ccy) |
| `executions.csv` | Trading desk OMS | exec_id, order_id, book, instrument_id, side (BUY/SELL), qty, price, exec_time |
| `orders.csv` | Trading desk OMS | audit context only — not used in any P&L |
| `config.json` | — | as_of date, day counts (365 ttm / 252 theta), base currency, ladder shifts, 5% breach threshold |

Everything derived (marks, Greeks, P&L) is **calculated, never input** —
so any edit stays internally consistent. Try it: bump AAPL's live spot in
`spot.csv` from 215.60 to 218.00, rerun `python3 run_paa.py paa`, and watch
DeltaPnl/GammaPnl move while unexplained stays tiny.

## Code layout — one module per calculation step

| Module | Mirrors | What it computes |
|---|---|---|
| `paa_cal/bs.py` | BS library in `02_paa_engine.py` | price, delta, gamma, vega, theta, rho, div_rho, volga, forward |
| `paa_cal/load.py` | `01_paa_source_tables.py` | reads the CSVs/config into dicts |
| `paa_cal/engine.py` | `02_paa_engine.py` | `compute_risk` (T-1 marks + Greeks, live marks), `compute_trades` (new-trade P&L), `compute_paa` (attribution rows) |
| `paa_cal/rollup.py` | `03_paa_rollups.py` | `aggregate` (any grouping incl. firm total), `summary` (stats + BREACH/OK flag) |
| `paa_cal/grids.py` | `04_risk_grid.py`, `05_paa_grid.py` | `risk_grid` (Greeks at shifted spot), `paa_grid` (attribution per shift) |
| `run_paa.py` | — | CLI: loads inputs, runs the pipeline, prints tables, optional CSV export |

Formula documentation lives with the main project docs:
[../PAA.md](../PAA.md) (methodology),
[../PAA-GRID.md](../PAA-GRID.md) (grid formulas),
[../MOCK-DATA-WALKTHROUGH.md](../MOCK-DATA-WALKTHROUGH.md) (these exact
numbers traced by hand).

## Using it from Python instead of the CLI

```python
from paa_cal import (load_inputs, compute_risk, compute_trades,
                     compute_paa, aggregate, summary, paa_grid)

inp = load_inputs("inputs")
risk = compute_risk(inp)                 # per-instrument marks + Greeks
trades = compute_trades(inp, risk)       # per (book, instrument) trade P&L
rows = compute_paa(inp, risk, trades)    # attribution rows (list of dicts)

print(risk["AAPL_C220_DEC26"]["delta"])          # 0.5118...
print(aggregate(rows, ["book"]))                  # book-level sums
print(summary(rows, breach_pct=5.0))              # quality check
```

## Sanity checks to expect with the shipped inputs

- `paa`: DESK1 AAPL_C220 explained ≈ +21,711 vs actual ≈ +21,711
  (unexplained −0.5)
- `rollup`/`summary`: both books OK at ~0.1% unexplained
- `paa-grid` (AAPL_C220): unexplained ≈ +1 at 0% shift, growing to
  ≈ −7,800 at −20% and ≈ −24,700 at +20% — the Taylor error the grid
  exists to show
- Cross-grid identity: `paa_grid.actual(s) = risk_grid.scenario_pnl(s) +
  paa.actual` at every shift

## Differences vs the Deephaven scripts

- Static snapshot instead of ticking: the Deephaven `spot_live` simulator
  is replaced by the `live` column in `spot.csv` (defaults are the
  simulator base values, matching the walkthrough).
- Same formulas, same conventions (vega/rho per 1.00, theta per year,
  SOD-anchored positions per
  [../SOD-VS-LIVE-POSITION.md](../SOD-VS-LIVE-POSITION.md)).
- `outputs/` is disposable — regenerate any time with `--csv-out outputs`.
