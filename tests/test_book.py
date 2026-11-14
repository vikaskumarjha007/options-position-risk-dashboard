import datetime as dt
import io
import json
import os
import tempfile
import unittest
from html.parser import HTMLParser

from riskdash import hedge, margin, portfolio, report, scenarios

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(ROOT, "examples")
VDATE = dt.date(2026, 11, 16)
HEADER = "underlying,type,strike,expiry,qty_lots,lot_size,entry_price,side,iv,ltp\n"


def market(spot=24500.0, kind="index", event=None, und="NIFTY"):
    return portfolio.market_from_dict({
        "valuation_date": VDATE.isoformat(), "risk_free_rate": 0.065, "india_vix": 14.0,
        "underlyings": {und: {"spot": spot, "dividend_yield": 0.0, "kind": kind}}, "event": event})


def book_from_csv(text, mkt=None):
    rows = list(__import__("csv").DictReader(io.StringIO(text)))
    return portfolio.Book(portfolio.parse_positions(rows, VDATE), mkt or market())


def example_book(name):
    d = os.path.join(EX, name)
    return portfolio.load_book(os.path.join(d, "positions.csv"), os.path.join(d, "market.json"))


class TestCsvValidation(unittest.TestCase):
    def parse(self, text):
        import csv
        reader = csv.DictReader(io.StringIO(text))
        return portfolio.parse_positions(list(reader), VDATE, fieldnames=reader.fieldnames)

    def test_valid_rows(self):
        pos = self.parse(HEADER + "NIFTY,CE,24900,2026-11-24,2,75,42,SELL,12.8,\n"
                                  "NIFTY,FUT,,2026-11-24,1,75,24455,BUY,,\n")
        self.assertEqual(pos[0].units, -150)
        self.assertEqual(pos[1].units, 75)
        self.assertAlmostEqual(pos[0].iv, 0.128)

    def test_missing_column(self):
        with self.assertRaises(portfolio.PositionValidationError) as cm:
            self.parse("underlying,type,strike,expiry,qty_lots,lot_size,entry_price\nNIFTY,CE,1,2026-11-24,1,75,1\n")
        self.assertIn("side", str(cm.exception))

    def test_collects_all_row_errors(self):
        bad = (HEADER
               + "NIFTY,XX,24900,2026-11-24,2,75,42,SELL,12.8,\n"     # bad type
               + "NIFTY,CE,24900,24/11/2026,2,75,42,SELL,12.8,\n"     # bad date
               + "NIFTY,PE,24000,2026-11-24,0,75,42,SELL,12.8,\n"     # zero qty
               + "NIFTY,PE,24000,2026-11-24,1,75,42,HOLD,12.8,\n"     # bad side
               + "NIFTY,PE,,2026-11-24,1,75,42,SELL,12.8,\n"          # option without strike
               + "NIFTY,PE,24000,2026-11-24,1,75,42,SELL,,\n"         # no iv / ltp
               + "NIFTY,CE,24000,2026-11-01,1,75,42,SELL,13,\n"       # expired
               + "NIFTY,CE,24000,2026-11-24,1,75,abc,SELL,13,\n")     # non-numeric price
        with self.assertRaises(portfolio.PositionValidationError) as cm:
            self.parse(bad)
        errs = cm.exception.errors
        self.assertEqual(len(errs), 8, errs)
        joined = "\n".join(errs)
        for needle in ("row 2: type", "row 3: expiry", "row 4: qty_lots", "row 5: side",
                       "row 6: strike", "row 7: options need iv", "row 8: expiry 2026-11-01",
                       "row 9: entry_price"):
            self.assertIn(needle, joined)

    def test_iv_given_as_decimal_rejected_politely(self):
        with self.assertRaises(portfolio.PositionValidationError):
            self.parse(HEADER + "NIFTY,CE,24900,2026-11-24,2,75,42,SELL,1300,\n")

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "empty.csv")
            open(p, "w").close()
            with self.assertRaises(portfolio.PositionValidationError):
                portfolio.load_positions(p)

    def test_unknown_underlying_in_market(self):
        with self.assertRaises(portfolio.PositionValidationError):
            book_from_csv(HEADER + "SENSEX,CE,80000,2026-11-24,1,20,100,SELL,14,\n")

    def test_iv_solved_from_ltp(self):
        b = book_from_csv(HEADER + "NIFTY,CE,24500,2026-11-24,1,75,100,BUY,,150\n")
        p = b.positions[0]
        self.assertEqual(p.iv_source, "solved from ltp")
        self.assertAlmostEqual(b.leg_unit_value(p)["price"], 150, places=4)


class TestBookAggregation(unittest.TestCase):
    def test_greeks_scale_with_units_and_side(self):
        b = book_from_csv(HEADER + "NIFTY,CE,24500,2026-11-24,2,75,100,SELL,13,\n")
        g = b.greeks_by_underlying()["NIFTY"]
        unit = b.leg_unit_value(b.positions[0])
        self.assertAlmostEqual(g["delta_units"], -150 * unit["delta"])
        self.assertAlmostEqual(g["vega_rupees_per_vol_pt"], -150 * unit["vega"])
        self.assertGreater(g["theta_rupees_per_day"], 0)  # short option earns theta
        self.assertAlmostEqual(g["delta_rupees"], g["delta_units"] * 24500)

    def test_payoff_at_expiry_and_breakevens(self):
        # short 1 lot 24500 straddle for 300 total premium -> BE at 24200 / 24800
        b = book_from_csv(HEADER + "NIFTY,CE,24500,2026-11-24,1,75,160,SELL,13,\n"
                                   "NIFTY,PE,24500,2026-11-24,1,75,140,SELL,13,\n")
        spots = [24000 + 10 * i for i in range(101)]
        pnl = b.payoff_at_expiry("NIFTY", spots)
        self.assertAlmostEqual(pnl[spots.index(24500)], 300 * 75)
        bes = portfolio.breakevens(spots, pnl)
        self.assertEqual(len(bes), 2)
        self.assertAlmostEqual(bes[0], 24200, places=6)
        self.assertAlmostEqual(bes[1], 24800, places=6)

    def test_mtm_and_premium(self):
        b = book_from_csv(HEADER + "NIFTY,CE,24500,2026-11-24,1,75,100,BUY,13,\n")
        model = b.leg_unit_value(b.positions[0])["price"]
        self.assertAlmostEqual(b.mtm_pnl(), (model - 100) * 75)
        self.assertAlmostEqual(b.net_premium(), -7500)


class TestScenarios(unittest.TestCase):
    def test_grid_shape(self):
        b = example_book("a_nifty_short_strangle")
        g = scenarios.scenario_grid(b, [-2, 0, 2], [-5, 0, 5, 10], [0, 1])
        self.assertEqual(len(g["pnl"]), 2)
        self.assertTrue(all(len(plane) == 4 for plane in g["pnl"]))
        self.assertTrue(all(len(row) == 3 for plane in g["pnl"] for row in plane))
        self.assertAlmostEqual(g["pnl"][0][1][1], 0.0, places=6)  # no change -> zero P&L

    def test_monotonic_sanity(self):
        long_call = book_from_csv(HEADER + "NIFTY,CE,24500,2026-11-24,1,75,100,BUY,13,\n")
        g = scenarios.scenario_grid(long_call, [-3, -1, 0, 1, 3], [-5, 0, 5], [0])
        for row in g["pnl"][0]:
            self.assertEqual(row, sorted(row))                 # up in spot
        col = [g["pnl"][0][v][2] for v in range(3)]
        self.assertEqual(col, sorted(col))                     # up in IV (long vega)
        short_strangle = example_book("a_nifty_short_strangle")
        g = scenarios.scenario_grid(short_strangle, [0], [-10, -5, 0, 5, 10], [0, 1, 3])
        for plane in g["pnl"]:
            col = [row[0] for row in plane]
            self.assertEqual(col, sorted(col, reverse=True))   # short vega loses as IV rises
        flat = [plane[2][0] for plane in g["pnl"]]
        self.assertEqual(flat, sorted(flat))                   # short theta earns as time passes

    def test_event_iv_crush_hurts_long_straddle(self):
        b = example_book("c_stock_results_straddle")
        ev = scenarios.event_iv_crush(b, "ACMEIND", 20, days_forward=3)
        self.assertLess(ev["pnl_if_unchanged"], 0)
        self.assertTrue(all(r["crush_cost"] < 0 for r in ev["rows"]))
        self.assertEqual(len(ev["breakeven_moves_pct"]), 2)
        lo, hi = ev["breakeven_moves_pct"]
        self.assertLess(lo, 0)
        self.assertGreater(hi, 0)

    def test_vix_regimes(self):
        self.assertEqual(scenarios.vix_regime(10)["regime"], "Low")
        self.assertEqual(scenarios.vix_regime(12)["regime"], "Normal")
        self.assertEqual(scenarios.vix_regime(18)["regime"], "Elevated")
        self.assertEqual(scenarios.vix_regime(30)["regime"], "Stress")
        self.assertEqual(scenarios.vix_regime(None)["regime"], "Unknown")


class TestHedge(unittest.TestCase):
    def test_sizing_and_residual(self):
        h = hedge.suggest_futures_hedge(-65.6, 75)
        self.assertEqual(h["lots"], 1)
        self.assertEqual(h["side"], "BUY")
        self.assertAlmostEqual(h["residual_delta_units"], 9.4)
        h = hedge.suggest_futures_hedge(260, 75)       # 3.47 lots long -> sell 3
        self.assertEqual(h["lots"], -3)
        self.assertAlmostEqual(h["residual_delta_units"], 35)

    def test_rounding_half_away_from_zero(self):
        self.assertEqual(hedge.suggest_futures_hedge(-187.5, 75)["lots"], 3)    # 2.5 -> 3
        self.assertEqual(hedge.suggest_futures_hedge(187.5, 75)["lots"], -3)
        self.assertEqual(hedge.suggest_futures_hedge(-112.5, 75)["lots"], 2)    # 1.5 -> 2
        self.assertEqual(hedge.suggest_futures_hedge(10, 75)["lots"], 0)
        self.assertEqual(hedge.suggest_futures_hedge(10, 75)["side"], "NONE")

    def test_residual_never_exceeds_half_lot(self):
        for d in range(-500, 501, 7):
            h = hedge.suggest_futures_hedge(d, 35, 1.0013)
            self.assertLessEqual(abs(h["residual_delta_units"]), 35 * 1.0013 / 2 + 1e-9)

    def test_futures_delta_per_unit(self):
        h = hedge.suggest_futures_hedge(-150, 75, futures_delta_per_unit=1.0)
        h2 = hedge.suggest_futures_hedge(-150, 75, futures_delta_per_unit=1.01)
        self.assertAlmostEqual(h["exact_lots"], 2.0)
        self.assertLess(h2["exact_lots"], 2.0)

    def test_adjustment_check(self):
        self.assertTrue(hedge.adjustment_check(-40, 75, 0.5)["breached"])
        self.assertFalse(hedge.adjustment_check(-30, 75, 0.5)["breached"])
        self.assertEqual(hedge.adjustment_check(-40, 75, 0.5)["direction"], "short")
        with self.assertRaises(ValueError):
            hedge.adjustment_check(1, 75, -1)
        with self.assertRaises(ValueError):
            hedge.suggest_futures_hedge(1, 0)

    def test_example_a_is_delta_neutral_after_futures(self):
        b = example_book("a_nifty_short_strangle")
        g = b.greeks_by_underlying()["NIFTY"]
        self.assertLess(abs(g["delta_lots_equiv"]), 0.5)
        h = hedge.suggest_futures_hedge(g["delta_units"], g["lot_size"], b.futures_delta_per_unit("NIFTY"))
        self.assertEqual(h["lots"], 0)


class TestMargin(unittest.TestCase):
    def books(self):
        yield example_book("a_nifty_short_strangle")
        yield example_book("b_banknifty_iron_condor")
        yield example_book("c_stock_results_straddle")
        yield book_from_csv(HEADER + "NIFTY,CE,24500,2026-11-24,1,75,100,BUY,13,\n")

    def test_never_negative_and_covers_scan_loss(self):
        for b in self.books():
            mg = margin.rough_margin(b)
            self.assertGreaterEqual(mg["total"], 0)
            for und, v in mg["by_underlying"].items():
                self.assertGreaterEqual(v["scan_risk"], 0)
                self.assertGreaterEqual(v["exposure"], 0)
                p = v["params"]
                worst = max(0.0, max(-b.revalue_pnl(m, 0, 0, underlying=und,
                                                    iv_shift_by_underlying={und: iv}) * w
                                     for m, iv, w in margin.scan_scenarios(p["price_scan_pct"],
                                                                           p["vol_scan_pts"])))
                self.assertAlmostEqual(v["scan_risk"], worst, places=6)
                self.assertGreaterEqual(v["total"], worst)

    def test_defined_risk_condor_cheaper_than_naked(self):
        b = example_book("b_banknifty_iron_condor")
        naked = portfolio.Book([p for p in b.positions if p.side == "SELL"], b.market)
        self.assertLess(margin.rough_margin(b)["total"], margin.rough_margin(naked)["total"])

    def test_condor_scan_loss_bounded_by_wing_width(self):
        b = example_book("b_banknifty_iron_condor")
        width_loss = 500 * 5 * 35   # 500-pt wings x 5 lots x 35
        self.assertLessEqual(margin.rough_margin(b)["by_underlying"]["BANKNIFTY"]["scan_risk"], width_loss)


class TestReport(unittest.TestCase):
    def test_end_to_end_html_and_json(self):
        class Checker(HTMLParser):
            VOID = {"meta", "br", "img", "input", "link", "hr", "circle", "line", "rect", "path"}

            def __init__(self):
                super().__init__()
                self.stack, self.errors, self.tags = [], [], set()

            def handle_starttag(self, tag, attrs):
                self.tags.add(tag)
                if tag == "script" or (tag == "link") or any(k == "src" for k, _ in attrs):
                    self.errors.append("external/JS resource: %s" % tag)
                if tag not in self.VOID:
                    self.stack.append(tag)

            def handle_startendtag(self, tag, attrs):
                self.tags.add(tag)

            def handle_endtag(self, tag):
                if tag in self.VOID:
                    return
                if not self.stack or self.stack[-1] != tag:
                    self.errors.append("mismatched </%s>, open=%s" % (tag, self.stack[-3:]))
                else:
                    self.stack.pop()

        for name in ("a_nifty_short_strangle", "b_banknifty_iron_condor", "c_stock_results_straddle"):
            with tempfile.TemporaryDirectory() as d:
                html_path, json_path, s = report.write_report(
                    os.path.join(EX, name, "positions.csv"), d)
                c = Checker()
                with open(html_path, encoding="utf-8") as fh:
                    c.feed(fh.read())
                c.close()
                self.assertEqual(c.errors, [], name)
                self.assertEqual(c.stack, [], name)
                self.assertIn("svg", c.tags)
                with open(json_path, encoding="utf-8") as fh:
                    data = json.load(fh)
                for key in ("greeks_by_underlying", "hedge_suggestion", "scenario_grid",
                            "rough_margin", "warnings", "payoff", "disclaimer"):
                    self.assertIn(key, data)
                self.assertIn("NOT exchange SPAN", data["rough_margin"]["label"])

    def test_inr_formatting(self):
        self.assertEqual(report.fmt_inr(1234567), "₹12,34,567")
        self.assertEqual(report.fmt_inr(-999), "−₹999")
        self.assertEqual(report.fmt_inr(0.4), "₹0")
        self.assertEqual(report.fmt_compact(250000), "₹2.5L")

    def test_cli_returns_error_code_on_bad_csv(self):
        from riskdash.__main__ import main
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.csv")
            with open(p, "w") as fh:
                fh.write(HEADER + "NIFTY,XX,1,2026-11-24,1,75,1,SELL,13,\n")
            with open(os.path.join(d, "market.json"), "w") as fh:
                json.dump({"valuation_date": "2026-11-16", "risk_free_rate": 0.065,
                           "underlyings": {"NIFTY": {"spot": 24500}}}, fh)
            import contextlib
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["report", p, "--out", os.path.join(d, "o")]), 2)


if __name__ == "__main__":
    unittest.main()
