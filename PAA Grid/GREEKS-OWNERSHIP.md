# Greeks Ownership — Who Provides Δ (and Every Other Greek), and How to Request Them

A design note answering: *which team should provide delta?* — extended to
the full Greek set used by this project, written so it can double as a
**data-request specification** to the owning team.

**Short answer: the quant/strats team.** Greeks are outputs of the pricing
model, and the non-negotiable requirement is that they come from **the same
model, calibrated to the same inputs, that produced the option marks.**

## Three roles behind "provide"

### 1. Who owns the number: quant/strats

Greeks are not market-observable — you cannot buy a delta feed from Activ
or Bloomberg the way you buy spot (vendor "Greeks" exist, but they are
computed off vendor mids with vendor assumptions and will not reprice your
marks). Greeks are model outputs: `bs.py` in this project, the quant
library in production. The quant team also owns the **convention choices**
hiding inside each number (see the per-Greek table below) — different
choices shift P&L between attribution lines, so the conventions must be
fixed and documented by whoever owns the model.

### 2. Who runs the computation: the risk technology / middle-office batch

For PAA, the Greeks in the attribution are **T-1 start-of-day** Greeks — so
operationally they are produced by the end-of-day risk batch: after product
control signs off the T-1 marks, the batch calls the quant library on the
official close snapshot and persists marks *and* Greeks together. That
persisted set is what `inst_prev` in
[02_paa_engine.py](deephaven-paa/02_paa_engine.py) mimics. The batch is
owned by risk tech, but it executes the quant team's library — it does not
compute Greeks its own way.

### 3. Who validates: product control and risk management

Product control's IPV covers the marks the Greeks derive from; risk
management consumes the Greeks and — via the PAA grid's unexplained column
— effectively audits whether the reported Greeks actually explain realized
P&L. Persistent unexplained tied to spot moves is the signature of a delta
convention problem (typically missing skew delta).

## Why this ownership is forced, not a preference

Per [SNAPSHOT-COHERENCE.md](SNAPSHOT-COHERENCE.md): `PrevPrice` and Δ must
be two outputs of **one pricing call**. If Greeks came from a different
team or system than the marks (e.g. a vendor analytics feed against
internal marks), the inconsistency lands straight in unexplained P&L, and
the 5% quality check in `paa_summary` would breach for reasons nobody could
fix. Greeks travel **with the mark**, in the pricing service's published
row — never recomputed downstream with different inputs.

## The full Greek set — definitions, units, and PAA usage

All conventions match [bs.py](paa-cal/paa_cal/bs.py) (fully documented
there) and the Deephaven engine.

| Greek | Definition | Units (as delivered) | Used in | Sign intuition |
|---|---|---|---|---|
| Delta (Δ) | dV/dS — price change per 1.00 spot move | per share, −1…+1 | `DeltaPnl = PosScale × Δ × dS`; hedge ratio on the risk grid | calls +, puts − |
| Gamma (Γ) | d²V/dS² — delta change per 1.00 spot move | per share per 1.00 | `GammaPnl = ½ × PosScale × Γ × dS²` | long options always + |
| Vega | dV/dσ — price change per vol change | per 1.00 vol (= 100 vol pts); ÷100 for per-point | `VegaPnl = PosScale × vega × dσ` | long options always + |
| Theta (θ) | dV/dt — time decay | per YEAR; ÷252 for per-trading-day | `ThetaPnl = PosScale × θ × 1/252` | long options usually − |
| Rho (ρ) | dV/dr — rate sensitivity | per 1.00 (= 10,000 bp); ÷10,000 for per-bp | `RhoPnl = PosScale × ρ × dr` | calls +, puts − |
| Div rho (∂V/∂q) | carry (dividend + borrow) sensitivity | per 1.00 change in q | `BorrDivPnl = PosScale × ∂V/∂q × dq` | calls −, puts + (mirror of rho) |
| Volga (vomma) | d²V/dσ² — vega change per vol change | per 1.00² vol | `VolgaPnl = ½ × PosScale × volga × dσ²` (PAA grid) | + away from ATM, ≈0 ATM |
| Vanna | d²V/dS dσ — cross spot/vol | per 1.00 spot × 1.00 vol | recommended extension: `VannaPnl = PosScale × vanna × dS × dσ` — shrinks wing unexplained ([PAA-GRID.md](PAA-GRID.md)) | sign follows skew exposure |

## Convention decisions to agree per Greek (the fine print of the request)

These are the questions to settle with the quant team **before** consuming
the feed — each one moves P&L between attribution lines:

| Greek | Decisions to pin down |
|---|---|
| Delta | Raw BS delta or **smile/skew-adjusted** (sticky-strike vs sticky-delta — does vol move when spot moves)? Spot or forward delta? Premium-adjusted (relevant for non-USD-premium conventions)? |
| Gamma | Same smile treatment as delta; confirm it is d(delivered delta)/dS, not raw BS gamma paired with a smile delta |
| Vega | Parallel-surface vega or bucketed by expiry/strike? Per 1.00 or per vol point as delivered? Against which surface parameterization (SVI etc.)? |
| Theta | Calendar-day or trading-day roll? Does it include carry/funding (rates and dividend accrual) or pure vol decay — i.e. does theta overlap with rho/borrDiv terms? |
| Rho | Parallel shift of which curve (discounting vs forwarding)? Per bp or per 1.00 as delivered? |
| Div rho | Against continuous yield q or discrete dividend bumps? Dividend and borrow split into two sensitivities or combined ([BORRDIV-OWNERSHIP.md](BORRDIV-OWNERSHIP.md))? |
| Volga / vanna | Delivered at all? Same bump sizes/conventions as vega? |
| All | Bump-and-reprice or analytic? If bumped: bump sizes, one-sided or centered? |

## The data-request specification

Ask the quant pricing service for **one row per instrument per snapshot**,
Greeks always published together with the mark and the inputs that produced
them:

```
instrument_id, snap_time, snap_type (EOD_OFFICIAL | INTRADAY),
mark,
delta, gamma, vega, theta, rho, div_rho, volga, vanna,
spot_used, vol_used, rate_used, div_used, borrow_used, ttm_used,
model_id / model_version
```

Two snapshots are required for PAA:

1. **T-1 EOD official** — computed on the product-control-signed close;
   feeds `inst_prev` (all attribution Greeks come from here).
2. **Live intraday** — at minimum the mark (`CurrPrice`); Greeks too if
   the risk grid should show live rather than SOD sensitivities.

Non-negotiables in the request:

- Greeks and mark from **one pricing call** (same inputs row) — never
  assembled from separate runs.
- Inputs (`*_used` columns) published alongside, so attribution consumes
  the pricer's inputs, not re-sourced market data.
- `model_version` included — a model change mid-window is itself a PAA
  line item (model P&L), not something to smear into unexplained.
- Conventions from the table above documented once and kept stable;
  convention changes announced like model changes.

## Where this appears in this project

| Production role | This project |
|---|---|
| Quant pricing library | [bs.py](paa-cal/paa_cal/bs.py) / BS functions in [02_paa_engine.py](deephaven-paa/02_paa_engine.py) |
| EOD risk batch output (mark + Greeks on official close) | `inst_prev` table |
| Intraday pricing service | `inst_now` table |
| The published-inputs rule | `spot_prev/vol_prev/...` feeding both mark and Greeks in one `update()` |

## Related docs

- [SNAPSHOT-COHERENCE.md](SNAPSHOT-COHERENCE.md) — why Greeks must share the mark's inputs
- [BORRDIV-OWNERSHIP.md](BORRDIV-OWNERSHIP.md) — ownership of the carry input feeding div_rho
- [OPTION-PRICE-SOURCES.md](OPTION-PRICE-SOURCES.md) — where the marks themselves come from
- [SOD-VS-LIVE-POSITION.md](SOD-VS-LIVE-POSITION.md) — why PAA uses T-1 (SOD) Greeks
- [DELTA-PNL-EXPLAINED.md](DELTA-PNL-EXPLAINED.md) — the delta term in depth
- [ARCHITECTURE.md](ARCHITECTURE.md) — team / data / calculation map
- [README.md](README.md) — project index
