# feat-02b: Polymarket adapter

**Lane:** parallel, after feat-01. **Depends on:** feat-01.
**Implements:** architecture §5.1, §5.3; venue_facts P1–P8; D11, D13, D14, D22, D25, D29.
**Owns only:** `src/equinox/adapters/polymarket.py`, `tests/test_polymarket.py`.

## Goal

Turn Polymarket's Gamma events and CLOB books into canonical markets, with term parsing for the Fed-decision family.

## Build

- `PolymarketAdapter(VenueAdapter)` with `venue = "polymarket"`. It makes the requests in §5.3 through the injected `Fetcher`, with configurable Gamma and CLOB base URLs.
- Parse `outcomes` and `clobTokenIds` with `json.loads`; they are strings that contain JSON (P1). If the outcomes aren't `["Yes", "No"]`, skip the market with a warning.
- **Books:** the YES token's `asks` and `bids` make the YES book; the NO token's make the NO book. Sort explicitly: CLOB returns bids ascending and asks descending, the best price last (P4). Polymarket's own OpenAPI spec says the opposite and is wrong. Never add one token's mirrored bids to the other token's asks (P5).
- **Terms (`fed_decision`):** parse `groupItemTitle` per §5.3. observed_on is the last day in "scheduled for October 27-28, 2026" in `description`. If that phrase is missing, use `endDate` converted to `America/New_York` and add a warning. A tracked event with any other family → terms None for its markets, plus one warning.
- **Fees:** `feesEnabled` false → coefficient 0. Otherwise `feeSchedule.rate` and `feeSchedule.exponent`; step 0.00001. Never read `takerBaseFee`; it is not a rate (P7).
- **captured_at:** the earlier of the two books' `timestamp` values (epoch milliseconds, UTC). The adapter accepts the `clock` argument (§5.1) and doesn't need it.

## Acceptance tests (snapshot via `FixtureFetcher`)

| # | Test | Expected |
|---|---|---|
| 1 | `fetch_markets()` with the default tracked events | 5 markets: 2589810–2589814; no warnings |
| 2 | Fed terms | The Polymarket rows of the §4.4 table, observed_on 2026-10-28 |
| 3 | 2589812 books | YES best ask 0.84 × 295850.63; NO best ask 0.17 × 67936.43; YES total ask depth 3,453,123.38 |
| 4 | Fees | coefficient 0.05, exponent 1, step 0.00001; the coefficient a `Decimal`, not a float |
| 5 | captured_at for 2589812 | 1791665072057 ms → 2026-10-10T20:44:32.057Z |
| 6 | A fixture copy with `outcomes: "[\"Up\", \"Down\"]"` | That market is skipped, and a warning names it |
| 7 | A fixture copy with `feesEnabled: false, feeSchedule: null` | coefficient 0 |
| 8 | A fixture copy with no "scheduled for" text | observed_on taken from `endDate` in New York time, plus a warning |
| 9 | The snapshot's AAPL event tracked with family `stock_close_above` | 5 markets with terms None, books and fees still filled (coefficient 0.04), plus one warning that the family has no parser |

## Done when

`make gate` passes.

## Out of scope

Term parsers for other families (stock "closes above" is only a fit-check example, architecture §9), "Up or Down" markets, v2 `positionIds` beyond reading them when `clobTokenIds` is null, the keyset endpoints, and event discovery.
