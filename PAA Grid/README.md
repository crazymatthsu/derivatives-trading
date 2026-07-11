# PAA Grid — P&L Attribution engine for vanilla options (Deephaven)

A live P&L Attribution Analysis (PAA) engine for vanilla options built as
Deephaven Python scripts. Methodology background is in [PAA.md](PAA.md).

## Scripts (in `deephaven-paa/`, run in order, same Deephaven session)

| Script | Layer | Produces |
|---|---|---|
| `deephaven-paa/01_paa_source_tables.py` | Raw source data | `instrument`, `book_position`, `orders`, `executions`, prev-close snapshots (`spot_prev`, `vol_prev`, `rates_prev`, `div_prev`, `fx_prev`), live market tables (`spot_live` — ticking simulator, `vol_live`, `rates_live`, `div_live`, `fx_live`) |
| `deephaven-paa/02_paa_engine.py` | Derived data / calculation | `inst_prev` (T-1 marks + Greeks), `inst_now` (live marks), `risk`, `trade_pnl`, **`paa`** (the attribution output, one row per Book × Instrument) |
| `deephaven-paa/03_paa_rollups.py` | Roll-ups / summary | `paa_rollup` (Book → Underlying → Instrument tree), `paa_by_underlying`, `paa_by_book`, `paa_firm`, `paa_summary` (stats + 5% quality flag) |

Because `spot_live` is a ticking `time_table` simulation collapsed with
`last_by`, every downstream table — marks, attribution, roll-ups, summary —
recomputes incrementally in real time. Swap the simulators/static samples
for real feeds (Kafka ingester, Barrage subscription) keeping the same
schemas and keys; nothing downstream changes.

## Data classification

### Raw source data (external inputs, keyed)

| Table | Key | Content |
|---|---|---|
| `instrument` | InstrumentId | Option contract terms: underlying, type, strike, expiry, multiplier, currency |
| `book_position` | Book, InstrumentId | Start-of-day holdings |
| `orders` | OrderId | Order state (audit/context only — P&L uses executions) |
| `executions` | ExecId | Intraday fills: side, qty, price, time |
| `spot_prev` / `spot_live` | Underlying | T-1 close / live underlying price |
| `vol_prev` / `vol_live` | InstrumentId | T-1 / live implied vol (interpolated surface point) |
| `rates_prev` / `rates_live` | Currency | T-1 / live risk-free rate |
| `div_prev` / `div_live` | Underlying | T-1 / live continuous dividend yield |
| `fx_prev` / `fx_live` | Currency | T-1 / live FX rate to base (USD) |

> Implied vol and rates were not in the original data list but are
> **mandatory** inputs — vanilla options cannot be marked or risked
> without them.

### Derived data (computed by the engine)

| Table | Derivation |
|---|---|
| `inst_prev` | Black-Scholes T-1 mark + Greeks (Δ, Γ, vega, θ, ρ, div-rho) per instrument at prev-close market, TTM+1 day |
| `inst_now` | Black-Scholes live mark per instrument at live market |
| `risk` | `inst_prev` ⋈ `inst_now` — full per-instrument risk/valuation view |
| `trade_pnl` | Executions aggregated to (Book, Instrument): signed qty, cost, `NewTradePnl = mult × (TradedQty × CurrPrice − TradedCost)` |
| `paa` | **Attribution output**: DeltaPnl, GammaPnl, VegaPnl, ThetaPnl, RhoPnl, DivPnl → ExplainedPnl; ActualPnl; UnexplainedPnl (+%); NewTradePnl; FxPnl; totals in local and base ccy |

### Roll-up data (aggregations of `paa`)

| Table | Grain |
|---|---|
| `paa_rollup` | Hierarchical tree Book → Underlying → Instrument, summed at each level |
| `paa_by_underlying` | Flat sums per (Book, Underlying) |
| `paa_by_book` | Flat sums per Book |
| `paa_firm` | One-row firm-wide grand total |
| `paa_summary` | Per-book stats: totals, avg/std/min/max unexplained, explained ratio, `BREACH`/`OK` flag at the 5% unexplained threshold |

## Attribution formulas (per Book × Instrument row)

```
PosScale     = SODQty × Multiplier
DeltaPnl     = PosScale × Δ × dS
GammaPnl     = ½ × PosScale × Γ × dS²
VegaPnl      = PosScale × vega × dσ          (vega per 1.00 vol)
ThetaPnl     = PosScale × θ × (1/252)        (θ per year)
RhoPnl       = PosScale × ρ × dr
DivPnl       = PosScale × (∂V/∂q) × dq
ExplainedPnl = Σ of the above
ActualPnl    = PosScale × (CurrPrice − PrevPrice)
Unexplained  = ActualPnl − ExplainedPnl
NewTradePnl  = Σ fills: signedQty × Mult × (CurrPrice − ExecPrice)
FxPnl        = PosScale × PrevPrice × (FX_now − FX_prev)      (base ccy)
TotalPnlBase = (ActualPnl + NewTradePnl) × FX_now + FxPnl
```
