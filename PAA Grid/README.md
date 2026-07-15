# PAA Grid — P&L Attribution engine for vanilla options (Deephaven)

A live P&L Attribution Analysis (PAA) engine for vanilla options built as
Deephaven Python scripts, with a standalone Python calculator
([paa-cal/](paa-cal/README.md)) for reproducing and fine-tuning every
number offline, plus a full documentation set (below).

## Documentation

### Methodology & formulas

| Doc | What it covers |
|---|---|
| [PAA.md](PAA.md) | PAA methodology: required source data, Taylor-expansion explain, full-revaluation waterfall, worked example |
| [PAA-GRID.md](PAA-GRID.md) | The PAA Grid in detail: scenario definition, all formulas (incl. volga, borrDiv), tables, conventions, extensions |
| [RISK-GRID-VS-PAA-GRID.md](RISK-GRID-VS-PAA-GRID.md) | How the two grids relate: state vs change, the exact identity connecting them, why the PAA grid audits the risk grid |
| [DELTA-PNL-EXPLAINED.md](DELTA-PNL-EXPLAINED.md) | `DeltaPnl = PosScale × Δ × DSpot` factor by factor: units, Taylor interpretation, hedging meaning, sign checks |
| [CONTRACT-MULTIPLIER.md](CONTRACT-MULTIPLIER.md) | Why P&L scales by the contract multiplier — and why it is not always 100 |

### Design decisions

| Doc | What it covers |
|---|---|
| [TRADE-PNL-VS-COST-PNL.md](TRADE-PNL-VS-COST-PNL.md) | Why trade P&L is marked from execution price, not original cost (the daily P&L identity, no double counting) |
| [SOD-VS-LIVE-POSITION.md](SOD-VS-LIVE-POSITION.md) | Which position snapshot each calculation anchors on: T-1 EOD = T SOD for PAA, live position for risk |
| [SNAPSHOT-COHERENCE.md](SNAPSHOT-COHERENCE.md) | Why attribution inputs must equal the pricer's mark-time inputs (spot, vol, rate, carry) |
| [TIMING-AND-CUTOFFS.md](TIMING-AND-CUTOFFS.md) | Snapshot time vs run time vs trade time: P&L is as-of the snapshot, trade cut-off must equal snap time, positions flow to risk in real time |

### Data sources & architecture

| Doc | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Team / data / calculation map with Mermaid diagram; editable draw.io version in [architecture.drawio](architecture.drawio) |
| [OPTION-PRICE-SOURCES.md](OPTION-PRICE-SOURCES.md) | Where option prices come from on a sell-side desk: vendor feeds (OPRA/NBBO) vs internal theo vs EOD marks, official names |
| [BORRDIV-OWNERSHIP.md](BORRDIV-OWNERSHIP.md) | Which teams own the borrow/dividend carry input (dividends desk, stock loan, quant-implied) vs the div_rho Greek |
| [GREEKS-OWNERSHIP.md](GREEKS-OWNERSHIP.md) | Who provides delta and every other Greek (quant model owner, risk-tech batch, PC/RM validation), full Greek reference, convention checklist, and a ready-to-send data-request spec |
| [MOCK-DATA-WALKTHROUGH.md](MOCK-DATA-WALKTHROUGH.md) | End-to-end mock-data trace: every value from Tier 1 to Tier 3 with formulas, plugged-in numbers, and a debugging guide |
| [DEPLOYMENT-AMPS-EKS.md](DEPLOYMENT-AMPS-EKS.md) | Infrastructure: Deephaven as a stateless Deployment on EKS (why not StatefulSet), AMPS on EC2 as the operational data store (topic design, ingest adapters, HA twins), consumer connectivity for on-prem + cross-namespace EKS (AMPS results topics vs Barrage), and scaling the Barrage tier as a read-replica pool with connection-affinity LB + KEDA |

### Runnable code

| Location | What it is |
|---|---|
| [deephaven-paa/](deephaven-paa/) | The live Deephaven scripts (01–05) — see next section |
| [paa-cal/](paa-cal/README.md) | Standalone stdlib-only Python calculator over editable CSV inputs; reproduces the walkthrough numbers exactly |

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
| `inst_prev` | Black-Scholes T-1 mark + Greeks (Δ, Γ, vega, θ, ρ, div-rho, volga) per instrument at prev-close market, TTM+1 day |
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
row reproduces the live PAA (exactly for ActualPnl; its ExplainedPnl adds the
volga term the flat `paa` table omits). All Greeks are T-1 (start-of-day),
position-scaled by `SODQty × Mult`:

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
