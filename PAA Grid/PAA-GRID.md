# PAA Grid — P&L Attribution Across a Spot Ladder

The PAA Grid combines the two desk tools built in this project: where the
Risk Grid ([04_risk_grid.py](deephaven-paa/04_risk_grid.py)) shows **Greeks**
at each spot shift, the PAA Grid ([05_paa_grid.py](deephaven-paa/05_paa_grid.py))
shows **attributed P&L** at each spot shift — for every ladder level, the
predicted T-1 → scenario P&L decomposed into Taylor components:

```
Spot shift % | Shifted spot | Delta | Gamma | Time | Vega | Volga | BorrDiv | Rate
             | Explained | Actual (full reval) | Unexplained
```

Methodology background for PAA itself is in [PAA.md](PAA.md); the overall
project layout is in [README.md](README.md).

## Scenario definition (per grid row)

Each row of the ladder (−20%, −15%, −10%, −5%, −2%, −1%, 0%, +1%, +2%, +5%,
+10%, +15%, +20%) represents one scenario:

- **Spot** moves from the T-1 close (`PrevSpot`) to
  `ShiftedSpot = live Spot × (1 + shift)`. The **0% row therefore reproduces
  today's live PAA** — the grid is always centered on the current market.
- **Vol, rate, and borrow/dividend** moves are the *actual* live T-1 → T
  changes (`dσ`, `dr`, `dq`) — the same at every ladder level.
- **Time** rolls one trading day (T-1 close → T).

So each non-zero row answers: *"how would today's P&L decompose if spot were
X% away from here, everything else as it actually happened?"*

## Formulas

All Greeks are **start-of-day (T-1)** Greeks from the Black-Scholes library
in [02_paa_engine.py](deephaven-paa/02_paa_engine.py), computed at prev-close
market with time-to-expiry + 1 day. Position scaling is
`PosScale = SODQty × Multiplier`.

```
DSpot        = ShiftedSpot − PrevSpot         ShiftedSpot = Spot × (1 + s)

DeltaPnl     = PosScale × Δ × DSpot
GammaPnl     = ½ × PosScale × Γ × DSpot²
TimePnl      = PosScale × θ × (1/252)         θ per year
VegaPnl      = PosScale × vega × dσ           vega per 1.00 vol
VolgaPnl     = ½ × PosScale × volga × dσ²     volga = vega × d1 × d2 / σ
BorrDivPnl   = PosScale × (∂V/∂q) × dq        q = dividend + borrow carry
RatePnl      = PosScale × ρ × dr

ExplainedPnl = DeltaPnl + GammaPnl + TimePnl + VegaPnl
             + VolgaPnl + BorrDivPnl + RatePnl

ActualPnl    = PosScale × (BS(ShiftedSpot, K, T, live r, q, σ) − PrevPrice)
UnexplainedPnl = ActualPnl − ExplainedPnl
```

`ActualPnl` is a **full revaluation** at the shifted spot with live
vol/rate/div — not a Taylor estimate. `UnexplainedPnl` therefore measures the
Taylor expansion error directly: it stays near zero around the 0% row and
grows toward the ±15–20% wings (residual third-order spot terms, cross terms
like vanna, etc.). Watching where it becomes material tells you exactly how
far the Greeks-based explain can be trusted.

### Volga (vomma)

Second-order vol sensitivity, added to the pricing library as `bs_volga`:

```
volga = ∂²V/∂σ² = vega × d1 × d2 / σ
      = S·e^(−qT)·φ(d1)·√T × d1 × d2 / σ
```

Units: per 1.00² vol change; `VolgaPnl` uses `dσ` in decimals, consistent
with the vega convention.

### BorrDiv (borrow / dividend carry)

The `q` input to the pricer is the **combined carry yield**: continuous
dividend yield plus stock borrow cost. `∂V/∂q` ("dividend rho"):

```
call:  ∂V/∂q = −T·S·e^(−qT)·N(d1)
put:   ∂V/∂q = +T·S·e^(−qT)·N(−d1)
```

If borrow is sourced separately from dividends, extend `div_prev`/`div_live`
with a `BorrowRate` column and feed `q = DivYield + BorrowRate` — the
attribution formulas are unchanged (or split `BorrDivPnl` into two terms
using the same `∂V/∂q` against `dDiv` and `dBorrow` separately).

## Tables produced (`05_paa_grid.py`)

| Table | Grain | Content |
|---|---|---|
| `paa_shift` | shift | Ladder definition (13 points, −20% … +20%) |
| `paa_grid_inst` | Instrument × shift | Per-option attribution components + `TheoAtShift` |
| **`paa_grid`** | Book × Instrument × shift | **The output**: position-scaled components, local + base (USD) ccy via `fx_live` |
| `paa_grid_by_underlying` | Book × Underlying × shift | Summed ladder |
| `paa_grid_by_book` | Book × shift | Summed ladder |
| `paa_grid_firm` | shift | Firm-wide ladder |
| `paa_grid_rollup` | tree | Book → Underlying → Instrument, keyed by shift |

## Mechanics and conventions

- **Run order:** 01 → 02 → 05. Scripts 03 (PAA roll-ups) and 04 (Risk Grid)
  are independent siblings — all three depend only on 01 + 02.
- Reuses the `risk` table from script 02 (T-1 Greeks incl. `Volga`, T-1 mark,
  live market) — the grid is `risk` cross-joined (`join` with no `on`)
  against the ladder, then position-scaled with `book_position` using `join`
  (not `natural_join`), because each position fans out across 13 ladder rows.
- Base-currency columns (`ExplainedPnlBase`, `ActualPnlBase`,
  `UnexplainedPnlBase`) convert via `fx_live`, so cross-currency books
  aggregate correctly in the roll-ups.
- Everything hangs off `spot_live`, so the entire grid **re-centers on every
  tick** — marks, attribution, roll-ups, and tree all update incrementally.
- Vega/volga are per 1.00 vol (divide by 100 for per-vol-point); theta is per
  year (attribution uses 1/252).

## Natural extensions

- **2-D grid:** cross-join a vol-shift ladder as a second dimension
  (spot × vol PAA surface) — same pattern, one more `join`.
- **Time dimension:** shift `Ttm` for a decay ladder (full scenario cube).
- **Vanna term:** add `bs_vanna` (∂²V/∂S∂σ) and `VannaPnl = vanna × DSpot × dσ`
  to shrink the unexplained residual in the wings where spot and vol cross
  effects matter.
