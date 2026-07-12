"""PAA calculation engine — mirrors deephaven-paa/02_paa_engine.py.

Pipeline:
  compute_risk()   -> per-instrument T-1 mark + Greeks and live mark
                      (Deephaven tables inst_prev / inst_now / risk)
  compute_trades() -> per (book, instrument) intraday new-trade P&L
                      (Deephaven table trade_pnl)
  compute_paa()    -> per (book, instrument) attribution rows
                      (Deephaven table paa)
"""

from datetime import date

from . import bs


def _ttm(expiry, as_of, day_count):
    days = (date.fromisoformat(expiry) - date.fromisoformat(as_of)).days
    return max(days, 0) / day_count


def compute_risk(inp):
    """T-1 valuation + Greeks (at TtmPrev = Ttm + 1 trading day) and live
    valuation, per instrument. Greeks are start-of-day by design."""
    cfg = inp["config"]
    dt_day = 1.0 / cfg["theta_day_count"]
    risk = {}
    for iid, m in inp["instruments"].items():
        und, ccy, k, cp = m["underlying"], m["currency"], m["strike"], m["option_type"]
        t = _ttm(m["expiry"], cfg["as_of"], cfg["ttm_day_count"])
        tp = t + dt_day
        sp = inp["spot"][und]["prev"]
        vp = inp["vol"][iid]["prev"]
        rp = inp["rates"][ccy]["prev"]
        qp = inp["dividends"][und]["prev"]
        sl = inp["spot"][und]["live"]
        vl = inp["vol"][iid]["live"]
        rl = inp["rates"][ccy]["live"]
        ql = inp["dividends"][und]["live"]
        risk[iid] = {
            "instrument_id": iid, "underlying": und, "currency": ccy,
            "option_type": cp, "strike": k, "expiry": m["expiry"],
            "multiplier": m["multiplier"],
            "ttm": t, "ttm_prev": tp,
            "prev_spot": sp, "spot": sl, "prev_vol": vp, "vol": vl,
            "prev_rate": rp, "rate": rl, "prev_div": qp, "div": ql,
            "d_spot": sl - sp, "d_vol": vl - vp,
            "d_rate": rl - rp, "d_div": ql - qp,
            "prev_price": bs.price(sp, k, tp, rp, qp, vp, cp),
            "delta": bs.delta(sp, k, tp, rp, qp, vp, cp),
            "gamma": bs.gamma(sp, k, tp, rp, qp, vp),
            "vega": bs.vega(sp, k, tp, rp, qp, vp),
            "theta": bs.theta(sp, k, tp, rp, qp, vp, cp),
            "rho": bs.rho(sp, k, tp, rp, qp, vp, cp),
            "div_rho": bs.div_rho(sp, k, tp, rp, qp, vp, cp),
            "volga": bs.volga(sp, k, tp, rp, qp, vp),
            "curr_price": bs.price(sl, k, t, rl, ql, vl, cp),
        }
    return risk


def compute_trades(inp, risk):
    """NewTradePnl = mult x (traded_qty x curr_price - traded_cost)."""
    agg = {}
    for e in inp["executions"]:
        sq = e["qty"] if e["side"] == "BUY" else -e["qty"]
        key = (e["book"], e["instrument_id"])
        a = agg.setdefault(key, {"book": e["book"], "instrument_id": e["instrument_id"],
                                 "traded_qty": 0, "traded_cost": 0.0, "num_execs": 0})
        a["traded_qty"] += sq
        a["traded_cost"] += sq * e["price"]
        a["num_execs"] += 1
    for (bk, iid), a in agg.items():
        g = risk[iid]
        a["curr_price"] = g["curr_price"]
        a["new_trade_pnl"] = g["multiplier"] * (
            a["traded_qty"] * g["curr_price"] - a["traded_cost"])
    return agg


def compute_paa(inp, risk, trades):
    """One attribution row per (book, instrument) SOD position."""
    cfg = inp["config"]
    dt_day = 1.0 / cfg["theta_day_count"]
    rows = []
    for p in inp["positions"]:
        g = risk[p["instrument_id"]]
        ps = p["sod_qty"] * g["multiplier"]
        tr = trades.get((p["book"], p["instrument_id"]),
                        {"traded_qty": 0, "new_trade_pnl": 0.0})
        fx = inp["fx"][g["currency"]]
        delta_pnl = ps * g["delta"] * g["d_spot"]
        gamma_pnl = 0.5 * ps * g["gamma"] * g["d_spot"] ** 2
        vega_pnl = ps * g["vega"] * g["d_vol"]
        theta_pnl = ps * g["theta"] * dt_day
        rho_pnl = ps * g["rho"] * g["d_rate"]
        div_pnl = ps * g["div_rho"] * g["d_div"]
        explained = delta_pnl + gamma_pnl + vega_pnl + theta_pnl + rho_pnl + div_pnl
        actual = ps * (g["curr_price"] - g["prev_price"])
        unexplained = actual - explained
        fx_pnl = ps * g["prev_price"] * (fx["live"] - fx["prev"])
        total_local = actual + tr["new_trade_pnl"]
        rows.append({
            "book": p["book"], "instrument_id": p["instrument_id"],
            "underlying": g["underlying"], "currency": g["currency"],
            "sod_qty": p["sod_qty"], "traded_qty": tr["traded_qty"],
            "prev_price": g["prev_price"], "curr_price": g["curr_price"],
            "d_spot": g["d_spot"], "d_vol": g["d_vol"],
            "d_rate": g["d_rate"], "d_div": g["d_div"],
            "delta_pnl": delta_pnl, "gamma_pnl": gamma_pnl,
            "vega_pnl": vega_pnl, "theta_pnl": theta_pnl,
            "rho_pnl": rho_pnl, "div_pnl": div_pnl,
            "explained_pnl": explained, "actual_pnl": actual,
            "unexplained_pnl": unexplained,
            "unexplained_pct": (100.0 * unexplained / abs(actual)) if actual else 0.0,
            "new_trade_pnl": tr["new_trade_pnl"],
            "total_pnl_local": total_local,
            "fx_pnl": fx_pnl,
            "actual_pnl_base": actual * fx["live"],
            "explained_pnl_base": explained * fx["live"],
            "unexplained_pnl_base": unexplained * fx["live"],
            "new_trade_pnl_base": tr["new_trade_pnl"] * fx["live"],
            "total_pnl_base": total_local * fx["live"] + fx_pnl,
        })
    return rows
