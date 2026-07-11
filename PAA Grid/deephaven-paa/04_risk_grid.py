"""
PAA engine — Step 4: Risk Grid (spot-ladder scenario risk).

For every instrument, revalues price and Greeks across a ladder of spot
shifts, producing the classic desk risk grid:

  Spot shift % | shifted spot | forward | theo | delta | gamma | vega | theta

Tables produced:

  spot_shift              — the ladder definition (one row per shift)
  risk_grid_inst          — per-instrument grid: instrument x shift, per-option
                            theo and Greeks at the shifted spot
  risk_grid_pos           — position-scaled grid per (Book, Instrument, shift),
                            incl. scenario P&L vs the unshifted theo and
                            base-ccy (USD) conversions
  risk_grid_by_underlying — ladder aggregated per (Book, Underlying, shift)
  risk_grid_by_book       — ladder aggregated per (Book, shift)
  risk_grid_firm          — firm-wide ladder per shift
  risk_grid_rollup        — hierarchical Book -> Underlying -> Instrument tree
                            keyed by shift

Run order: 01 -> 02 -> 04 (03 is independent). Reuses the Black-Scholes
functions (bs_price, bs_delta, ...) and opt_ttm defined in 02_paa_engine.py
and the live market tables from 01_paa_source_tables.py, so the whole grid
re-centers on every spot tick.

Conventions (same as the PAA engine):
  - Delta/Gamma per unit of underlying; Vega per 1.00 vol (VegaPoint = /100
    for per-vol-point); Theta per year (ThetaDay = /252 for per-day).
  - Forward = ShiftedSpot * exp((r - q) * T), continuous dividend yield q.
  - Vol, rate, dividend and time are held at live values: this is a pure
    spot ladder (add a vol dimension the same way via a second cross join).
"""

from deephaven import new_table, agg
from deephaven.column import double_col

# ---------------------------------------------------------------- ladder
_SHIFTS_PCT = [-20.0, -15.0, -10.0, -5.0, -2.0, -1.0, 0.0,
               1.0, 2.0, 5.0, 10.0, 15.0, 20.0]

spot_shift = new_table([
    double_col("SpotShiftPct", _SHIFTS_PCT),
]).update("SpotShift = SpotShiftPct / 100.0")

# ------------------------------------------------- per-instrument grid
# Base = live market per instrument (ticks with spot_live). BaseTheo is the
# unshifted mark, kept so each scenario row can express P&L vs base.
_inst_base = (
    instrument
    .natural_join(spot_live, on=["Underlying"], joins=["Spot"])
    .natural_join(vol_live, on=["InstrumentId"])
    .natural_join(rates_live, on=["Currency"])
    .natural_join(div_live, on=["Underlying"])
    .update([
        "Ttm = opt_ttm(Expiry)",
        "BaseTheo = bs_price(Spot, Strike, Ttm, Rate, DivYield, Vol, OptionType)",
    ])
)

risk_grid_inst = (
    _inst_base
    .join(spot_shift)  # no `on` => cross join: instrument x shift
    .update([
        "ShiftedSpot = Spot * (1.0 + SpotShift)",
        "Forward = ShiftedSpot * exp((Rate - DivYield) * Ttm)",
        "Theo = bs_price(ShiftedSpot, Strike, Ttm, Rate, DivYield, Vol, OptionType)",
        "Delta = bs_delta(ShiftedSpot, Strike, Ttm, Rate, DivYield, Vol, OptionType)",
        "Gamma = bs_gamma(ShiftedSpot, Strike, Ttm, Rate, DivYield, Vol)",
        "Vega = bs_vega(ShiftedSpot, Strike, Ttm, Rate, DivYield, Vol)",
        "Theta = bs_theta(ShiftedSpot, Strike, Ttm, Rate, DivYield, Vol, OptionType)",
        "VegaPoint = Vega / 100.0",
        "ThetaDay = Theta / 252.0",
    ])
    .view([
        "InstrumentId", "Underlying", "OptionType", "Strike", "Expiry",
        "Currency", "SpotShiftPct", "Spot", "ShiftedSpot", "Forward",
        "BaseTheo", "Theo", "Delta", "Gamma", "Vega", "VegaPoint",
        "Theta", "ThetaDay",
    ])
    .sort(["InstrumentId", "SpotShiftPct"])
)

# ------------------------------------------------ position-scaled grid
# join (not natural_join): risk_grid_inst has one row per shift per
# instrument, so each position row fans out across the ladder.
risk_grid_pos = (
    book_position
    .join(risk_grid_inst, on=["InstrumentId"])
    .natural_join(fx_live, on=["Currency"])
    .update([
        "PosScale = SODQty * Multiplier",
        "PosTheo = PosScale * Theo",
        "ScenarioPnl = PosScale * (Theo - BaseTheo)",     # local ccy
        "PosDelta = PosScale * Delta",                    # underlying units
        "DollarDelta = PosDelta * ShiftedSpot",           # local ccy
        "PosGamma = PosScale * Gamma",
        "PosVegaPoint = PosScale * VegaPoint",            # per vol point
        "PosThetaDay = PosScale * ThetaDay",              # per trading day
        # base-ccy (USD) conversions for cross-currency aggregation
        "ScenarioPnlBase = ScenarioPnl * FxRate",
        "DollarDeltaBase = DollarDelta * FxRate",
    ])
    .view([
        "Book", "InstrumentId", "Underlying", "Currency", "SODQty",
        "SpotShiftPct", "ShiftedSpot", "Forward", "Theo",
        "PosTheo", "ScenarioPnl", "ScenarioPnlBase",
        "PosDelta", "DollarDelta", "DollarDeltaBase",
        "PosGamma", "PosVegaPoint", "PosThetaDay",
    ])
    .sort(["Book", "InstrumentId", "SpotShiftPct"])
)

# --------------------------------------------------------------- roll-ups
# Only position-scaled (dollar) Greeks are summed — per-option Greeks are
# not additive across instruments. Base-ccy columns are safe to sum across
# currencies; local-ccy sums are meaningful within a single underlying.
_GRID_SUM_COLS = [
    "PosTheo", "ScenarioPnl", "ScenarioPnlBase",
    "PosDelta", "DollarDelta", "DollarDeltaBase",
    "PosGamma", "PosVegaPoint", "PosThetaDay",
]
_grid_aggs = [agg.sum_(_GRID_SUM_COLS), agg.count_("NumPositions")]

risk_grid_by_underlying = (
    risk_grid_pos
    .agg_by(_grid_aggs, by=["Book", "Underlying", "SpotShiftPct"])
    .sort(["Book", "Underlying", "SpotShiftPct"])
)

risk_grid_by_book = (
    risk_grid_pos
    .agg_by(_grid_aggs, by=["Book", "SpotShiftPct"])
    .sort(["Book", "SpotShiftPct"])
)

risk_grid_firm = (
    risk_grid_pos
    .agg_by(_grid_aggs, by=["SpotShiftPct"])
    .sort(["SpotShiftPct"])
)

# Hierarchical tree: expand Book -> Underlying -> Instrument at each shift.
risk_grid_rollup = risk_grid_pos.rollup(
    aggs=_grid_aggs,
    by=["SpotShiftPct", "Book", "Underlying", "InstrumentId"],
)
