#!/usr/bin/env python3
"""paa-cal command-line runner.

Usage:
  python3 run_paa.py all
  python3 run_paa.py risk | trades | paa | rollup | risk-grid | paa-grid
  python3 run_paa.py paa-grid --instrument AAPL_C220_DEC26
  python3 run_paa.py all --csv-out outputs
  python3 run_paa.py all --inputs my_other_inputs_dir

Reads the CSV/JSON inputs, runs the same calculations as the Deephaven
scripts, and prints aligned tables (optionally also writing CSVs).
"""

import argparse
import csv
import sys
from pathlib import Path

from paa_cal import (load_inputs, compute_risk, compute_trades, compute_paa,
                     aggregate, summary, risk_grid, paa_grid)


def fmt(v, spec):
    if v is None:
        return ""
    if isinstance(v, float):
        return format(v, spec)
    return str(v)


def print_table(title, rows, cols):
    """cols: list of (key, float_format) — headers are the keys."""
    print(f"\n=== {title} ===")
    if not rows:
        print("(no rows)")
        return
    cells = [[fmt(r.get(k), spec) for k, spec in cols] for r in rows]
    widths = [max(len(k), *(len(c[i]) for c in cells)) + 2
              for i, (k, _) in enumerate(cols)]
    print("".join(k.rjust(w) for (k, _), w in zip(cols, widths)))
    for c in cells:
        print("".join(v.rjust(w) for v, w in zip(c, widths)))


def write_csv(rows, path):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path}")


REPORTS = ["risk", "trades", "paa", "rollup", "risk-grid", "paa-grid", "all"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", choices=REPORTS, help="which report to run")
    ap.add_argument("--inputs", default=str(Path(__file__).parent / "inputs"),
                    help="inputs directory (default: ./inputs)")
    ap.add_argument("--csv-out", metavar="DIR",
                    help="also write each report as CSV into DIR")
    ap.add_argument("--instrument", help="filter grid reports to one instrument")
    ap.add_argument("--book", help="filter reports to one book")
    args = ap.parse_args()

    inp = load_inputs(args.inputs)
    cfg = inp["config"]
    risk = compute_risk(inp)
    trades = compute_trades(inp, risk)
    paa_rows = compute_paa(inp, risk, trades)

    def keep(r):
        return ((not args.instrument or r.get("instrument_id") == args.instrument)
                and (not args.book or r.get("book") == args.book))

    out = {}

    if args.report in ("risk", "all"):
        rows = [r for r in risk.values() if keep(r)]
        out["risk"] = (rows, [
            ("instrument_id", ""), ("ttm", ".4f"), ("prev_price", ".4f"),
            ("curr_price", ".4f"), ("delta", ".4f"), ("gamma", ".5f"),
            ("vega", ".3f"), ("theta", ".3f"), ("rho", ".3f"),
            ("div_rho", ".3f"), ("volga", ".3f"),
            ("d_spot", ".2f"), ("d_vol", ".4f"), ("d_rate", ".4f"), ("d_div", ".4f")])

    if args.report in ("trades", "all"):
        rows = [t for t in trades.values() if keep(t)]
        out["trades"] = (rows, [
            ("book", ""), ("instrument_id", ""), ("traded_qty", ""),
            ("traded_cost", ".2f"), ("num_execs", ""),
            ("curr_price", ".4f"), ("new_trade_pnl", ",.2f")])

    if args.report in ("paa", "all"):
        rows = [r for r in paa_rows if keep(r)]
        out["paa"] = (rows, [
            ("book", ""), ("instrument_id", ""), ("sod_qty", ""),
            ("delta_pnl", ",.0f"), ("gamma_pnl", ",.0f"), ("vega_pnl", ",.0f"),
            ("theta_pnl", ",.0f"), ("rho_pnl", ",.0f"), ("div_pnl", ",.0f"),
            ("explained_pnl", ",.0f"), ("actual_pnl", ",.0f"),
            ("unexplained_pnl", ",.1f"), ("new_trade_pnl", ",.0f"),
            ("fx_pnl", ",.0f"), ("total_pnl_base", ",.0f")])

    if args.report in ("rollup", "all"):
        agg_cols = [("book", ""), ("num_positions", ""),
                    ("explained_pnl", ",.0f"), ("actual_pnl", ",.0f"),
                    ("unexplained_pnl", ",.1f"), ("new_trade_pnl", ",.0f"),
                    ("total_pnl_base", ",.0f")]
        out["rollup_by_book"] = (aggregate(paa_rows, ["book"]), agg_cols)
        out["rollup_by_underlying"] = (
            aggregate(paa_rows, ["book", "underlying"]),
            [("book", ""), ("underlying", "")] + agg_cols[2:])
        out["rollup_firm"] = (aggregate(paa_rows, []),
                              [("level", "")] + agg_cols[1:])
        out["summary"] = (summary(paa_rows, cfg["unexplained_breach_pct"]), [
            ("book", ""), ("num_positions", ""),
            ("total_actual_pnl", ",.0f"), ("total_explained_pnl", ",.0f"),
            ("total_unexplained_pnl", ",.1f"),
            ("unexplained_pct_of_actual", ".2f"), ("quality_flag", ""),
            ("avg_unexplained", ",.1f"), ("std_unexplained", ",.1f"),
            ("min_unexplained", ",.1f"), ("max_unexplained", ",.1f")])

    if args.report in ("risk-grid", "all"):
        rows = [r for r in risk_grid(inp, risk) if keep(r)]
        out["risk_grid"] = (rows, [
            ("book", ""), ("instrument_id", ""), ("shift_pct", ".0f"),
            ("shifted_spot", ".2f"), ("forward", ".2f"), ("theo", ".4f"),
            ("delta", ".4f"), ("gamma", ".5f"), ("vega", ".3f"),
            ("theta", ".3f"), ("scenario_pnl", ",.0f"),
            ("pos_delta", ",.0f"), ("dollar_delta_base", ",.0f")])

    if args.report in ("paa-grid", "all"):
        rows = [r for r in paa_grid(inp, risk) if keep(r)]
        out["paa_grid"] = (rows, [
            ("book", ""), ("instrument_id", ""), ("shift_pct", ".0f"),
            ("shifted_spot", ".2f"), ("d_spot", ".2f"),
            ("delta_pnl", ",.0f"), ("gamma_pnl", ",.0f"), ("time_pnl", ",.0f"),
            ("vega_pnl", ",.0f"), ("volga_pnl", ",.1f"),
            ("borrdiv_pnl", ",.1f"), ("rate_pnl", ",.0f"),
            ("explained_pnl", ",.0f"), ("actual_pnl", ",.0f"),
            ("unexplained_pnl", ",.0f")])

    for name, (rows, cols) in out.items():
        print_table(name, rows, cols)

    if args.csv_out:
        d = Path(args.csv_out)
        d.mkdir(parents=True, exist_ok=True)
        for name, (rows, _) in out.items():
            write_csv(rows, d / f"{name}.csv")

    return 0


if __name__ == "__main__":
    sys.exit(main())
