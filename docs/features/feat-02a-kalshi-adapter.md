# feat-02a: Kalshi adapter

**Lane:** parallel, after feat-01. **Depends on:** feat-01 (models, `base.py`, `fetch.py`, snapshot fixture).
**Implements:** architecture §5.1, §5.2; venue_facts K1–K10; D4, D11, D13, D14, D22, D25, D37, A3.
**Owns only:** `src/equinox/adapters/kalshi.py`, `tests/test_kalshi.py`.

## Goal

Turn Kalshi's series, event and orderbook responses into canonical markets. That means both outcomes' books sorted best-first, Fed-decision terms, and fees taken from the series multiplier.

## Build

- `KalshiAdapter(VenueAdapter)` with `venue = "kalshi"`. It makes the requests listed in §5.2, through the injected `Fetcher` only. The base URL comes from the constructor; the default is K1.
- The field mapping exactly as in the §5.2 table. Notes:
  - **Books:** Kalshi lists bids ascending, with the best bid last (K4). YES asks are `1 − p` over `no_dollars`, cheapest first. An empty array means an empty book, not an error.
  - **Terms:** for the `fed_decision` family, parse `custom_strike` with the five shapes in §5.2. Any other shape → `terms=None`, plus a warning naming the ticker.
  - **observed_on:** the event's `strike_date`, converted to `America/New_York` with `zoneinfo`.
  - **Fee coefficient:** `Decimal("0.07") * multiplier`. Use the event's `fee_multiplier_override` if present, else the series' `fee_multiplier`.
  - **captured_at:** `clock()`, called when each orderbook is read. Kalshi's response has no timestamp (D37).
- A market that fails validation is skipped, with a warning. The other markets still return.

## Acceptance tests (snapshot via `FixtureFetcher`; write first, see each fail)

| # | Test | Expected |
|---|---|---|
| 1 | `fetch_markets()` | 5 markets, `kalshi:KXFEDDECISION-26OCT-{C26,C25,H0,H25,H26}`; no warnings |
| 2 | Terms per market | Exactly the Kalshi rows of the §4.4 table, observed_on 2026-10-28 |
| 3 | H0 books | YES best ask 0.8500 × 60329.95; NO best ask 0.1600 × 534.49; total YES ask depth 4,649,443.27 |
| 4 | C25 NO book | No asks (the snapshot has no YES bids) |
| 5 | Fees | coefficient 0.07, exponent 1, rounding_step 0.01 |
| 6 | Other fields | resolution institution `federalreserve.gov`; collateral USD with value; tradable True; trading_closes_at 2026-10-28T17:59Z; resolves_at 18:05Z; data_source as constructed |
| 7 | A fixture copy with `custom_strike {"Cut": "50"}` in a temp directory | That market has terms None, and a warning names it |
| 8 | A fixture copy with the event's `fee_multiplier_override: 0.5` | coefficient 0.035 |
| 9 | `clock` set to the snapshot's `FixtureFetcher.captured_at` | Every market's captured_at is 2026-10-10T20:44:29.495262Z |

## Done when

`make gate` passes, including `test_layering.py`.

## Out of scope

Other Kalshi series, discovering events, batch orderbook requests, and the live-failure fallback (the CLI handles that).
