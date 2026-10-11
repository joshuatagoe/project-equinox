# feat-09: Read and compare every open market

**Lane:** after feat-08. **Depends on:** feat-08 merged (its adapters, `sources.py`, and the catalog sample in `snapshot-2026-10-11`).
**Implements:** D48, D49 (the catalog tier), D50; architecture §2, §6.3, §8.2, §8.3 and §11; venue facts K12 and P11.
**Owns only these files:**
- `src/equinox/models/catalog.py` (new): `CatalogEntry`, `CatalogSummary`
- `src/equinox/adapters/*`: `list_open()` for each venue
- `src/equinox/matcher/index.py` (new)
- `src/equinox/catalog.py` (new): refresh and cache
- `src/equinox/cli.py`: `catalog refresh`, `catalog status`, `match --catalog`
- `src/equinox/web/markets.py` (new), and the route and nav link in `web/app.py` and `pages.py`
- `tests/test_catalog.py`, `tests/test_index.py`, `tests/test_web_catalog.py` (new)
- Docs: the README, and the "Comparing every open market" section of `docs/EQUIVALENCE.md` with the counts from a real refresh

## Goal

Equinox reads every open market on both venues, compares every cross-venue pair it can, and shows the result honestly:
- **same bet**, where the terms can be read;
- **unclear, never routed**, with the reasons and the title score, where only titles match;
- **only on one venue** for the rest.

A person can search all of it.

## Build

1. **`CatalogEntry`:** market ID, venue, event ID and title, title, outcome label, close and resolve times, tradable, best YES and NO ask, and terms or none. Frozen, with no books and no rules text, so 500,000 entries stay small.
2. **`list_open()`**, yielding entries page by page:
   - **Kalshi:** `GET /events?status=open&with_nested_markets=true&limit=200`, paged with `cursor` until it's empty. This lists no combo markets (K12).
   - **Polymarket:** `GET /events/keyset?closed=false&limit=100`, paged with `after_cursor` until `next_cursor` is absent (P11). Non-Yes/No markets are counted, not listed.
   - Terms are parsed where the family has a parser.
3. **`matcher/index.py`** (pure, no venue names):
   - `informative_words(title)`;
   - `candidates(entries)`, built from an inverted index: cross-venue pairs whose close dates are within 3 days and which share at least two informative words;
   - each candidate decided by `text_match`;
   - counts recorded per refresh: candidates, DISTINCT by each veto, AMBIGUOUS.

   Entries with terms are clustered by terms, as today.
4. **`catalog.py`:**
   - `refresh(settings, progress)` streams both venues, builds the index, and writes `catalog-<UTC timestamp>.jsonl.gz` plus a summary to `EQUINOX_CACHE_DIR` through a temporary file and a rename. A failure leaves the previous catalog in place.
   - `load_latest()` reads the newest catalog, or returns None.
5. **CLI:**
   - `catalog refresh` prints progress per venue and a summary: entries, candidates, unclear, same bet, and time taken;
   - `catalog status` prints the cache's age and counts;
   - `match --catalog` adds the unclear candidates.
6. **Web, the All markets page (`/markets`):**
   - a search box (words in title) and filters (venue; same bet, unclear, only on one venue);
   - paged results, each showing its best asks, status, confidence and, for unclear pairs, the reasons and title score;
   - the catalog's age, and with no catalog, the command that builds one.

## Acceptance tests (catalog sample in `snapshot-2026-10-11`, plus synthetic entries; write first, see each fail)

| # | Test | Expected |
|---|---|---|
| 1 | Kalshi `list_open()` on the sample | Pages with `cursor` until it's empty; no ticker starts with `KXMVE`; entries carry best asks; Fed markets carry terms |
| 2 | Polymarket `list_open()` on the sample | Pages with `after_cursor`; a non-Yes/No market is counted, not listed; offset paging is never requested |
| 3 | `candidates` on hand-made entries | A pair sharing two informative words with close dates 1 day apart is a candidate; the same pair 10 days apart, or sharing one word, is not; same-venue pairs never are |
| 4 | Index outcomes | A number veto gives DISTINCT, a matching pair gives AMBIGUOUS with its score, and nothing is ever EQUIVALENT; the summary counts add up |
| 5 | Scale | 50,000 synthetic entries per venue are indexed and matched in under 60 seconds on the gate machine |
| 6 | `refresh` with a fetcher that fails on page 3 | The previous catalog file is unchanged and the error is reported; no partial file is left |
| 7 | `refresh` then `load_latest` on the sample | The same entries and counts come back |
| 8 | CLI `catalog refresh` and `catalog status` on the sample | Progress and summary lines; status reports age and counts |
| 9 | Web `/markets` | Search finds an entry by a title word; the filters narrow it; an unclear pair shows its reasons and title score; with no catalog, the page shows the refresh command |
| 10 | Layering | `matcher/index.py` passes the layering guard |
| 11 | Docs | `EQUIVALENCE.md` reports the counts from a recorded live refresh; the README has the refresh command, its time and download size, and the memory note; `test_docs.py` passes |

**Live evidence**, recorded on the card: one `catalog refresh` against both venues, with its counts and timing.

## Done when

`make gate` passes; tests 1–11 pass; the live refresh is recorded.

## Out of scope

New term parsers (more families), order books for catalog entries (only families get books, on demand), and background refresh inside the server.
