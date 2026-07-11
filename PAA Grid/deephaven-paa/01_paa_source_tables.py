"""
PAA engine — Step 1: raw source data tables (keyed).

Creates every keyed source table the PAA calculation engine consumes:

  Reference (static):     instrument, book_position, orders
  Prev-close snapshots:   spot_prev, vol_prev, rates_prev, div_prev, fx_prev
  Live market data:       spot_live (ticking simulation), vol_live,
                          rates_live, div_live, fx_live
  Trading activity:       executions

Run order: 01 -> 02 -> 03 (same Deephaven console/session).

In production, replace the new_table(...) samples and the spot simulator
with real feeds (Kafka ingester, Barrage subscription, etc.) while keeping
the same schemas and key columns — the downstream engine only depends on
the schemas.

NOTE: implied vol and interest rates are not optional. Vanilla-option PAA
cannot be computed from position/spot/div/FX alone — vol_prev/vol_live and
rates_prev/rates_live are required source data.
"""

from deephaven import new_table, time_table
from deephaven.column import string_col, double_col, int_col

# =========================================================================
# 1. Reference data
# =========================================================================

# instrument — one row per listed vanilla option. Key: InstrumentId
instrument = new_table([
    string_col("InstrumentId", ["AAPL_C220_DEC26", "AAPL_P200_DEC26",
                                "MSFT_C500_SEP26", "MSFT_P480_SEP26",
                                "SAP_C260_DEC26", "SAP_P240_SEP26"]),
    string_col("Underlying",   ["AAPL", "AAPL", "MSFT", "MSFT", "SAP", "SAP"]),
    string_col("OptionType",   ["CALL", "PUT", "CALL", "PUT", "CALL", "PUT"]),
    double_col("Strike",       [220.0, 200.0, 500.0, 480.0, 260.0, 240.0]),
    string_col("Expiry",       ["2026-12-18", "2026-12-18", "2026-09-18",
                                "2026-09-18", "2026-12-18", "2026-09-18"]),
    int_col("Multiplier",      [100, 100, 100, 100, 100, 100]),
    string_col("Currency",     ["USD", "USD", "USD", "USD", "EUR", "EUR"]),
])

# book_position — start-of-day holdings. Key: (Book, InstrumentId)
book_position = new_table([
    string_col("Book",         ["DESK1", "DESK1", "DESK1",
                                "DESK2", "DESK2", "DESK2"]),
    string_col("InstrumentId", ["AAPL_C220_DEC26", "AAPL_P200_DEC26",
                                "MSFT_C500_SEP26", "MSFT_P480_SEP26",
                                "SAP_C260_DEC26", "SAP_P240_SEP26"]),
    int_col("SODQty",          [150, -80, 60, -40, 120, -55]),
])

# orders — audit/context only; P&L attribution consumes executions, not
# orders. Key: OrderId
orders = new_table([
    string_col("OrderId",      ["ORD-1001", "ORD-1002", "ORD-1003", "ORD-1004"]),
    string_col("Book",         ["DESK1", "DESK1", "DESK2", "DESK2"]),
    string_col("InstrumentId", ["AAPL_C220_DEC26", "MSFT_C500_SEP26",
                                "SAP_C260_DEC26", "SAP_P240_SEP26"]),
    string_col("Side",         ["BUY", "SELL", "BUY", "SELL"]),
    int_col("OrderQty",        [25, 15, 30, 20]),
    double_col("LimitPrice",   [12.50, 21.00, 14.80, 9.60]),
    string_col("Status",       ["FILLED", "FILLED", "FILLED", "WORKING"]),
])

# executions — intraday fills, drive new-trade P&L. Key: ExecId
executions = new_table([
    string_col("ExecId",       ["EX-1", "EX-2", "EX-3", "EX-4", "EX-5"]),
    string_col("OrderId",      ["ORD-1001", "ORD-1001", "ORD-1002",
                                "ORD-1003", "ORD-1003"]),
    string_col("Book",         ["DESK1", "DESK1", "DESK1", "DESK2", "DESK2"]),
    string_col("InstrumentId", ["AAPL_C220_DEC26", "AAPL_C220_DEC26",
                                "MSFT_C500_SEP26", "SAP_C260_DEC26",
                                "SAP_C260_DEC26"]),
    string_col("Side",         ["BUY", "BUY", "SELL", "BUY", "BUY"]),
    int_col("ExecQty",         [15, 10, 15, 20, 10]),
    double_col("ExecPrice",    [12.45, 12.55, 21.10, 14.75, 14.85]),
    string_col("ExecTime",     ["2026-07-11T09:31:05", "2026-07-11T10:02:44",
                                "2026-07-11T11:15:20", "2026-07-11T09:45:12",
                                "2026-07-11T13:22:31"]),
])

# =========================================================================
# 2. Prev-close (T-1) market snapshots — static by nature
# =========================================================================

spot_prev = new_table([                       # Key: Underlying
    string_col("Underlying", ["AAPL", "MSFT", "SAP"]),
    double_col("PrevSpot",   [214.00, 492.50, 251.00]),
])

vol_prev = new_table([                        # Key: InstrumentId (interpolated surface point)
    string_col("InstrumentId", ["AAPL_C220_DEC26", "AAPL_P200_DEC26",
                                "MSFT_C500_SEP26", "MSFT_P480_SEP26",
                                "SAP_C260_DEC26", "SAP_P240_SEP26"]),
    double_col("PrevVol",      [0.280, 0.310, 0.255, 0.290, 0.240, 0.275]),
])

rates_prev = new_table([                      # Key: Currency
    string_col("Currency", ["USD", "EUR"]),
    double_col("PrevRate", [0.0420, 0.0250]),
])

div_prev = new_table([                        # Key: Underlying (continuous yield)
    string_col("Underlying",   ["AAPL", "MSFT", "SAP"]),
    double_col("PrevDivYield", [0.0050, 0.0070, 0.0150]),
])

fx_prev = new_table([                         # Key: Currency (units of USD per 1 ccy)
    string_col("Currency",   ["USD", "EUR"]),
    double_col("PrevFxRate", [1.0000, 1.0750]),
])

# =========================================================================
# 3. Live (T) market data
# =========================================================================

# Ticking spot simulator: one tick per second, cycling the underlyings and
# wobbling around a base price. last_by collapses the stream into a keyed
# live table, so the entire downstream PAA DAG updates in real time.
_UNDS = ["AAPL", "MSFT", "SAP"]
_BASE = {"AAPL": 215.60, "MSFT": 495.25, "SAP": 252.40}


def _sim_und(i: int) -> str:
    return _UNDS[i % len(_UNDS)]


def _sim_spot(und: str, i: int) -> float:
    import math
    import random
    base = _BASE[und]
    return base * (1.0 + 0.003 * math.sin(i / 40.0)
                   + 0.0006 * (random.random() - 0.5))


spot_ticks = time_table("PT1S").update([
    "Underlying = _sim_und((int) ii)",
    "Spot = _sim_spot(Underlying, (int) ii)",
])
spot_live = spot_ticks.last_by("Underlying")  # Key: Underlying

# Static live snapshots for the slower-moving inputs; in production these
# would also be last_by views over a feed.
vol_live = new_table([                        # Key: InstrumentId
    string_col("InstrumentId", ["AAPL_C220_DEC26", "AAPL_P200_DEC26",
                                "MSFT_C500_SEP26", "MSFT_P480_SEP26",
                                "SAP_C260_DEC26", "SAP_P240_SEP26"]),
    double_col("Vol",          [0.292, 0.318, 0.249, 0.296, 0.246, 0.271]),
])

rates_live = new_table([                      # Key: Currency
    string_col("Currency", ["USD", "EUR"]),
    double_col("Rate",     [0.0425, 0.0248]),
])

div_live = new_table([                        # Key: Underlying
    string_col("Underlying", ["AAPL", "MSFT", "SAP"]),
    double_col("DivYield",   [0.0050, 0.0072, 0.0148]),
])

fx_live = new_table([                         # Key: Currency
    string_col("Currency", ["USD", "EUR"]),
    double_col("FxRate",   [1.0000, 1.0820]),
])
