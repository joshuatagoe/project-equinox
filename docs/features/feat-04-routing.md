# feat-04: Routing simulator

**Lane:** parallel, after feat-01. **Depends on:** feat-01 (models and the golden file). It does not depend on the matcher: tests build `EquivalenceCluster` objects directly from golden markets.
**Implements:** architecture §7 and §8.1; D5, D6, D7, D13, D16, D17, D24, D25, D27, D30, A5.
**Owns only:** `src/equinox/router/*`, `tests/test_router.py`.

## Goal

For one order and one cluster, simulate the order on every market. Walk the book level by level, add that venue's fees, and record why each venue is or isn't eligible. Then pick the cheapest eligible venue and write a trace whose status and rationale explain the result without naming any venue in code.

## Build

- `router/depth.py`: `walk(book: OutcomeBook, quantity) -> tuple[list[Fill], Decimal]`, which returns the fills and the filled quantity (§7.1 step 1).
- `router/engine.py`:
  - `quote(market, order, now, stale_after) -> VenueQuote`, covering §7.1 steps 2–4. All reasons are collected, and every market is simulated even when it is excluded.
  - `simulate(order, cluster, now, stale_after=300 s, trace_id=None) -> EquinoxTrace`: the decision, status and tie-break from §7.2, plus savings.
  - `failure_trace(status, message, order=None, now=…) -> EquinoxTrace`, for the CLI's MARKET_NOT_FOUND and INVALID_INPUT.
- `router/rationale.py`: the sentences in §7.2. It reads venue display names from `market.venue` (capitalized), and copies the cluster's risk flags. Assumptions A1, A2, A3 and A5 go into `trace.assumptions` in plain words.
- No venue names in the code. The layering guard enforces it.

## Acceptance tests (golden markets; injected `now = 2026-10-10T20:50:00Z`)

| # | Order on the cluster | Expected |
|---|---|---|
| 1 | Kalshi H0 + Polymarket 2589812, 100 YES | ROUTED to Polymarket. Totals 84.672 vs 85.90. Fees 0.672 and 0.90. Savings 1.228 (1.43%). |
| 2 | Same cluster, 100 NO | ROUTED to Kalshi. 16.95 vs 17.7055. |
| 3 | Same cluster, 5000 NO | ROUTED to Polymarket. 885.275 vs 893.7951. The Kalshi quote has fills [(0.16, 534.49), (0.17, 4465.51)], average 0.1689 (rounded to 4 dp), slippage 0.0089. |
| 4 | Same cluster, 100 YES, budget 80 | BUDGET_EXCEEDED. Both quotes OVER_BUDGET. |
| 5 | Same cluster, 5000000 YES. The golden books hold only 3 levels, so build the cluster with `depth_complete=False` on both books. | INSUFFICIENT_LIQUIDITY. Both PARTIAL_FILL, each with a DEPTH_INCOMPLETE warning. |
| 6 | Kalshi C25 + Polymarket 2589811, 100 NO | ROUTED to Polymarket at 99.61992. The Kalshi quote has EMPTY_BOOK. |
| 7 | Fit-check markets (§9.3): Polymarket 5455686 + Meridian-style AAPL-330, 5 YES | ROUTED to Polymarket at 4.80768. The Meridian quote is TEST_MONEY with total 4.75, and the rationale includes "would cost $4.75". |
| 8 | Same AAPL cluster, 10 YES | ROUTED to Polymarket at 9.61536. Meridian has TEST_MONEY and PARTIAL_FILL (5 of 10). |
| 9 | Meridian-style AAPL-320 alone, 5 YES | NO_ELIGIBLE_VENUE |
| 10 | H0 with `tradable=False` + 2589812, 100 YES | ROUTED to Polymarket. Kalshi NOT_TRADABLE. |
| 11 | Two eligible quotes with equal totals | The lower fee wins; if fees are equal too, the lower `market_id` |
| 12 | `captured_at` 10 minutes before `now`; `data_source="fixture"` | STALE_DATA and FIXTURE_DATA warnings, and the venue is still eligible |
| 13 | Rationale for test 1 | Contains "Polymarket is the cheapest venue that can fill all 100 YES contracts", "$84.67", "$85.90", "1.43%", and an "Edge-case rules differ" sentence |

## Done when

`make gate` passes, including the layering guard.

## Out of scope

Split orders, selling, maker orders, rebates (A5), and output formatting (feat-05).
