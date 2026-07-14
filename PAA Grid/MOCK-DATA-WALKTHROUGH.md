# Mock Data Walkthrough — Every Value from Tier 1 to Tier 3, with Formulas

End-to-end trace of the architecture in [ARCHITECTURE.md](ARCHITECTURE.md)
using the sample data from the scripts. Every number below was computed with
the same Black-Scholes functions as
[02_paa_engine.py](deephaven-paa/02_paa_engine.py), so you can reproduce,
debug, and fine-tune any step.

Conventions: valuation date T = 2026-07-11; live spot frozen at the
simulator base values (the ticking `spot_live` wobbles around these);
multiplier = 100 for all options; base currency USD.

---

## Tier 1 — Teams and the values they publish

### Market data tech (vendor feeds: Activ / B-PIPE / Elektron over OPRA)

| Feed | AAPL | MSFT | SAP |
|---|---|---|---|
| Live spot | 215.60 | 495.25 | 252.40 |

| FX (USD per 1 ccy) | USD | EUR |
|---|---|---|
| Live | 1.0000 | 1.0820 |

### Quant / strats (marked vol surface, per instrument)

| Instrument | Live implied vol |
|---|---|
| AAPL_C220_DEC26 | 0.292 |
| AAPL_P200_DEC26 | 0.318 |
| MSFT_C500_SEP26 | 0.249 |
| MSFT_P480_SEP26 | 0.296 |
| SAP_C260_DEC26 | 0.246 |
| SAP_P240_SEP26 | 0.271 |

### Quant / strats — pricing service publication (marks + Greeks feed)

In production the quant pricing service also publishes marks **and Greeks
together** as Tier-1 data, in the request-spec shape of
[GREEKS-OWNERSHIP.md](GREEKS-OWNERSHIP.md). These mock values are fully
known — Greeks are deterministic outputs of (model, inputs), and this is
what the service would publish running Black-Scholes on the snapshots
above (`model_version = BS-1.0`).

`snap_type = EOD_OFFICIAL` (computed on product control's T-1 close —
feeds `inst_prev`):

| instrument_id | mark | delta | gamma | vega | theta | rho | div_rho | volga |
|---|---|---|---|---|---|---|---|---|
| AAPL_C220_DEC26 | 14.7477 | 0.5118 | 0.00998 | 56.62 | −21.36 | 41.93 | −48.45 | −1.01 |
| AAPL_P200_DEC26 | 9.5935 | −0.3041 | 0.00792 | 49.73 | −14.62 | −33.03 | 28.79 | 24.94 |
| MSFT_C500_SEP26 | 20.0595 | 0.4919 | 0.00722 | 86.19 | −64.57 | 42.89 | −46.76 | 0.82 |
| MSFT_P480_SEP26 | 17.5202 | −0.3745 | 0.00604 | 81.94 | −54.37 | −38.99 | 35.60 | 17.20 |
| SAP_C260_DEC26 | 12.5070 | 0.4519 | 0.00983 | 65.73 | −18.66 | 44.64 | −50.18 | 8.46 |
| SAP_P240_SEP26 | 6.9350 | −0.3264 | 0.01187 | 39.69 | −27.28 | −17.15 | 15.81 | 21.08 |

The `*_used` input columns of this feed equal product control's T-1
snapshot exactly (spot_used = 214.00 for AAPL, vol_used = 0.280, …) —
that equality is the snapshot-coherence requirement of
[SNAPSHOT-COHERENCE.md](SNAPSHOT-COHERENCE.md), not a coincidence.

`snap_type = INTRADAY` (live marks — feeds `inst_now`):

| instrument_id | mark | spot_used | vol_used |
|---|---|---|---|
| AAPL_C220_DEC26 | 16.1951 | 215.60 | 0.292 |
| AAPL_P200_DEC26 | 9.4354 | 215.60 | 0.318 |
| MSFT_C500_SEP26 | 20.6775 | 495.25 | 0.249 |
| MSFT_P480_SEP26 | 16.7675 | 495.25 | 0.296 |
| SAP_C260_DEC26 | 13.4718 | 252.40 | 0.246 |
| SAP_P240_SEP26 | 6.2286 | 252.40 | 0.271 |

> **Demo vs production:** in this project the engine *computes* these
> numbers itself (bs.py / script 02 plays the quant team's role), so they
> appear again in Tier 3 Step 02-a/02-b as derived data — and match this
> feed to the digit. In production the engine would *consume* this feed as
> raw source data and skip the computation; either way every downstream
> P&L number is identical.

### Rates & dividends team

| | USD | EUR | | AAPL | MSFT | SAP |
|---|---|---|---|---|---|---|
| Live rate | 0.0425 | 0.0248 | Live div/borrow yield | 0.0050 | 0.0072 | 0.0148 |

### Trading desk (OMS/EMS) — today's executions

| ExecId | Book | Instrument | Side | Qty | Price |
|---|---|---|---|---|---|
| EX-1 | DESK1 | AAPL_C220_DEC26 | BUY | 15 | 12.45 |
| EX-2 | DESK1 | AAPL_C220_DEC26 | BUY | 10 | 12.55 |
| EX-3 | DESK1 | MSFT_C500_SEP26 | SELL | 15 | 21.10 |
| EX-4 | DESK2 | SAP_C260_DEC26 | BUY | 20 | 14.75 |
| EX-5 | DESK2 | SAP_C260_DEC26 | BUY | 10 | 14.85 |

(Plus `orders` ORD-1001…1004 — audit context only, not used in P&L.)

### Operations / middle office — reconciled SOD positions & security master

| Book | Instrument | SODQty | | Instrument terms | Type | Strike | Expiry | Ccy |
|---|---|---|---|---|---|---|---|---|
| DESK1 | AAPL_C220_DEC26 | +150 | | AAPL_C220_DEC26 | CALL | 220 | 2026-12-18 | USD |
| DESK1 | AAPL_P200_DEC26 | −80 | | AAPL_P200_DEC26 | PUT | 200 | 2026-12-18 | USD |
| DESK1 | MSFT_C500_SEP26 | +60 | | MSFT_C500_SEP26 | CALL | 500 | 2026-09-18 | USD |
| DESK2 | MSFT_P480_SEP26 | −40 | | MSFT_P480_SEP26 | PUT | 480 | 2026-09-18 | USD |
| DESK2 | SAP_C260_DEC26 | +120 | | SAP_C260_DEC26 | CALL | 260 | 2026-12-18 | EUR |
| DESK2 | SAP_P240_SEP26 | −55 | | SAP_P240_SEP26 | PUT | 240 | 2026-09-18 | EUR |

### Product control — T-1 official close snapshot

| | AAPL | MSFT | SAP | | USD | EUR |
|---|---|---|---|---|---|---|
| Prev spot | 214.00 | 492.50 | 251.00 | Prev rate | 0.0420 | 0.0250 |
| Prev div yield | 0.0050 | 0.0070 | 0.0150 | Prev FX | 1.0000 | 1.0750 |

| Instrument | Prev implied vol |
|---|---|
| AAPL_C220_DEC26 / P200 | 0.280 / 0.310 |
| MSFT_C500 / P480 | 0.255 / 0.290 |
| SAP_C260 / P240 | 0.240 / 0.275 |

---

## Tier 2 — Deephaven keyed source tables (01)

Tier 1 values land unchanged in keyed tables; only the shape changes:

| Table | Key | Provider (Tier 1) | Values |
|---|---|---|---|
| `spot_prev` / `spot_live` | Underlying | Product control / Market data tech | 214.00→215.60, 492.50→495.25, 251.00→252.40 |
| `vol_prev` / `vol_live` | InstrumentId | Product control / Quant | e.g. AAPL_C220: 0.280→0.292 |
| `rates_prev` / `rates_live` | Currency | Product control / Rates team | USD 0.0420→0.0425, EUR 0.0250→0.0248 |
| `div_prev` / `div_live` | Underlying | Product control / Rates team | e.g. MSFT 0.0070→0.0072 |
| `fx_prev` / `fx_live` | Currency | Product control / Market data tech | EUR 1.0750→1.0820 |
| `instrument` | InstrumentId | Operations (security master) | terms table above |
| `book_position` | Book, InstrumentId | Operations (SOD recon) | qty table above |
| `orders` / `executions` | OrderId / ExecId | Trading desk OMS | fills table above |

---

## Tier 3 — Calculations, step by step

### Step 02-a: `inst_prev` — T-1 marks and Greeks

In this demo these are **computed** here; in production they **arrive** as
the quant team's EOD_OFFICIAL feed shown in Tier 1 — the numbers are
identical by construction.

Formulas (all at **prev** market, `TtmPrev = Ttm + 1/252`):

```
Ttm      = days(AS_OF → Expiry) / 365
PrevPrice = BS(PrevSpot, K, TtmPrev, PrevRate, PrevDiv, PrevVol, C/P)
Delta, Gamma, Vega, Theta, Rho, DivRho, Volga = BS Greeks (same inputs)
```

| Instrument | Ttm | PrevPrice | Delta | Gamma | Vega | Theta | Rho | DivRho | Volga |
|---|---|---|---|---|---|---|---|---|---|
| AAPL_C220_DEC26 | 0.4384 | 14.7477 | 0.5118 | 0.00998 | 56.62 | −21.36 | 41.93 | −48.45 | −1.01 |
| AAPL_P200_DEC26 | 0.4384 | 9.5935 | −0.3041 | 0.00792 | 49.73 | −14.62 | −33.03 | 28.79 | 24.94 |
| MSFT_C500_SEP26 | 0.1890 | 20.0595 | 0.4919 | 0.00722 | 86.19 | −64.57 | 42.89 | −46.76 | 0.82 |
| MSFT_P480_SEP26 | 0.1890 | 17.5202 | −0.3745 | 0.00604 | 81.94 | −54.37 | −38.99 | 35.60 | 17.20 |
| SAP_C260_DEC26 | 0.4384 | 12.5070 | 0.4519 | 0.00983 | 65.73 | −18.66 | 44.64 | −50.18 | 8.46 |
| SAP_P240_SEP26 | 0.1890 | 6.9350 | −0.3264 | 0.01187 | 39.69 | −27.28 | −17.15 | 15.81 | 21.08 |

(Vega/Rho/DivRho per 1.00; Theta per year; Volga per 1.00².)

### Step 02-b: `inst_now` — live marks

`CurrPrice = BS(Spot, K, Ttm, Rate, Div, Vol, C/P)` at **live** market:

| Instrument | CurrPrice | | Market moves | DSpot | DVol | DRate | DDiv |
|---|---|---|---|---|---|---|---|
| AAPL_C220_DEC26 | 16.1951 | | AAPL / USD | +1.60 | +0.012 | +0.0005 | 0.0000 |
| AAPL_P200_DEC26 | 9.4354 | | AAPL / USD | +1.60 | +0.008 | +0.0005 | 0.0000 |
| MSFT_C500_SEP26 | 20.6775 | | MSFT / USD | +2.75 | −0.006 | +0.0005 | +0.0002 |
| MSFT_P480_SEP26 | 16.7675 | | MSFT / USD | +2.75 | +0.006 | +0.0005 | +0.0002 |
| SAP_C260_DEC26 | 13.4718 | | SAP / EUR | +1.40 | +0.006 | −0.0002 | −0.0002 |
| SAP_P240_SEP26 | 6.2286 | | SAP / EUR | +1.40 | −0.004 | −0.0002 | −0.0002 |

### Step 02-c: `trade_pnl` — intraday fills marked to current price

```
NewTradePnl = Mult × (TradedQty × CurrPrice − TradedCost)
```

| Book | Instrument | TradedQty | TradedCost | NewTradePnl |
|---|---|---|---|---|
| DESK1 | AAPL_C220_DEC26 | +25 | 312.25 | +9,262.69 |
| DESK1 | MSFT_C500_SEP26 | −15 | −316.50 | +633.80 |
| DESK2 | SAP_C260_DEC26 | +30 | 443.50 | −3,934.71 |

Traced (DESK1 AAPL_C220): cost = 15×12.45 + 10×12.55 = 312.25;
NewTradePnl = 100 × (25 × 16.1951 − 312.25) ≈ **+9,262.69**.

### Step 02-d: `paa` — the attribution table

```
PosScale = SODQty × Mult
DeltaPnl = PosScale × Δ × DSpot          GammaPnl = ½ × PosScale × Γ × DSpot²
VegaPnl  = PosScale × vega × DVol        ThetaPnl = PosScale × θ × (1/252)
RhoPnl   = PosScale × ρ × DRate          DivPnl   = PosScale × DivRho × DDiv
Explained = Σ above                      Actual   = PosScale × (Curr − Prev)
Unexplained = Actual − Explained         FxPnl    = PosScale × Prev × (FX − PrevFX)
TotalBase = (Actual + NewTrade) × FX + FxPnl
```

| Book | Instrument | Qty | DeltaPnl | GammaPnl | VegaPnl | ThetaPnl | RhoPnl | DivPnl | Explained | Actual | Unexpl | NewTrade | FxPnl | TotalBase |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DESK1 | AAPL_C220 | +150 | 12,284 | 192 | 10,192 | −1,271 | 314 | 0 | 21,711 | 21,711 | −0.5 | 9,263 | 0 | 30,974 |
| DESK1 | AAPL_P200 | −80 | 3,893 | −81 | −3,183 | 464 | 132 | 0 | 1,225 | 1,265 | +39.3 | 0 | 0 | 1,265 |
| DESK1 | MSFT_C500 | +60 | 8,117 | 164 | −3,103 | −1,537 | 129 | −56 | 3,713 | 3,708 | −5.2 | 634 | 0 | 4,341 |
| DESK2 | MSFT_P480 | −40 | 4,120 | −91 | −1,967 | 863 | 78 | −28 | 2,975 | 3,010 | +35.9 | 0 | 0 | 3,010 |
| DESK2 | SAP_C260 | +120 | 7,592 | 116 | 4,733 | −888 | −107 | 120 | 11,566 | 11,578 | +11.8 | −3,935 | 1,051 | 9,320 |
| DESK2 | SAP_P240 | −55 | 2,513 | −64 | 873 | 595 | −19 | 17 | 3,916 | 3,885 | −30.8 | 0 | −267 | 3,937 |

Traced (DESK1 AAPL_C220, PosScale = 150 × 100 = 15,000):

```
DeltaPnl = 15,000 × 0.5118 × 1.60            ≈ +12,284
GammaPnl = ½ × 15,000 × 0.00998 × 1.60²      ≈ +192
VegaPnl  = 15,000 × 56.62 × 0.012            ≈ +10,192
ThetaPnl = 15,000 × (−21.36) / 252           ≈ −1,271
RhoPnl   = 15,000 × 41.93 × 0.0005           ≈ +314
DivPnl   = 15,000 × (−48.45) × 0.0000        = 0
Explained                                     ≈ +21,711
Actual   = 15,000 × (16.1951 − 14.7477)      ≈ +21,711  → Unexplained ≈ −0.5 ✓
```

FX example (DESK2 SAP_C260, EUR book): FxPnl = 12,000 × 12.5070 ×
(1.0820 − 1.0750) ≈ +1,051 USD; TotalBase = (11,578 − 3,935) × 1.0820 +
1,051 ≈ +9,320 USD.

### Step 03: roll-ups and summary

| Book | Explained | Actual | Unexplained | % of \|actual\| | Flag | NewTrade | TotalBase |
|---|---|---|---|---|---|---|---|
| DESK1 | 26,649 | 26,683 | +33.6 | 0.13% | OK | +9,897 | 36,579 |
| DESK2 | 18,457 | 18,474 | +16.9 | 0.09% | OK | −3,935 | 16,268 |

### Step 04: Risk Grid (AAPL_C220_DEC26, live market, sample shifts)

```
ShiftedSpot = Spot × (1+s)    Forward = ShiftedSpot × e^((r−q)T)
Theo & Greeks = BS at ShiftedSpot     ScenarioPnl = PosScale × (Theo − BaseTheo)
```

| Shift | ShiftedSpot | Forward | Theo | Delta | Gamma | Vega | Theta | ScenarioPnl (150 lots) |
|---|---|---|---|---|---|---|---|---|
| −5% | 204.82 | 208.21 | 11.0492 | 0.4245 | 0.00988 | 53.04 | −20.45 | −77,188 |
| 0% | 215.60 | 219.17 | 16.1951 | 0.5296 | 0.00952 | 56.65 | −22.46 | 0 |
| +5% | 226.38 | 230.13 | 22.4421 | 0.6278 | 0.00861 | 56.51 | −23.20 | +93,705 |

Note the Greeks are **recomputed at each shifted spot** — delta rises from
0.42 to 0.63 across the ladder.

### Step 05: PAA Grid (DESK1 AAPL_C220_DEC26, 150 lots, sample shifts)

```
DSpot = ShiftedSpot − PrevSpot;  T-1 Greeks fixed;  dσ/dr/dq = actual moves
VolgaPnl = ½ × PosScale × volga × dσ²;  Actual = PosScale × (BS(ShiftedSpot) − Prev)
```

| Shift | ShiftedSpot | DSpot | Delta | Gamma | Time | Vega | Volga | BorrDiv | Rate | Explained | Actual | Unexplained |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| −5% | 204.82 | −9.18 | −70,479 | +6,310 | −1,271 | +10,192 | −1 | 0 | +314 | −54,935 | −55,477 | −542 |
| 0% | 215.60 | +1.60 | +12,284 | +192 | −1,271 | +10,192 | −1 | 0 | +314 | +21,710 | +21,711 | +1 |
| +5% | 226.38 | +12.38 | +95,047 | +11,476 | −1,271 | +10,192 | −1 | 0 | +314 | +115,758 | +115,416 | −342 |

Note the pattern: **unexplained ≈ 0 at the 0% row** (reproduces live PAA)
and grows in the wings (−542 / −342) — the Taylor error the PAA grid exists
to measure. The identity vs the Risk Grid also checks out:
Actual(+5%) = ScenarioPnl(+5%) + Actual(0%) → 93,705 + 21,711 = 115,416 ✓.

---

## Debugging guide — which step to check when a number looks wrong

| Symptom | Check |
|---|---|
| PrevPrice ≠ official T-1 mark | Tier 1 product control snapshot; is `vol_prev` the marked vol? ([SNAPSHOT-COHERENCE.md](SNAPSHOT-COHERENCE.md)) |
| Big DeltaPnl surprise | DSpot inputs — same spot as the pricer used? |
| Unexplained large at 0% shift | Input mismatch (spot/vol snap incoherence) or missing Greek term |
| Unexplained large only in wings | Expected Taylor error — consider adding vanna |
| NewTradePnl looks off | `executions` rows: side sign, qty, cost = Σ qty×price |
| Book totals off in USD | FX columns: FxPnl uses PrevPrice, conversion uses live FX |

Reproduce all numbers with the standalone calculator in
[paa-cal/](paa-cal/README.md): `cd paa-cal && python3 run_paa.py all`. Its
inputs ship with the exact values above (live spot fixed at
215.60 / 495.25 / 252.40), and every figure in this document falls out.
