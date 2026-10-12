# feat-11: An exact-score parser, and the model as its cross-check

**Lane:** after docs-01. **Depends on:** feat-10 (the reader, the evals and catalog pricing).
**Implements:** D60's first graduation; D61–D65. The gold traps and the reader work it led to are feat-12.
**Owns only these files:**
- `src/equinox/adapters/teams.py`, `team_aliases.json` (new): one key per team name
- `src/equinox/adapters/kalshi_terms.py`, `kalshi.py`, `polymarket_terms.py`, `polymarket.py`: the score parsers, in catalog entries and in listings
- `src/equinox/matcher/compare.py`, `models/catalog.py`, `catalog/texts.py`: parser pairs that look alike by title
- `src/equinox/reader/pricing.py`, `reader/check.py` (new), `reader/evals.py`, `cli.py`, `cli_catalog.py`: pricing parser pairs, `catalog check`, the score gold set
- `src/equinox/web/app.py`, `web/markets.py`, `web/view.py`: one link per same bet
- `tests/test_scores.py` (new), `src/equinox/fixtures/snapshot-2026-10-11-scores/` (new), `evals/`
- `docs/research/capture_scores.py` (new), `capture_pair.py`: the raw capture
- Docs: README, `EQUIVALENCE.md`, architecture, DECISIONS, AI_USAGE

## Goal

Exact scores were about 58% of the model's same bets in the full read (D60). Kalshi publishes each score as fields and Polymarket writes every one the same way, so a parser can read them exactly, for free and offline. The model then reads the parser's pairs as a cross-check and reports where the two disagree.

## Build

1. **Terms** (D61). One shape for both venues: subject `"<home> vs <away>"` as team keys, measure `full_time_score_<home goals>_<away goals>` or `first_half_score_…`, measured by `official_match_score`, observed on the date the match was "originally scheduled for", comparison `eq`, threshold 1, unit `indicator`.
   - **Kalshi.** The event title is `"<home> vs <away>: Correct Score"` or `": 1st Half Correct Score"`; the goals are `custom_strike.home_score` and `away_score`. The rules must name the match in that order, state the period ("after 90 minutes plus stoppage time (does not include extra time or penalties)", or "at the end of the 1st Half") and state the same score.
   - **Polymarket.** `sportsMarketType` is `soccer_exact_score` or `soccer_first_half_exact_score`; the event's `teams` say which is home and away; the question must read `"Exact Score: <home> <h> - <a> <away>?"` (or `"1st Half Exact Score: …"`); the description must state the period (90 minutes of regulation plus stoppage time, or the first 45 minutes plus first-half stoppage time). Its postponement and no-data rules become fallback rules. "Any Other Score" has no terms: the venues list different scores.
2. **Team keys** (D62). Accents, case and punctuation are dropped, and so are club words and Brazilian state codes ("FC", "SC", "Club", "de", "RJ", "SP"…); "St." reads "Saint". Then `team_aliases.json` maps the names that still differ, seeded from the model's same bets ("PSV Eindhoven" is "PSV"). A wrong merge needs both teams and the date to collide; a missing alias only misses a pair, which the cross-check reports.
3. **Source** (D63). A Polymarket market with no `resolutionSource` takes its event's (score markets have none; their events name the league's site).
4. **Catalog** (D64). Parser same bets are found by terms, as for Fed. Parser pairs whose terms differ but whose titles look alike are kept as "different", with both markets' texts, so the cross-check can read them. Market statuses don't change.
5. **Pricing** (D65). A parser same bet in the catalog is priced like a model-read one (`simulate --market`, or the All markets page), without the eval gate or the model flag, so it can reach High confidence. The All markets page links every same bet by its market; a market in a loaded family (Fed) opens its usual outcome.
6. **Cross-check.** `catalog check --limit N` reads the parser's pairs with the model, decides them with the same rules, and lists every pair where the parser and the model disagree. It changes no status and reports the tokens spent.
7. **Gold labels.** A fourth eval set, `scores`, labelled by the parsers' terms on `snapshot-2026-10-11-scores` (D60). Like every set, it must show zero false same-bets for model-read pairs to be routed.

## Acceptance tests (write first, see each fail)

| # | Test | Expected |
|---|---|---|
| 1 | Kalshi terms | A home win, an away win and a draw read as the right `full_time_score`; a 1st-half market reads `first_half_score`; a rules text with another score or period gives no terms |
| 2 | Polymarket terms | The same scores read the same keys; "Any Other Score" and a question with other team names give no terms |
| 3 | Team keys | "Coventry City" = "Coventry City FC"; "Atlético" = "Atletico"; "PSV Eindhoven" = "PSV" through the alias table; two different clubs stay different |
| 4 | Pairs | 2-1 on Kalshi is the same bet as 2-1 on Polymarket; 2-1 against 1-2, and full time against half time, are different; an unknown team name gives no same bet |
| 5 | Source | A score market takes its event's resolution source; a Fed market with none is still skipped |
| 6 | Catalog | A refresh over the score listings finds the parser's same bets, keeps title-alike different pairs as "different", and keeps their texts |
| 7 | Pricing | `simulate --market` prices a parser same bet from the catalog with no "read by a model" flag; the All markets page links it by market |
| 8 | Cross-check | On a recorded answer, agreements are counted and each disagreement is listed; nothing in the catalog changes |
| 9 | Gold set | The recorded `scores` answers score as recorded, with zero false same-bets |

**Live evidence**, recorded on the card and in EQUIVALENCE.md: one live refresh (2026-10-12, 718 score same bets), the parser's same bets compared with the model's 456 (7 model false same-bets found, 0 parser errors in a 30-pair sample), two score pairs priced live, and the cross-check's cost (about $0.47 for every pair; not run, by the user's choice).

## Out of scope

Other score-like families ("First Team to Score", totals, corners), "Any Other Score", reading team IDs, and replacing the model's reads of other families.
