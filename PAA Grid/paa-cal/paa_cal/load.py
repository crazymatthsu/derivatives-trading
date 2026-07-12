"""Load the mock-data input files (CSVs + config.json) into plain dicts.

Every file lives in one inputs directory; edit the CSVs to change the
scenario — no code changes needed. See inputs/README section in the
project README for the file formats.
"""

import csv
import json
from pathlib import Path


def _rows(path):
    with open(path, newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def _prev_live_map(path, key):
    """Two-snapshot table: key column + prev + live columns."""
    return {r[key]: {"prev": float(r["prev"]), "live": float(r["live"])}
            for r in _rows(path)}


def load_inputs(inputs_dir):
    d = Path(inputs_dir)

    with open(d / "config.json") as f:
        config = json.load(f)

    instruments = {}
    for r in _rows(d / "instrument.csv"):
        instruments[r["instrument_id"]] = {
            "underlying": r["underlying"],
            "option_type": r["option_type"],
            "strike": float(r["strike"]),
            "expiry": r["expiry"],
            "multiplier": int(r["multiplier"]),
            "currency": r["currency"],
        }

    positions = [{"book": r["book"],
                  "instrument_id": r["instrument_id"],
                  "sod_qty": int(r["sod_qty"])}
                 for r in _rows(d / "book_position.csv")]

    executions = [{"exec_id": r["exec_id"],
                   "order_id": r["order_id"],
                   "book": r["book"],
                   "instrument_id": r["instrument_id"],
                   "side": r["side"],
                   "qty": int(r["qty"]),
                   "price": float(r["price"]),
                   "exec_time": r["exec_time"]}
                  for r in _rows(d / "executions.csv")]

    return {
        "config": config,
        "instruments": instruments,
        "positions": positions,
        "executions": executions,
        "orders": _rows(d / "orders.csv"),          # audit context only
        "spot": _prev_live_map(d / "spot.csv", "underlying"),
        "vol": _prev_live_map(d / "vol.csv", "instrument_id"),
        "rates": _prev_live_map(d / "rates.csv", "currency"),
        "dividends": _prev_live_map(d / "dividends.csv", "underlying"),
        "fx": _prev_live_map(d / "fx.csv", "currency"),
    }
