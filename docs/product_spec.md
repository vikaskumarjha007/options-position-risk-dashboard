# Product spec – Options Position Risk Dashboard

*Status: MVP built (this repo). Data: synthetic. Owner: BA/PO case study.*

## 1. Problem

Traders and dealing desks running multi-leg NSE options books (NIFTY, BANK NIFTY, stock options)
re-check the same risk questions many times a day: net delta and whether to re-hedge, exposure to a
gap move combined with an IV spike, decay versus gamma near expiry, and – around results – how much
an IV crush will cost. Typical broker screens show per-leg Greeks and an expiry payoff, but not a
book-level **spot × IV × time** view, a **lot-rounded hedge**, or an **event IV-crush** view in one
place. Users rebuild this in spreadsheets, which is slow, error-prone and hard to share with RMS.

**Problem statement:** *Active options traders and dealers lack a fast, shareable view of book risk
across spot, implied volatility and time, so re-hedging and sizing decisions are made late or on
partial information.*

## 2. Personas

| Persona | Context | Pain today | What success looks like |
|---|---|---|---|
| **Ravi – active index-options trader** | Sells delta-neutral premium on NIFTY / BANK NIFTY weeklies, sizes by India VIX, re-hedges with futures | Recomputes net delta by hand; unsure whether 0.6 lots of drift is worth a futures trade | Sees net delta in lots and a rounded hedge with residual in seconds |
| **Meera – dealer / RMS analyst** | Monitors client or desk books against limits | Needs a one-page summary she can forward; margin "what-ifs" need a separate tool | Opens one offline HTML file; sees breaches, worst scenario and rough margin |
| **Arjun – product manager, broker tech** | Owns the options trading experience on a broker platform | Needs a reference spec and acceptance criteria for a "position risk" feature | Reuses personas, stories and test traceability from this pack |

## 3. Jobs to be done

1. *When my book drifts after a move, I want to know how many futures lots bring it back to
   delta-neutral, so I can re-hedge without over-trading.*
2. *Before I add or hold a short-vol position, I want to see losses for gap + IV spike scenarios,
   so I can size within my risk tolerance.*
3. *Before results, I want to know the move required to break even after the IV crush, so I can
   decide whether a long straddle is worth it.*
4. *At the end of the day, I want a one-page risk snapshot I can share, so RMS / a colleague can
   review it without my spreadsheet.*

## 4. MVP scope

**In scope (built)**
- CSV positions import with row-level validation (all errors reported at once).
- Black-Scholes-Merton pricing, Greeks, IV solver (marks from IV or from LTP).
- Book Greeks in ₹ per underlying; MTM vs entry; payoff at expiry with breakevens.
- Scenario grid: spot −5…+5% × IV −10…+10 pts × T+0/1/3 days.
- Event IV-crush scenario with break-even move.
- India VIX regime tag (illustrative bands).
- Futures re-hedge suggestion (lot-rounded, residual shown) and delta-threshold alert.
- Rough margin approximation (SPAN-like, explicitly not exchange SPAN).
- Offline single-file HTML dashboard + JSON summary; CLI.

**Out of scope (MVP)**
- Live market data, broker/OMS integration, order placement.
- Exchange-accurate SPAN / ELM margins; physical-settlement obligations for stock options.
- Volatility skew dynamics, correlation between underlyings, American exercise.
- Multi-user storage, authentication, intraday push alerts.

## 5. Success metrics

| Metric | Target (pilot) | How measured |
|---|---|---|
| Time to answer "how many lots to re-hedge?" | < 10 s from CSV export (vs ~3–5 min in a spreadsheet) | Timed task with pilot users |
| Hedge decision accuracy | 100% match with manual calc on 20 test books | Test suite + UAT sample |
| Scenario coverage | ≥ 1 gap + IV-spike scenario reviewed before adding size | Self-reported / usage log |
| Adoption | ≥ 60% of pilot users generate a dashboard ≥ 3 days a week | Usage log |
| Data-quality friction | < 5% of runs fail validation after week 1 | CLI exit codes |

## 6. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Users treat the rough margin as real SPAN | Under-capitalised positions | Label in UI, JSON and docs; roadmap item: parse NSE SPAN files |
| BS with flat IV mis-states wing risk (skew) | Scenario losses understated for OTM shorts | Show tail-risk warning; roadmap: skew-aware scenarios |
| Stale or wrong IV input | Wrong Greeks and hedge | Option to solve IV from LTP; validation of IV range; show IV source per leg |
| Lot rounding leaves material residual delta | False comfort after hedging | Always show exact lots and residual alongside the rounded trade |
| Uniform % move across underlyings | Mixed books mis-stated | Documented; roadmap: beta-to-index |
| Regulatory perception (advice) | Compliance concern | Tool shows risk only, makes no trade recommendations beyond hedge arithmetic; disclaimer on every output |
