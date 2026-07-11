"""
PAA engine — Step 2: derived data and the attribution calculation.

Consumes the keyed source tables from 01_paa_source_tables.py and produces:

  inst_prev   — per-instrument T-1 valuation + Greeks (Black-Scholes)
  inst_now    — per-instrument live valuation
  risk        — inst_prev and inst_now combined (one row per instrument)
  trade_pnl   — per (Book, InstrumentId) intraday new-trade P&L
  paa         — THE OUTPUT: one row per (Book, InstrumentId) with the full
                Taylor-expansion attribution, actual P&L, unexplained
                residual, new-trade P&L and FX translation, in local and
                base (USD) currency.

Conventions:
  - Greeks are computed at T-1 market data (start-of-day risk), per option.
  - Vega and Rho are per 1.00 change (i.e. per 100 vol points / 10,000 bp);
    the d-terms (DVol, DRate) are in the same decimal units, so the
    products are consistent. Divide Vega by 100 to view "per vol point".
  - Theta is per year; ThetaPnl uses Dt = 1/252.
  - Dividends enter as a continuous yield q; DivPnl uses dV/dq ("div rho").
  - Because spot_live ticks, `paa` recomputes on every spot update.
"""

import math

# =========================================================================
# Black-Scholes pricer and Greeks (continuous dividend yield q)
# =========================================================================

AS_OF = "2026-07-11"          # valuation date T
DT_DAY = 1.0 / 252.0          # one trading day, in years


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def opt_ttm(expiry: str) -> float:
    """Year fraction (ACT/365) from AS_OF to expiry."""
    from datetime import date
    days = (date.fromisoformat(expiry) - date.fromisoformat(AS_OF)).days
    return max(days, 0) / 365.0


def _d1d2(s, k, t, r, q, v):
    d1 = (math.log(s / k) + (r - q + 0.5 * v * v) * t) / (v * math.sqrt(t))
    return d1, d1 - v * math.sqrt(t)


def bs_price(s: float, k: float, t: float, r: float, q: float,
             v: float, cp: str) -> float:
    if t <= 1e-8 or v <= 1e-8:
        return max(s - k, 0.0) if cp == "CALL" else max(k - s, 0.0)
    d1, d2 = _d1d2(s, k, t, r, q, v)
    if cp == "CALL":
        return s * math.exp(-q * t) * _ncdf(d1) - k * math.exp(-r * t) * _ncdf(d2)
    return k * math.exp(-r * t) * _ncdf(-d2) - s * math.exp(-q * t) * _ncdf(-d1)


def bs_delta(s: float, k: float, t: float, r: float, q: float,
             v: float, cp: str) -> float:
    if t <= 1e-8 or v <= 1e-8:
        itm = s > k if cp == "CALL" else s < k
        return (1.0 if cp == "CALL" else -1.0) if itm else 0.0
    d1, _ = _d1d2(s, k, t, r, q, v)
    dq = math.exp(-q * t)
    return dq * _ncdf(d1) if cp == "CALL" else dq * (_ncdf(d1) - 1.0)


def bs_gamma(s: float, k: float, t: float, r: float, q: float,
             v: float) -> float:
    if t <= 1e-8 or v <= 1e-8:
        return 0.0
    d1, _ = _d1d2(s, k, t, r, q, v)
    return math.exp(-q * t) * _npdf(d1) / (s * v * math.sqrt(t))


def bs_vega(s: float, k: float, t: float, r: float, q: float,
            v: float) -> float:
    """Per 1.00 vol change."""
    if t <= 1e-8 or v <= 1e-8:
        return 0.0
    d1, _ = _d1d2(s, k, t, r, q, v)
    return s * math.exp(-q * t) * _npdf(d1) * math.sqrt(t)


def bs_theta(s: float, k: float, t: float, r: float, q: float,
             v: float, cp: str) -> float:
    """Per year."""
    if t <= 1e-8 or v <= 1e-8:
        return 0.0
    d1, d2 = _d1d2(s, k, t, r, q, v)
    decay = -s * math.exp(-q * t) * _npdf(d1) * v / (2.0 * math.sqrt(t))
    if cp == "CALL":
        return (decay - r * k * math.exp(-r * t) * _ncdf(d2)
                + q * s * math.exp(-q * t) * _ncdf(d1))
    return (decay + r * k * math.exp(-r * t) * _ncdf(-d2)
            - q * s * math.exp(-q * t) * _ncdf(-d1))


def bs_rho(s: float, k: float, t: float, r: float, q: float,
           v: float, cp: str) -> float:
    """Per 1.00 rate change."""
    if t <= 1e-8 or v <= 1e-8:
        return 0.0
    _, d2 = _d1d2(s, k, t, r, q, v)
    if cp == "CALL":
        return k * t * math.exp(-r * t) * _ncdf(d2)
    return -k * t * math.exp(-r * t) * _ncdf(-d2)


def bs_div_rho(s: float, k: float, t: float, r: float, q: float,
               v: float, cp: str) -> float:
    """dV/dq per 1.00 dividend-yield change."""
    if t <= 1e-8 or v <= 1e-8:
        return 0.0
    d1, _ = _d1d2(s, k, t, r, q, v)
    if cp == "CALL":
        return -t * s * math.exp(-q * t) * _ncdf(d1)
    return t * s * math.exp(-q * t) * _ncdf(-d1)


def bs_volga(s: float, k: float, t: float, r: float, q: float,
             v: float) -> float:
    """d2V/dvol2 (vomma), per 1.00 vol change squared."""
    if t <= 1e-8 or v <= 1e-8:
        return 0.0
    d1, d2 = _d1d2(s, k, t, r, q, v)
    vega = s * math.exp(-q * t) * _npdf(d1) * math.sqrt(t)
    return vega * d1 * d2 / v


# =========================================================================
# Derived table 1: T-1 valuation and Greeks per instrument
# =========================================================================
# Time-to-expiry at the T-1 close is one trading day longer than at T, so
# the prev-close mark decays into today's mark and theta is attributed.

inst_prev = (
    instrument
    .natural_join(spot_prev, on=["Underlying"])
    .natural_join(vol_prev, on=["InstrumentId"])
    .natural_join(rates_prev, on=["Currency"])
    .natural_join(div_prev, on=["Underlying"])
    .update([
        "Ttm = opt_ttm(Expiry)",
        "TtmPrev = Ttm + DT_DAY",
        "PrevPrice = bs_price(PrevSpot, Strike, TtmPrev, PrevRate, PrevDivYield, PrevVol, OptionType)",
        "Delta = bs_delta(PrevSpot, Strike, TtmPrev, PrevRate, PrevDivYield, PrevVol, OptionType)",
        "Gamma = bs_gamma(PrevSpot, Strike, TtmPrev, PrevRate, PrevDivYield, PrevVol)",
        "Vega = bs_vega(PrevSpot, Strike, TtmPrev, PrevRate, PrevDivYield, PrevVol)",
        "Theta = bs_theta(PrevSpot, Strike, TtmPrev, PrevRate, PrevDivYield, PrevVol, OptionType)",
        "Rho = bs_rho(PrevSpot, Strike, TtmPrev, PrevRate, PrevDivYield, PrevVol, OptionType)",
        "DivRho = bs_div_rho(PrevSpot, Strike, TtmPrev, PrevRate, PrevDivYield, PrevVol, OptionType)",
        "Volga = bs_volga(PrevSpot, Strike, TtmPrev, PrevRate, PrevDivYield, PrevVol)",
    ])
)

# =========================================================================
# Derived table 2: live valuation per instrument (ticks with spot_live)
# =========================================================================

inst_now = (
    instrument
    .natural_join(spot_live, on=["Underlying"], joins=["Spot"])
    .natural_join(vol_live, on=["InstrumentId"])
    .natural_join(rates_live, on=["Currency"])
    .natural_join(div_live, on=["Underlying"])
    .update([
        "Ttm = opt_ttm(Expiry)",
        "CurrPrice = bs_price(Spot, Strike, Ttm, Rate, DivYield, Vol, OptionType)",
    ])
)

# =========================================================================
# Derived table 3: combined per-instrument risk view
# =========================================================================

risk = inst_prev.natural_join(
    inst_now.view(["InstrumentId", "Spot", "Vol", "Rate", "DivYield", "CurrPrice"]),
    on=["InstrumentId"],
)

# =========================================================================
# Derived table 4: intraday new-trade P&L per (Book, InstrumentId)
# =========================================================================
# NewTradePnl = sum over fills of signedQty * mult * (CurrPrice - ExecPrice)
#             = mult * (TradedQty * CurrPrice - TradedCost)

from deephaven import agg

exec_signed = executions.update([
    "SignedQty = Side == `BUY` ? ExecQty : -ExecQty",
    "SignedCost = SignedQty * ExecPrice",
])

trade_pnl = (
    exec_signed
    .agg_by(
        [agg.sum_(["TradedQty = SignedQty", "TradedCost = SignedCost"]),
         agg.count_("NumExecs")],
        by=["Book", "InstrumentId"],
    )
    .natural_join(risk, on=["InstrumentId"], joins=["CurrPrice", "Multiplier"])
    .update(["NewTradePnl = Multiplier * (TradedQty * CurrPrice - TradedCost)"])
)

# =========================================================================
# THE PAA OUTPUT TABLE — one row per (Book, InstrumentId)
# =========================================================================
# NOTE: trades on instruments with no SOD position are dropped by this
# natural_join; in production use a full outer join
# (deephaven.experimental.outer_joins) or merge a zero-SODQty row instead.

paa = (
    book_position
    .natural_join(risk, on=["InstrumentId"])
    .natural_join(trade_pnl, on=["Book", "InstrumentId"],
                  joins=["TradedQty", "NumExecs", "NewTradePnl"])
    .natural_join(fx_prev, on=["Currency"])
    .natural_join(fx_live, on=["Currency"])
    .update([
        # market moves T-1 -> T
        "DSpot = Spot - PrevSpot",
        "DVol = Vol - PrevVol",
        "DRate = Rate - PrevRate",
        "DDiv = DivYield - PrevDivYield",
        # position scale
        "PosScale = SODQty * Multiplier",
        # ---- Taylor-expansion attribution (local currency) ----
        "DeltaPnl = PosScale * Delta * DSpot",
        "GammaPnl = 0.5 * PosScale * Gamma * DSpot * DSpot",
        "VegaPnl = PosScale * Vega * DVol",
        "ThetaPnl = PosScale * Theta * DT_DAY",
        "RhoPnl = PosScale * Rho * DRate",
        "DivPnl = PosScale * DivRho * DDiv",
        "ExplainedPnl = DeltaPnl + GammaPnl + VegaPnl + ThetaPnl + RhoPnl + DivPnl",
        # ---- actuals and residual (local currency) ----
        "ActualPnl = PosScale * (CurrPrice - PrevPrice)",
        "UnexplainedPnl = ActualPnl - ExplainedPnl",
        "UnexplainedPct = ActualPnl == 0 ? 0.0 : 100.0 * UnexplainedPnl / abs(ActualPnl)",
        # ---- trading activity ----
        "NewTradePnl = isNull(NewTradePnl) ? 0.0 : NewTradePnl",
        "TradedQty = isNull(TradedQty) ? 0 : TradedQty",
        "TotalPnlLocal = ActualPnl + NewTradePnl",
        # ---- FX translation into base (USD) ----
        # base-ccy value change = ActualPnl*FxRate + FxPnl (exact identity)
        "FxPnl = PosScale * PrevPrice * (FxRate - PrevFxRate)",
        "ActualPnlBase = ActualPnl * FxRate",
        "ExplainedPnlBase = ExplainedPnl * FxRate",
        "UnexplainedPnlBase = UnexplainedPnl * FxRate",
        "NewTradePnlBase = NewTradePnl * FxRate",
        "TotalPnlBase = TotalPnlLocal * FxRate + FxPnl",
    ])
    .view([
        "Book", "InstrumentId", "Underlying", "Currency", "SODQty", "TradedQty",
        "PrevPrice", "CurrPrice", "DSpot", "DVol", "DRate", "DDiv",
        "DeltaPnl", "GammaPnl", "VegaPnl", "ThetaPnl", "RhoPnl", "DivPnl",
        "ExplainedPnl", "ActualPnl", "UnexplainedPnl", "UnexplainedPct",
        "NewTradePnl", "TotalPnlLocal",
        "FxPnl", "ActualPnlBase", "ExplainedPnlBase", "UnexplainedPnlBase",
        "NewTradePnlBase", "TotalPnlBase",
    ])
)
