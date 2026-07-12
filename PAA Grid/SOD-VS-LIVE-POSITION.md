# Which Position Does Each Calculation Use? — T-1 EOD, T SOD, or Live

A design note answering: *do the risk and PAA calculations care about the
T-1 EOD position and T SOD position, or only today's traded quantity /
today's new position?*

**Short answer:** they anchor on different positions, and neither uses only
today's traded quantity. **PAA anchors on the T SOD position (which should
equal the T-1 EOD position) plus today's trades as a separate term. Risk
should anchor on the current live position (SOD + today's fills)** — and
that second point is a known limitation in the current scripts (see the
last section).

## T-1 EOD vs T SOD: the same number, in principle

T-1 EOD position and T SOD position are the same snapshot viewed from
either side of the overnight batch. They only differ when overnight
lifecycle events fire:

- option expiries, exercises, assignments
- settlements
- corporate actions (splits change both qty and strike)
- book transfers

Production systems run an SOD reconciliation, and any break becomes its own
PAA line (expiry P&L, assignment P&L) — not something smeared into delta or
theta. `book_position.SODQty` in
[01_paa_source_tables.py](deephaven-paa/01_paa_source_tables.py) represents
that reconciled snapshot; the engine assumes T-1 EOD = T SOD.

## What PAA uses — and why it must be SOD, not current position

The attribution in [02_paa_engine.py](deephaven-paa/02_paa_engine.py) scales
every market-move term by `SODQty`:

```
ActualPnl = SODQty × Mult × (CurrPrice − PrevPrice)
DeltaPnl  = SODQty × Mult × Δ × dS     …etc.
```

This is deliberate. The market move `PrevPrice → CurrPrice` was only
experienced by the position that **existed at the prior close**. A lot
bought at 11am did not ride the overnight gap or the morning move —
attributing the full-day price change to it would invent P&L that nobody
earned.

Today's trades therefore enter through their own term, measured from their
own cost basis:

```
NewTradePnl = TradedQty × Mult × (CurrPrice − ExecPrice)
```

(the full reasoning is in [TRADE-PNL-VS-COST-PNL.md](TRADE-PNL-VS-COST-PNL.md)).

The EOD position never appears explicitly, but it is implied by the
identity — with `EODQty = SODQty + TradedQty`:

```
SODQty × (Curr − Prev) + TradedQty × Curr − TradedCost
  = EODQty × Curr − SODQty × Prev − TradedCost   (total daily P&L, exact)
```

Using "today's new position × price change" instead would **double-count**
intraday buys (charging them the full day's move *and* their fill-to-now
move) and **miss** the P&L on anything sold during the day.

## What risk should use — live position

Risk is the opposite: it is about **what you hold right now**, regardless of
when you acquired it. If you started flat and bought 500 delta-equivalent
this morning, the live risk grid must show 500 — the hedge you would need is
against the current book, not yesterday's.

## Known limitation in the current scripts

[04_risk_grid.py](deephaven-paa/04_risk_grid.py) and the position-scaled
tables in [05_paa_grid.py](deephaven-paa/05_paa_grid.py) scale by `SODQty`
only. That is:

- **correct** for a *start-of-day risk report*, and
- **correct** for the PAA grid's attribution columns (which must stay
  SOD-based, same window as the Greeks explain), but
- **understates live risk** in the risk grid as soon as the desk trades.

The fix is small and the data already flows through the engine:

```
CurrentQty = SODQty + Σ signed intraday fills     (from `executions`)
```

Derive a `current_position` table by aggregating `exec_signed` per
(Book, InstrumentId) and adding it to `book_position` (an outer-join-style
merge, so trades in instruments with no SOD position appear too), then scale
the risk grid by `CurrentQty` instead of `SODQty`. Because `executions` is a
live table, position risk then updates tick-by-tick as fills arrive,
alongside the spot-driven updates.

## Summary per calculation

| Calculation | Position it should use | Why |
|---|---|---|
| PAA market-move terms (delta, gamma, vega, …) | T SOD (= reconciled T-1 EOD) | Only that position experienced the T-1 → T move |
| PAA new-trade term | Today's fills, individually | Cost basis is the exec price, not the prior close |
| Risk grid / hedge ratios | Current live = SOD + today's fills | Hedging is about what you hold now |
| PAA grid attribution columns | T SOD | Same window as the Greeks explain |

## Related docs

- [PAA.md](PAA.md) — PAA methodology (Taylor explain, step reval, source data)
- [PAA-GRID.md](PAA-GRID.md) — PAA Grid formulas, tables, and conventions
- [RISK-GRID-VS-PAA-GRID.md](RISK-GRID-VS-PAA-GRID.md) — Risk Grid vs PAA Grid
- [TRADE-PNL-VS-COST-PNL.md](TRADE-PNL-VS-COST-PNL.md) — why trade P&L is marked from exec price
- [README.md](README.md) — project index, run order, data classification
