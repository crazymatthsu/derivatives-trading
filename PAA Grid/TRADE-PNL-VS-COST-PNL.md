# Why Trade P&L Is "Intraday New-Trade P&L", Not True-Cost P&L

A design note on the `NewTradePnl` term in
[02_paa_engine.py](deephaven-paa/02_paa_engine.py):

```
NewTradePnl = Multiplier × (TradedQty × CurrPrice − TradedCost)
```

i.e. today's fills marked against the current price — rather than measuring
P&L against the position's original trade cost.

**Short answer:** PAA is a *daily* explain, and "true cost" is a *lifetime*
measure. Using original trade cost inside a daily attribution would
double-count past days' P&L and break the link to the Greeks.

## The accounting identity the engine implements

The book's total economic P&L for day T is, per instrument (× multiplier):

```
TotalPnl = EODQty × CurrPrice − SODQty × PrevPrice − TradedCost
```

where `TradedCost` is the net cash paid for today's fills. Substituting
`EODQty = SODQty + TradedQty` and rearranging:

```
TotalPnl = SODQty × (CurrPrice − PrevPrice)        ← ActualPnl (SOD position)
         + TradedQty × CurrPrice − TradedCost      ← NewTradePnl
```

That second term is exactly what the engine computes. `NewTradePnl` is not
an approximation or a convenience — it is the **unique remainder that makes
the daily P&L identity exact**. It also automatically contains both the
"realized" part (you sold above/below today's reference) and the
"unrealized" part (fills marked to the current price), with no FIFO or
average-cost lot logic required.

## Why not cost basis for the SOD position?

Under daily mark-to-market, **yesterday's close mark *is* the cost basis** —
every prior day's P&L versus original cost was already recognized on those
days.

Example: buy an option Monday at $10; it closes Monday at $12; it is $13 now
on Tuesday. True-cost P&L says +$3, but $2 of that was Monday's P&L, already
reported. Tuesday's PAA must show only +$1 — otherwise the sum of daily
P&Ls no longer equals lifetime P&L, and every day after the trade
double-counts.

This is also precisely what makes attribution *work*: the Greeks explain
(`Δ·dS + ½Γ·dS² + …`) spans exactly one day of market moves, T-1 close →
now. `ActualPnl = SODQty × (CurrPrice − PrevPrice)` spans the same window,
so `Unexplained = Actual − Explained` is a meaningful model-quality
residual. If `ActualPnl` were measured against original cost, it would embed
weeks of past market moves that today's `dS`, `dσ`, `dr` cannot explain —
the unexplained column would be garbage.

## Why exec price for intraday trades?

For a trade done *today*, the execution price **is** the true cost basis —
the position did not exist at the prior close, so there is no earlier mark
to measure from. `(CurrPrice − ExecPrice) × qty` is simultaneously its
true-cost P&L and its one-day P&L; the two definitions coincide on trade
date and only diverge from tomorrow onward, when the fill rolls into
`SODQty` and gets measured from the close like everything else.

## Where a cost view does belong

Cost-based numbers are a different, complementary report layered on top —
not a replacement inside PAA:

- **Realized/unrealized split** (average cost or FIFO lots) — an
  accounting/books view. It re-partitions the same total P&L, never changes
  it, and is not attributable to daily market factors.
- **Execution-quality split** — decompose `NewTradePnl` into:
  - *execution edge*: fill price vs the market mid **at trade time**, and
  - *market move since fill*: mid-at-trade-time vs current mark.

  A genuinely useful desk enhancement, but it requires capturing a mark at
  execution time — an extra column on the `executions` feed
  (e.g. `MidAtExec`).

## Summary

| Measure | Window | Reference price | Belongs in |
|---|---|---|---|
| `ActualPnl` (SOD position) | T-1 close → now | Yesterday's close mark | Daily PAA |
| `NewTradePnl` (today's fills) | fill time → now | Execution price | Daily PAA |
| True-cost / inception P&L | trade date → now | Original trade cost | Lifetime books view |
| Realized vs unrealized | trade date → now | Avg cost / FIFO lots | Accounting overlay |

## Related docs

- [PAA.md](PAA.md) — PAA methodology (Taylor explain, step reval, source data)
- [PAA-GRID.md](PAA-GRID.md) — PAA Grid formulas, tables, and conventions
- [RISK-GRID-VS-PAA-GRID.md](RISK-GRID-VS-PAA-GRID.md) — Risk Grid vs PAA Grid
- [README.md](README.md) — project index, run order, data classification
