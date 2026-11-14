"""Build the JSON summary and the self-contained HTML dashboard.

The HTML uses inline CSS and inline SVG only: no external JS, CSS, fonts or
images, so the file can be emailed or opened offline.
"""

import html
import json
import os

from . import hedge, margin, portfolio, scenarios

DISCLAIMER = ("Synthetic, fictional positions and market data for demonstration only. "
              "Lot sizes, expiries and margin parameters are illustrative. "
              "Not investment advice and not the author's trading results.")

PAYOFF_RANGE_PCT = {"index": 6.0, "stock": 15.0}
PAYOFF_POINTS = 161


# ------------------------------------------------------------------ formatting

def _indian_group(int_str):
    if len(int_str) <= 3:
        return int_str
    head, tail = int_str[:-3], int_str[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def fmt_inr(x, decimals=0):
    """Rupee amount with Indian digit grouping: 1234567 -> ₹12,34,567."""
    if x is None:
        return "-"
    neg = x < 0
    s = ("%." + str(decimals) + "f") % abs(x)
    whole, _, frac = s.partition(".")
    out = "₹" + _indian_group(whole) + ("." + frac if frac else "")
    return ("−" if neg and float(s) != 0 else "") + out


def fmt_compact(x):
    """Short axis label in lakh / crore."""
    a = abs(x)
    sign = "−" if x < 0 else ""
    if a >= 1e7:
        return "%s₹%.2fCr" % (sign, a / 1e7)
    if a >= 1e5:
        return "%s₹%.1fL" % (sign, a / 1e5)
    if a >= 1e3:
        return "%s₹%.0fk" % (sign, a / 1e3)
    return "%s₹%.0f" % (sign, a)


def fmt_level(x):
    """Index / price level with Indian grouping and 2 decimals."""
    whole, _, frac = ("%.2f" % x).partition(".")
    return _indian_group(whole) + "." + frac


def fmt_num(x, decimals=2):
    return "-" if x is None else ("%." + str(decimals) + "f") % x


def _r(x, nd=2):
    return None if x is None else round(x, nd)


# ------------------------------------------------------------------ analysis

def analyse(book, delta_threshold_lots=0.5, title=None, source=None):
    """Run every analysis and return a JSON-serialisable summary dict."""
    m = book.market
    regime = scenarios.vix_regime(m.india_vix)
    greeks = book.greeks_by_underlying()
    totals = book.totals()

    payoff, hedges, checks = {}, {}, {}
    for und in book.underlyings():
        um = m.underlyings[und]
        rng = PAYOFF_RANGE_PCT[um.kind]
        lo, hi = um.spot * (1 - rng / 100), um.spot * (1 + rng / 100)
        step = (hi - lo) / (PAYOFF_POINTS - 1)
        spots = [lo + i * step for i in range(PAYOFF_POINTS)]
        exp_pnl = book.payoff_at_expiry(und, spots)
        t0 = book.pnl_today(und, spots)
        payoff[und] = {
            "nearest_expiry": book.nearest_expiry(und).isoformat(),
            "days_to_expiry": (book.nearest_expiry(und) - m.valuation_date).days,
            "range_pct": rng,
            "spots": [_r(s, 2) for s in spots],
            "pnl_at_expiry": [_r(p, 2) for p in exp_pnl],
            "pnl_today": [_r(p, 2) for p in t0],
            "breakevens_at_expiry": [_r(b, 1) for b in portfolio.breakevens(spots, exp_pnl)],
            "max_profit_in_range": _r(max(exp_pnl)),
            "max_loss_in_range": _r(min(exp_pnl)),
            "loss_grows_at_edges": _edges_unbounded(exp_pnl),
        }
        g = greeks[und]
        hedges[und] = hedge.suggest_futures_hedge(
            g["delta_units"], g["lot_size"], book.futures_delta_per_unit(und), spot=um.spot)
        checks[und] = hedge.adjustment_check(g["delta_units"], g["lot_size"], delta_threshold_lots)

    grid = scenarios.scenario_grid(book)
    event = None
    if m.event:
        ev = m.event
        event = scenarios.event_iv_crush(book, ev["underlying"].upper(), float(ev["iv_crush_pts"]),
                                         int(ev.get("days_forward", 1)))
        event["name"] = ev.get("name", "Event")
        event["event_date"] = ev.get("date")
    mg = margin.rough_margin(book)

    summary = {
        "title": title or "Options position risk dashboard",
        "source_positions": source,
        "generated_by": "riskdash",
        "disclaimer": DISCLAIMER,
        "valuation_date": m.valuation_date.isoformat(),
        "risk_free_rate": m.risk_free_rate,
        "india_vix": m.india_vix,
        "vix_regime": regime,
        "market_notes": m.notes,
        "underlyings": {u: {"spot": v.spot, "dividend_yield": v.dividend_yield, "kind": v.kind}
                        for u, v in m.underlyings.items() if u in book.underlyings()},
        "legs": book.leg_table(),
        "greeks_by_underlying": {u: {k: _r(v, 4) if isinstance(v, float) else v
                                     for k, v in g.items()} for u, g in greeks.items()},
        "totals": {k: _r(v) for k, v in totals.items()},
        "mtm_pnl_vs_entry": _r(book.mtm_pnl()),
        "net_premium_received": _r(book.net_premium()),
        "payoff": payoff,
        "hedge_suggestion": {u: {k: _r(v, 3) if isinstance(v, float) else v for k, v in h.items()}
                             for u, h in hedges.items()},
        "adjustment_check": {u: {k: _r(v, 3) if isinstance(v, float) else v for k, v in c.items()}
                             for u, c in checks.items()},
        "scenario_grid": {**grid, "pnl": [[[_r(x) for x in row] for row in plane]
                                          for plane in grid["pnl"]],
                          "worst": _r(grid["worst"]), "best": _r(grid["best"])},
        "event_iv_crush": _round_event(event),
        "rough_margin": _round_margin(mg),
    }
    summary["warnings"] = build_warnings(book, summary)
    return summary


def _edges_unbounded(pnl):
    """True if the expiry P&L is still falling at either edge of the range."""
    return (pnl[0] < pnl[1] and pnl[0] < 0) or (pnl[-1] < pnl[-2] and pnl[-1] < 0)


def _round_event(ev):
    if not ev:
        return None
    ev = dict(ev)
    ev["rows"] = [{k: _r(v) for k, v in row.items()} for row in ev["rows"]]
    ev["breakeven_moves_pct"] = [_r(b) for b in ev["breakeven_moves_pct"]]
    ev["pnl_if_unchanged"] = _r(ev["pnl_if_unchanged"])
    return ev


def _round_margin(mg):
    out = dict(mg)
    out["total"] = _r(mg["total"])
    out["by_underlying"] = {
        u: {**v, "scan_risk": _r(v["scan_risk"]), "exposure": _r(v["exposure"]),
            "total": _r(v["total"]), "exposure_base_notional": _r(v["exposure_base_notional"])}
        for u, v in mg["by_underlying"].items()}
    return out


def build_warnings(book, s):
    w = []
    for und, c in s["adjustment_check"].items():
        if c["breached"]:
            h = s["hedge_suggestion"][und]
            w.append({"level": "warn", "topic": "Delta",
                      "text": "%s: %s. Suggested hedge: %s %d futures lot(s)."
                      % (und, c["message"], h["side"], h["abs_lots"])})
        else:
            w.append({"level": "ok", "topic": "Delta", "text": "%s: %s." % (und, c["message"])})
    for und, g in s["greeks_by_underlying"].items():
        dte = s["payoff"][und]["days_to_expiry"]
        if g["gamma_units_per_point"] < 0 and dte <= 3:
            w.append({"level": "warn", "topic": "Gamma",
                      "text": "%s: short gamma with %d day(s) to expiry - small moves cause large "
                              "delta swings (1%% move ≈ %s from gamma alone)."
                              % (und, dte, fmt_inr(g["gamma_pnl_1pct_move"]))})
        if s["payoff"][und]["loss_grows_at_edges"]:
            w.append({"level": "warn", "topic": "Tail risk",
                      "text": "%s: undefined-risk profile - expiry loss keeps growing beyond the "
                              "±%g%% range shown (%s at the edge)."
                              % (und, s["payoff"][und]["range_pct"],
                                 fmt_inr(s["payoff"][und]["max_loss_in_range"]))})
    reg = s["vix_regime"]
    if reg["regime"] in ("Elevated", "Stress"):
        w.append({"level": "warn", "topic": "Regime",
                  "text": "India VIX %.1f → %s regime. %s" % (reg["vix"], reg["regime"], reg["guidance"])})
    elif reg["regime"] != "Unknown":
        w.append({"level": "info", "topic": "Regime",
                  "text": "India VIX %.1f → %s regime. %s" % (reg["vix"], reg["regime"], reg["guidance"])})
    ev = s["event_iv_crush"]
    if ev and ev["pnl_if_unchanged"] is not None and ev["pnl_if_unchanged"] < 0:
        bes = ", ".join("%+.1f%%" % b for b in ev["breakeven_moves_pct"]) or "none in range"
        w.append({"level": "warn", "topic": "Event",
                  "text": "%s on %s: a %g-pt IV crush with spot unchanged loses %s; "
                          "break-even needs a move of %s."
                          % (ev["name"], ev["underlying"], ev["iv_crush_pts"],
                             fmt_inr(abs(ev["pnl_if_unchanged"])), bes)})
    grid = s["scenario_grid"]
    w.append({"level": "info", "topic": "Scenarios",
              "text": "Worst grid scenario %s; best %s (spot ±%g%%, IV ±%g pts, up to %d days)."
              % (fmt_inr(grid["worst"]), fmt_inr(grid["best"]),
                 max(abs(x) for x in grid["spot_moves_pct"]),
                 max(abs(x) for x in grid["iv_shifts_pts"]), max(grid["days_forward"]))})
    solved = [l["label"] for l in s["legs"] if l["iv_source"] == "solved from ltp"]
    if solved:
        w.append({"level": "info", "topic": "Marking",
                  "text": "IV solved from last traded price for %d leg(s)." % len(solved)})
    return w


# ------------------------------------------------------------------ SVG

def nice_ticks(lo, hi, target=5):
    """Round-number tick values (1/2/5 x 10^n steps) covering [lo, hi]."""
    import math
    raw = (hi - lo) / target
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
    v = math.ceil(lo / step) * step
    out = []
    while v <= hi + 1e-9:
        out.append(0.0 if abs(v) < step * 1e-9 else v)
        v += step
    return out


def svg_payoff(und, p, spot_now, width=760, height=320):
    spots, exp_pnl, t0 = p["spots"], p["pnl_at_expiry"], p["pnl_today"]
    L, R, T, B = 78, 18, 16, 42
    pw, ph = width - L - R, height - T - B
    ys = exp_pnl + t0 + [0.0]
    ymin, ymax = min(ys), max(ys)
    pad = (ymax - ymin) * 0.08 or 1.0
    ymin, ymax = ymin - pad, ymax + pad
    xmin, xmax = spots[0], spots[-1]

    def X(v):
        return L + (v - xmin) / (xmax - xmin) * pw

    def Y(v):
        return T + (ymax - v) / (ymax - ymin) * ph

    def path(vals):
        return "M" + " L".join("%.1f,%.1f" % (X(s), Y(v)) for s, v in zip(spots, vals))

    out = ['<svg class="chart" viewBox="0 0 %d %d" role="img" aria-label="%s payoff at expiry">'
           % (width, height, html.escape(und))]
    # profit / loss shading split at zero
    y0 = Y(0)
    out.append('<rect x="%d" y="%d" width="%d" height="%.1f" class="zone-profit"/>'
               % (L, T, pw, max(y0 - T, 0)))
    out.append('<rect x="%d" y="%.1f" width="%d" height="%.1f" class="zone-loss"/>'
               % (L, y0, pw, max(T + ph - y0, 0)))
    for v in nice_ticks(ymin, ymax):  # y grid at round values
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" class="grid"/>' % (L, L + pw, Y(v), Y(v)))
        out.append('<text x="%d" y="%.1f" class="tick" text-anchor="end">%s</text>'
                   % (L - 6, Y(v) + 4, fmt_compact(v)))
    for i in range(6):  # x ticks
        v = xmin + (xmax - xmin) * i / 5
        out.append('<text x="%.1f" y="%d" class="tick" text-anchor="middle">%s</text>'
                   % (X(v), T + ph + 16, _indian_group("%d" % round(v))))
    out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" class="zero"/>' % (L, L + pw, y0, y0))
    out.append('<line x1="%.1f" x2="%.1f" y1="%d" y2="%d" class="spot"/>'
               % (X(spot_now), X(spot_now), T, T + ph))
    out.append('<text x="%.1f" y="%d" class="tick spot-label" text-anchor="middle">spot %s</text>'
               % (X(spot_now), T + ph + 32, _indian_group("%d" % round(spot_now))))
    out.append('<path d="%s" class="line-t0"/>' % path(t0))
    out.append('<path d="%s" class="line-exp"/>' % path(exp_pnl))
    for i, be in enumerate(p["breakevens_at_expiry"]):
        out.append('<circle cx="%.1f" cy="%.1f" r="4.5" class="be"/>' % (X(be), y0))
        out.append('<text x="%.1f" y="%.1f" class="be-label" text-anchor="middle">BE %s</text>'
                   % (X(be), y0 - 10 if i % 2 == 0 else y0 + 20, _indian_group("%d" % round(be))))
    out.append("</svg>")
    return "\n".join(out)


def _heat_style(v, m):
    if m <= 0 or v is None:
        return ""
    t = max(-1.0, min(1.0, v / m))
    a = 0.12 + 0.6 * abs(t)
    if t >= 0:
        return ' style="background:rgba(22,140,74,%.2f)"' % a
    return ' style="background:rgba(205,44,44,%.2f)"' % a


# ------------------------------------------------------------------ HTML

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#16202a;--muted:#5b6673;--line:#dde2e8;--accent:#1f5fbf;
--warn:#b45309;--warnbg:#fff7e6;--ok:#15803d;--okbg:#ecfdf3;--info:#1f5fbf;--infobg:#eef4ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 10px}h3{font-size:14px;margin:14px 0 6px}
.sub{color:var(--muted);margin:0 0 12px}.disc{font-size:12px;color:var(--muted);border:1px dashed var(--line);
padding:8px 10px;border-radius:6px;background:var(--card)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.card .k{font-size:12px;color:var(--muted)}.card .v{font-size:20px;font-weight:600;margin-top:2px}
.card .s{font-size:12px;color:var(--muted)}
.panel{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:5px 8px;border-bottom:1px solid var(--line);
text-align:right;white-space:nowrap}th{color:var(--muted);font-weight:600}td.l,th.l{text-align:left}
.heat td{border:1px solid #fff}.heat th.corner{text-align:left}
.warn{list-style:none;padding:0;margin:0}.warn li{padding:7px 10px;border-radius:6px;margin-bottom:6px}
.warn .warn-l{background:var(--warnbg);border-left:4px solid var(--warn)}
.warn .ok-l{background:var(--okbg);border-left:4px solid var(--ok)}
.warn .info-l{background:var(--infobg);border-left:4px solid var(--info)}
.tag{font-weight:600;margin-right:6px}
svg.chart{width:100%;height:auto;display:block}
.zone-profit{fill:rgba(22,140,74,.06)}.zone-loss{fill:rgba(205,44,44,.06)}
.grid{stroke:#e8ecf0;stroke-width:1}.zero{stroke:#7a8794;stroke-width:1.2}
.spot{stroke:#8a6d00;stroke-width:1.2;stroke-dasharray:3 3}.spot-label{fill:#8a6d00}
.line-exp{fill:none;stroke:var(--accent);stroke-width:2.4}
.line-t0{fill:none;stroke:#7a8794;stroke-width:1.6;stroke-dasharray:6 4}
.be{fill:#fff;stroke:var(--ink);stroke-width:1.5}.be-label{font-size:11px;fill:var(--ink);font-weight:600}
.tick{font-size:11px;fill:var(--muted)}.legend{font-size:12px;color:var(--muted);margin-top:6px}
.sw{display:inline-block;width:18px;height:0;border-top:3px solid var(--accent);vertical-align:middle;margin-right:4px}
.sw.t0{border-top:2px dashed #7a8794}.pos{color:var(--ok)}.neg{color:#b42318}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:760px){.two{grid-template-columns:1fr}}
footer{margin-top:28px;font-size:12px;color:var(--muted)}
"""


def _cls(v):
    return "pos" if v is not None and v > 0 else ("neg" if v is not None and v < 0 else "")


def render_html(s):
    e = html.escape
    parts = ['<!DOCTYPE html>', '<html lang="en">', '<head>', '<meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<title>%s</title>' % e(s["title"]), '<style>%s</style>' % CSS, '</head>', '<body>',
             '<div class="wrap">']
    reg = s["vix_regime"]
    spots_txt = " · ".join("%s %s" % (u, fmt_level(v["spot"])) for u, v in s["underlyings"].items())
    parts.append('<h1>%s</h1>' % e(s["title"]))
    parts.append('<p class="sub">Valuation %s · %s · India VIX %s (%s regime, illustrative bands) · r = %.2f%%</p>'
                 % (e(s["valuation_date"]), e(spots_txt), fmt_num(s["india_vix"], 1),
                    e(reg["regime"]), s["risk_free_rate"] * 100))
    parts.append('<p class="disc">%s</p>' % e(s["disclaimer"]))

    # ---- Greeks summary cards
    t = s["totals"]
    mg = s["rough_margin"]
    parts.append('<h2>Book summary</h2><div class="cards">')
    for und, g in s["greeks_by_underlying"].items():
        parts.append('<div class="card"><div class="k">Net delta · %s</div><div class="v %s">%+.2f lots</div>'
                     '<div class="s">%+.1f units · %s notional</div></div>'
                     % (e(und), _cls(g["delta_units"]), g["delta_lots_equiv"], g["delta_units"],
                        fmt_inr(g["delta_rupees"])))
    cards = [
        ("Gamma P&amp;L, 1% move", fmt_inr(t["gamma_pnl_1pct_move"]), t["gamma_pnl_1pct_move"],
         "½·Γ·(1% of spot)², summed"),
        ("Vega", fmt_inr(t["vega_rupees_per_vol_pt"]), t["vega_rupees_per_vol_pt"], "per +1 vol point"),
        ("Theta", fmt_inr(t["theta_rupees_per_day"]), t["theta_rupees_per_day"], "per calendar day"),
        ("Rho", fmt_inr(t["rho_rupees_per_1pct"]), t["rho_rupees_per_1pct"], "per +1% rate"),
        ("Mark-to-model P&amp;L", fmt_inr(s["mtm_pnl_vs_entry"]), s["mtm_pnl_vs_entry"], "vs entry prices"),
        ("Net premium", fmt_inr(s["net_premium_received"]), s["net_premium_received"],
         "received (+) / paid (−)"),
        ("Rough margin*", fmt_inr(mg["total"]), None, "approximation, not SPAN"),
    ]
    for k, v, raw, sub in cards:
        parts.append('<div class="card"><div class="k">%s</div><div class="v %s">%s</div><div class="s">%s</div></div>'
                     % (k, _cls(raw), v, sub))
    parts.append('</div>')

    # ---- Warnings
    parts.append('<h2>Warnings &amp; checks</h2><ul class="warn">')
    for w in s["warnings"]:
        parts.append('<li class="%s-l"><span class="tag">%s</span>%s</li>'
                     % (w["level"], e(w["topic"]), e(w["text"])))
    parts.append('</ul>')

    # ---- Hedge
    parts.append('<h2>Delta re-hedge suggestion</h2><div class="panel"><table><tr>'
                 '<th class="l">Underlying</th><th>Net delta (units)</th><th>Exact lots</th>'
                 '<th class="l">Suggested futures trade</th><th>Residual delta (units)</th>'
                 '<th>Residual (lots)</th><th>Residual notional</th><th class="l">Threshold check</th></tr>')
    for und, h in s["hedge_suggestion"].items():
        c = s["adjustment_check"][und]
        trade = "No trade" if h["lots"] == 0 else "%s %d lot(s)" % (h["side"], h["abs_lots"])
        parts.append('<tr><td class="l">%s</td><td>%+.1f</td><td>%+.2f</td><td class="l"><b>%s</b></td>'
                     '<td>%+.1f</td><td>%+.2f</td><td>%s</td><td class="l">%s</td></tr>'
                     % (e(und), h["net_delta_units"], h["exact_lots"], trade, h["residual_delta_units"],
                        h["residual_delta_lots_equiv"], fmt_inr(h.get("residual_delta_rupees")),
                        ("⚠ breached (&gt; %.2f lots)" % c["threshold_lots"]) if c["breached"]
                        else "within ±%.2f lots" % c["threshold_lots"]))
    parts.append('</table><p class="legend">Rounded to whole lots (halves away from zero); '
                 'futures delta per unit = e^{(r−q)T} of the nearest expiry.</p></div>')

    # ---- Payoff charts
    parts.append('<h2>Payoff</h2>')
    for und, p in s["payoff"].items():
        bes = ", ".join(_indian_group("%d" % round(b)) for b in p["breakevens_at_expiry"]) or "none in range"
        parts.append('<div class="panel"><h3>%s · nearest expiry %s (%d day(s))</h3>'
                     % (e(und), e(p["nearest_expiry"]), p["days_to_expiry"]))
        parts.append(svg_payoff(und, p, s["underlyings"][und]["spot"]))
        parts.append('<p class="legend"><span class="sw"></span>P&amp;L at expiry vs entry &nbsp; '
                     '<span class="sw t0"></span>P&amp;L today (model) &nbsp; · Breakevens: <b>%s</b> · '
                     'Max profit in range %s · Max loss in range %s</p></div>'
                     % (bes, fmt_inr(p["max_profit_in_range"]), fmt_inr(p["max_loss_in_range"])))

    # ---- Scenario heatmaps
    g = s["scenario_grid"]
    m = max(abs(g["worst"]), abs(g["best"]))
    parts.append('<h2>Scenario P&amp;L (vs current mark)</h2>'
                 '<p class="sub">Rows: parallel IV shift (vol pts). Columns: spot move applied to every '
                 'underlying. Colour scale shared across tables.</p>')
    for di, d in enumerate(g["days_forward"]):
        parts.append('<div class="panel" style="margin-bottom:10px"><h3>T + %d day(s)</h3>'
                     '<table class="heat"><tr><th class="corner">IV \\ spot</th>' % d)
        parts.extend('<th>%+g%%</th>' % x for x in g["spot_moves_pct"])
        parts.append('</tr>')
        for vi, v in enumerate(g["iv_shifts_pts"]):
            parts.append('<tr><th class="l">%+g pts</th>' % v)
            for val in g["pnl"][di][vi]:
                parts.append('<td%s>%s</td>' % (_heat_style(val, m), fmt_compact(val)))
            parts.append('</tr>')
        parts.append('</table></div>')

    # ---- Event IV crush
    ev = s["event_iv_crush"]
    if ev:
        parts.append('<h2>Event scenario: %s (%s)</h2>' % (e(ev["name"]), e(ev["underlying"])))
        parts.append('<div class="panel"><p class="sub">IV on %s falls %g vol pts and %d day(s) pass '
                     '(event date %s). Break-even spot moves after crush: <b>%s</b>.</p>'
                     % (e(ev["underlying"]), ev["iv_crush_pts"], ev["days_forward"], e(str(ev["event_date"])),
                        ", ".join("%+.1f%%" % b for b in ev["breakeven_moves_pct"]) or "none in range"))
        parts.append('<table><tr><th>Spot move</th><th>P&amp;L with IV crush</th>'
                     '<th>P&amp;L without crush</th><th>Cost of crush</th></tr>')
        for r in ev["rows"]:
            parts.append('<tr><td>%+g%%</td><td class="%s">%s</td><td class="%s">%s</td><td class="%s">%s</td></tr>'
                         % (r["spot_move_pct"], _cls(r["pnl_with_crush"]), fmt_inr(r["pnl_with_crush"]),
                            _cls(r["pnl_no_crush"]), fmt_inr(r["pnl_no_crush"]),
                            _cls(r["crush_cost"]), fmt_inr(r["crush_cost"])))
        parts.append('</table></div>')

    # ---- Margin
    parts.append('<h2>%s</h2><div class="panel"><table><tr><th class="l">Underlying</th>'
                 '<th>Price scan</th><th>Vol scan</th><th>Scan risk (worst loss)</th>'
                 '<th class="l">Worst scenario</th><th>Exposure %%</th><th>Exposure</th><th>Total</th></tr>'
                 % e(mg["label"]))
    for und, v in mg["by_underlying"].items():
        ws = v["worst_scenario"]
        wtxt = ("spot %+.1f%%, IV %+g pts, weight %g" % (ws["spot_move_pct"], ws["iv_shift_pts"], ws["weight"])
                if ws else "no loss scenario")
        parts.append('<tr><td class="l">%s</td><td>±%g%%</td><td>±%g pts</td><td>%s</td><td class="l">%s</td>'
                     '<td>%g%%</td><td>%s</td><td><b>%s</b></td></tr>'
                     % (e(und), v["params"]["price_scan_pct"], v["params"]["vol_scan_pts"],
                        fmt_inr(v["scan_risk"]), e(wtxt), v["params"]["exposure_pct"],
                        fmt_inr(v["exposure"]), fmt_inr(v["total"])))
    parts.append('</table><p class="legend">* Illustrative parameters. Real NSE Clearing margins use '
                 'SPAN risk-parameter files, short-option minimums, spread credits and broker add-ons. '
                 'Use this only to compare structures, never to size real capital.</p></div>')

    # ---- Legs
    parts.append('<h2>Positions</h2><div class="panel"><table><tr><th class="l">Leg</th><th>Units</th>'
                 '<th>Entry</th><th>Model</th><th>IV %</th><th>MTM P&amp;L</th><th>Delta (units)</th>'
                 '<th>Vega ₹/pt</th><th>Theta ₹/day</th></tr>')
    for l in s["legs"]:
        iv = "-" if l["iv_pct"] is None else ("%.2f%s" % (l["iv_pct"], "†" if l["iv_source"] == "solved from ltp" else ""))
        parts.append('<tr><td class="l">%s</td><td>%+d</td><td>%s</td><td>%s</td><td>%s</td>'
                     '<td class="%s">%s</td><td>%+.1f</td><td>%s</td><td>%s</td></tr>'
                     % (e(l["label"]), l["units"], fmt_num(l["entry_price"]), fmt_num(l["model_price"]), iv,
                        _cls(l["mtm_pnl"]), fmt_inr(l["mtm_pnl"]), l["delta_units"],
                        fmt_inr(l["vega_rupees"]), fmt_inr(l["theta_rupees_per_day"])))
    parts.append('</table><p class="legend">† IV solved from the supplied last traded price. '
                 'Model: Black-Scholes-Merton (European), continuous dividend yield, calendar-day time.</p></div>')

    parts.append('<footer>Generated by riskdash from %s. %s</footer>'
                 % (e(str(s["source_positions"])), e(s["disclaimer"])))
    parts.append('</div></body></html>')
    return "\n".join(parts)


def write_report(positions_path, out_dir, market_path=None, delta_threshold_lots=0.5, title=None):
    if market_path is None:
        market_path = os.path.join(os.path.dirname(os.path.abspath(positions_path)), "market.json")
    book = portfolio.load_book(positions_path, market_path)
    summary = analyse(book, delta_threshold_lots, title, source=os.path.basename(positions_path))
    os.makedirs(out_dir, exist_ok=True)
    html_path = os.path.join(out_dir, "dashboard.html")
    json_path = os.path.join(out_dir, "summary.json")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(render_html(summary))
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    return html_path, json_path, summary
