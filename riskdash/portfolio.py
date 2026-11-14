"""Positions, market snapshot, revaluation and book-level aggregation.

Positions CSV columns (header row required, case-insensitive):

    underlying   e.g. NIFTY, BANKNIFTY, ACMEIND (synthetic stock)
    type         CE | PE | FUT
    strike       option strike (ignored / may be blank for FUT)
    expiry       YYYY-MM-DD
    qty_lots     positive integer number of lots
    lot_size     units per lot (illustrative; exchange lot sizes change)
    entry_price  traded price per unit, rupees
    side         BUY | SELL
    iv           (options) current implied vol in percent, e.g. 14.5
    ltp          (options, optional) current option price; used to solve IV
                 when ``iv`` is blank

Market snapshot JSON (``market.json``)::

    {"valuation_date": "2026-11-16", "risk_free_rate": 0.065,
     "india_vix": 14.2,
     "underlyings": {"NIFTY": {"spot": 24510, "dividend_yield": 0.012,
                                "kind": "index"}},
     "event": {...optional, see scenarios.event_iv_crush...}}
"""

import csv
import datetime as _dt
import json
import math
from dataclasses import dataclass, field, replace

from . import pricing

REQUIRED_COLUMNS = ["underlying", "type", "strike", "expiry", "qty_lots",
                    "lot_size", "entry_price", "side"]
OPTIONAL_COLUMNS = ["iv", "ltp"]
VALID_TYPES = ("CE", "PE", "FUT")
VALID_SIDES = ("BUY", "SELL")
MIN_SIGMA = 0.005  # floor applied after IV shifts (0.5 vol)


class PositionValidationError(ValueError):
    """Raised with every problem found in a positions file, not just the first."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("Invalid positions file:\n  - " + "\n  - ".join(self.errors))


@dataclass(frozen=True)
class Position:
    underlying: str
    instrument: str          # CE / PE / FUT
    strike: float            # 0.0 for futures
    expiry: _dt.date
    qty_lots: int
    lot_size: int
    entry_price: float
    side: str                # BUY / SELL
    iv: float = None         # decimal, e.g. 0.145
    ltp: float = None
    iv_source: str = ""      # "input" | "solved from ltp"
    row: int = 0

    @property
    def sign(self):
        return 1 if self.side == "BUY" else -1

    @property
    def units(self):
        """Signed quantity in underlying units (lots x lot size)."""
        return self.sign * self.qty_lots * self.lot_size

    @property
    def is_option(self):
        return self.instrument in ("CE", "PE")

    def label(self):
        if self.is_option:
            return "%s %s %s %g %s x%d" % (self.side, self.underlying, self.expiry.isoformat(),
                                          self.strike, self.instrument, self.qty_lots)
        return "%s %s %s FUT x%d" % (self.side, self.underlying, self.expiry.isoformat(),
                                     self.qty_lots)


@dataclass
class UnderlyingMarket:
    spot: float
    dividend_yield: float = 0.0
    kind: str = "index"      # index | stock (drives illustrative margin params)


@dataclass
class Market:
    valuation_date: _dt.date
    risk_free_rate: float
    underlyings: dict
    india_vix: float = None
    event: dict = None
    notes: str = ""


# --------------------------------------------------------------------------- IO

def _parse_date(text):
    return _dt.datetime.strptime(str(text).strip(), "%Y-%m-%d").date()


def load_market(path):
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return market_from_dict(raw)


def market_from_dict(raw):
    errors = []
    try:
        vdate = _parse_date(raw["valuation_date"])
    except (KeyError, ValueError):
        errors.append("market: valuation_date missing or not YYYY-MM-DD")
        vdate = None
    rate = raw.get("risk_free_rate", 0.0)
    unders = {}
    for name, u in (raw.get("underlyings") or {}).items():
        spot = u.get("spot")
        if not isinstance(spot, (int, float)) or spot <= 0:
            errors.append("market: %s spot must be a positive number" % name)
            continue
        kind = u.get("kind", "index")
        if kind not in ("index", "stock"):
            errors.append("market: %s kind must be index or stock" % name)
        unders[name.upper()] = UnderlyingMarket(float(spot), float(u.get("dividend_yield", 0.0)), kind)
    if not unders:
        errors.append("market: at least one underlying with a spot is required")
    if errors:
        raise ValueError("; ".join(errors))
    return Market(vdate, float(rate), unders, raw.get("india_vix"), raw.get("event"),
                  raw.get("notes", ""))


def load_positions(path, valuation_date=None):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise PositionValidationError(["file is empty (no header row)"])
        return parse_positions(reader, valuation_date, fieldnames=reader.fieldnames)


def parse_positions(rows, valuation_date=None, fieldnames=None):
    """Validate dict rows into Positions. Collects all errors before raising."""
    rows = list(rows)
    errors = []
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    cols = {c.strip().lower() for c in fieldnames if c}
    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    if missing:
        raise PositionValidationError(["missing required column(s): " + ", ".join(missing)])
    if not rows:
        raise PositionValidationError(["no position rows found"])

    positions = []
    for i, raw in enumerate(rows, start=2):  # row 1 is the header
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not any(r.values()):
            continue
        row_err = []

        def num(name, cast=float, required=True, positive=True):
            text = r.get(name, "")
            if text == "":
                if required:
                    row_err.append("row %d: %s is required" % (i, name))
                return None
            try:
                val = cast(text)
            except ValueError:
                row_err.append("row %d: %s=%r is not a valid number" % (i, name, text))
                return None
            if positive and val <= 0:
                row_err.append("row %d: %s must be > 0 (got %s)" % (i, name, text))
                return None
            return val

        und = r.get("underlying", "").upper()
        if not und:
            row_err.append("row %d: underlying is required" % i)
        inst = r.get("type", "").upper()
        if inst not in VALID_TYPES:
            row_err.append("row %d: type must be one of CE/PE/FUT (got %r)" % (i, r.get("type", "")))
        side = r.get("side", "").upper()
        if side not in VALID_SIDES:
            row_err.append("row %d: side must be BUY or SELL (got %r)" % (i, r.get("side", "")))
        expiry = None
        try:
            expiry = _parse_date(r.get("expiry", ""))
        except ValueError:
            row_err.append("row %d: expiry %r must be YYYY-MM-DD" % (i, r.get("expiry", "")))
        if expiry and valuation_date and expiry < valuation_date:
            row_err.append("row %d: expiry %s is before valuation date %s"
                           % (i, expiry, valuation_date))
        is_opt = inst in ("CE", "PE")
        strike = num("strike", required=is_opt) if is_opt else 0.0
        qty = num("qty_lots", int)
        lot = num("lot_size", int)
        entry = num("entry_price", positive=False)
        if entry is not None and entry < 0:
            row_err.append("row %d: entry_price cannot be negative" % i)
        iv = num("iv", required=False) if is_opt else None
        ltp = num("ltp", required=False, positive=False) if is_opt else None
        if is_opt and r.get("iv", "") == "" and r.get("ltp", "") == "":
            row_err.append("row %d: options need iv (percent) or ltp to mark the position" % i)
        if iv is not None and iv > 300:
            row_err.append("row %d: iv=%s looks wrong; give percent e.g. 14.5" % (i, iv))

        if row_err:
            errors.extend(row_err)
            continue
        positions.append(Position(
            underlying=und, instrument=inst, strike=float(strike), expiry=expiry,
            qty_lots=qty, lot_size=lot, entry_price=float(entry), side=side,
            iv=(iv / 100.0) if iv is not None else None, ltp=ltp,
            iv_source="input" if iv is not None else "", row=i))
    if errors:
        raise PositionValidationError(errors)
    if not positions:
        raise PositionValidationError(["no position rows found"])
    return positions


# ---------------------------------------------------------------------- Book

def year_fraction(start, end):
    return max((end - start).days, 0) / 365.0


class Book:
    """A set of positions marked against a market snapshot."""

    def __init__(self, positions, market):
        self.market = market
        errors = []
        for p in positions:
            if p.underlying not in market.underlyings:
                errors.append("row %d: no spot for underlying %s in market snapshot"
                              % (p.row, p.underlying))
            if p.expiry < market.valuation_date:
                errors.append("row %d: expiry %s is before valuation date %s"
                              % (p.row, p.expiry, market.valuation_date))
        if errors:
            raise PositionValidationError(errors)
        self.positions = [self._resolve_iv(p) for p in positions]

    # -- marking helpers -------------------------------------------------
    def _resolve_iv(self, p):
        if not p.is_option or p.iv is not None:
            return p
        u = self.market.underlyings[p.underlying]
        T = year_fraction(self.market.valuation_date, p.expiry)
        try:
            iv = pricing.implied_vol(p.ltp, u.spot, p.strike, T, self.market.risk_free_rate,
                                     p.instrument, u.dividend_yield)
        except ValueError as exc:
            raise PositionValidationError(["row %d: could not solve IV from ltp %s (%s)"
                                           % (p.row, p.ltp, exc)])
        return replace(p, iv=iv, iv_source="solved from ltp")

    def underlyings(self):
        seen = []
        for p in self.positions:
            if p.underlying not in seen:
                seen.append(p.underlying)
        return seen

    def legs_for(self, underlying):
        return [p for p in self.positions if p.underlying == underlying]

    def lot_size_for(self, underlying):
        legs = self.legs_for(underlying)
        futs = [p.lot_size for p in legs if p.instrument == "FUT"]
        if futs:
            return futs[0]
        sizes = [p.lot_size for p in legs]
        return max(set(sizes), key=sizes.count)

    def nearest_expiry(self, underlying=None):
        legs = self.legs_for(underlying) if underlying else self.positions
        return min(p.expiry for p in legs)

    def futures_delta_per_unit(self, underlying):
        """Delta of one unit of the nearest futures contract (= e^{(r-q)T})."""
        u = self.market.underlyings[underlying]
        T = year_fraction(self.market.valuation_date, self.nearest_expiry(underlying))
        return math.exp((self.market.risk_free_rate - u.dividend_yield) * T)

    def leg_unit_value(self, p, spot=None, iv_shift_pts=0.0, days_forward=0, as_of=None):
        """Model value and Greeks per unit for one leg.

        ``as_of`` overrides the valuation date (used for payoff-at-expiry);
        otherwise valuation_date + days_forward is used.
        """
        u = self.market.underlyings[p.underlying]
        S = u.spot if spot is None else spot
        when = as_of or (self.market.valuation_date + _dt.timedelta(days=days_forward))
        T = year_fraction(when, p.expiry)
        r, q = self.market.risk_free_rate, u.dividend_yield
        if p.instrument == "FUT":
            carry = math.exp((r - q) * T)
            return {"price": S * carry, "delta": carry, "gamma": 0.0, "vega": 0.0,
                    "theta": 0.0, "rho": 0.0}
        sigma = max(p.iv + iv_shift_pts / 100.0, MIN_SIGMA)
        return pricing.bs_greeks(S, p.strike, T, r, sigma, p.instrument, q)

    def revalue_pnl(self, spot_shift_pct=0.0, iv_shift_pts=0.0, days_forward=0,
                    underlying=None, iv_shift_by_underlying=None):
        """Sum of (scenario value - current model value) x units, rupees."""
        total = 0.0
        for p in self.positions:
            if underlying and p.underlying != underlying:
                continue
            spot0 = self.market.underlyings[p.underlying].spot
            shift = iv_shift_pts
            if iv_shift_by_underlying and p.underlying in iv_shift_by_underlying:
                shift = iv_shift_by_underlying[p.underlying]
            now = self.leg_unit_value(p)["price"]
            scen = self.leg_unit_value(p, spot0 * (1 + spot_shift_pct / 100.0), shift, days_forward)["price"]
            total += (scen - now) * p.units
        return total

    # -- reporting views -------------------------------------------------
    def leg_table(self):
        out = []
        for p in self.positions:
            g = self.leg_unit_value(p)
            spot = self.market.underlyings[p.underlying].spot
            out.append({
                "label": p.label(), "underlying": p.underlying, "type": p.instrument,
                "strike": p.strike, "expiry": p.expiry.isoformat(), "side": p.side,
                "qty_lots": p.qty_lots, "lot_size": p.lot_size, "units": p.units,
                "entry_price": p.entry_price, "model_price": round(g["price"], 2),
                "iv_pct": round(p.iv * 100, 2) if p.iv is not None else None,
                "iv_source": p.iv_source,
                "mtm_pnl": round((g["price"] - p.entry_price) * p.units, 2),
                "delta_units": round(g["delta"] * p.units, 2),
                "delta_rupees": round(g["delta"] * p.units * spot, 0),
                "vega_rupees": round(g["vega"] * p.units, 2),
                "theta_rupees_per_day": round(g["theta"] * p.units, 2),
            })
        return out

    def greeks_by_underlying(self):
        res = {}
        for und in self.underlyings():
            spot = self.market.underlyings[und].spot
            agg = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
            for p in self.legs_for(und):
                g = self.leg_unit_value(p)
                for k in agg:
                    agg[k] += g[k] * p.units
            lot = self.lot_size_for(und)
            res[und] = {
                "spot": spot,
                "lot_size": lot,
                "delta_units": agg["delta"],
                "delta_lots_equiv": agg["delta"] / lot,
                "delta_rupees": agg["delta"] * spot,
                "gamma_units_per_point": agg["gamma"],
                # P&L from gamma alone for a 1% move: 0.5 * G * (1% of S)^2
                "gamma_pnl_1pct_move": 0.5 * agg["gamma"] * (0.01 * spot) ** 2,
                "vega_rupees_per_vol_pt": agg["vega"],
                "theta_rupees_per_day": agg["theta"],
                "rho_rupees_per_1pct": agg["rho"],
            }
        return res

    def totals(self):
        g = self.greeks_by_underlying()
        keys = ["delta_rupees", "gamma_pnl_1pct_move", "vega_rupees_per_vol_pt",
                "theta_rupees_per_day", "rho_rupees_per_1pct"]
        return {k: sum(v[k] for v in g.values()) for k in keys}

    def mtm_pnl(self):
        """Mark-to-model P&L versus entry prices, rupees."""
        return sum((self.leg_unit_value(p)["price"] - p.entry_price) * p.units
                   for p in self.positions)

    def net_premium(self):
        """Premium received (+) / paid (-) on option legs at entry."""
        return sum(-p.entry_price * p.units for p in self.positions if p.is_option)

    def payoff_at_expiry(self, underlying, spots):
        """P&L vs entry at the nearest expiry for this underlying.

        Legs expiring then settle at intrinsic (futures at S_T). Any later-dated
        legs are valued with Black-Scholes at their current IV on that date.
        """
        exp = self.nearest_expiry(underlying)
        out = []
        for s in spots:
            pnl = 0.0
            for p in self.legs_for(underlying):
                if p.expiry == exp:
                    val = s if p.instrument == "FUT" else pricing.intrinsic(s, p.strike, p.instrument)
                else:
                    val = self.leg_unit_value(p, spot=s, as_of=exp)["price"]
                pnl += (val - p.entry_price) * p.units
            out.append(pnl)
        return out

    def pnl_today(self, underlying, spots):
        """Mark-to-model P&L vs entry at the valuation date (T+0 curve)."""
        out = []
        for s in spots:
            out.append(sum((self.leg_unit_value(p, spot=s)["price"] - p.entry_price) * p.units
                           for p in self.legs_for(underlying)))
        return out


def breakevens(spots, pnls):
    """Spot levels where the P&L curve crosses zero (linear interpolation)."""
    out = []
    for i in range(1, len(spots)):
        a, b = pnls[i - 1], pnls[i]
        if a == 0 and (not out or out[-1] != spots[i - 1]):
            out.append(spots[i - 1])
        elif (a < 0 < b) or (a > 0 > b):
            out.append(spots[i - 1] + (spots[i] - spots[i - 1]) * (-a) / (b - a))
    return out


def load_book(positions_path, market_path):
    market = load_market(market_path)
    positions = load_positions(positions_path, market.valuation_date)
    return Book(positions, market)
