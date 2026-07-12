# Risk Grid vs PAA Grid — Relationship and Differences

Both grids ([04_risk_grid.py](deephaven-paa/04_risk_grid.py) and
[05_paa_grid.py](deephaven-paa/05_paa_grid.py)) are the same scaffolding
asking two different questions — they share the 13-point spot ladder, the
Black-Scholes library from [02_paa_engine.py](deephaven-paa/02_paa_engine.py),
and the live ticking data spine, but one shows **state** (your risk if spot
were there) and the other shows **change** (your P&L if spot went there).

## What each one answers

**Risk Grid (04)** — *"If spot were X% away, what would my book look like?"*

At each shift it does a full revaluation at the shifted spot with **live**
vol/rates/div and **live** time-to-expiry, and reports the resulting state:
theo, forward, and Greeks recomputed *at that shifted spot*. It is
forward-looking and has no memory of yesterday — `PrevSpot` never appears.
Its natural consumer is the hedger: "if the market gaps down 5%, my delta
becomes +12,400 shares — that's what I'd need to trade to get flat."

**PAA Grid (05)** — *"If spot went to X%, how would today's P&L decompose?"*

At each shift it measures the change from the **T-1 close** to the scenario,
and splits it into Taylor components using **fixed start-of-day Greeks**:
delta, gamma, time, vega, volga, borrDiv, rate. It is anchored to yesterday —
`PrevSpot`, `PrevPrice`, and the actual overnight vol/rate/carry moves are
all baked in. Its natural consumer is P&L explain and risk control: "if we
close down 10%, roughly −$480k, of which −$510k delta, +$65k gamma,
−$20k decay…"

## Structural differences, side by side

| | Risk Grid (04) | PAA Grid (05) |
|---|---|---|
| Question | What is my risk *at* that spot? | What is my P&L *getting to* that spot? |
| Output units | Greeks & prices (state) | P&L dollars (change) |
| Baseline | Live market (0% row = current book) | T-1 close (0% row = today's live PAA) |
| Greeks | Recomputed **at each shifted spot** | Fixed **T-1** Greeks, multiplied by factor moves |
| Vol / rate / div | Held at live values (pure spot ladder) | Actual T-1 → T moves attributed (vega, volga, rate, borrDiv terms) |
| Time | Live TTM, unchanged | Rolls one trading day (time P&L term) |
| Key extra columns | Forward, VegaPoint, ThetaDay, DollarDelta | ExplainedPnl, ActualPnl (full reval), UnexplainedPnl |
| Primary consumer | Hedging decisions | P&L explain, risk control, model validation |

## The exact mathematical link

Both grids call the identical full revaluation at the shifted spot — script
04's `Theo` and script 05's `TheoAtShift` are the same number
(`bs_price(ShiftedSpot, K, Ttm, live r, q, σ)`). So per position:

```
paa_grid.ActualPnl  =  risk_grid.ScenarioPnl  +  paa.ActualPnl (live, script 02)

(TheoShift − PrevPrice) = (TheoShift − BaseTheo) + (BaseTheo − PrevPrice)
```

The PAA grid's actual P&L is the risk grid's scenario P&L **plus** today's
already-realized P&L.

In the other direction, the **risk grid is the derivative of the PAA grid**:
the slope of the P&L ladder across shifts is (dollar) delta, its curvature is
gamma. Plot `paa_grid_firm.ActualPnl` against shift and the risk grid's
delta/gamma ladder is its first and second differences.

## Why you want both: the PAA grid audits the risk grid

The risk grid hands the desk Greeks and implicitly promises "these numbers
describe your book." The PAA grid's `UnexplainedPnl` column tests that
promise at every shift:

- near the 0% row it is tiny (Taylor expansion is locally exact);
- it grows toward the ±15–20% wings as third-order spot terms and
  cross-effects (vanna) exceed what delta/gamma/vega/volga capture.

The shift level where unexplained becomes material is precisely the boundary
beyond which hedging off the risk grid's Greeks stops being safe — that is
the operational reason desks run the two grids as a pair.

## Related docs

- [PAA.md](PAA.md) — PAA methodology (Taylor explain, step reval, source data)
- [PAA-GRID.md](PAA-GRID.md) — PAA Grid formulas, tables, and conventions
- [README.md](README.md) — project index, run order, data classification
