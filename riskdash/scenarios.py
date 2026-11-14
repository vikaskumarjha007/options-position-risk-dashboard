"""Scenario analysis: spot x IV x time grid, event IV crush, VIX regime tag.

All scenario P&L is measured against the *current model value* of the book
(i.e. "what happens from here"), not against entry prices. Spot moves are
applied as the same percentage to every underlying in the book, and IV shifts
are parallel (same vol points on every strike) - no skew dynamics.
"""

DEFAULT_SPOT_MOVES = [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5]          # percent
DEFAULT_IV_SHIFTS = [-10, -5, 0, 5, 10]                              # vol points
DEFAULT_DAYS_FORWARD = [0, 1, 3]                                     # calendar days

# Illustrative India VIX regime bands. These are *not* an official
# classification; they are round numbers a premium seller might use to
# decide position size and strike distance. Document and tune per desk.
VIX_REGIMES = [
    (12.0, "Low", "Complacent vol: premiums thin, short-vol pays little for tail risk."),
    (16.0, "Normal", "Typical regime: standard sizing and strike distances."),
    (22.0, "Elevated", "Rich premiums but larger realised moves: widen strikes / cut size."),
    (float("inf"), "Stress", "Gap risk dominates: prefer defined-risk structures or stand aside."),
]


def vix_regime(vix):
    """Map an India VIX level to an illustrative regime tag."""
    if vix is None:
        return {"vix": None, "regime": "Unknown", "guidance": "No VIX supplied."}
    if vix < 0:
        raise ValueError("VIX cannot be negative")
    for upper, name, guidance in VIX_REGIMES:
        if vix < upper:
            return {"vix": vix, "regime": name, "guidance": guidance}


def scenario_grid(book, spot_moves=None, iv_shifts=None, days_forward=None):
    """P&L cube indexed pnl[d][v][s] (days x iv shift x spot move)."""
    spot_moves = list(DEFAULT_SPOT_MOVES if spot_moves is None else spot_moves)
    iv_shifts = list(DEFAULT_IV_SHIFTS if iv_shifts is None else iv_shifts)
    days_forward = list(DEFAULT_DAYS_FORWARD if days_forward is None else days_forward)
    cube = []
    for d in days_forward:
        plane = []
        for v in iv_shifts:
            plane.append([book.revalue_pnl(s, v, d) for s in spot_moves])
        cube.append(plane)
    flat = [x for plane in cube for row in plane for x in row]
    return {
        "spot_moves_pct": spot_moves,
        "iv_shifts_pts": iv_shifts,
        "days_forward": days_forward,
        "pnl": cube,
        "worst": min(flat),
        "best": max(flat),
    }


def event_iv_crush(book, underlying, iv_crush_pts, days_forward=1, spot_moves=None):
    """Results-day scenario: IV on ``underlying`` drops by ``iv_crush_pts``
    while time passes ``days_forward`` days, across a range of spot moves.

    Returns rows with P&L with the crush and without it (time decay only), plus
    the approximate spot move needed to break even after the crush.
    """
    if iv_crush_pts < 0:
        raise ValueError("iv_crush_pts is the size of the drop; pass a positive number")
    if spot_moves is None:
        spot_moves = [-12, -10, -8, -6, -4, -2, 0, 2, 4, 6, 8, 10, 12]
    rows = []
    for s in spot_moves:
        crushed = book.revalue_pnl(s, 0.0, days_forward, underlying=underlying,
                                   iv_shift_by_underlying={underlying: -iv_crush_pts})
        no_crush = book.revalue_pnl(s, 0.0, days_forward, underlying=underlying)
        rows.append({"spot_move_pct": s, "pnl_with_crush": crushed,
                     "pnl_no_crush": no_crush, "crush_cost": crushed - no_crush})
    # breakeven moves after crush (interpolate sign changes)
    be = []
    for a, b in zip(rows, rows[1:]):
        pa, pb = a["pnl_with_crush"], b["pnl_with_crush"]
        if (pa < 0 <= pb) or (pa >= 0 > pb):
            sa, sb = a["spot_move_pct"], b["spot_move_pct"]
            be.append(sa + (sb - sa) * (-pa) / (pb - pa) if pb != pa else sa)
    flat = next((r for r in rows if r["spot_move_pct"] == 0), None)
    return {
        "underlying": underlying,
        "iv_crush_pts": iv_crush_pts,
        "days_forward": days_forward,
        "rows": rows,
        "breakeven_moves_pct": be,
        "pnl_if_unchanged": flat["pnl_with_crush"] if flat else None,
    }
