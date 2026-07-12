# PAA Grid — P&L Attribution engine for vanilla options (Deephaven)

A live P&L Attribution Analysis (PAA) engine for vanilla options built as
Deephaven Python scripts. Methodology background is in [PAA.md](PAA.md);
the PAA Grid (attribution × spot ladder) is documented in detail in
[PAA-GRID.md](PAA-GRID.md); how the Risk Grid and PAA Grid relate is in
[RISK-GRID-VS-PAA-GRID.md](RISK-GRID-VS-PAA-GRID.md); why trade P&L is
marked from execution price rather than original cost is explained in
[TRADE-PNL-VS-COST-PNL.md](TRADE-PNL-VS-COST-PNL.md).

## Scripts (in `deephaven-paa/`, run in order, same Deephaven session)

| Script | Layer | Produces |
|---|---|---|
| `deephaven-paa/01_paa_source_tables.py` | Raw source data | `instrument`, `book_position`, `orders`, `executions`, prev-close snapshots (`spot_prev`, `vol_prev`, `rates_prev`, `div_prev`, `fx_prev`), live market tables (`spot_live` — ticking simulator, `vol_live`, `rates_live`, `div_live`, `fx_live`) |
| `deephaven-paa/02_paa_engine.py` | Derived data / calculation | `inst_prev` (T-1 marks + Greeks), `inst_now` (live marks), `risk`, `trade_pnl`, **`paa`** (the attribution output, one row per Book × Instrument) |
| `deephaven-paa/03_paa_rollups.py` | Roll-ups / summary | `paa_rollup` (Book → Underlying → Instrument tree), `paa_by_underlying`, `paa_by_book`, `paa_firm`, `paa_summary` (stats + 5% quality flag) |
| `deephaven-paa/04_risk_grid.py` | Scenario risk (spot ladder) | `spot_shift` (ladder definition), `risk_grid_inst` (instrument × shift: shifted spot, forward, theo, Greeks), `risk_grid_pos` (position-scaled + scenario P&L), `risk_grid_by_underlying` / `risk_grid_by_book` / `risk_grid_firm`, `risk_grid_rollup` |
| `deephaven-paa/05_paa_grid.py` | PAA Grid (attribution × spot ladder) | `paa_shift`, `paa_grid_inst` (instrument × shift attribution), **`paa_grid`** (position-scaled: delta/gamma/time/vega/volga/borrDiv/rate P&L + full-reval actual + unexplained), `paa_grid_by_underlying` / `paa_grid_by_book` / `paa_grid_firm`, `paa_grid_rollup` |

Run order: 01 → 02 → then any of 03/04/05 (each depends only on 01+02).

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

### Risk Grid (spot ladder, `04_risk_grid.py`)

Derived: `risk_grid_inst` (instrument × shift), `risk_grid_pos` (position-scaled).
Roll-ups: `risk_grid_by_underlying`, `risk_grid_by_book`, `risk_grid_firm`, `risk_grid_rollup`.

Per grid cell (shift `s`, holding vol/rate/div/time at live values):

```
ShiftedSpot = Spot × (1 + s)
Forward     = ShiftedSpot × e^((r − q) × T)
Theo        = BS(ShiftedSpot, K, T, r, q, σ)
Delta/Gamma/Vega/Theta = BS Greeks at ShiftedSpot
ScenarioPnl = SODQty × Mult × (Theo − BaseTheo)      BaseTheo = theo at s = 0
```

Vega is per 1.00 vol (`VegaPoint` = per vol point); Theta per year (`ThetaDay` = per trading day). Position rows carry `PosDelta`, `DollarDelta(＋Base)`, `PosGamma`, `PosVegaPoint`, `PosThetaDay`; only these scaled Greeks are summed in roll-ups (per-option Greeks are not additive).

### PAA Grid (attribution × spot ladder, `05_paa_grid.py`)

Derived: `paa_grid_inst` (instrument × shift), **`paa_grid`** (position-scaled).
Roll-ups: `paa_grid_by_underlying`, `paa_grid_by_book`, `paa_grid_firm`, `paa_grid_rollup`.

Scenario per grid row: spot moves T-1 → live × (1 + shift); vol/rate/borrow-div
moves are the actual live T-1 → T changes; time rolls one trading day. The 0%
row reproduces the live PAA. All Greeks are T-1 (start-of-day), position-scaled
by `SODQty × Mult`:

```
DSpot       = ShiftedSpot − PrevSpot          ShiftedSpot = Spot × (1 + s)
DeltaPnl    = Δ × DSpot
GammaPnl    = ½ × Γ × DSpot²
TimePnl     = θ × (1/252)
VegaPnl     = vega × dσ
VolgaPnl    = ½ × volga × dσ²                 volga = vega·d1·d2/σ
BorrDivPnl  = (∂V/∂q) × dq                    q = dividend + borrow carry
RatePnl     = ρ × dr
ExplainedPnl = Σ of the above
ActualPnl   = BS(ShiftedSpot, live σ/r/q, T) − PrevPrice     (full reval)
Unexplained = ActualPnl − ExplainedPnl        (Taylor error, grows with |s|)
```

If borrow cost is sourced separately from dividends, extend `div_prev`/`div_live`
with a `BorrowRate` column and feed `q = DivYield + BorrowRate` — the
attribution formulas are unchanged.

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
