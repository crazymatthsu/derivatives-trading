# Who Calculates BorrDiv? — Ownership of the Carry Yield and Its Greek

A design note answering: *in [bs.py](paa-cal/paa_cal/bs.py), which team
should calculate borrDiv?*

**Short answer:** two different things get "calculated", and they belong to
different teams — the **input** `q` (the carry yield itself) versus the
**sensitivity** `div_rho` (the Greek in bs.py).

## The input `q` — assembled from two sources, owned by two desks

`q` in bs.py is the combined carry yield: dividend yield + stock borrow
cost. On a sell-side equities desk those halves have different owners:

### Dividend forecasts — equity forwards / dividends desk

Real dividends are discrete cash amounts on forecast ex-dates, not a smooth
yield. The equity forwards/dividends desk (sometimes quant research)
maintains a dividend curve per stock — announced dividends near-term,
modeled forecasts further out — which gets converted to the
continuous-yield equivalent Black-Scholes wants, roughly:

```
q_div ≈ ln(1 + PV(dividends to expiry) / S) / T     per expiry
```

### Borrow cost — securities lending / stock loan desk

The stock loan desk (Delta One or prime services) knows each name's actual
financing: general-collateral names borrow at a few basis points;
"specials" (heavily shorted stocks) can cost several hundred bps. Borrow
cost belongs in `q` because it changes the forward exactly like a dividend
does.

### Implied carry — quant / strats

In practice the quant team often does not take these estimates as gospel
but **implies the total carry from market prices** — backing `r − q` out of
index futures, equity forwards, or put-call parity on liquid option pairs.
When implied carry and the assembled dividend+borrow estimate disagree,
that is a real signal (the market pricing a dividend cut, or borrow
tightening). Marking off implied carry is generally preferred for pricing
consistency — it makes marks match where forwards actually trade.

This is why [ARCHITECTURE.md](ARCHITECTURE.md) labels the Tier-1 owner
"Rates & dividends team (curves, div/borrow yields)" — shorthand for this
dividend-desk + stock-loan + quant-implied assembly, landing in the
`div_prev` / `div_live` tables (or `dividends.csv` in
[paa-cal](paa-cal/README.md)).

## The Greek `div_rho` — computed by whoever runs the pricer

The `div_rho` function itself is just math on the inputs, so it is
calculated wherever the pricing library runs:

- production: the **quant/strats pricing service**
- this sub-project: [bs.py](paa-cal/paa_cal/bs.py)
- the Deephaven demo: [02_paa_engine.py](deephaven-paa/02_paa_engine.py)

Same for the attribution term `BorrDivPnl = pos × div_rho × dq` — that is
the PAA engine's arithmetic, not a team judgment.

## Governance and coherence

- Per [SNAPSHOT-COHERENCE.md](SNAPSHOT-COHERENCE.md), the `dq` used in
  attribution must be the change in the carry **the pricer actually used**
  for the marks — not an independently sourced dividend estimate.
- **Product control** closes the loop in IPV: a mismarked borrow on a
  hard-to-borrow name shows up as persistent unexplained P&L against where
  the forwards trade.

## Summary of ownership

| Piece | Owner | Deliverable |
|---|---|---|
| Dividend forecast curve | Equity forwards / dividends desk | discrete dividends per ex-date → continuous `q_div` per expiry |
| Borrow rate | Securities lending / stock loan desk | GC vs special borrow cost per name |
| Implied carry check / final mark | Quant / strats | `r − q` implied from futures, forwards, put-call parity |
| `div_rho` Greek + `BorrDivPnl` | Pricing library / PAA engine | pure calculation on the inputs |
| Validation | Product control (IPV) | carry curve vs traded forwards |

## Modeling caveat

The continuous-`q` treatment in bs.py is the standard simplification for a
PAA engine. For short-dated options around a large discrete ex-date, desks
price with the discrete dividend explicitly (escrowed-dividend or
piecewise-forward models), because the continuous approximation misstates
early-exercise value on American calls and the gamma profile across the
ex-date.

## Related docs

- [OPTION-PRICE-SOURCES.md](OPTION-PRICE-SOURCES.md) — vendor vs internal prices and their official names
- [SNAPSHOT-COHERENCE.md](SNAPSHOT-COHERENCE.md) — attribution inputs must equal mark-time inputs
- [ARCHITECTURE.md](ARCHITECTURE.md) — team / data / calculation map
- [PAA-GRID.md](PAA-GRID.md) — where BorrDivPnl sits in the PAA grid
- [README.md](README.md) — project index
