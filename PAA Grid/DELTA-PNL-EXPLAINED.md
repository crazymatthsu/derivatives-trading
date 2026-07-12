# DeltaPnl = PosScale × Δ × DSpot — The Formula Explained

A design note explaining the first-order term of the P&L attribution. It
answers: *"how much money did the position make purely because the
underlying moved, assuming the option responded linearly?"*

## The three factors

**Δ (delta)** — the option's price sensitivity, in **dollars per share, per
$1 move in the underlying**. The AAPL 220 call has Δ = 0.5118: if AAPL
rises $1, one share's worth of this option gains about $0.51. It is the
local slope of the option-price curve, computed by `bs_delta` at the **T-1
close market** (start-of-day delta — see conventions below).

**DSpot** — the underlying's actual move over the attribution window:
`DSpot = Spot − PrevSpot = 215.60 − 214.00 = +$1.60`. Note this is the
*stock's* move, not the option's — the whole point of the formula is to
translate a stock move into option P&L.

**PosScale** — the unit converter from "per share" to "position dollars":
`SODQty × Mult = 150 contracts × 100 shares = 15,000 shares` of exposure
(see [CONTRACT-MULTIPLIER.md](CONTRACT-MULTIPLIER.md)).

## The units chain

```
DeltaPnl = 15,000 shares × 0.5118 $/share per $1 × $1.60
         ≈ +$12,284

shares × (sensitivity per share per dollar) × dollars = dollars of P&L
```

Of DESK1's ~$21,711 actual P&L on this position
([MOCK-DATA-WALKTHROUGH.md](MOCK-DATA-WALKTHROUGH.md)), $12,284 is
attributed to "the stock went up and we were long delta."

## What it really is: the first term of a Taylor expansion

The exact P&L is the full change in option value, `V(S_new) − V(S_old)`.
The Taylor expansion around yesterday's spot is:

```
ΔV ≈ Δ·dS  +  ½Γ·dS²  +  (higher-order terms)
     ↑ DeltaPnl  ↑ GammaPnl
```

DeltaPnl is the **linear approximation** — it treats the option as if it
were a fixed block of `0.5118 × 15,000 ≈ 7,677` shares of stock for the
whole move.

That is also the hedging interpretation: if the desk had sold 7,677 shares
of AAPL against this position, DeltaPnl would be cancelled and only the
other terms (gamma, vega, theta, …) would remain — which is precisely what
"delta-hedged" means.

The linear treatment is why DeltaPnl alone is never the whole story: delta
itself changed during the move (from 0.5118 toward 0.53 as spot rallied),
and the money earned from *that* — delta being higher on average during the
rally than at its start — is the gamma term:
`½ × 15,000 × 0.00998 × 1.60² ≈ +$192`. Small here because $1.60 is a
small move. At the PAA grid's −20% shift, DeltaPnl is −318,770, the gamma
correction is +129,078, and even together they leave −7,768 unexplained —
the linear+quadratic approximation visibly breaking down at large moves
(see [PAA-GRID.md](PAA-GRID.md)).

## Two conventions baked into the formula

1. **Δ is the T-1 (start-of-day) delta**, not the current one. The
   attribution asks "given the risk we *knew we had* at yesterday's close,
   what did today's moves generate?" Using today's delta would answer a
   different question and would leak part of the gamma effect into the
   delta line (see [SOD-VS-LIVE-POSITION.md](SOD-VS-LIVE-POSITION.md)).
2. **DSpot must be the spot the pricer used** for the marks at both ends —
   otherwise the difference between "your spot" and "the pricer's spot"
   times delta lands in unexplained
   (see [SNAPSHOT-COHERENCE.md](SNAPSHOT-COHERENCE.md)).

## Sign intuition (cross-check)

- Long calls (Δ > 0) make money when spot rises.
- Long puts (Δ < 0) make money when spot falls.
- A short put position (negative qty × negative delta) gains on a rally —
  which is exactly why DESK1's −80 lot AAPL put position shows *positive*
  DeltaPnl (+$3,893) on the +$1.60 move.

## Where the formula lives

| Implementation | Location |
|---|---|
| Deephaven | `"DeltaPnl = PosScale * Delta * DSpot"` in [02_paa_engine.py](deephaven-paa/02_paa_engine.py) and (per shift) [05_paa_grid.py](deephaven-paa/05_paa_grid.py) |
| paa-cal | `delta_pnl = ps * g["delta"] * g["d_spot"]` in [engine.py](paa-cal/paa_cal/engine.py) and [grids.py](paa-cal/paa_cal/grids.py) |
| Delta itself | `bs_delta` / `delta()` in [bs.py](paa-cal/paa_cal/bs.py) — fully documented there |

## Related docs

- [PAA.md](PAA.md) — the full Taylor-expansion methodology
- [CONTRACT-MULTIPLIER.md](CONTRACT-MULTIPLIER.md) — PosScale and the multiplier
- [SOD-VS-LIVE-POSITION.md](SOD-VS-LIVE-POSITION.md) — why SOD quantities and Greeks
- [SNAPSHOT-COHERENCE.md](SNAPSHOT-COHERENCE.md) — why DSpot must match the pricer's spot
- [MOCK-DATA-WALKTHROUGH.md](MOCK-DATA-WALKTHROUGH.md) — all numbers used above
- [README.md](README.md) — project index
