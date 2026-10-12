# feat-10: Read terms with a model, decide with rules

**Lane:** after feat-09. **Depends on:** feat-09 merged (the catalog and its unclear pairs).
**Implements:** D56–D58; architecture §6.5 and §8.2. The brief allows matching that is "rule-based, heuristic, AI-assisted, or hybrid"; this is the hybrid.
**Owns only these files:**
- `src/equinox/reader/` (new): the prompt, the model client, the checks, the reading cache, the groups, the evals
- `src/equinox/models/canonical.py`: `ContractTerms.unit` gains `percent`, `count` and `indicator` (D56)
- `src/equinox/models/catalog.py`, `adapters/kalshi.py`, `adapters/polymarket.py`: each listed market's rules text and strike fields
- `src/equinox/catalog/`: the texts table, and applying readings to pairs
- `src/equinox/matcher/terms.py`: the pair rules, callable on two sets of terms
- `src/equinox/cli.py`, `cli_catalog.py`: `catalog read`
- `src/equinox/web/markets.py`, `markets_html.py`: the "read by a model" status
- `tests/test_reader.py`, `tests/test_reader_evals.py` (new), `evals/` (new)
- Docs: README, `EQUIVALENCE.md`, architecture, DECISIONS, AI_USAGE

## Goal

Catalog pairs that only titles could match are read by a model into contract terms (D22), checked by deterministic code, and decided by the same rules as the Fed parser's terms. Equivalence is then inferred beyond Fed without writing a parser per family. The model never decides equivalence; it only fills the terms.

## Build

1. **Texts.** Each listing page also yields each market's rules text and, on Kalshi, its strike fields. A refresh writes them to disk as pages arrive and keeps them in the catalog only for markets in unclear pairs, so memory doesn't grow.
2. **Groups.** The markets of one event's unclear pairs are read together with all their candidate partners, at most 20 markets per call. They share one vocabulary, so equal things get equal names.
3. **Reading.** One Messages API call per group (`claude-haiku-5-5` by default), forced through a tool whose input is one terms record per market: subject, measure, measured_by, observed_on, comparison, threshold, upper, unit, and the evidence phrase. A yes/no outcome is an indicator: comparison `eq`, threshold 1, the outcome named in the measure.
4. **Checks.** A reading is rejected when:
   - its evidence phrase is not in the market's own text;
   - its threshold (or upper bound) is not a number in that text, except an indicator's 1;
   - its comparison disagrees with the evidence's words ("above" is `gt`, "at least" and "+" are `ge`, none of them is `eq`);
   - its date doesn't parse or falls after the market closes plus 7 days;
   - Kalshi's strike fields disagree with it.
   A rejected market keeps its pair unclear, with the reason.
5. **Decision.** Two accepted readings from the same call go through the terms rules. EQUIVALENT makes the pair the same bet, marked "read by a model". DISTINCT makes it a different bet. AMBIGUOUS leaves it unclear.
6. **Cache.** Each call is saved by a hash of its request (prompt version, model and texts), so a re-run pays only for groups whose text changed. A venue that rewords a market is read again automatically.
7. **Command.** `catalog read [--limit N]` reads at most N markets, most similar pairs first, and prints the tokens used. With no key it exits 1 and reads nothing. The key comes from `ANTHROPIC_API_KEY` or from `.env` at the repo root (gitignored).
8. **Evals.** `python -m equinox.reader.evals` reads two gold sets live and scores them; tests replay the recorded answers offline.
   - **Fed:** every pair of the three meetings both venues list in `snapshot-2026-10-11`, decided by the parser's terms.
   - **Labelled pairs:** catalog pairs labelled by hand, including traps.
   It reports false same-bets, missed same-bets and rejected readings.

Routing model-read pairs is commit 2 of this feature (`reader/pricing.py`, `web/catalog_order.py`, `sources.load_by_id`, each adapter's `event_of`, D59): the trace flags "terms read by a model", confidence is Medium at most, and it routes only when the committed evals show zero false same-bets for the model and prompt that read the pair. Its tests replay `snapshot-2026-10-11-pair`, recorded raw by `docs/research/capture_pair.py`.

## Acceptance tests (write first, see each fail)

| # | Test | Expected |
|---|---|---|
| 1 | Listing texts | Kalshi and Polymarket pages carry each market's rules text; a Kalshi market with strike fields carries them |
| 2 | Refresh keeps texts on disk | The catalog holds texts only for markets in unclear pairs; no temporary file is left |
| 3 | Terms rules on terms alone | Same outcome is EQUIVALENT; "above" vs "exactly" is DISTINCT; "above" vs "at least" is EQUIVALENT with a tie flag; a different measuring source is AMBIGUOUS |
| 4 | Checks | A reading with its threshold or evidence missing from the text, a comparison against its words, or a strike disagreement is rejected with the reason |
| 5 | Reading a group (recorded client) | Accepted readings decide their pairs; a rejected one leaves its pair unclear; tokens are counted |
| 6 | Cache | The same request is never sent twice |
| 7 | CLI | `catalog read --limit` reads at most that many markets and prints tokens; without a key, exit 1 and nothing is read |
| 8 | Evals replay | On the recorded answers, zero false same-bets on both gold sets, and the report's counts |
| 9 | Web | A model-read same bet says so on the All markets page |

**Live evidence**, recorded on the card: the eval scores, and a 100-market `catalog read` sample with its tokens. A full run happens only with the user's OK.

## Out of scope

Reading markets that are not in a candidate pair, letting the model decide equivalence, replacing the Fed parser, and reading in the background.
