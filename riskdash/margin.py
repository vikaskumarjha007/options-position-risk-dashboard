"""ROUGH MARGIN APPROXIMATION - illustrative only. This is NOT exchange SPAN.

Real NSE Clearing margins come from SPAN risk-parameter files published
several times a day (price scan range, volatility scan range, short option
minimum charge, calendar-spread and inter-commodity credits) plus exposure
margin rules, extreme-loss margins and broker add-ons. None of those are
modelled exactly here.

What this module does, per underlying:
  1. "Scan risk": revalue the book on a SPAN-*like* grid - 7 price levels
     (-1, -2/3, -1/3, 0, +1/3, +2/3, +1) x price scan range, each with the
     volatility scan range up and down, plus two extreme moves (+/-2x price
     scan, vol unchanged) whose loss is weighted at 35%. Scan risk = worst
     loss, floored at zero.
  2. "Exposure": exposure_pct x gross notional of short options and futures.
  3. Total = scan risk + exposure, summed across underlyings with no
     cross-underlying offsets.
Long-only option books would in practice simply pay the premium upfront;
this approximation will show a small or zero figure for them.
"""

# Illustrative parameters only - NOT exchange values.
DEFAULT_PARAMS = {
    "index": {"price_scan_pct": 6.0, "vol_scan_pts": 4.0, "exposure_pct": 2.0},
    "stock": {"price_scan_pct": 12.0, "vol_scan_pts": 8.0, "exposure_pct": 3.5},
}
EXTREME_MULTIPLIER = 2.0
EXTREME_WEIGHT = 0.35
PRICE_FRACTIONS = [-1.0, -2.0 / 3, -1.0 / 3, 0.0, 1.0 / 3, 2.0 / 3, 1.0]

LABEL = "Rough margin approximation (illustrative, SPAN-like; NOT exchange SPAN)"


def scan_scenarios(price_scan_pct, vol_scan_pts):
    """List of (spot_move_pct, iv_shift_pts, weight)."""
    out = []
    for f in PRICE_FRACTIONS:
        for v in (vol_scan_pts, -vol_scan_pts):
            out.append((f * price_scan_pct, v, 1.0))
    for sgn in (-1, 1):
        out.append((sgn * EXTREME_MULTIPLIER * price_scan_pct, 0.0, EXTREME_WEIGHT))
    return out


def rough_margin(book, params=None):
    params = params or DEFAULT_PARAMS
    by_und = {}
    total = 0.0
    for und in book.underlyings():
        um = book.market.underlyings[und]
        p = params[um.kind]
        worst = 0.0
        worst_scn = None
        for move, vol, w in scan_scenarios(p["price_scan_pct"], p["vol_scan_pts"]):
            loss = -book.revalue_pnl(move, 0.0, 0, underlying=und,
                                     iv_shift_by_underlying={und: vol}) * w
            if loss > worst:
                worst, worst_scn = loss, {"spot_move_pct": move, "iv_shift_pts": vol, "weight": w}
        gross_short_notional = sum(
            abs(pos.units) * um.spot for pos in book.legs_for(und)
            if pos.instrument == "FUT" or (pos.is_option and pos.side == "SELL"))
        exposure = p["exposure_pct"] / 100.0 * gross_short_notional
        und_total = max(worst, 0.0) + exposure
        by_und[und] = {
            "scan_risk": max(worst, 0.0),
            "worst_scenario": worst_scn,
            "exposure": exposure,
            "exposure_base_notional": gross_short_notional,
            "total": und_total,
            "params": dict(p),
        }
        total += und_total
    return {"label": LABEL, "total": total, "by_underlying": by_und,
            "extreme_multiplier": EXTREME_MULTIPLIER, "extreme_weight": EXTREME_WEIGHT}
