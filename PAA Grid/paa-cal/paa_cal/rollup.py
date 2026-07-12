"""Roll-ups and summary statistics — mirrors deephaven-paa/03_paa_rollups.py."""

import math

PNL_COLS = ["delta_pnl", "gamma_pnl", "vega_pnl", "theta_pnl", "rho_pnl",
            "div_pnl", "explained_pnl", "actual_pnl", "unexplained_pnl",
            "new_trade_pnl", "total_pnl_local", "fx_pnl",
            "actual_pnl_base", "explained_pnl_base", "unexplained_pnl_base",
            "new_trade_pnl_base", "total_pnl_base"]


def aggregate(paa_rows, by):
    """Sum every P&L column grouped by the given key columns.
    by=[] gives the firm-wide grand total (one row)."""
    groups = {}
    for r in paa_rows:
        key = tuple(r[k] for k in by)
        g = groups.setdefault(key, {**{k: r[k] for k in by},
                                    **{c: 0.0 for c in PNL_COLS},
                                    "num_positions": 0})
        for c in PNL_COLS:
            g[c] += r[c]
        g["num_positions"] += 1
    if not by:
        for g in groups.values():
            g["level"] = "FIRM"
    return sorted(groups.values(), key=lambda g: tuple(g[k] for k in by))


def summary(paa_rows, breach_pct):
    """Per-book stats on the unexplained residual + quality flag."""
    out = []
    for g in aggregate(paa_rows, ["book"]):
        un = [r["unexplained_pnl"] for r in paa_rows if r["book"] == g["book"]]
        n = len(un)
        avg = sum(un) / n
        std = math.sqrt(sum((x - avg) ** 2 for x in un) / (n - 1)) if n > 1 else 0.0
        pct = (100.0 * abs(g["unexplained_pnl"]) / abs(g["actual_pnl"])
               if g["actual_pnl"] else 0.0)
        out.append({
            "book": g["book"], "num_positions": n,
            "total_actual_pnl": g["actual_pnl"],
            "total_explained_pnl": g["explained_pnl"],
            "total_unexplained_pnl": g["unexplained_pnl"],
            "total_new_trade_pnl": g["new_trade_pnl"],
            "total_pnl_base": g["total_pnl_base"],
            "avg_unexplained": avg, "std_unexplained": std,
            "min_unexplained": min(un), "max_unexplained": max(un),
            "unexplained_pct_of_actual": pct,
            "quality_flag": "BREACH" if pct > breach_pct else "OK",
        })
    return out
