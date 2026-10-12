# feat-14: Equinox as an app

**Lane:** after feat-13. **Depends on:** the catalog (feat-09), catalog pricing (feat-10, feat-11, D78).
**Implements:** D86 onward.
**Owns only these files:** `src/equinox/web/`, `src/equinox/catalog/` (topics, events, background refresh, carried decisions), `models/catalog.py`, the Kalshi adapter's catalog listing, `server.py`, `tests/test_web*.py`, README, architecture §8.3, DECISIONS, AI_USAGE.

## Goal

From the user (2026-10-12): "why does clicking price and order only show fed rate? the ux needs a massive overhaul still, we need to define what we want the userflow to look like. it should look like an actual application than rudimentary test software, for example, why is there a dropdown with snapshots, what purpose does it solve?"

The flow, agreed the same day from `user/users.md`: Markets (search, topics, events both venues list) → an event (each outcome's prices on both venues) → the order ticket (answer first, cost on each venue, why) with "Is this really the same bet?" beside it → match review for Morgan.

## Build (three commits, each with a browser check at desktop and phone width)

1. **Markets, an event and the order ticket, from the catalog** (D86-D89). Topics from each event's category; the old pages and the data selector leave the web app.
2. **Fresh data without a command** (D90, D91). The server refreshes the catalog hourly in the background, with a Refresh button; a first-run page while it builds; the venues can't be reached, said plainly. A refresh, from the server or the command line, keeps a model's decision when both markets' rule texts are unchanged. The server never calls the model. Also here, from the user's first look at the ticket: it says what comparing does, what the budget is for and what the contracts pay (D92).
3. **Match review for Morgan** (D94). Every pair Equinox kept, by how it was decided, each same bet opening its ticket's panel.

## Acceptance (grill, 2026-10-12: all recommended)

| # | Check | Expected |
|---|---|---|
| 1 | Markets | One card per event both venues list, with both venues' prices; topics filter; a search finds a bet by either venue's words |
| 2 | Negative | A pair whose titles only look alike never appears; a search with no match says so |
| 3 | Event | Every outcome, likeliest first, with YES and NO on each venue and Buy buttons |
| 4 | Ticket | Answer, then cost on each venue, then whether it's the same bet; it agrees with `simulate --json` |
| 5 | Failures | Venues unreachable: said, not priced; a refused model pair says why; bad input is explained |
| 6 | Old pages | No data selector; `/board`, `/match`, `/markets` are gone from the web |

The user agreed to retire the tests that pinned the old pages (Q1), replaced by `tests/test_web_app.py`; every non-web test stays frozen.

## Out of scope

Placing orders, accounts, a JavaScript framework or build step, model spend from the server, and running offline.
