# P&L Attribution Analysis (PAA) in Derivatives Trading

P&L Attribution Analysis (PAA) — also called "P&L explain" or "P&L decomposition" — is the process of breaking down a derivatives book's day-over-day P&L into its risk-factor drivers, so you can verify that the P&L you actually made is consistent with the risks you knew you were holding.

## The core idea

Each day, a derivatives position's value changes because of many things at once: the underlying moved, volatility moved, rates moved, a day of time decay passed, you traded, and so on. PAA answers:

```
Total P&L = Delta P&L + Gamma P&L + Vega P&L + Theta P&L + Rho P&L + ...   (explained)
          + New trades + Fees/Carry                                        (activity)
          + Residual                                                       (unexplained)
```

A small residual means your risk model captures reality; a large one means missing risk factors, stale marks, or a model problem. (Under FRTB, regulators formalize this as the "P&L Attribution test" comparing risk-theoretical P&L to hypothetical P&L.)

## Required source data

### 1. Position data (start of day)
- Instrument identifiers, trade economics (strike, expiry, notional, direction)
- Quantities/holdings as of prior close
- Trade lifecycle events during the day: new trades, amendments, cancellations, exercises, expiries, settlements

### 2. Market data — two snapshots (T-1 close and T close)
- Underlying prices (spot/futures)
- Implied volatility surfaces (per strike/expiry)
- Interest rate curves (discounting and forwarding)
- Dividend/repo/carry curves, FX rates if multi-currency
- Credit spreads for credit-sensitive products

### 3. Risk sensitivities (Greeks) computed at T-1 close
- Delta (Δ), Gamma (Γ), Vega (ν), Theta (Θ), Rho (ρ)
- Cross-Greeks (vanna, volga) for higher precision

### 4. Valuations
- Official mark-to-market at T-1 and T from the same pricing model
- Cash flows during the day: premiums paid/received, fees, commissions, funding, margin interest, coupons/dividends

## Method 1: Sensitivity-based (Taylor expansion / "Greeks explain")

Take the position's value `V(S, σ, r, t)` and expand the daily change:

```
ΔV ≈ Δ·δS                (Delta P&L)
   + ½·Γ·(δS)²           (Gamma P&L)
   + ν·δσ                (Vega P&L)
   + Θ·δt                (Theta P&L)
   + ρ·δr                (Rho P&L)
```

where:

- `δS = S_T − S_{T-1}` — change in the underlying
- `δσ` — change in implied vol (per point on the surface, or a parallel measure)
- `δt` — one day, in years (1/365 or 1/252 depending on convention)
- `δr` — change in the relevant rate

Then:

```
Unexplained = Actual P&L − Σ(Greek P&L terms) − New-trade P&L − Cash flows
```

New-trade P&L is computed separately: for each intraday trade, `(end-of-day mark − execution price) × quantity`.

### Worked example

Long 100 calls (contract multiplier 100), yesterday's Greeks per option: Δ = 0.55, Γ = 0.04, ν = 0.12 (per vol point), Θ = −0.06/day. Today: underlying +$2.00, implied vol +1.5 points.

| Component | Formula | P&L |
|---|---|---|
| Delta | 0.55 × 2.00 × 10,000 | +$11,000 |
| Gamma | ½ × 0.04 × 2.00² × 10,000 | +$800 |
| Vega | 0.12 × 1.5 × 10,000 | +$1,800 |
| Theta | −0.06 × 1 × 10,000 | −$600 |
| **Explained** | | **+$13,000** |

If the actual mark-to-market change was +$13,150, the unexplained residual is +$150 (~1%) — healthy. Persistent large residuals point at missing terms (vanna/volga, vol-surface skew moves, dividend changes).

## Method 2: Full revaluation waterfall ("step reval")

More accurate, standard for exotic books where Greeks are unreliable for large moves. You reprice the T-1 portfolio repeatedly, updating one market factor at a time in a fixed sequence:

1. `V0` = value with all T-1 market data (yesterday's official mark)
2. `V1` = roll the date to T only → **Theta/Carry P&L** = `V1 − V0`
3. `V2` = also update the underlying to T → **Price P&L (delta+gamma combined)** = `V2 − V1`
4. `V3` = also update the vol surface → **Vol P&L** = `V3 − V2`
5. `V4` = also update rate curves → **Rates P&L** = `V4 − V3`
6. Continue for FX, dividends, credit spreads…
7. `Vn` = all T market data → residual vs. official T mark is **unexplained** (should be ≈ 0 if the same model produces official marks)

Note the ordering matters (cross-effects get bundled into whichever factor moves later in the sequence); desks fix a convention and keep it stable, or symmetrize the cross terms.

## Assembling the full report

```
Total P&L = Explained (by method 1 or 2)
          + New-trade/amend P&L
          + Fees & commissions
          + Funding/carry cash flows
          + Unexplained
```

Typical desk tolerance: unexplained under ~5% of total P&L (or a fixed dollar threshold) — breaches get investigated for stale marks, missed trades, or model gaps. Under FRTB's PLA test, banks formally compare risk-theoretical P&L against hypothetical P&L using Spearman correlation and Kolmogorov–Smirnov statistics, and desks that fail lose internal-model approval.
