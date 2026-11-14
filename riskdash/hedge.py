"""Delta re-hedge sizing with futures and a delta-threshold adjustment check."""

import math


def round_half_away(x):
    """Round to nearest integer, halves away from zero (2.5 -> 3, -2.5 -> -3).

    Python's round() uses banker's rounding, which would make hedge sizing
    depend on parity - surprising for a dealer.
    """
    return int(math.copysign(math.floor(abs(x) + 0.5), x))


def suggest_futures_hedge(net_delta_units, lot_size, futures_delta_per_unit=1.0, spot=None):
    """Futures lots that bring the book closest to delta-neutral.

    net_delta_units        book delta in underlying units (shares / index units)
    lot_size               futures lot size
    futures_delta_per_unit delta of one futures unit (e^{(r-q)T}, ~1.0)

    Returns lots (signed: + buy, - sell), the side, the exact fractional lots,
    and the residual delta left after the rounded hedge.
    """
    if lot_size <= 0:
        raise ValueError("lot_size must be positive")
    if futures_delta_per_unit <= 0:
        raise ValueError("futures_delta_per_unit must be positive")
    per_lot = lot_size * futures_delta_per_unit
    exact = -net_delta_units / per_lot
    lots = round_half_away(exact)
    residual = net_delta_units + lots * per_lot
    out = {
        "net_delta_units": net_delta_units,
        "exact_lots": exact,
        "lots": lots,
        "side": "BUY" if lots > 0 else ("SELL" if lots < 0 else "NONE"),
        "abs_lots": abs(lots),
        "residual_delta_units": residual,
        "residual_delta_lots_equiv": residual / lot_size,
    }
    if spot is not None:
        out["residual_delta_rupees"] = residual * spot
    return out


def adjustment_check(net_delta_units, lot_size, threshold_lots=0.5):
    """Flag when |delta| exceeds a user threshold expressed in lots-equivalent."""
    if threshold_lots < 0:
        raise ValueError("threshold_lots cannot be negative")
    lots_equiv = net_delta_units / lot_size
    breached = abs(lots_equiv) > threshold_lots
    direction = "long" if lots_equiv > 0 else "short" if lots_equiv < 0 else "flat"
    msg = ("|delta| %.2f lots-equiv exceeds threshold %.2f: book is %s delta - re-hedge or adjust"
           % (abs(lots_equiv), threshold_lots, direction)) if breached else (
           "|delta| %.2f lots-equiv within threshold %.2f" % (abs(lots_equiv), threshold_lots))
    return {"breached": breached, "delta_lots_equiv": lots_equiv,
            "threshold_lots": threshold_lots, "direction": direction, "message": msg}
