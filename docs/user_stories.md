# User stories

MoSCoW: **M** = Must, **S** = Should, **C** = Could, **W** = Won't (this release).
Personas: trader (Ravi), dealer/RMS (Meera), PM (Arjun) – see the product spec.

| ID | Story | MoSCoW |
|---|---|---|
| US-01 | Import & validate positions | M |
| US-02 | Mark the book (IV or LTP) | M |
| US-03 | Net Greeks in ₹ per underlying | M |
| US-04 | Payoff at expiry with breakevens | M |
| US-05 | Spot × IV × time scenario grid | M |
| US-06 | Futures re-hedge suggestion & delta alert | M |
| US-07 | Results-day IV-crush scenario | S |
| US-08 | India VIX regime tag | C |
| US-09 | Rough margin comparison | S |
| US-10 | Shareable offline dashboard + JSON | M |
| — | Live broker data / exchange SPAN / order placement | W |

---

**US-01 – Import & validate positions (M)**
As a trader, I want to load my positions from a CSV so that I don't re-key legs.
- *Given* a CSV with required columns, *when* I run the report, *then* every leg is loaded with signed units = lots × lot size × (+1 BUY / −1 SELL).
- *Given* a CSV with several bad rows (bad type, date, side, zero qty, missing strike/IV), *when* I run the report, *then* I see **all** errors with row numbers and the CLI exits with code 2 without writing output.
- *Given* an option expiring before the valuation date, *then* that row is rejected.

**US-02 – Mark the book (M)**
As a trader, I want each option marked from my IV, or from the last traded price when I don't have IV, so that P&L and Greeks reflect the market.
- *Given* an option row with `iv`, *then* it is priced with Black-Scholes-Merton at that IV.
- *Given* an option row with only `ltp`, *then* IV is solved so the model price equals the LTP (± ₹0.0001) and the leg is marked "solved from ltp".
- *Given* an LTP outside no-arbitrage bounds, *then* the row fails with a clear message.

**US-03 – Net Greeks in ₹ (M)**
As a trader, I want net delta, gamma, vega, theta and rho per underlying in ₹ so that I know what the book is exposed to.
- *Given* a book, *then* delta is shown in units, lots-equivalent and ₹ notional; vega per vol point; theta per calendar day; gamma as ₹ P&L for a 1% move.
- *Given* a short option, *then* theta is positive and vega negative.
- Greeks match finite-difference bumps of the pricer.

**US-04 – Payoff at expiry with breakevens (M)**
As a trader, I want the expiry payoff and breakevens so that I know my safe range.
- *Given* a short straddle at strike K with total premium P, *then* breakevens are K ± P and max profit is P × units.
- *Given* an undefined-risk book, *then* a tail-risk warning shows the loss at the edge of the range.

**US-05 – Scenario grid (M)**
As a dealer, I want P&L for spot −5…+5% × IV −10…+10 pts at T+0/1/3 so that I can see gap-plus-vol risk.
- *Given* any book, *then* the grid has shape days × IV shifts × spot moves and the (0%, 0 pts, T+0) cell is ₹0.
- *Given* a long call, *then* P&L rises with spot and with IV; *given* a short strangle, P&L falls as IV rises and rises as days pass (spot unchanged).

**US-06 – Futures re-hedge suggestion & delta alert (M)**
As a trader, I want the number of futures lots that brings me closest to delta-neutral, and an alert when |delta| exceeds my threshold.
- *Given* net delta D units and lot size L, *then* suggested lots = round-half-away(−D / (L × futures delta)) and the residual delta is shown in units, lots and ₹.
- *Given* |D| / L > threshold (default 0.5 lots), *then* a warning names the direction and the suggested trade.
- *Given* exactly 2.5 lots short, *then* the suggestion is BUY 3 (not banker's rounding to 2).

**US-07 – Results-day IV-crush scenario (S)**
As a trader holding a long straddle into results, I want to see P&L after an IV crush and N days so that I know the move I need.
- *Given* an event block (underlying, crush pts, days), *then* the dashboard shows P&L with and without the crush across spot moves and the break-even moves.
- *Given* spot unchanged, *then* a long straddle shows a loss and a warning.

**US-08 – India VIX regime tag (C)**
As a premium seller who sizes by VIX, I want the current VIX tagged with a regime so that I apply the right sizing rule.
- *Given* VIX = 13.4, *then* the tag is "Normal"; ≥ 16 "Elevated" with a warning; bands are documented as illustrative.

**US-09 – Rough margin comparison (S)**
As a dealer, I want a rough margin figure so that I can compare structures (e.g. condor vs naked strangle).
- *Then* margin = worst SPAN-like scan loss (≥ 0) + exposure % × short notional, and is never negative.
- *Given* an iron condor and the same book without wings, *then* the condor's figure is lower.
- The figure is labelled "NOT exchange SPAN" in HTML and JSON.

**US-10 – Shareable offline dashboard (M)**
As an RMS analyst, I want a single HTML file plus JSON so that I can forward or ingest the snapshot.
- *Then* the HTML is well-formed, has no scripts or external resources, includes the disclaimer, and the JSON has Greeks, hedge, grid, margin and warnings.
