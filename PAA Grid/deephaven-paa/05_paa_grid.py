"""
PAA engine — Step 5: PAA Grid (P&L attribution across a spot ladder).

Where 04_risk_grid.py shows GREEKS at each spot shift, this grid shows the
ATTRIBUTED P&L at each spot shift: for every ladder level, the predicted
T-1 -> scenario P&L is decomposed into Taylor components using the
start-of-day (T-1) Greeks from 02_paa_engine.py:

  Spot shift % | shifted spot | delta | gamma | time | vega | volga
               | borrDiv | rate | explained | actual (full reval) | unexplained

Scenario definition per grid row:
  - Spot moves from PrevSpot to ShiftedSpot = live Spot x (1 + shift);
    the 0% row therefore reproduces today's live PAA (plus the volga term).
  - Vol, rate and borrow/dividend moves are the ACTUAL live T-1 -> T
    changes (same at every ladder level); time rolls one trading day.
  - ActualPnl is a full revaluation at the shifted spot with live
    vol/rate/div, so UnexplainedPnl shows the Taylor expansion degrading
    as the shift grows (residual gamma/higher-order terms).

BorrDiv: the q input is the combined carry yield (dividend + stock borrow).
If borrow is sourced separately, extend div_prev/div_live with a
BorrowRate column and feed q = DivYield + BorrowRate; the attribution
formula is unchanged.

Tables produced:

  paa_shift               — ladder definition
  paa_grid_inst           — per-option grid: instrument x shift
  paa_grid                — THE OUTPUT: position-scaled grid per
                            (Book, Instrument, shift), local + base ccy
  paa_grid_by_underlying  — sums per (Book, Underlying, shift)
  paa_grid_by_book        — sums per (Book, shift)
  paa_grid_firm           — firm-wide ladder per shift
  paa_grid_rollup         — Book -> Underlying -> Instrument tree per shift

Run order: 01 -> 02 -> 05 (03/04 independent). Reuses `risk` (T-1 Greeks
incl. Volga + live market) and the BS functions from 02; ticks with
spot_live.
"""

from deephaven import new_table, agg
from deephaven.column import double_col

# ---------------------------------------------------------------- ladder
_PAA_SHIFTS_PCT = [-20.0, -15.0, -10.0, -5.0, -2.0, -1.0, 0.0,
                   1.0, 2.0, 5.0, 10.0, 15.0, 20.0]

paa_shift = new_table([
    double_col("SpotShiftPct", _PAA_SHIFTS_PCT),
]).update("SpotShift = SpotShiftPct / 100.0")

# ------------------------------------------------- per-option PAA grid
# `risk` carries the T-1 Greeks (Delta, Gamma, Vega, Volga, Theta, Rho,
# DivRho), the T-1 mark (PrevPrice) and live market (Spot, Vol, Rate,
# DivYield). Cross join fans each instrument across the ladder.
paa_grid_inst = (
    risk
    .join(paa_shift)  # no `on` => cross join: instrument x shift
    .update([
        "ShiftedSpot = Spot * (1.0 + SpotShift)",
        # factor moves for this scenario
        "DSpot = ShiftedSpot - PrevSpot",
        "DVol = Vol - PrevVol",
        "DRate = Rate - PrevRate",
        "DDiv = DivYield - PrevDivYield",
        # ---- Taylor attribution per option (T-1 Greeks) ----
        "DeltaPnl = Delta * DSpot",
        "GammaPnl = 0.5 * Gamma * DSpot * DSpot",
        "TimePnl = Theta * DT_DAY",
        "VegaPnl = Vega * DVol",
        "VolgaPnl = 0.5 * Volga * DVol * DVol",
        "BorrDivPnl = DivRho * DDiv",
        "RatePnl = Rho * DRate",
        "ExplainedPnl = DeltaPnl + GammaPnl + TimePnl + VegaPnl"
        "    + VolgaPnl + BorrDivPnl + RatePnl",
        # ---- full revaluation at the shifted spot ----
        "TheoAtShift = bs_price(ShiftedSpot, Strike, Ttm, Rate, DivYield, Vol, OptionType)",
        "ActualPnl = TheoAtShift - PrevPrice",
        "UnexplainedPnl = ActualPnl - ExplainedPnl",
    ])
    .view([
        "InstrumentId", "Underlying", "OptionType", "Strike", "Expiry",
        "Currency", "Multiplier",
        "SpotShiftPct", "ShiftedSpot", "TheoAtShift",
        "DeltaPnl", "GammaPnl", "TimePnl", "VegaPnl", "VolgaPnl",
        "BorrDivPnl", "RatePnl",
        "ExplainedPnl", "ActualPnl", "UnexplainedPnl",
    ])
    .sort(["InstrumentId", "SpotShiftPct"])
)

# --------------------------------------------- position-scaled PAA grid
_PAA_GRID_COMPONENTS = [
    "DeltaPnl", "GammaPnl", "TimePnl", "VegaPnl", "VolgaPnl",
    "BorrDivPnl", "RatePnl", "ExplainedPnl", "ActualPnl", "UnexplainedPnl",
]

# join (not natural_join): each position fans out across the ladder rows.
paa_grid = (
    book_position
    .join(paa_grid_inst, on=["InstrumentId"])
    .natural_join(fx_live, on=["Currency"])
    .update(["PosScale = SODQty * Multiplier"]
            # scale every per-option component in place
            + [f"{c} = PosScale * {c}" for c in _PAA_GRID_COMPONENTS]
            # base-ccy (USD) headline columns for cross-currency roll-ups
            + [
                "ExplainedPnlBase = ExplainedPnl * FxRate",
                "ActualPnlBase = ActualPnl * FxRate",
                "UnexplainedPnlBase = UnexplainedPnl * FxRate",
            ])
    .view([
        "Book", "InstrumentId", "Underlying", "Currency", "SODQty",
        "SpotShiftPct", "ShiftedSpot",
        "DeltaPnl", "GammaPnl", "TimePnl", "VegaPnl", "VolgaPnl",
        "BorrDivPnl", "RatePnl",
        "ExplainedPnl", "ActualPnl", "UnexplainedPnl",
        "ExplainedPnlBase", "ActualPnlBase", "UnexplainedPnlBase",
    ])
    .sort(["Book", "InstrumentId", "SpotShiftPct"])
)

# --------------------------------------------------------------- roll-ups
_PAA_GRID_SUM_COLS = _PAA_GRID_COMPONENTS + [
    "ExplainedPnlBase", "ActualPnlBase", "UnexplainedPnlBase",
]
_paa_grid_aggs = [agg.sum_(_PAA_GRID_SUM_COLS), agg.count_("NumPositions")]

paa_grid_by_underlying = (
    paa_grid
    .agg_by(_paa_grid_aggs, by=["Book", "Underlying", "SpotShiftPct"])
    .sort(["Book", "Underlying", "SpotShiftPct"])
)

paa_grid_by_book = (
    paa_grid
    .agg_by(_paa_grid_aggs, by=["Book", "SpotShiftPct"])
    .sort(["Book", "SpotShiftPct"])
)

paa_grid_firm = (
    paa_grid
    .agg_by(_paa_grid_aggs, by=["SpotShiftPct"])
    .sort(["SpotShiftPct"])
)

# Hierarchical tree per shift: expand Book -> Underlying -> Instrument.
paa_grid_rollup = paa_grid.rollup(
    aggs=_paa_grid_aggs,
    by=["SpotShiftPct", "Book", "Underlying", "InstrumentId"],
)
