# feat-13: A clearer app: what's happening, where the data comes from, why each decision

> **Superseded by feat-14 (D86).** The order page, All markets and the data menu are gone.

**Lane:** after feat-12. **Depends on:** the catalog (feat-09), catalog pricing (feat-10, feat-11).
**Implements:** D77 onward.
**Owns only these files:** `src/equinox/web/` (order, search, view, pages, words, app, markets, markets_html), `src/equinox/catalog/store.py` (search), `src/equinox/sources.py` (snapshots offered), `tests/test_web_*.py`, README, architecture §8.3, DECISIONS, AI_USAGE.

## Goal

From the user (2026-10-11): "it should be easy to understand what's happening, where data is coming from, and why certain decisions are made", and "better UX on which markets we want to show and how they are shown". Screens follow the user stories: Jordan wants the cheapest venue for an order and why; Morgan wants to know why two markets are the same bet, how sure, and the risk.

## Build (three commits, each with a browser check)

1. **The order page.** It opens on the most likely outcome both venues list, lists those first and labels the rest "only on Kalshi" (D77). A search box finds any same bet in the catalog by its words, each pair once, priced from where the catalog was read (D78); numbers match whole (D79). The banner says how old a snapshot is, and old-data notes are in plain words (D80).
2. **All markets.** One row per same bet: both venues' prices side by side, what YES pays in plain words, how the match was made, and one button to compare the cost (D81). It opens on the same bets that can be priced, a parser's matches first (D82); markets that only look alike, or have no match, are behind a filter. Each confidence level is explained in a line, and a model's reasons are folded under "How it matched" (D83). A market with no match says what was looked for, not that no other venue lists it (D84).
3. **Data sources.** The test snapshots (pair, scores) leave the data menu; one opened by name is still shown in it (D85). Last, and droppable: a snapshot can build its own catalog, so scores can be seen offline. Dropped: it needs a catalog built from a snapshot's events, a new data path (cut list).

## Acceptance tests (write first, see each fail)

| # | Test | Expected |
|---|---|---|
| 1 | Default outcome | The order page opens on an outcome both venues list; a Kalshi-only outcome is labelled and never the default |
| 2 | Search | "coventry 2-1" finds each 2-1 pair once, linked to its comparison, priced from the catalog's source; no match says so; no catalog says how to build one |
| 3 | Plain data | The banner says a snapshot's age; an old book is described in hours, not seconds and timestamps |
| 4 | All markets | A same bet is one row with both venues' prices, what YES pays and how it was matched |
| 5 | Default view | All markets opens on priceable same bets |
| 6 | Data menu | The test snapshots aren't offered |

## Out of scope

JSON output, new families, and a visual redesign: the same look, with clearer words and structure. No model spend.
