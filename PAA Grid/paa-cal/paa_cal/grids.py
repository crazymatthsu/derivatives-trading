"""Risk Grid and PAA Grid — mirror deephaven-paa/04_risk_grid.py and
05_paa_grid.py.

Risk Grid: Greeks and theo RECOMPUTED at each shifted spot, live market,
live time (state view — "what is my risk if spot were there").

PAA Grid: P&L components from FIXED T-1 Greeks, spot shifted from the T-1
close, actual vol/rate/div moves, one day of decay (change view — "what is
my P&L getting to that spot"). Actual is a full revaluation, so unexplained
measures the Taylor error at each shift.
"""

from . import bs


def risk_grid(inp, risk):
    """Position-scaled spot ladder: one row per (book, instrument, shift)."""
    cfg = inp["config"]
    rows = []
    for p in inp["positions"]:
        g = risk[p["instrument_id"]]
        ps = p["sod_qty"] * g["multiplier"]
        k, t, cp = g["strike"], g["ttm"], g["option_type"]
        rl, ql, vl = g["rate"], g["div"], g["vol"]
        base_theo = g["curr_price"]
        fx_live = inp["fx"][g["currency"]]["live"]
        for s_pct in cfg["spot_shifts_pct"]:
            ss = g["spot"] * (1.0 + s_pct / 100.0)
            theo = bs.price(ss, k, t, rl, ql, vl, cp)
            de = bs.delta(ss, k, t, rl, ql, vl, cp)
            rows.append({
                "book": p["book"], "instrument_id": p["instrument_id"],
                "underlying": g["underlying"], "sod_qty": p["sod_qty"],
                "shift_pct": s_pct,
                "shifted_spot": ss,
                "forward": bs.forward(ss, t, rl, ql),
                "theo": theo,
                "delta": de,
                "gamma": bs.gamma(ss, k, t, rl, ql, vl),
                "vega": bs.vega(ss, k, t, rl, ql, vl),
                "theta": bs.theta(ss, k, t, rl, ql, vl, cp),
                "scenario_pnl": ps * (theo - base_theo),
                "pos_delta": ps * de,
                "dollar_delta_base": ps * de * ss * fx_live,
            })
    return rows


def paa_grid(inp, risk):
    """Attribution ladder: one row per (book, instrument, shift)."""
    cfg = inp["config"]
    dt_day = 1.0 / cfg["theta_day_count"]
    rows = []
    for p in inp["positions"]:
        g = risk[p["instrument_id"]]
        ps = p["sod_qty"] * g["multiplier"]
        k, t, cp = g["strike"], g["ttm"], g["option_type"]
        for s_pct in cfg["spot_shifts_pct"]:
            ss = g["spot"] * (1.0 + s_pct / 100.0)
            ds = ss - g["prev_spot"]
            delta_pnl = ps * g["delta"] * ds
            gamma_pnl = 0.5 * ps * g["gamma"] * ds * ds
            time_pnl = ps * g["theta"] * dt_day
            vega_pnl = ps * g["vega"] * g["d_vol"]
            volga_pnl = 0.5 * ps * g["volga"] * g["d_vol"] ** 2
            borrdiv_pnl = ps * g["div_rho"] * g["d_div"]
            rate_pnl = ps * g["rho"] * g["d_rate"]
            explained = (delta_pnl + gamma_pnl + time_pnl + vega_pnl
                         + volga_pnl + borrdiv_pnl + rate_pnl)
            theo = bs.price(ss, k, t, g["rate"], g["div"], g["vol"], cp)
            actual = ps * (theo - g["prev_price"])
            rows.append({
                "book": p["book"], "instrument_id": p["instrument_id"],
                "underlying": g["underlying"], "sod_qty": p["sod_qty"],
                "shift_pct": s_pct,
                "shifted_spot": ss,
                "d_spot": ds,
                "delta_pnl": delta_pnl, "gamma_pnl": gamma_pnl,
                "time_pnl": time_pnl, "vega_pnl": vega_pnl,
                "volga_pnl": volga_pnl, "borrdiv_pnl": borrdiv_pnl,
                "rate_pnl": rate_pnl,
                "explained_pnl": explained,
                "actual_pnl": actual,
                "unexplained_pnl": actual - explained,
            })
    return rows
