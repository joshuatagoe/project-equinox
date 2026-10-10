# feat-03: Equivalence matcher

**Lane:** parallel, after feat-01. **Depends on:** feat-01 (models and the golden file). It does not depend on the adapters.
**Implements:** architecture §6; D8, D15, D18, D20, D22, D23.
**Owns only:** `src/equinox/matcher/*`, `tests/test_matcher.py`.

## Goal

Decide which markets on different venues pay out under exactly the same conditions, explain each decision, and attach the risks that remain. Decisions come from contract terms. Title similarity is a fallback that can never reach EQUIVALENT.

## Build

- `matcher/terms.py`:
  - `evaluate_pair(a, b) -> MatchResult` applies the rules in §6.1, in order.
  - Measure grids: `{"fed_upper_bound_change": Decimal(25)}`. Normalize on the grid: `lt t` becomes `le t−grid`, and `gt t` becomes `ge t+grid`.
  - Direction groups: above = {gt, ge}, below = {lt, le}; `eq` and `between` are their own groups.
- **Risk flags** (exact leading phrases, so tests and the router can rely on them):
  - `"Tie rule differs: "`, then the threshold and which venue pays what at exactly that value.
  - `"Equal only on the 25 bps grid: "`
  - `"Edge-case rules differ: "`, then each venue's `fallback_rules`.
  - `"Resolution sources differ: "` (D18: compare institutions, not URLs).
- `matcher/clusters.py`:
  - `build_clusters(markets) -> list[EquivalenceCluster]` groups markets by the normalized key in §6.2. A market with terms that has no partner is still a one-market cluster. `ambiguous` holds the AMBIGUOUS pairs that involve a member.
  - `cluster_for(market_id, clusters)` returns that market's cluster, or None.
  - `cluster_id` is the normalized key rendered as text, for example `FOMC|fed_upper_bound_change|fomc_statement|2026-10-28|eq|0|bps`.
- `matcher/text.py`: the fallback in §6.3. Its output is MatchResults with `method="text"`, and never EQUIVALENT.
- No venue names anywhere; `test_layering.py` enforces it. Venue names may appear in result text only by reading `market.venue`.

## Acceptance tests (golden canonical markets; write first, see each fail)

| # | Test | Expected |
|---|---|---|
| 1–13 | Pairs E1–E13 in architecture §6.4. E7–E10 use the fit-check markets (§9.3). | Exactly the status in the table. For EQUIVALENT pairs, each flag listed in the table, identified by its leading phrase. |
| 14 | `build_clusters(golden)` | A cluster `…|eq|0|bps` holding Kalshi H0 and Polymarket 2589812. AAPL `…|above|330|usd` holds Polymarket 5455686 and Meridian AAPL-330, and lists the `official_close` variant (E10) in `ambiguous`, not in `markets`. Meridian AAPL-320 is a cluster of one. |
| 15 | Invariant: for every cluster, every pair of members | `evaluate_pair` returns EQUIVALENT |
| 16 | Order independence: `build_clusters` on the golden list reversed | The same clusters (compare by `cluster_id` and member IDs) |
| 17 | The six term-less golden markets | They appear in no cluster's `markets`; text results as in E11–E13 |

## Done when

`make gate` passes, including the layering guard.

## Out of scope

AI-assisted matching, routing, and any adapter code.
