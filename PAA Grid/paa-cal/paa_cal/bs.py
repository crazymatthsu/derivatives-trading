"""Black-Scholes pricer and Greeks for European vanilla options.

Identical math to deephaven-paa/02_paa_engine.py
The model is Black-Scholes-Merton with a continuous carry yield `q`
(dividend yield + stock borrow cost combined).

Common parameters (same meaning in every function)
---------------------------------------------------
s : float
    Spot price of the underlying stock, in the option's currency
    (e.g. 215.60).
k : float
    Strike price of the option, same units as `s` (e.g. 220.0).
t : float
    Time to expiry in YEARS (e.g. 0.4384 for ~160 calendar days,
    computed as days / 365). Must be >= 0; values <= 1e-8 are treated
    as "expired" and fall back to intrinsic value / zero Greeks.
r : float
    Continuously-compounded risk-free interest rate as a DECIMAL per
    year (e.g. 0.0425 means 4.25%).
q : float
    Continuous carry yield as a DECIMAL per year: dividend yield plus
    stock borrow cost (e.g. 0.0072 means 0.72%). This is the "borrDiv"
    input of the PAA grid.
v : float
    Implied volatility as a DECIMAL per year (e.g. 0.292 means 29.2
    vol points). Must be >= 0; values <= 1e-8 trigger the expired
    fallback.
cp : str
    Option type: the exact string "CALL" or "PUT" (anything that is
    not "CALL" is treated as a put).

Unit conventions of the outputs
-------------------------------
- price:    option premium per 1 unit of underlying (multiply by
            contract multiplier, e.g. 100, for the contract value).
- delta:    per 1.00 move in spot (dimensionless, -1..+1).
- gamma:    change of delta per 1.00 move in spot.
- vega:     per 1.00 change in vol (i.e. per 100 vol points).
            Divide by 100 for the per-vol-point vega quoted on desks.
- theta:    per YEAR of time decay. Divide by 252 for per-trading-day.
- rho:      per 1.00 change in the interest rate (per 10,000 bp).
            Divide by 10,000 for the per-basis-point rho.
- div_rho:  per 1.00 change in the carry yield q (same scaling as rho).
- volga:    change of vega per 1.00 change in vol (second derivative).

Intermediate quantities
-----------------------
d1 = [ln(s/k) + (r - q + v^2/2) t] / (v sqrt(t))
d2 = d1 - v sqrt(t)
N(x)   = standard normal CDF (probability that a standard normal <= x)
phi(x) = standard normal PDF (bell-curve density)
Under the risk-neutral measure, N(d2) is the probability the call
finishes in the money; s e^(-qt) N(d1) is the delta-weighted spot leg.
"""

import math


def _ncdf(x: float) -> float:
    """Standard normal cumulative distribution function N(x).

    Args:
        x: any real number.
    Returns:
        P(Z <= x) for Z ~ N(0,1), a probability in [0, 1].
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x: float) -> float:
    """Standard normal probability density function phi(x).

    Args:
        x: any real number.
    Returns:
        The bell-curve density at x, a positive float <= ~0.3989.
    """
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1d2(s, k, t, r, q, v):
    """The two Black-Scholes auxiliary terms.

    Args:
        s, k, t, r, q, v: see module docstring (all floats; t > 0, v > 0).
    Returns:
        (d1, d2) tuple of floats:
        d1 = [ln(s/k) + (r - q + v^2/2) t] / (v sqrt(t))
        d2 = d1 - v sqrt(t)
    """
    d1 = (math.log(s / k) + (r - q + 0.5 * v * v) * t) / (v * math.sqrt(t))
    return d1, d1 - v * math.sqrt(t)


def _expired(t, v):
    """True when the option should be valued at intrinsic (no optionality).

    Triggered by t <= 1e-8 (already expired / expiring now) or
    v <= 1e-8 (no volatility, so no time value). In this state price()
    returns intrinsic value and every Greek returns 0 (delta returns
    the +/-1 or 0 step function).

    Args:
        t: time to expiry in years (float).
        v: implied volatility as a decimal (float).
    Returns:
        bool — True if the intrinsic-value fallback applies.
    """
    return t <= 1e-8 or v <= 1e-8


def price(s, k, t, r, q, v, cp):
    """Fair value (theoretical price / "theo") of the option.

    The number the desk marks the option at: for a call,
    s e^(-qt) N(d1) - k e^(-rt) N(d2); for a put,
    k e^(-rt) N(-d2) - s e^(-qt) N(-d1).

    In the PAA engine this is used twice: with T-1 inputs it produces
    PrevPrice (yesterday's mark) and with live inputs CurrPrice
    (today's mark); ActualPnl = qty x mult x (CurrPrice - PrevPrice).

    Args:
        s, k, t, r, q, v, cp: see module docstring.
    Returns:
        float — option premium per 1 unit of underlying, >= 0.
        Falls back to intrinsic value max(s-k, 0) / max(k-s, 0) when
        expired.
    """
    if _expired(t, v):
        return max(s - k, 0.0) if cp == "CALL" else max(k - s, 0.0)
    d1, d2 = _d1d2(s, k, t, r, q, v)
    if cp == "CALL":
        return s * math.exp(-q * t) * _ncdf(d1) - k * math.exp(-r * t) * _ncdf(d2)
    return k * math.exp(-r * t) * _ncdf(-d2) - s * math.exp(-q * t) * _ncdf(-d1)


def delta(s, k, t, r, q, v, cp):
    """Delta: dV/dS — sensitivity of the option price to a 1.00 spot move.

    The share-equivalent exposure: an option with delta 0.51 gains
    ~0.51 when the stock rises 1.00. Calls have delta in (0, +1),
    puts in (-1, 0). Used in PAA as DeltaPnl = pos x delta x dSpot,
    and it is the hedge ratio traders read off the risk grid.

    Args:
        s, k, t, r, q, v, cp: see module docstring.
    Returns:
        float in [-1, +1] — e^(-qt) N(d1) for calls,
        e^(-qt) (N(d1) - 1) for puts. When expired: +/-1 if in the
        money (call/put respectively), else 0.
    """
    if _expired(t, v):
        itm = s > k if cp == "CALL" else s < k
        return (1.0 if cp == "CALL" else -1.0) if itm else 0.0
    d1, _ = _d1d2(s, k, t, r, q, v)
    dq = math.exp(-q * t)
    return dq * _ncdf(d1) if cp == "CALL" else dq * (_ncdf(d1) - 1.0)


def gamma(s, k, t, r, q, v):
    """Gamma: d2V/dS2 — how fast delta changes as spot moves.

    A long option position is always long gamma (>= 0): delta rises as
    spot rallies and falls as spot drops, which earns money on large
    moves in either direction. Identical for calls and puts, hence no
    `cp` argument. Used in PAA as GammaPnl = 0.5 x pos x gamma x dSpot^2
    (the 1/2 comes from the second-order Taylor term).

    Args:
        s, k, t, r, q, v: see module docstring.
    Returns:
        float >= 0 — e^(-qt) phi(d1) / (s v sqrt(t)); change in delta
        per 1.00 move in spot. 0 when expired.
    """
    if _expired(t, v):
        return 0.0
    d1, _ = _d1d2(s, k, t, r, q, v)
    return math.exp(-q * t) * _npdf(d1) / (s * v * math.sqrt(t))


def vega(s, k, t, r, q, v):
    """Vega: dV/dvol — sensitivity to a change in implied volatility.

    A long option is always long vega (>= 0): higher vol means more
    optionality value. Identical for calls and puts. Used in PAA as
    VegaPnl = pos x vega x dVol with dVol in decimals.

    Args:
        s, k, t, r, q, v: see module docstring.
    Returns:
        float >= 0 — s e^(-qt) phi(d1) sqrt(t), per 1.00 (=100 vol
        points) change in vol. Divide by 100 for the per-vol-point
        number desks quote. 0 when expired.
    """
    if _expired(t, v):
        return 0.0
    d1, _ = _d1d2(s, k, t, r, q, v)
    return s * math.exp(-q * t) * _npdf(d1) * math.sqrt(t)


def theta(s, k, t, r, q, v, cp):
    """Theta: dV/dt — time decay of the option value.

    Usually negative for long options: as one day passes with nothing
    else moving, the option loses time value. Composed of the vol-decay
    term (always negative for longs) plus carry terms in r and q that
    differ between calls and puts. Used in PAA as
    ThetaPnl = pos x theta x (1/252) — one trading day of decay.

    Args:
        s, k, t, r, q, v, cp: see module docstring.
    Returns:
        float — value change per YEAR of elapsed time (typically
        negative for a long option). Divide by 252 for per-trading-day
        theta. 0 when expired.
    """
    if _expired(t, v):
        return 0.0
    d1, d2 = _d1d2(s, k, t, r, q, v)
    decay = -s * math.exp(-q * t) * _npdf(d1) * v / (2.0 * math.sqrt(t))
    if cp == "CALL":
        return (decay - r * k * math.exp(-r * t) * _ncdf(d2)
                + q * s * math.exp(-q * t) * _ncdf(d1))
    return (decay + r * k * math.exp(-r * t) * _ncdf(-d2)
            - q * s * math.exp(-q * t) * _ncdf(-d1))


def rho(s, k, t, r, q, v, cp):
    """Rho: dV/dr — sensitivity to the risk-free interest rate.

    A higher rate raises the forward and cheapens the discounted
    strike, so calls gain (rho > 0) and puts lose (rho < 0). Used in
    PAA as RhoPnl = pos x rho x dRate with dRate in decimals.

    Args:
        s, k, t, r, q, v, cp: see module docstring.
    Returns:
        float — k t e^(-rt) N(d2) for calls, -k t e^(-rt) N(-d2) for
        puts; per 1.00 (=10,000 bp) rate change. Divide by 10,000 for
        per-basis-point rho. 0 when expired.
    """
    if _expired(t, v):
        return 0.0
    _, d2 = _d1d2(s, k, t, r, q, v)
    if cp == "CALL":
        return k * t * math.exp(-r * t) * _ncdf(d2)
    return -k * t * math.exp(-r * t) * _ncdf(-d2)


def div_rho(s, k, t, r, q, v, cp):
    """Dividend rho ("borrDiv" sensitivity): dV/dq — sensitivity to the
    carry yield (dividend + borrow).

    A higher carry yield lowers the forward, so calls lose
    (div_rho < 0) and puts gain (div_rho > 0) — the mirror image of
    rho. Used in the PAA grid as BorrDivPnl = pos x div_rho x dDiv.

    Args:
        s, k, t, r, q, v, cp: see module docstring.
    Returns:
        float — -t s e^(-qt) N(d1) for calls, +t s e^(-qt) N(-d1) for
        puts; per 1.00 change in q. 0 when expired.
    """
    if _expired(t, v):
        return 0.0
    d1, _ = _d1d2(s, k, t, r, q, v)
    if cp == "CALL":
        return -t * s * math.exp(-q * t) * _ncdf(d1)
    return t * s * math.exp(-q * t) * _ncdf(-d1)


def volga(s, k, t, r, q, v):
    """Volga (vomma): d2V/dvol2 — how fast vega changes as vol moves.

    The second-order vol Greek: positive for options away from
    at-the-money (their vega grows as vol rises), near zero for ATM
    options. Identical for calls and puts. Used in the PAA grid as
    VolgaPnl = 0.5 x pos x volga x dVol^2 — the vol analogue of the
    gamma term, capturing curvature when vol moves a lot.

    Args:
        s, k, t, r, q, v: see module docstring.
    Returns:
        float — vega x d1 x d2 / v, per 1.00^2 change in vol (can be
        negative when d1 and d2 straddle zero, i.e. near ATM).
        0 when expired.
    """
    if _expired(t, v):
        return 0.0
    d1, d2 = _d1d2(s, k, t, r, q, v)
    return vega(s, k, t, r, q, v) * d1 * d2 / v


def forward(s, t, r, q):
    """Forward price of the underlying for delivery at expiry.

    The no-arbitrage forward under continuous compounding:
    F = s e^((r - q) t). Rates raise the forward (cost of funding the
    stock), carry (dividends + borrow) lowers it (income the forward
    holder forgoes). Shown per ladder row in the risk grid.

    Args:
        s: spot price of the underlying (float, e.g. 215.60).
        t: time to delivery in years (float, >= 0).
        r: risk-free rate, decimal per year (float).
        q: carry yield (dividend + borrow), decimal per year (float).
    Returns:
        float — the forward price, same units as `s`.
    """
    return s * math.exp((r - q) * t)
