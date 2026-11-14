import math
import unittest

from riskdash import pricing


class TestBlackScholes(unittest.TestCase):
    def test_textbook_values_hull(self):
        # Hull, Options Futures & Other Derivatives: S=42, K=40, r=10%, sigma=20%, T=0.5
        c = pricing.bs_price(42, 40, 0.5, 0.10, 0.20, "CE")
        p = pricing.bs_price(42, 40, 0.5, 0.10, 0.20, "PE")
        self.assertAlmostEqual(c, 4.76, places=2)
        self.assertAlmostEqual(p, 0.81, places=2)

    def test_textbook_value_with_dividend_yield(self):
        # Hull index option example: S=930, K=900, r=8%, q=3%, sigma=20%, T=2/12 -> call ~ 51.83
        c = pricing.bs_price(930, 900, 2 / 12, 0.08, 0.20, "CE", q=0.03)
        self.assertAlmostEqual(c, 51.83, places=1)

    def test_put_call_parity(self):
        for S, K, T, r, sig, q in [(24500, 24000, 8 / 365, 0.065, 0.13, 0.012),
                                   (100, 120, 1.0, 0.05, 0.4, 0.02),
                                   (1500, 1500, 30 / 365, 0.07, 0.55, 0.0)]:
            c = pricing.bs_price(S, K, T, r, sig, "CE", q)
            p = pricing.bs_price(S, K, T, r, sig, "PE", q)
            self.assertAlmostEqual(c - p, S * math.exp(-q * T) - K * math.exp(-r * T), places=8)

    def test_expired_option_is_intrinsic(self):
        self.assertEqual(pricing.bs_price(105, 100, 0, 0.05, 0.2, "CE"), 5)
        self.assertEqual(pricing.bs_price(105, 100, 0, 0.05, 0.2, "PE"), 0)
        g = pricing.bs_greeks(95, 100, 0, 0.05, 0.2, "PE")
        self.assertEqual(g["delta"], -1.0)
        self.assertEqual(g["gamma"], 0.0)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            pricing.bs_price(-1, 100, 1, 0.05, 0.2, "CE")
        with self.assertRaises(ValueError):
            pricing.bs_price(100, 100, 1, 0.05, 0.2, "XX")


class TestGreeksFiniteDifference(unittest.TestCase):
    CASES = [(24510, 24900, 8 / 365, 0.065, 0.128, 0.012, "CE"),
             (24510, 23800, 8 / 365, 0.065, 0.146, 0.012, "PE"),
             (100, 95, 0.75, 0.05, 0.3, 0.02, "CE"),
             (100, 110, 0.75, 0.05, 0.3, 0.02, "PE")]

    def test_greeks_match_bumps(self):
        for S, K, T, r, sig, q, t in self.CASES:
            g = pricing.bs_greeks(S, K, T, r, sig, t, q)
            f = lambda S_=S, T_=T, r_=r, s_=sig: pricing.bs_price(S_, K, T_, r_, s_, t, q)
            h = S * 1e-4
            delta_fd = (f(S_=S + h) - f(S_=S - h)) / (2 * h)
            gamma_fd = (f(S_=S + h) - 2 * f() + f(S_=S - h)) / (h * h)
            vega_fd = (f(s_=sig + 1e-4) - f(s_=sig - 1e-4)) / 2e-4 / 100
            dt = 1e-5
            theta_fd = -(f(T_=T + dt) - f(T_=T - dt)) / (2 * dt) / 365
            rho_fd = (f(r_=r + 1e-5) - f(r_=r - 1e-5)) / 2e-5 / 100
            msg = (S, K, t)
            self.assertAlmostEqual(g["delta"], delta_fd, delta=1e-5, msg=msg)
            self.assertAlmostEqual(g["gamma"], gamma_fd, delta=max(1e-6, abs(gamma_fd) * 1e-3), msg=msg)
            self.assertAlmostEqual(g["vega"], vega_fd, delta=max(1e-6, abs(vega_fd) * 1e-5), msg=msg)
            self.assertAlmostEqual(g["theta"], theta_fd, delta=max(1e-6, abs(theta_fd) * 1e-4), msg=msg)
            self.assertAlmostEqual(g["rho"], rho_fd, delta=max(1e-6, abs(rho_fd) * 1e-5), msg=msg)

    def test_atm_straddle_delta_near_zero(self):
        # Zero-carry ATM-forward straddle: call delta + put delta = 2N(d1) - 1, d1 = sigma*sqrt(T)/2
        S, T, sig = 24500, 7 / 365, 0.13
        c = pricing.bs_greeks(S, S, T, 0.0, sig, "CE")
        p = pricing.bs_greeks(S, S, T, 0.0, sig, "PE")
        self.assertLess(abs(c["delta"] + p["delta"]), 0.01)
        # with carry, a straddle struck at the forward is near-symmetric again
        r, q = 0.065, 0.012
        K = S * math.exp((r - q) * T)
        c = pricing.bs_greeks(S, K, T, r, sig, "CE", q)
        p = pricing.bs_greeks(S, K, T, r, sig, "PE", q)
        self.assertLess(abs(c["delta"] + p["delta"]), 0.01)
        # spot-ATM with carry: small positive delta (carry pushes the forward above K)
        c = pricing.bs_greeks(S, S, T, r, sig, "CE", q)
        p = pricing.bs_greeks(S, S, T, r, sig, "PE", q)
        self.assertTrue(0 < c["delta"] + p["delta"] < 0.06)


class TestImpliedVol(unittest.TestCase):
    def test_round_trip(self):
        for S, K, T, r, q in [(24510, 24900, 8 / 365, 0.065, 0.012), (1502, 1500, 8 / 365, 0.065, 0.0),
                              (100, 60, 1.0, 0.05, 0.0), (100, 150, 0.25, 0.05, 0.01)]:
            for sig in (0.05, 0.13, 0.35, 0.8, 1.8):
                for t in ("CE", "PE"):
                    price = pricing.bs_price(S, K, T, r, sig, t, q)
                    if pricing.bs_greeks(S, K, T, r, sig, t, q)["vega"] < 1e-4:
                        continue  # no time value left: IV not identifiable
                    iv = pricing.implied_vol(price, S, K, T, r, t, q)
                    self.assertAlmostEqual(pricing.bs_price(S, K, T, r, iv, t, q), price, places=5)
                    self.assertAlmostEqual(iv, sig, delta=1e-4, msg=(S, K, sig, t))

    def test_rejects_arbitrage_prices(self):
        with self.assertRaises(ValueError):
            pricing.implied_vol(150, 100, 100, 0.5, 0.05, "CE")  # above spot
        with self.assertRaises(ValueError):
            pricing.implied_vol(1.0, 120, 100, 0.5, 0.05, "CE")  # below intrinsic
        with self.assertRaises(ValueError):
            pricing.implied_vol(5.0, 100, 100, 0.0, 0.05, "CE")  # expired


if __name__ == "__main__":
    unittest.main()
