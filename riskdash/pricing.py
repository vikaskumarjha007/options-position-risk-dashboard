"""Black-Scholes(-Merton) pricing, Greeks and implied volatility.

European exercise with a continuous dividend yield / cost-of-carry term ``q``.
NSE index options and NSE stock options are both European-style, so the
European model is the right starting point (it still ignores discrete
dividends, early-exercise-free settlement nuances, skew and jumps).

Units used throughout:
    S, K       price in rupees
    T          time to expiry in years (calendar days / 365)
    r, q       continuously compounded, decimal (0.065 = 6.5%)
    sigma      decimal volatility (0.15 = 15%)
Greeks returned by :func:`bs_greeks` are *per one unit of underlying*:
    delta      dV/dS
    gamma      d2V/dS2 (per 1 rupee move)
    vega       change in V for +1 volatility point (sigma + 0.01)
    theta      change in V for one calendar day passing (negative = decay)
    rho        change in V for +1 percentage point in r
"""

import math

_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)


def norm_cdf(x):
    """Standard normal CDF via math.erf (stdlib only)."""
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def norm_pdf(x):
    return math.exp(-0.5 * x * x) / _SQRT2PI


def normalise_type(option_type):
    t = str(option_type).strip().upper()
    if t in ("CE", "C", "CALL"):
        return "CE"
    if t in ("PE", "P", "PUT"):
        return "PE"
    raise ValueError("option_type must be CE or PE, got %r" % (option_type,))


def _validate(S, K, T, sigma):
    if not (S > 0 and K > 0):
        raise ValueError("spot and strike must be positive")
    if T < 0:
        raise ValueError("time to expiry cannot be negative")
    if sigma < 0:
        raise ValueError("volatility cannot be negative")


def intrinsic(S, K, option_type):
    t = normalise_type(option_type)
    return max(S - K, 0.0) if t == "CE" else max(K - S, 0.0)


def _d1_d2(S, K, T, r, sigma, q):
    vol_sqrt_t = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vol_sqrt_t
    return d1, d1 - vol_sqrt_t


def bs_price(S, K, T, r, sigma, option_type, q=0.0):
    """Black-Scholes-Merton price of a European call (CE) or put (PE)."""
    _validate(S, K, T, sigma)
    t = normalise_type(option_type)
    if T == 0:
        return intrinsic(S, K, t)
    df_q = math.exp(-q * T)
    df_r = math.exp(-r * T)
    if sigma == 0:
        fwd_intr = S * df_q - K * df_r
        return max(fwd_intr, 0.0) if t == "CE" else max(-fwd_intr, 0.0)
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    if t == "CE":
        return S * df_q * norm_cdf(d1) - K * df_r * norm_cdf(d2)
    return K * df_r * norm_cdf(-d2) - S * df_q * norm_cdf(-d1)


def bs_greeks(S, K, T, r, sigma, option_type, q=0.0):
    """Price and Greeks per unit. See module docstring for units."""
    _validate(S, K, T, sigma)
    t = normalise_type(option_type)
    price = bs_price(S, K, T, r, sigma, t, q)
    if T == 0 or sigma == 0:
        # Expired / zero-vol: delta is a step function, other Greeks vanish.
        if t == "CE":
            delta = 1.0 if S > K else 0.0
        else:
            delta = -1.0 if S < K else 0.0
        return {"price": price, "delta": delta, "gamma": 0.0, "vega": 0.0,
                "theta": 0.0, "rho": 0.0}
    df_q = math.exp(-q * T)
    df_r = math.exp(-r * T)
    sqrt_t = math.sqrt(T)
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    pdf_d1 = norm_pdf(d1)
    gamma = df_q * pdf_d1 / (S * sigma * sqrt_t)
    vega = S * df_q * pdf_d1 * sqrt_t
    decay = -S * df_q * pdf_d1 * sigma / (2.0 * sqrt_t)
    if t == "CE":
        delta = df_q * norm_cdf(d1)
        theta = decay - r * K * df_r * norm_cdf(d2) + q * S * df_q * norm_cdf(d1)
        rho = K * T * df_r * norm_cdf(d2)
    else:
        delta = -df_q * norm_cdf(-d1)
        theta = decay + r * K * df_r * norm_cdf(-d2) - q * S * df_q * norm_cdf(-d1)
        rho = -K * T * df_r * norm_cdf(-d2)
    return {
        "price": price,
        "delta": delta,
        "gamma": gamma,
        "vega": vega / 100.0,      # per 1 vol point
        "theta": theta / 365.0,    # per calendar day
        "rho": rho / 100.0,        # per 1% change in r
    }


def implied_vol(price, S, K, T, r, option_type, q=0.0,
                lo=1e-4, hi=5.0, tol=1e-8, max_iter=300):
    """Implied volatility by bracketed bisection.

    BS price is strictly increasing in sigma, so bisection on a valid bracket
    always converges. The bracket upper bound is expanded (up to 2000% vol) if
    needed. Raises ValueError for prices outside no-arbitrage bounds or for
    expired options.
    """
    _validate(S, K, T, 0.0)
    t = normalise_type(option_type)
    if T == 0:
        raise ValueError("cannot imply volatility for an expired option")
    if price is None or price < 0:
        raise ValueError("price must be non-negative")
    df_q = math.exp(-q * T)
    df_r = math.exp(-r * T)
    if t == "CE":
        lower, upper = max(S * df_q - K * df_r, 0.0), S * df_q
    else:
        lower, upper = max(K * df_r - S * df_q, 0.0), K * df_r
    eps = 1e-10 * max(1.0, upper)
    if price < lower - eps or price >= upper:
        raise ValueError(
            "price %.6f outside no-arbitrage bounds [%.6f, %.6f)" % (price, lower, upper))
    if price <= lower + eps:
        return lo

    def f(sig):
        return bs_price(S, K, T, r, sig, t, q) - price

    f_lo = f(lo)
    if f_lo > 0:
        return lo  # price below the value at minimal vol: treat as ~zero vol
    while f(hi) < 0:
        hi *= 2.0
        if hi > 20.0:
            raise ValueError("implied volatility above 2000%; check inputs")
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = f(mid)
        if abs(f_mid) < tol or (hi - lo) < tol:
            return mid
        if f_mid < 0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
