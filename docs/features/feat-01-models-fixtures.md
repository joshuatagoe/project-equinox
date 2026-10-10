# feat-01: Models, fetchers, fixtures and golden data

**Lane:** runs first, alone. **Depends on:** nothing (workflow prep fixes `make gate` on Windows first).
**Implements:** architecture §4, §5.1, §8.1, §3 (layering guard), §9.3 and §10 (golden file); D3, D11, D13, D14, D17, D22, D24, D25, D26, D29, D30.
**Owns only these files:**
- `src/equinox/models/*`
- `src/equinox/adapters/__init__.py`, `adapters/base.py`, `adapters/fetch.py`
- `src/equinox/fixtures/**`, `src/equinox/tracked_events.json`
- `tests/golden/canonical_markets.json`, `tests/test_models.py`, `tests/test_layering.py`
- `requirements.txt`
- The path constants in `docs/research/running_example.py` and `capture_snapshot.py`

## Goal

Fix every shape the other lanes build against, and the data they test with. After this lane, the adapters, the matcher and the router can be built at the same time without talking to each other.

## Build

1. **Dependencies.** Add `pydantic` 2.x and `tzdata` to `requirements.txt`, each pinned to the exact latest release (look it up with `pip index versions`, don't guess). Without `tzdata`, Windows has no time-zone data (architecture §10).
2. **Models.** Write the models in architecture §4.1–4.4 and §8.1, with exactly those names and fields, and the validation rules in §4.5. `FeeSchedule.fee(fills)` rounds up once with `ROUND_CEILING` to `rounding_step`. Also add:
   - `QuoteReason`, `QuoteWarning`, `RoutingStatus` and `EXIT_CODES` (§7.2), in `models/routing.py`;
   - `EquivalenceStatus`, `MatchResult` and `EquivalenceCluster` (§8.1), in `models/equivalence.py`.
3. **Adapter base.** `adapters/base.py` holds `Fetcher`, `FetchError`, `TrackedEvent`, `AdapterResult` and `VenueAdapter`, as in §5.1.
4. **Fetchers.** `adapters/fetch.py` holds:
   - `HttpFetcher(timeout)`: urllib, a `User-Agent` header, `json.loads(body, parse_float=Decimal)`. Raises `FetchError` on any HTTP or parse error.
   - `FixtureFetcher(snapshot_dir)`: reads the directory's `index.json` (filename → URL) and serves the file for a URL. Query-parameter order is ignored. Raises `FetchError` for a URL that isn't in the index.
5. **Snapshot fixture.** `git mv docs/research/samples/snapshot-2026-10-10 src/equinox/fixtures/snapshot-2026-10-10`. Do not edit any response file. Update the two research scripts to the new path.
6. **Tracked events.** `tracked_events.json` lists Kalshi `KXFEDDECISION-26OCT` and Polymarket `fed-decision-in-october-20260617190323537`, both with family `fed_decision`.
7. **Golden canonical markets.** `tests/golden/canonical_markets.json` holds hand-written `CanonicalMarket` objects, in three groups. The books carry the top 3 levels of every side.
   - **Fed markets**, with books copied from the snapshot:
     - Kalshi C25, C26, H0 and H26.
     - Polymarket 2589810–2589814.
     - Terms, fees, collateral and tradability exactly as the adapters will produce them (§4.4, §5.2, §5.3).
   - **Fit-check markets (architecture §9.3).** No adapter produces these; they stand in for a venue like Meridian. Label each with `venue_metadata: {"fit_check": true}`.
     - Polymarket 5455686 ("$330") and 5455687 ("$335"): terms from the §4.4 table; books copied from the research snapshot's `polymarket_book_5455686_*.json` and `…5455687_*.json`; fee coefficient 0.04, step 0.00001.
     - Meridian-style AAPL-330 and AAPL-320 for 2026-10-12, mapped as in §9.1: devnet USDC with no value, coefficient 0, step 0.01. AAPL-330's book is YES asks [(0.95, 5)] and YES bids [(0.93, 5)], so NO asks [(0.07, 5)] and NO bids [(0.05, 5)]. AAPL-320 has a similar 5-contract book.
     - The E9 variant (AAPL-330 on 2026-10-13) and the E10 variant (an `official_close` copy of AAPL-330).
   - **Six term-less markets** with the titles in architecture §6.4 E11–E13.
8. **Layering guard.** `tests/test_layering.py` as described in architecture §3. Until the engine folders exist it skips them, but it must fail if a venue name or a forbidden import appears.

## Acceptance tests (write each first and see it fail)

| # | Test | Expected |
|---|---|---|
| 1 | Fee: Kalshi coefficient 0.07, fills [(0.85, 100)], step 0.01 | 0.90 (raw 0.8925) |
| 2 | Fee: Polymarket coefficient 0.05, [(0.84, 100)], step 0.00001 | 0.672 |
| 3 | Fee: Kalshi, [(0.16, 534.49), (0.17, 4465.51)] | 49.14 (raw 49.13432419) |
| 4 | Fee per level vs on the average price: coefficient 0.07, [(0.10, 100), (0.90, 100)] | 1.26 per level; the average-price formula would give 3.50 (the test documents why D5 exists) |
| 5 | Each §4.5 rule rejects its bad input | `ValidationError` |
| 6 | `FixtureFetcher` on the snapshot: the Kalshi H0 orderbook URL, with query parameters in a different order where applicable | The file's JSON; numbers are `Decimal` |
| 7 | `FixtureFetcher` with an unknown URL | `FetchError` |
| 8 | The golden file loads into `list[CanonicalMarket]` | No errors. Every market has YES and NO books; asks rise and bids fall. |
| 9 | Layering guard on a temp file containing `import equinox.adapters` or the word "kalshi" | Fails |

## Done when

`make gate` passes; tests 1–9 pass; `python docs/research/running_example.py` still prints the numbers in architecture §1.

## Out of scope

Any adapter logic, matcher or router code, and CLI changes.
