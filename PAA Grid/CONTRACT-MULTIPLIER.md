# Why PosScale = SODQty × Mult — The Contract Multiplier

A design note answering: *for `PosScale = SODQty × Mult`, why does it need
to multiply by `Mult`? Is the multiplier always 100?*

**Short answer:** option prices and Greeks are quoted **per share of the
underlying**, but positions are counted in **contracts** — and one contract
controls `Mult` shares. `PosScale` converts "contracts held" into "shares
of exposure", the unit every per-share number must be multiplied by to
become currency P&L. And no — the multiplier is not always 100; hardcoding
100 is a classic production bug.

## Why the multiplication is needed

Trace it with the numbers from
[MOCK-DATA-WALKTHROUGH.md](MOCK-DATA-WALKTHROUGH.md):

- The AAPL 220 call's mark moved 14.7477 → 16.1951 — that is **dollars per
  share**.
- DESK1 holds 150 contracts × 100 shares each = **15,000 shares of
  exposure**.
- `ActualPnl = 15,000 × 1.4474 ≈ $21,711`.

Drop the `Mult` and you would report $217 — understated by exactly 100×.

The same logic applies to every Greek term: delta of 0.5118 means the
option gains $0.5118 per share per $1 spot move, so the position's
share-equivalent delta is `150 × 100 × 0.5118 ≈ 7,677 shares` — the number
a hedger would sell against it.

Quoted option **prices** are per share too, so trade cost follows the same
rule: in `NewTradePnl`, a fill at 12.45 costs `12.45 × Mult` dollars per
contract, which is why the formula is
`NewTradePnl = Mult × (TradedQty × CurrPrice − TradedCost)` with both
prices on a per-share basis.

## Is the multiplier always 100? No.

100 is the convention for *standard* US equity options — one convention
among many:

- **Corporate-action-adjusted contracts** (the sneaky one): after a split,
  merger, or special dividend, OCC adjusts existing contracts rather than
  repricing them. A 3-for-2 split can leave a contract delivering 150
  shares; some adjusted contracts deliver 100 shares *plus* cash or shares
  of a spin-off. Non-standard contracts trade alongside standard ones on
  the same underlying for months.
- **Index options**: SPX is $100 per index point, but Euro Stoxx 50 is €10,
  DAX €5, FTSE 100 £10, Nikkei 225 ¥1,000, Hang Seng HK$50, KOSPI 200
  ₩250,000. There is no universal number.
- **Non-US equity options**: many European markets use 100, but some
  markets set contract size per underlying based on board lots (Hong Kong
  stock options vary name by name), and historical UK contracts were 1,000
  shares.
- **Options on futures**: the "multiplier" is the futures contract's own
  size — $50 per point for E-mini S&P options, 1,000 barrels for crude.

## Design consequence: multiplier is reference data, not a constant

This is exactly why `Multiplier` is a **per-instrument column in the
`instrument` table** — owned by operations / security master per
[ARCHITECTURE.md](ARCHITECTURE.md) — rather than a constant in the code:

- Deephaven: `instrument` table in
  [01_paa_source_tables.py](deephaven-paa/01_paa_source_tables.py)
- paa-cal: `multiplier` column in `paa-cal/inputs/instrument.csv`

The engine reads it per row in every formula, so an adjusted 150-share
AAPL contract just carries `Multiplier = 150` in its reference data and
the P&L, Greeks scaling, and both grids stay correct with no code change.
The sample data uses 100 everywhere only because all six mock instruments
are standard US equity options.

## Where PosScale appears

| Formula | File |
|---|---|
| `ActualPnl = PosScale × (CurrPrice − PrevPrice)` | [02_paa_engine.py](deephaven-paa/02_paa_engine.py), [engine.py](paa-cal/paa_cal/engine.py) |
| All Greek P&L terms (`DeltaPnl = PosScale × Δ × dS`, …) | same |
| `NewTradePnl = Mult × (TradedQty × CurrPrice − TradedCost)` | same |
| `ScenarioPnl = PosScale × (Theo − BaseTheo)` | [04_risk_grid.py](deephaven-paa/04_risk_grid.py), [grids.py](paa-cal/paa_cal/grids.py) |
| PAA grid components | [05_paa_grid.py](deephaven-paa/05_paa_grid.py), [grids.py](paa-cal/paa_cal/grids.py) |

## Related docs

- [MOCK-DATA-WALKTHROUGH.md](MOCK-DATA-WALKTHROUGH.md) — the traced numbers used above
- [SOD-VS-LIVE-POSITION.md](SOD-VS-LIVE-POSITION.md) — which position snapshot SODQty represents
- [TRADE-PNL-VS-COST-PNL.md](TRADE-PNL-VS-COST-PNL.md) — the NewTradePnl formula
- [ARCHITECTURE.md](ARCHITECTURE.md) — security master owns instrument reference data
- [README.md](README.md) — project index
