# feat-08: Find every Fed meeting, price on demand, and say what bps means

**Lane:** after chore-01. **Depends on:** chore-01 merged.
**Implements:** D47, D49 (books on demand), D51; architecture §2, §5.1, §8.2, §8.3 and §11; venue facts K12, K13, P11, P12.
**Owns only these files:**
- `src/equinox/models/canonical.py`: `books` optional, `best_asks` added
- `src/equinox/adapters/base.py`, `kalshi.py`, `polymarket.py`: `discover`, `list_markets`, `fetch_books`. An adapter that would pass 300 lines becomes a package, such as `adapters/kalshi/`.
- `src/equinox/router/engine.py`: refuses a market without books
- `src/equinox/sources.py`, `src/equinox/cli.py`: `--snapshot`, discovery with its pinned fallback, books on demand
- `src/equinox/web/*`: one board table per meeting, the data selector, the bps wording
- `src/equinox/fixtures/snapshot-2026-10-11/**` (new capture) and `docs/research/capture_snapshot.py`
- `tests/test_discovery.py`, `tests/test_web_discovery.py` (new)
- Docs: README, `docs/EQUIVALENCE.md`, `docs/ROUTING.md`, `docs/AI_USAGE.md`, `user/users.md` where they describe these

## Goal

Equinox finds every Fed-decision meeting that Kalshi and Polymarket list and matches them itself, with no hand-picked event. It reads order books only for the markets being priced. And it explains basis points in plain words.

## Build

1. **Model.** `CanonicalMarket.books` becomes `dict[Outcome, OutcomeBook] | None`. When books are present they must still hold both YES and NO. A new `best_asks: dict[Outcome, Exact | None]` holds the best price to buy each outcome, taken from the listing.
2. **Discovery** (`discover(family)`):
   - **Kalshi:** `GET /events?series_ticker=KXFEDDECISION&status=open` (K13).
   - **Polymarket:** `GET /events/keyset?closed=false&tag_slug=fed-rates&limit=100`, paged with `after_cursor` (P11). It keeps only events that are open, neg-risk and titled "Fed Decision in <Month>?", because closed 2025 events and other Fed events share the tag (P12).
   - Either one raises `FetchError` when the request fails.
3. **Listing without books** (`list_markets()`): the same markets as today, with `best_asks` from the listing fields (Kalshi `yes_ask_dollars` and `no_ask_dollars`; Polymarket `bestAsk`, and 1 − `bestBid` for NO) and `books=None`. Polymarket keeps each market's two token IDs in `venue_metadata`, so `fetch_books` can find them.
4. **Books on demand** (`fetch_books(market)`): the same market, with both books, from today's book requests. `fetch_markets()` becomes `list_markets()` followed by `fetch_books()` for each market, so every existing adapter test is unchanged.
5. **Sources:**
   - discover per venue, falling back to `tracked_events.json` with a warning when discovery fails. A failed discovery request doesn't send the venue to the snapshot; only a failed event or book request does (D17).
   - `--snapshot NAME` and `EQUINOX_SNAPSHOT`, defaulting to `snapshot-2026-10-10` (D51);
   - `with_books(cluster)` fetches the books for one cluster's markets.
6. **Router:** `simulate` raises `ValueError` naming any cluster market without books.
7. **Snapshot:** `capture_snapshot.py` also records the discovery requests, every discovered event on both venues, every book for those events, and two short catalog pages per venue (`limit=20`) for feat-09's tests. It writes to `src/equinox/fixtures/snapshot-2026-10-11/`. The 2026-10-10 snapshot is not touched.
8. **Web UI:**
   - the data selector lists every snapshot and live data;
   - the board shows one table per discovered meeting;
   - board books are fetched only for groups listed on more than one venue, and a one-venue group shows its listing prices and "Only on Kalshi";
   - the order screen fetches books for the one group being priced.
9. **Plain bps:**
   - outcome names gain the size in percentage points, e.g. "Cut 25 bps (0.25 percentage points)" and "Cut 50 bps or more (0.50 percentage points or more)";
   - every page that shows bps carries the note "bps means basis points: 1 bp is 0.01 percentage point, so 25 bps is a quarter of a point";
   - the existing names stay as written, so the frozen UI tests still find them.

## Acceptance tests (on `snapshot-2026-10-11` unless stated; write first, see each fail)

| # | Test | Expected |
|---|---|---|
| 1 | Kalshi `discover("fed_decision")` | Every open KXFEDDECISION event in the snapshot, in date order; a family it doesn't know gives an empty list and a warning |
| 2 | Polymarket `discover("fed_decision")` | Only the open, neg-risk "Fed Decision in …?" events; a closed 2025 event and a non-decision `fed-rates` event in the same response are rejected |
| 3 | Polymarket discovery paging | The second page is requested with `after_cursor`, and paging stops when `next_cursor` is absent |
| 4 | `list_markets()` with a fetcher that records URLs | No book URL is requested; `best_asks` equal each book's first ask for every market |
| 5 | Pricing one outcome through `sources` | Requests the books of that group only |
| 6 | Clusters on the snapshot | Every meeting listed on both venues forms cross-venue clusters; a Kalshi-only meeting forms one-market clusters |
| 7 | The 2026-10-10 snapshot | Discovery falls back to the pinned October event with a warning that names the snapshot; every existing test passes unchanged |
| 8 | Live mode where discovery fails but the event and books load | Pinned events are used; quotes have no FIXTURE_DATA |
| 9 | `simulate` with a market that has no books | `ValueError` naming it |
| 10 | CLI: `markets --snapshot snapshot-2026-10-11 --source fixtures`, and `simulate` on a December market | All discovered markets are listed; the December order is ROUTED, with totals equal to a hand calculation from the fixture books |
| 11 | Web: the board on `snapshot-2026-10-11` | One table per discovered meeting; the selector offers both snapshots and live |
| 12 | Web: bps wording | Outcome names show percentage points; the basis-point note is on the order, board and match pages |
| 13 | Docs: `tests/test_docs.py` | New README demo rows for a December order on `snapshot-2026-10-11` run and match; every reference exists |

**Browser check**, recorded: the board with several meetings, a December order, and the bps note.

## Done when

`make gate` passes; tests 1–13 pass; the browser check is recorded. The README, `EQUIVALENCE.md` ("how Equinox finds markets") and `ROUTING.md` ("books on demand") describe the new behaviour.

## Out of scope

The full catalog (feat-09), families other than Fed decisions, and order-book batch endpoints.
