# feat-12: Measure the setup's strength, and a stronger reader

**Lane:** after feat-11. **Depends on:** feat-11 (the score parsers, which label the model's answers for free).
**Implements:** D66–D76.
**Owns only these files:**
- `src/equinox/reader/evals.py`, `checks.py`, `prompt.py`, `check.py`: the scores, the score-order check, the reader's tool, upkeep detection
- `evals/traps.json`, `evals/score_pairs.json` (new), `evals/recorded.json`, `evals/scores.json`
- `docs/research/build_traps.py`, `build_score_pairs.py` (new): how the gold sets were made
- `tests/test_strength.py` (new)
- Docs: README, `EQUIVALENCE.md`, DECISIONS, AI_USAGE

## Goal

feat-11's parser found 7 false same-bets among the model's 456 score same bets, which the gold sets and a 30-pair hand check had missed. The evals should say how strong the setup is: how often the model alone is wrong, how often a wrong reading still gets through the checks, and with what certainty. Then the reader should get better on the measure that matters, not on the six examples we happen to know.

## Build

**Commit 1: measure (the baseline, with prompt feat-10.7).**
1. **Raw and guarded.** Every gold set is scored twice: raw, from every reading that forms valid terms, and guarded, after the checks. Each score gives a one-sided 95% upper bound on its false same-bet rate (Clopper-Pearson), so "0 of 7" reads as "under 35%", not as safe. The gate stays: zero guarded false same-bets on every set.
2. **Traps.** `evals/traps.json`: the 7 reversed-score pairs from the full read, labelled different, with the texts the model read.
3. **A larger score set.** `evals/score_pairs.json`: about 16 groups of the live catalog's score markets, grouped as `catalog read` groups them (up to 20 markets, the conditions the misreads happened in), labelled by the parsers. Split by match into a tuning half and a judging half that share no match; the reader is tuned only on the first.
4. **A score-order check.** A reading of a score must have the goals in the order the venue states them: Kalshi's `home_score` and `away_score`, or Polymarket's "h - a" as written. Otherwise it is rejected and its pair stays unclear.
5. **Upkeep detection.** Each catalog market records the parser family meant to read it (a `family` column, D69). `catalog check --drift --limit N` reads only a family's markets that got no terms and says which look like the family (a venue reworded them) and which don't.

**Commit 2: a stronger reader.** The tool the model fills gets separate score fields (home team, away team, home goals, away goals), a field that works out the order before them, a description on every field, and strict mode if the API accepts it. Measured against the baseline: the traps go to 0 raw false same-bets, the judging half misses fewer than its 7 same bets, and no set gains a raw false same-bet (agreed after the baseline showed 0 raw false same-bets on the judging half). A helper tool only if the raw numbers still fall short.

## Acceptance tests (write first, see each fail)

| # | Test | Expected |
|---|---|---|
| 1 | Raw and guarded | A case where the checks reject a misread shows a raw false same-bet and no guarded one |
| 2 | Bounds | 0 false of 7 gives an upper bound near 35%; 0 of 300 under 1% |
| 3 | Traps | 7 cases, all labelled different, scored as recorded |
| 4 | Score set | Tuning and judging halves share no match; labels come from the parsers' terms |
| 5 | Score-order check | "Lens 1 - 4 Sporting" read as 4-1 is rejected; read as 1-4 is accepted; Kalshi's fields decide its order |
| 6 | Upkeep detection | A family market without terms is listed and read; one the model reads as the family is reported as a likely rewording; nothing is routed |
| 7 | Replay | Every set, recorded live, scores as recorded |

**Live evidence**, on the card: the baseline (raw and guarded, every set), the reader's numbers after commit 2, the upkeep run, the full cross-check, and the catalog re-read. Each paid run is reported before it runs.

## Out of scope

New parsers, the web UI (feat-13), and routing changes.
