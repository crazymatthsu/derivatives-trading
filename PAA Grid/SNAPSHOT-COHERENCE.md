# Snapshot Coherence — Matching Spot to the Spot Used in the Option Mark

A design note answering: *when calculating PAA, do I need to match the
underlying spot price with the spot price used to calculate the option's
current price?*

**Short answer: yes — strictly.** The spot used for `DSpot` in the
attribution must be **the exact same spot that was fed into the pricing
model that produced the option's mark**, at both ends of the window (T-1
and now). Any mismatch does not just add noise — it manufactures fake
unexplained P&L in a predictable way.

## Why the mismatch shows up directly in unexplained

The PAA identity is:

```
Unexplained = [CurrPrice − PrevPrice] − [Δ·dS + ½Γ·dS² + vega·dσ + …]
```

The left side is driven by the spot the *pricer* saw; the right side by the
spot the *attribution* saw. If they differ by ε (say the pricer marked the
option at spot 214.95 but the attribution snapped spot at 215.05), the
residual picks up approximately **Δ × ε per option** — pure artifact.

On a large delta book, a few cents of spot incoherence produces
"unexplained" that swamps the genuine model residual you are trying to
monitor, and the 5% quality check in `paa_summary`
([03_paa_rollups.py](deephaven-paa/03_paa_rollups.py)) breaches for no real
reason.

## Why the Deephaven engine is coherent by construction

In this project's engine, coherence is automatic:

- `CurrPrice` in `inst_now` and `DSpot` in `paa`
  ([02_paa_engine.py](deephaven-paa/02_paa_engine.py)) both reference the
  same `Spot` column from the same `spot_live` row;
- Deephaven's update graph applies each cycle transactionally, so within
  any tick, pricer and attribution see identical inputs;
- at the T-1 end, `PrevPrice` is computed *from* `PrevSpot`, so they cannot
  diverge.

## Where it breaks in production

The problem appears when the option mark and the spot are sourced
**independently** — the normal situation on a real desk:

- **Asynchronous ticks.** The option mark was generated when the quant
  library last ran (spot = 214.95 at 14:03:07.2), but the PAA job snaps
  spot from the vendor feed at 14:03:09.8 (215.05). Fix: build a
  **coherent market snapshot** — an atomic snap where the spot recorded is
  the spot the pricing run actually consumed, not a fresh read.
- **Marks that are not model prices.** If `CurrPrice` is a market-observed
  number (quote mid, settlement), there is no explicit "spot input" — but
  the quoted price embeds the market's spot at quote time. Pair it with
  spot from the same timestamp. At EOD this mostly resolves itself because
  exchanges align them: option settlements are computed off the official
  underlying close.
- **Surface-fitting spot.** When marks come off a fitted vol surface, the
  surface was calibrated with a specific spot (the "fit spot" / surface
  anchor). Best practice: the pricing service **publishes the inputs
  alongside the mark** — spot, vol, rate, div, timestamp — and PAA consumes
  those published inputs rather than re-sourcing them.

The rule: **attribution inputs = mark-time pricing inputs — recorded, never
re-fetched.**

## The same rule applies to every input, not just spot

This is the general snapshot-coherence principle:

- the vol in the vega term must be the vol that reprices the mark (the
  marked vol — see [OPTION-PRICE-SOURCES.md](OPTION-PRICE-SOURCES.md));
- the rate in the rho term must be the curve the pricer discounted with;
- the dividend/borrow in the borrDiv term must be the carry the pricer used.

A clean mental model: **PAA does not explain "the market's move" — it
explains "the move in the pricer's inputs."** Whenever those two drift
apart, the drift must either be eliminated (coherent snaps) or measured (a
separate "input alignment" P&L line) — never silently absorbed into delta
or unexplained.

## Practical implication for the production data model

The valuation feed should carry the mark **and its inputs as one row**:

```
(Mark, SpotUsed, VolUsed, RateUsed, DivUsed, SnapTime)
```

The `spot_live`-equivalent for PAA purposes is then `SpotUsed` from that
row — **not** an independent subscription to the underlying feed. The
underlying feed remains the right source for trading/execution systems; PAA
specifically needs the pricer's view.

## Related docs

- [PAA.md](PAA.md) — PAA methodology (Taylor explain, step reval, source data)
- [PAA-GRID.md](PAA-GRID.md) — PAA Grid formulas, tables, and conventions
- [RISK-GRID-VS-PAA-GRID.md](RISK-GRID-VS-PAA-GRID.md) — Risk Grid vs PAA Grid
- [TRADE-PNL-VS-COST-PNL.md](TRADE-PNL-VS-COST-PNL.md) — why trade P&L is marked from exec price
- [SOD-VS-LIVE-POSITION.md](SOD-VS-LIVE-POSITION.md) — which position snapshot each calculation uses
- [OPTION-PRICE-SOURCES.md](OPTION-PRICE-SOURCES.md) — vendor vs internal prices and their official names
- [README.md](README.md) — project index, run order, data classification
