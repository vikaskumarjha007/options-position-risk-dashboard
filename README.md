# Options Position Risk Dashboard (NSE index & stock options)

A small product case study plus a working build: load an options book from a CSV, see its
risk across **spot × implied volatility × time** in one offline HTML page, and get a
**futures re-hedge suggestion** when delta drifts.

> **All data is synthetic.** Positions, prices, IVs, India VIX levels and the stock `ACMEIND`
> are fictional. Lot sizes, expiry dates and margin parameters are **illustrative** (NSE
> changes lot sizes and expiry days from time to time). Nothing here is trading advice or
> anyone's real P&L.

## The problem

Active options traders and dealing/RMS desks running short-premium books (strangles, iron
condors, straddles) need to answer a few questions many times a day:

- *Am I still delta-neutral, and if not, how many futures lots fix it?*
- *What do I lose if NIFTY gaps 3% and IV jumps 5 points? What if nothing happens for 3 days?*
- *Where are my breakevens at expiry, and is the loss beyond them capped?*
- *If I am long a straddle into results, how big a move do I need once IV gets crushed?*

Broker terminals show per-leg Greeks and an expiry payoff, but rarely a **book-level
spot × IV × time grid, an event-IV-crush view, and a lot-rounded hedge** together.
This project specifies and builds that view.

## Users

| User | Needs from the dashboard |
|---|---|
| **Active options trader** (retail / prop) | Net Greeks in ₹, breakevens, "what if" grid, when to re-hedge |
| **Dealer / RMS analyst** | Quick book risk summary, threshold breaches, rough margin comparison across structures |
| **Product manager** (broker / exchange tech) | A reference spec for a "position risk" feature: personas, stories, acceptance criteria, tests |

## What it shows

Each run writes **one self-contained HTML file** (inline CSS + inline SVG, no JavaScript, no
external resources; works offline / as an email attachment) and a **JSON summary** for
downstream systems.

- **Book summary cards** – net delta (lots-equivalent, units, ₹ notional), gamma P&L for a 1% move,
  vega (₹ per vol point), theta (₹ per day), rho, mark-to-model P&L vs entry, net premium, rough margin.
- **Warnings & checks** – delta-threshold breach, short gamma near expiry, undefined-risk tails,
  India VIX regime tag, event IV-crush loss, IV-solved legs.
- **Delta re-hedge** – futures lots to trade (rounded), exact fractional lots, residual delta.
- **Payoff chart** – P&L at expiry vs entry (solid) and today's model P&L (dashed), breakevens marked.
- **Scenario heatmaps** – spot −5%…+5% × IV −10…+10 vol pts, at T+0, T+1, T+3 days.
- **Event scenario** – results-day IV crush: P&L with vs without crush, break-even move needed.
- **Rough margin approximation** – SPAN-*like* scan + exposure, clearly labelled *not exchange SPAN*.
- **Positions table** – per-leg model price, IV (input or solved from LTP), MTM, delta, vega, theta.

Committed example outputs (open in any browser):

| Example | Book | Dashboard | JSON |
|---|---|---|---|
| (a) | NIFTY short strangle, delta-hedged with 1 lot of futures | [dashboard.html](examples/a_nifty_short_strangle/outputs/dashboard.html) | [summary.json](examples/a_nifty_short_strangle/outputs/summary.json) |
| (b) | BANK NIFTY iron condor, spot rallied towards the short call | [dashboard.html](examples/b_banknifty_iron_condor/outputs/dashboard.html) | [summary.json](examples/b_banknifty_iron_condor/outputs/summary.json) |
| (c) | Fictional stock `ACMEIND` long straddle before results (IV crush) | [dashboard.html](examples/c_stock_results_straddle/outputs/dashboard.html) | [summary.json](examples/c_stock_results_straddle/outputs/summary.json) |

## Quick start

Python 3.9+ standard library only – nothing to install.

```bash
cd options-position-risk-dashboard
python3 -m riskdash report examples/a_nifty_short_strangle/positions.csv \
        --out examples/a_nifty_short_strangle/outputs
# optional: --market path/to/market.json  (default: market.json next to the CSV)
#           --delta-threshold-lots 0.5     (flag when |net delta| > 0.5 lots-equivalent)
python3 -m unittest            # 35 tests
```

Positions CSV (one row per leg; `iv` in percent, or leave it blank and give `ltp` to solve IV):

```csv
underlying,type,strike,expiry,qty_lots,lot_size,entry_price,side,iv,ltp
NIFTY,CE,24900,2026-11-24,6,75,42.00,SELL,12.8,
NIFTY,PE,23800,2026-11-24,6,75,31.00,SELL,14.6,
NIFTY,FUT,,2026-11-24,1,75,24455.00,BUY,,
```

`market.json` holds the valuation date, risk-free rate, India VIX, spot / dividend yield / kind
(index or stock) per underlying, and an optional `event` block for the IV-crush scenario.
Invalid files fail with **every** problem listed by row (e.g. `row 4: qty_lots must be > 0`).

## Sample output – example (a), NIFTY short strangle + futures hedge (synthetic)

Valuation 2026-11-16, NIFTY 24,510, India VIX 13.4 (→ *Normal* regime), 8 days to the illustrative expiry.
Short 6 lots 24900 CE + short 6 lots 23800 PE, long 1 lot NIFTY futures (lot size 75, illustrative).

| Metric | Value |
|---|---|
| Net delta | **+9.5 units = +0.13 lots-equivalent** (₹2.33 L notional) |
| Gamma P&L for a 1% move | −₹12,369 |
| Vega | −₹7,231 per +1 vol point |
| Theta | +₹6,278 per day |
| Net premium received | ₹32,850 |
| Breakevens at expiry | 24,017 / 25,077 |
| Hedge suggestion | **No trade** – exact −0.13 lots rounds to 0; residual +9.5 units, within the ±0.5-lot threshold |
| Worst scenario in grid | −₹3.48 L (spot −5%, IV +10 pts) |
| Rough margin approximation | ₹9.02 L (scan ₹4.24 L + exposure ₹4.78 L) – illustrative, not SPAN |

Without the futures leg the strangle alone is about −0.87 lots short delta – the dashboard would
then suggest *BUY 1 lot*. Example (b) shows the breach case: the condor is −0.53 lots short delta,
the tool suggests BUY 1 lot and shows that lot rounding leaves +0.47 lots residual – the kind of
trade-off a dealer should see before acting.

## Assumptions & limitations

- **Model:** Black-Scholes-Merton, European exercise, continuous dividend yield / carry. NSE
  index options **and** NSE stock options are European-style, so no early-exercise adjustment
  is needed. (Index options are cash-settled; stock options are physically settled – delivery
  obligations for ITM stock options are not modelled.) The model still ignores skew/smile dynamics,
  jumps, discrete dividends and the exact settlement-price mechanics.
- **Time:** calendar days / 365; an option expiring on the valuation date is valued at intrinsic.
- **Scenarios:** the same % spot move is applied to every underlying (no correlation model);
  IV shifts are parallel across strikes; scenario P&L is vs the current model mark.
- **Futures:** valued at cost-of-carry `S·e^{(r−q)T}`; basis is not modelled separately.
- **Margin:** a rough SPAN-*like* approximation with illustrative parameters. It is **not NSE
  SPAN** (no risk-parameter files, short-option minimum, spread credits, ELM or broker add-ons).
  Use it to compare structures, never to size capital.
- **VIX regimes:** illustrative bands (<12 Low, 12–16 Normal, 16–22 Elevated, ≥22 Stress), not
  an official classification.
- **Data:** synthetic snapshots only; no live prices.

## What I'd do next

1. **Live data via a broker API** (positions, LTP, option chain) with IVs solved from mid prices.
2. **Real SPAN:** parse NSE Clearing SPAN risk-parameter files for exchange-accurate margin and
   what-if margin on a proposed hedge.
3. **Intraday alerts:** push a notification when |delta|, gamma near expiry, or a scenario loss
   breaches a desk limit; log hedges for an audit trail.
4. **Skew-aware scenarios** (sticky-strike vs sticky-delta), per-underlying beta to NIFTY.
5. **Hedge optimiser** choosing between futures and options (e.g. buying wings) by cost and residual gamma.

## Project docs

- [Product spec](docs/product_spec.md) – problem, personas, JTBD, MVP scope, metrics, risks
- [User stories](docs/user_stories.md) – 10 stories, Given/When/Then, MoSCoW
- [Test plan](docs/test_plan.md) – test cases traced to stories

## Layout

```
riskdash/   pricing.py  portfolio.py  scenarios.py  hedge.py  margin.py  report.py  __main__.py
examples/   a_nifty_short_strangle/  b_banknifty_iron_condor/  c_stock_results_straddle/
            (positions.csv, market.json, outputs/dashboard.html, outputs/summary.json)
tests/      test_pricing.py  test_book.py
docs/       product_spec.md  user_stories.md  test_plan.md
```
