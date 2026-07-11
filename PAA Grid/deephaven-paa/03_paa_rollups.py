"""
PAA engine — Step 3: roll-ups and summary statistics.

Consumes the `paa` table from 02_paa_engine.py and produces:

  paa_rollup          — hierarchical rollup Book -> Underlying -> Instrument
                        (expandable tree in the Deephaven UI)
  paa_by_underlying   — flat aggregate per (Book, Underlying)
  paa_by_book         — flat aggregate per Book
  paa_firm            — single-row firm-wide grand total
  paa_summary         — per-book summary statistics + attribution-quality
                        flag (unexplained > 5% of |actual| => BREACH)

All tables tick with the live spot feed.
"""

from deephaven import agg

# P&L columns aggregated by simple sum at every level (all in base ccy for
# the headline columns; local-ccy Greeks P&L sums are meaningful only
# within a single currency, which Book->Underlying grouping guarantees
# per underlying, so both are kept).
PNL_COLS = [
    "DeltaPnl", "GammaPnl", "VegaPnl", "ThetaPnl", "RhoPnl", "DivPnl",
    "ExplainedPnl", "ActualPnl", "UnexplainedPnl", "NewTradePnl",
    "TotalPnlLocal", "FxPnl", "ActualPnlBase", "ExplainedPnlBase",
    "UnexplainedPnlBase", "NewTradePnlBase", "TotalPnlBase",
]

_sum_aggs = [agg.sum_(PNL_COLS), agg.count_("NumPositions")]

# ---------------------------------------------------------------- rollup
# Hierarchical tree: expand a book to see underlyings, an underlying to
# see individual option lines. Sums recompute at every level on each tick.
paa_rollup = paa.rollup(aggs=_sum_aggs, by=["Book", "Underlying", "InstrumentId"])

# ------------------------------------------------------- flat aggregates
paa_by_underlying = paa.agg_by(_sum_aggs, by=["Book", "Underlying"])

paa_by_book = paa.agg_by(_sum_aggs, by=["Book"])

paa_firm = paa.agg_by(_sum_aggs)  # no `by` => single grand-total row

# ----------------------------------------------------- summary statistics
# Per-book distribution stats of the residual, plus the desk-standard
# attribution-quality check: |sum unexplained| <= 5% of |sum actual|.
paa_summary = (
    paa.agg_by(
        [
            agg.sum_([
                "TotalActualPnl = ActualPnl",
                "TotalExplainedPnl = ExplainedPnl",
                "TotalUnexplainedPnl = UnexplainedPnl",
                "TotalNewTradePnl = NewTradePnl",
                "TotalPnlBaseSum = TotalPnlBase",
            ]),
            agg.avg(["AvgUnexplained = UnexplainedPnl"]),
            agg.std(["StdUnexplained = UnexplainedPnl"]),
            agg.min_(["MinUnexplained = UnexplainedPnl"]),
            agg.max_(["MaxUnexplained = UnexplainedPnl"]),
            agg.count_("NumPositions"),
        ],
        by=["Book"],
    )
    .update([
        "ExplainedRatioPct = TotalActualPnl == 0 ? 100.0"
        "    : 100.0 * TotalExplainedPnl / TotalActualPnl",
        "UnexplainedPctOfActual = TotalActualPnl == 0 ? 0.0"
        "    : 100.0 * abs(TotalUnexplainedPnl) / abs(TotalActualPnl)",
        "QualityFlag = UnexplainedPctOfActual > 5.0 ? `BREACH` : `OK`",
    ])
)
