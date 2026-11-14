# Test plan & traceability

Run: `python3 -m unittest` from the project root (stdlib only). All tests are automated;
files `tests/test_pricing.py` (P) and `tests/test_book.py` (B).

## Approach

- **Model correctness** – textbook values, put-call parity, Greeks vs finite differences, IV round-trips.
- **Business rules** – hedge sizing/rounding, threshold alert, margin floor and coverage, CSV validation.
- **Sanity / property checks** – monotonic scenario P&L, residual delta ≤ ½ lot for any input.
- **End-to-end** – all three example books through the report writer; HTML parsed with `html.parser`.

## Traceability matrix

| TC | Test (file › class › method) | What it checks | Story |
|---|---|---|---|
| TC-01 | B › TestCsvValidation › test_valid_rows | Signed units, IV % → decimal | US-01 |
| TC-02 | B › TestCsvValidation › test_missing_column | Missing required column named | US-01 |
| TC-03 | B › TestCsvValidation › test_collects_all_row_errors | 8 bad rows → 8 row-numbered errors | US-01 |
| TC-04 | B › TestCsvValidation › test_iv_given_as_decimal_rejected_politely | Implausible IV rejected | US-01 |
| TC-05 | B › TestCsvValidation › test_empty_file | Empty file rejected | US-01 |
| TC-06 | B › TestCsvValidation › test_unknown_underlying_in_market | Leg without a spot rejected | US-01 |
| TC-07 | B › TestReport › test_cli_returns_error_code_on_bad_csv | CLI exit code 2 on invalid CSV | US-01 |
| TC-08 | P › TestBlackScholes › test_textbook_values_hull | Hull call 4.76 / put 0.81 | US-02 |
| TC-09 | P › TestBlackScholes › test_textbook_value_with_dividend_yield | Index option with q (51.83) | US-02 |
| TC-10 | P › TestBlackScholes › test_put_call_parity | C − P = S·e^{−qT} − K·e^{−rT} | US-02 |
| TC-11 | P › TestBlackScholes › test_expired_option_is_intrinsic | T = 0 handling | US-02 |
| TC-12 | P › TestBlackScholes › test_invalid_inputs | Bad spot / option type | US-02 |
| TC-13 | P › TestImpliedVol › test_round_trip | IV solver recovers 5%–180% vols | US-02 |
| TC-14 | P › TestImpliedVol › test_rejects_arbitrage_prices | Out-of-bounds / expired prices | US-02 |
| TC-15 | B › TestCsvValidation › test_iv_solved_from_ltp | Leg marked to LTP via solved IV | US-02 |
| TC-16 | B › TestBookAggregation › test_mtm_and_premium | MTM vs entry, net premium sign | US-02 |
| TC-17 | P › TestGreeksFiniteDifference › test_greeks_match_bumps | Δ Γ vega θ ρ vs bumps | US-03 |
| TC-18 | P › TestGreeksFiniteDifference › test_atm_straddle_delta_near_zero | ATM straddle Δ ≈ 0 | US-03 |
| TC-19 | B › TestBookAggregation › test_greeks_scale_with_units_and_side | Book Greeks = unit × signed qty | US-03 |
| TC-20 | B › TestBookAggregation › test_payoff_at_expiry_and_breakevens | Straddle BE = K ± premium | US-04 |
| TC-21 | B › TestScenarios › test_grid_shape | days × IV × spot shape; zero cell | US-05 |
| TC-22 | B › TestScenarios › test_monotonic_sanity | Spot/IV/time monotonicity | US-05 |
| TC-23 | B › TestHedge › test_sizing_and_residual | Lots and residual arithmetic | US-06 |
| TC-24 | B › TestHedge › test_rounding_half_away_from_zero | 2.5 → 3, 1.5 → 2, small → 0 | US-06 |
| TC-25 | B › TestHedge › test_residual_never_exceeds_half_lot | Property over a delta sweep | US-06 |
| TC-26 | B › TestHedge › test_futures_delta_per_unit | Carry-adjusted futures delta | US-06 |
| TC-27 | B › TestHedge › test_adjustment_check | Threshold breach, direction, bad input | US-06 |
| TC-28 | B › TestHedge › test_example_a_is_delta_neutral_after_futures | Example (a) needs no trade | US-06 |
| TC-29 | B › TestScenarios › test_event_iv_crush_hurts_long_straddle | Crush loss, two break-even moves | US-07 |
| TC-30 | B › TestScenarios › test_vix_regimes | Band boundaries | US-08 |
| TC-31 | B › TestMargin › test_never_negative_and_covers_scan_loss | Margin ≥ 0 and ≥ max scan loss | US-09 |
| TC-32 | B › TestMargin › test_defined_risk_condor_cheaper_than_naked | Wings reduce margin | US-09 |
| TC-33 | B › TestMargin › test_condor_scan_loss_bounded_by_wing_width | Scan loss ≤ wing width × qty | US-09 |
| TC-34 | B › TestReport › test_end_to_end_html_and_json | 3 examples; well-formed HTML, no JS/external; JSON keys; SPAN label | US-10 |
| TC-35 | B › TestReport › test_inr_formatting | Indian grouping ₹12,34,567, lakh labels | US-10 |

Coverage: every Must/Should/Could story has ≥ 1 automated test. US-08 (Could) has one.

## Manual / UAT checks (not automated)

| Check | Story | Result (this build) |
|---|---|---|
| Open each example `dashboard.html` offline in a browser; charts and heatmaps render | US-10 | Pass |
| Narrow (phone-width) window: cards and tables reflow / scroll without breaking | US-10 | Pass |
| Breakeven markers on the payoff chart match the JSON values | US-04 | Pass |
| Rough-margin label visible in the section heading and card footnote | US-09 | Pass |

## Out of scope for testing

Exchange SPAN parity, live data feeds, performance with > 1,000 legs.
