# feat-07: Web UI for Jordan and Morgan

> **Superseded by feat-14 (D86).** The order page on `/`, `/board`, `/match`, the snapshot default and the 60-second live cache are gone; Morgan's view is now Matches (D94).

**Lane:** after feat-06. **Depends on:** feat-01 to feat-06 merged.
**Implements:** the brief's "produce a decision, and clearly explain why that venue was selected", "log and explain its matching and routing decisions" and "handle imperfect data gracefully and document assumptions", for the two people in `user/users.md`. D45, D46.
**Owns only these files:**
- `src/equinox/server.py`; `src/equinox/index.html` (deleted: the pages replace it)
- `src/equinox/web/*`
- `src/equinox/matcher/confidence.py`, and its export in `matcher/__init__.py`
- `src/equinox/cli.py` (one line: `match` prints each cluster's confidence)
- `tests/test_web.py`, `tests/test_confidence.py`
- Docs: this file; the UI section of `README.md`; the confidence section of `docs/EQUIVALENCE.md`; architecture §3 and §8.3; `docs/DECISIONS.md`; `docs/AI_USAGE.md`; Morgan's needs in `user/users.md`

## Goal

A person opens one local page, describes an order, and gets Equinox's recommendation: which venue, what it costs, how much it saves, and why, in plain words. From the same page they can see every market side by side and the evidence that the venues being compared are the same bet.

## Who it is for

| User (`users.md`) | Their need | Where the UI meets it |
|---|---|---|
| Jordan, the trader | "Tell me which venue gives me the best net price for my order, and explain why." | **Order screen**: the recommendation is the headline, then the reasons and each venue's cost |
| Jordan | Not "monitoring multiple separate apps", calculating fees, or converting cents to USDC | **Market board**: both venues side by side per outcome, in dollars and cents, with the best venue for a standard order |
| Morgan, the auditor | "A clear, explainable audit trail showing *why* the system declared two markets equivalent" | **Match screen**: the venues' rules side by side, differences marked, the verdict and its reasons |
| Morgan | "Explicit confidence and risk warnings for ambiguous markets" | A confidence level with its reason on every match (D46); risk flags in words; pairs set aside, with reasons and, for title-only pairs, the title score |
| AutoTrader, a program | Machine-readable output | Not a UI user: `simulate --json` (D21) |

| Brief | Where the UI meets it |
|---|---|
| Simulate routing and "clearly explain why that venue was selected" | Order screen headline and "Why" section, from the router's own trace |
| "Log and explain its matching … decisions" | Match screen; the verdict line on the order screen links to it |
| "Handle imperfect data gracefully and document assumptions" | A data banner on every page (snapshot or live, capture time, venue failures); thin books, empty books, closed or test-money venues in words; the assumptions A1–A5 |
| "Routing logic should not contain venue-specific assumptions" | The UI only renders the router's and matcher's output and names venues only from each market's `venue` field |
| "Production UI" out of scope; "UI polish does not matter" | Plain server-rendered pages, no framework, no build step; it says it places no orders |

## Screens

Every page shows the data banner and the footer "Equinox simulates orders. It doesn't place them."

### 1. Order (`/`, the home page)

- **Form:** outcome (a list grouped by event, in plain names such as "No change" or "Cut 50 bps or more"), Buy YES or Buy NO, number of contracts, optional maximum budget, and data source (snapshot or live). The defaults are No change, Buy YES, 100 contracts, snapshot.
- **Headline**, one sentence per status:
  - Routed: "Buy on Polymarket: $84.67 for 100 YES contracts, including $0.67 in fees. That's $1.23 (1.43%) less than Kalshi at $85.90." With one eligible venue: "… Polymarket is the only venue that can take this order."
  - Over budget: "No venue can fill 100 YES contracts within $80.00. The cheapest full fill is Polymarket at $84.67."
  - Not enough liquidity: "No venue has 5,000,000 YES contracts for sale. The most on offer is …"
  - No eligible venue: the router's sentence.
  - Bad input or an unknown outcome: a message next to the form, and no result.
- **Why:** the router's rationale, word for word.
- **Cost on each venue:** venue; can it take the order; the contracts it would buy at each price ("534.49 at 16¢, 4,465.51 at 17¢"); average price; fee; total; and, if it can't, why, in words.
- **Same bet?** The match verdict and confidence for this outcome, with a link to the match screen.
- **Things to know:** the risk flags, the data warnings and, folded away, the assumptions.

### 2. Market board (`/board`)

- One table per event, such as "Fed rate decision, October 28, 2026", with one row per outcome.
- Each row: the outcome in plain words; each venue's price to buy YES and to buy NO, in cents ("–" if nobody is selling); the verdict and confidence; the best venue for 100 YES and for 100 NO with its total; a link "Price my order" that opens the order screen with this outcome.
- A market no other venue matches is listed as "Only on {venue}". Markets without contract terms are listed under "Can't be compared yet", with their titles.

### 3. Why these match (`/match`)

- Pick an outcome. One column per venue, one row per rule:
  - the venue's question;
  - "Pays YES if", in words;
  - measured by;
  - observed on, with the time when the venue states one;
  - settlement source, with a link;
  - trading closes;
  - expected to resolve;
  - edge-case rules.
- Rows where the venues differ are marked.
- The verdict ("Same bet", "Unclear" or "Different"), the confidence level with its reason, and each risk flag in words.
- **Considered and set aside:** every AMBIGUOUS pair, with its reasons, and the title score for title-only pairs.

## Confidence (D46)

`matcher/confidence.py` gives every match result a level and a one-line reason. The level is derived from the verdict and its flags; it never changes a verdict:

| Level | When |
|---|---|
| High | EQUIVALENT, and nothing differs but the venues' edge-case rules (or nothing at all) |
| Medium | EQUIVALENT, but the payout can still differ in one stated case: equal only on the measure's grid, a different tie rule, or different resolution sources |
| Low | AMBIGUOUS: never routed. A title-only pair also shows its title score. |
| (none) | DISTINCT: not the same bet |

## Build

- `server.py` renders the three pages with the same functions the CLI uses: `load_markets`, `build_clusters`, `simulate`, `evaluate_pair`, `text_matches`. No JSON API: D21 stands.
- `web/` holds the page code. The plain-language names (event titles, outcome names, "Pays YES if") are written from the contract terms, keyed by measure, never by venue. Every string that came from a venue is HTML-escaped.
- Snapshot data is loaded once. Live data is cached for 60 seconds per server, and the banner gives its age. A venue whose live request fails falls back to the snapshot, as in the CLI (D17).
- `python -m equinox.server` and `make run` serve it at http://127.0.0.1:8741. `/health` stays.

## Acceptance tests (write first, see each fail)

The tests use snapshot data through the real HTTP server on a free local port, as `tests/test_equinox.py` does.

| # | Test | Expected |
|---|---|---|
| 1 | `GET /` | 200; all five Fed outcomes in plain words; the default order's headline names Polymarket, $84.67, $0.67, $1.23, 1.43%, Kalshi and $85.90 |
| 2 | No change, Buy NO, 100 | Headline: Kalshi, $16.95; Polymarket $17.71 in the table |
| 3 | No change, Buy NO, 5000 | Headline: Polymarket, $885.28; Kalshi's row shows 534.49 at 16¢ and 4,465.51 at 17¢ |
| 4 | No change, Buy YES, 100, budget 80 | The over-budget headline with $80.00 and Polymarket at $84.67 |
| 5 | No change, Buy YES, 5,000,000 | The not-enough-contracts headline |
| 6 | Cut 25 bps, Buy NO, 100 | Headline: Polymarket, $99.62; Kalshi's row says nobody is selling NO |
| 7 | Quantity 0, quantity "abc", side "MAYBE", an unknown outcome | 200 with an input message next to the form; no result; no traceback |
| 8 | `GET /board` | Five rows in order: Cut 50 bps or more, Cut 25 bps, No change, Hike 25 bps, Hike 50 bps or more. No change: YES 85¢ on Kalshi and 84¢ on Polymarket; best for 100 YES Polymarket, for 100 NO Kalshi; the snapshot banner. |
| 9 | `GET /match` for No change, then for Cut 50 bps or more | Both questions, "Same bet", High, both venues' edge-case rules; then Medium with the 25 bps grid reason; differing rows marked |
| 10 | Confidence on the golden pairs | E1 High; E3 and E4 Medium (grid); E7 Medium (tie rule); E10 and E13 Low, E13 with its title score; E5 none |
| 11 | Live data with an injected fetcher that fails for one venue | The banner says that venue's live data failed and its snapshot is used |
| 12 | Every architecture §7.4 order through the page and through `cli.main --json` | The same totals, to the cent |
| 13 | A market whose title holds `<script>` | Rendered escaped |
| 14 | `/health`, an unknown path | Unchanged: JSON ok; 404 |
| 15 | The source of `web/` | Names no venue |

**Browser check**, recorded as evidence: open http://127.0.0.1:8741, run the default order and 5,000 NO, open the board and the match screen.

## Done when

`make gate` passes; tests 1–15 pass; the browser check is recorded; the user has used the page.

## Out of scope

Placing orders, accounts, a JavaScript framework, a JSON API (D21), Meridian or any fit-check market in the UI (D26), and visual polish beyond readable.
