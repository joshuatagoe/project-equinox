# Equivalence: when two markets are the same bet

The brief asks what "equivalent" means and why. This is Equinox's answer, how the matcher applies it, and where it stops. The design is architecture §6; the decisions are D8, D15, D18, D20, D22, D23, D42, D50, D54, D56–D58 and D60–D65.

## How Equinox finds the markets to compare

Equinox doesn't start from a list of pairs. For each event family it can read (today, Fed rate decisions) it asks each venue for every open event of that family, then matches whatever it finds (D47):

- **Kalshi** lists every meeting in the `KXFEDDECISION` series (venue fact K13).
- **Polymarket** tags its Fed events `fed-rates`. The tag also covers about 34 other Fed and Treasury events, and closed 2025 events with near-identical titles still exist, so only open, neg-risk events titled "Fed Decision in …?" are kept (P12).

On the 2026-10-11 snapshot that finds 11 meetings on Kalshi and 3 on Polymarket. The matcher then pairs the three meetings both venues list (October, December and January), outcome by outcome: 15 groups of two. The other 40 Kalshi markets are groups of one: Equinox can still price them on Kalshi, but there is nothing to compare them with. If discovery can't run, for example on the 2026-10-10 snapshot, which was captured before discovery existed, the pinned events in `tracked_events.json` are used and the output says so.

## The definition

> Two markets are equivalent if and only if holding YES on one pays out under exactly the same real-world conditions as holding YES on the other. (D8)

The definition is strict on purpose. Routing treats equivalent markets as interchangeable: it sends the order to whichever is cheaper. If two markets can pay differently, a cheaper price on one isn't a saving, it's a different bet. Two cases show why "close enough" isn't good enough:

- "Will the Fed cut by 25 bps?" and "Will the Fed cut by 50 bps?" look alike, but they pay on different outcomes. Holding one when the other happens loses the whole stake.
- "AAPL closes above $330" and "AAPL closes at or above $330" agree on every day except one where AAPL closes at exactly $330.00. There they pay opposite ways.

The first pair must never be matched. The second can be, but only with that difference stated wherever the match is used.

## Contract terms, not titles

Equinox decides equivalence from **contract terms**: a venue-neutral description of what a market pays on (D15, D22). The adapters, the only venue-aware code, read them from each venue's structured fields. On Kalshi that is `custom_strike`; on Polymarket it is `groupItemTitle` plus the meeting date in the description (K8, P6).

| Field | Meaning | Example |
|---|---|---|
| subject | What the market is about | `FOMC`, `AAPL` |
| measure | The number that decides it | `fed_upper_bound_change` (bps), `close_price` (USD) |
| measured_by | Who or what produces that number | `fomc_statement`, `pyth_regular_close`, `official_close` |
| observed_on / observed_at | The New York date, and the exact instant when the venue states one | `2026-10-28`; `2026-10-12T20:00:00Z` |
| comparison and threshold | `gt`, `ge`, `lt`, `le`, `eq` or `between`, against a number | `eq 0`, `gt 330` |
| fallback_rules | The venue's edge-case rules, in plain words | "If the meeting is cancelled, 'Fed maintains rate' resolves Yes." |

How the October 2026 Fed markets map onto terms (architecture §4.4):

| Kalshi | Terms | Polymarket | Terms |
|---|---|---|---|
| Cut >25bps (`C26`) | change `lt` −25 bps | 50+ bps decrease | change `le` −50 bps |
| Cut 25bps (`C25`) | `eq` −25 | 25 bps decrease | `eq` −25 |
| Fed maintains rate (`H0`) | `eq` 0 | No change | `eq` 0 |
| Hike 25bps (`H25`) | `eq` 25 | 25 bps increase | `eq` 25 |
| Hike >25bps (`H26`) | `gt` 25 | 50+ bps increase | `ge` 50 |

Every market is observed on 2026-10-28, measured by the FOMC statement.

## The rules

The matcher compares two markets' terms field by field, in this order. The first rule that applies decides (architecture §6.1, D23, D42).

1. **Either market has no terms** → the title fallback below, which can say AMBIGUOUS at most.
2. **Different event** → DISTINCT. The subject, measure, unit or observation date differ, or both markets state an observation instant and the instants differ.
3. **Different outcome** → DISTINCT. After normalizing on the measure's grid, the direction (above, below, equal, between) or the threshold differs.
4. **Measured differently** → AMBIGUOUS. Everything above matches, but `measured_by` differs: a Pyth price against the exchange's official close, say. These can differ on an ordinary day, so the pair is shown and never routed.
5. **Observation time stated by only one market** → AMBIGUOUS. The other market might observe at a different moment.
6. **Otherwise** → EQUIVALENT, with a risk flag for every difference that remains.

**The grid.** Fed decisions move in 25 bps steps, so on that grid "below −25" and "at or below −50" pay out on exactly the same moves. Kalshi's "Cut >25bps" and Polymarket's "50+ bps decrease" are therefore equivalent (D20). The matcher normalizes `lt t` to `le t−25` and `gt t` to `ge t+25` for that measure only. Stock prices have no grid, so "above 330" never becomes "at or above 331".

**Risk flags** start with fixed phrases, so tests and the router can rely on them:

| Flag | Raised when | Example from the data |
|---|---|---|
| `Tie rule differs:` | Only the strictness differs (`gt` against `ge`) | "at exactly 330 USD, Polymarket pays No and Meridian pays Yes." |
| `Equal only on the 25 bps grid:` | The terms agree only after grid normalization | Kalshi "below −25 bps" against Polymarket "at or below −50 bps" |
| `Edge-case rules differ:` | The venues' fallback procedures differ | Kalshi: a cancelled meeting resolves "Fed maintains rate" Yes. Polymarket: an off-grid move is rounded up to the nearest 25 bps. |
| `Resolution sources differ:` | The resolving institutions differ | Not raised for the Fed pairs (see below) |

Resolution sources are compared by **institution**, not URL (D18). Kalshi cites `https://www.federalreserve.gov` and Polymarket cites the FOMC calendar page on the same site (K7, P6). Comparing the text would flag a difference that isn't there.

**Why the edge-case difference doesn't block the match.** Polymarket rounds an off-grid move (say 12.5 bps) up to the nearest bracket; Kalshi's rules don't say what it does. That only matters for a move that isn't a multiple of 25 bps, and treating it as a mismatch would mean no Fed pair is ever routed. So the pair is EQUIVALENT and the difference goes into every trace that uses it (D20).

## Clusters

A **cluster** is every market with the same normalized terms. Its ID is those terms as text, for example `FOMC|fed_upper_bound_change|fomc_statement|2026-10-28|eq|0|bps`. Inside a cluster every pair is EQUIVALENT, and a test checks that on the golden data. A cluster keeps its members' risk flags and lists any AMBIGUOUS pair that involves a member, so the trace can show what was considered and set aside. A market with terms and no partner is a cluster of one: it can still be quoted and explained on its own venue.

On the snapshot, `python -m equinox match --source fixtures` finds five clusters, one per Fed outcome, each pairing one Kalshi market with one Polymarket market. All five carry the edge-case flag; the two "more than 25 bps" pairs also carry the grid flag.

## Confidence

Every match result also carries a confidence level and its reason (D46). The level is read from the verdict and its flags; it never changes a verdict, and routing still takes EQUIVALENT pairs only.

| Level | When | Example |
|---|---|---|
| High | EQUIVALENT, and only the venues' rare-event rules differ, or nothing does | Kalshi "Fed maintains rate" and Polymarket "No change" |
| Medium | EQUIVALENT, but the payout can still differ in one stated case | Kalshi "Cut >25bps" and Polymarket "50+ bps decrease", which agree only for moves in 25 bps steps |
| Low | AMBIGUOUS, so never routed. A pair compared by title alone also shows its title score | The E13 titles, score 0.56 |
| none | DISTINCT | "No change" and "25 bps increase" |

`python -m equinox match` prints each cluster's level, and the web UI shows it on every page (architecture §8.3).

## Why not title similarity

The first design matched markets by how similar their titles were, with a numeric veto. Running that code on realistic titles before building on it showed three failures (AI_USAGE items 2–4):

| Pair | First design | Correct |
|---|---|---|
| "Will the Fed cut rates by 25 bps in December 2025?" against the same with 50 bps | 0.946, EQUIVALENT: "2025" counted as a shared number | DISTINCT |
| "Will Trump win Pennsylvania in 2024?" against "…Michigan in 2024?" | 0.867, EQUIVALENT: no entity veto in the code | DISTINCT |
| "Will the Fed cut rates at the December 2025 FOMC meeting?" against "Fed decreases interest rates after December 2025 meeting?" | 0.419, DISTINCT: a true pair worded the way the two venues word things | Not decidable from titles |

Titles are written for people, and venues word the same event differently. Similar words prove nothing about payout. The structured fields that both venues publish for these markets do.

## The title fallback

Markets without terms (any event family that has no parser) reach only a title fallback, and it can never say EQUIVALENT (architecture §6.3, D15). A pair is a candidate when the share of title words they have in common, stop words removed, is at least 0.3. A candidate is DISTINCT if:

- their numbers differ (years from 1900 to 2099 are ignored);
- a US state or a month differs; or
- one title leans "cut" and the other "hike" (or above against below, win against lose).

Every other candidate is AMBIGUOUS, with its score. On the three pairs above, the fallback now says DISTINCT (score 0.75, numbers differ), DISTINCT (0.60, states differ) and AMBIGUOUS (0.56). The model refuses a text match marked EQUIVALENT (D39), so nothing the fallback finds is ever routed.

## Comparing every open market

Families are one way in. The catalog is the other: `python -m equinox catalog refresh` reads every open market on both venues and compares every cross-venue pair it can (D48–D50, D54). The recorded refresh ran at 2026-10-11 15:52 UTC:

| Step | Count |
|---|---|
| Open markets read | 287,523: 128,798 on Kalshi and 158,725 Yes/No on Polymarket, in 286 requests (151 MiB with gzip, 94 s) |
| Left out | 120,489 markets that aren't Yes/No or couldn't be read |
| Cross-venue pairs | about 20.4 billion |
| Same bet, by contract terms | 15 outcomes: the October, December and January Fed meetings, 5 outcomes each |
| Title candidates from the index | 981,797: about 1 pair in 20,800 |
| Different bets | 970,840. Title score under 0.3: 838,863. Numbers differ: 87,658. Months: 41,165. Outcomes: 23,896. States: 4,813. Opposite words: 1,108. A pair can have more than one veto. |
| Unclear, never routed | 10,957 pairs, involving 3,902 Kalshi and 5,294 Polymarket markets |

Comparing took 56 s, and the whole refresh 158 s at 383 MiB of memory.

**How the candidates are found.** A title (with its outcome label) is reduced to its informative words: stop words go, and so does any word in more than 2% of a venue's titles. Two markets on different venues are a candidate only if they close within 3 days of each other and share at least two informative words. Each candidate then goes through the title fallback above. Markets with terms are matched by terms instead, as in the rest of this document.

**One veto only the catalog can apply.** Listings carry outcome labels. In the first refresh, 25,517 of 34,807 unclear pairs (73%) were two markets that each named a different outcome, such as "Will Keria win Finals MVP at League of Legends Worlds?" (Keria) and "Will Eddie win Worlds 2026 Finals MVP?" (Eddie). Such a pair is now DISTINCT unless one label appears in the other title, so "Will Frank Ocean release a new album in 2026?" (labelled 2026) still matches "Will Frank Ocean release an album in 2026?" (labelled Frank Ocean).

**What "unclear" looks like.** The most similar pairs are very likely the same bet. Both venues list "Will Taylor Swift be Time Person of the Year 2026?", and 20 such pairs score 1.00. Even so, nothing in the titles says how each venue resolves them, and their stated close times are 29 hours apart (Kalshi at 11:59 PM ET on December 31, Polymarket at 00:00 UTC on December 31). Lower down, titles mislead in both directions:

- "Will the rate of core PCE inflation be above 0.5% in September 2026?" and "Will Core PCE MoM be 0.5% or more in September?" read alike (score 0.45). At exactly 0.5%, though, one pays No and the other Yes. That is the tie rule the terms rules flag, which titles can't show.
- "Joe Burrow: 2+ passing interceptions" and "Joe Burrow: 2+ Touchdowns" score 0.50 and are different bets.

This is why D15 holds at catalog scale: titles find candidates for a person to check, and only terms make a market routable. The All markets page (`/markets`) shows each unclear pair with its score and reasons.

**What the index misses.** A true pair worded with fewer than two shared informative words, or closing more than 3 days apart, is never a candidate (D50). 1,866 Kalshi markets close in 2030 or later, some in "2099" as a placeholder for "eventually", and 1,424 Polymarket markets have no end date at all, so long-dated questions rarely pair.

## Reading terms with a model

Titles find candidates but can't be routed (D15), and a parser per family doesn't scale. The term reader is the hybrid the brief allows ("rule-based, heuristic, AI-assisted, or hybrid"): a model reads each market in an unclear pair into the same terms shape the Fed parsers fill, deterministic checks refuse any reading the venue's own text doesn't support, and the terms rules above decide (D56–D58). The model never says whether two markets are the same bet.

**What the checks refuse.** A reading is rejected when:
- its evidence phrase isn't in the market's text;
- its threshold isn't a number the venue wrote, in the text or Kalshi's strike fields;
- its comparison disagrees with the evidence's words ("above" is gt, "at least" and "+" are ge);
- its date falls after the market closes;
- Kalshi's own strike fields say otherwise.

A rejected market leaves its pair unclear, with the reason.

**What a reading looks like.** Kalshi's "Final score Al Ahli Saudi FC wins 1-0?" (Al Wasl at home) and Polymarket's "Exact Score: Al Wasl FC 0 - 1 Al Ahli Saudi FC?" both read as `al_wasl_fc_vs_al_ahli_saudi_fc`, `final_score_0_1`, an indicator. The rules make them the same bet. Polymarket's "Al Wasl FC 1 - 0 Al Ahli Saudi FC", with the same words, reads as `final_score_1_0`: a different bet. That's the pair titles can't tell apart.

**Evals** (`python -m equinox.reader.evals`; recorded with prompt feat-10.7 and `claude-haiku-5-5`):

| Gold set | Pairs | Same bets labelled | Found | False same-bets | Readings rejected |
|---|---|---|---|---|---|
| Fed meetings both venues list, labelled by the parsers' terms | 75 | 15 | 13 | 0 | 0 of 30 |
| Catalog pairs labelled by hand (the prompt was tuned on these) | 35 | 13 | 8 | 0 | 5 of 70 |
| Held-out pairs, labelled after tuning and never tuned on | 18 | 4 | 3 | 0 | 1 of 36 |

A false same-bet is the number that matters: it would route money to the wrong contract. A missed same-bet only leaves a pair unclear. The tests replay the recorded answers, so the gate checks these numbers on every run without calling the model.

**What the live sample found.** A 100-market sample of the live catalog read 8 IPO pairs as the same bet while every gold set showed zero false same-bets. Kalshi pays when an IPO is *confirmed* (the S-1 declared effective, the price set, or a ticker assigned, even if trading starts after January 1); Polymarket pays when it is *completed*, by the first sale of shares, by December 31. A company that prices on December 30 and trades on January 2 pays Yes on one and No on the other. The IPO pairs joined the gold set, the prompt now names a measure as narrowly as the rules define it, and the next sample read all 19 IPO pairs as different and 12 Ballon d'Or pairs as the same bet. An eval set is evidence about the families in it, so samples of the live catalog are read by hand too (AI_USAGE 23).

**Routing.** A model-read same bet can be priced like any other (`simulate --market`, or the All markets page), but only while the committed evals show zero false same-bets for the model and prompt that read it (D58). Its trace says the terms were read by a model, at Medium confidence at most.

**Cost.** 100 markets took 8 requests, about 47,000 input and 14,000 output tokens.

**The full read.** On 2026-10-11 the reader read every unclear pair in the live catalog: 12,910 markets in 1,094 requests (a market paired with several others is read once per group), 8.05 million input and 1.79 million output tokens, about $1.70 at Haiku 5.5's prices. It accepted 12,158 readings and rejected 752. It decided 740 pairs as the same bet (752 with the earlier sample), 7,380 as different, and left 1,303 unclear; all 19 IPO pairs read as different. Thirty of the same bets, picked at random and checked by hand against both venues' rules, had no false same-bet: exact scores (including away wins, "Lille wins 2-0" against "Arsenal 0 - 2 Lille"), league and tournament winners, Game Awards, Google rankings and arrests. Where their rules differ it is in edge-case fallbacks, such as a shared MVP paid 1/N on Kalshi, which D23 flags rather than refuses. That sample was too small: once exact scores had a parser, every one of the model's 456 score same bets was checked against the venues' own score fields, and 7 were false (below). Answers are cached by request, so a re-run pays only for markets whose text changed.

## Parsers and the model reader

Two things read a market's terms, and each does a job the other can't (D60):

- A **parser** is code for one family on one venue. It is exact, free and offline, and its pairs can reach High confidence. Fed decisions have one on each venue.
- The **model reader** covers every family without a parser, behind the checks and the eval gate. Its pairs are Medium confidence at most.

The model doesn't replace the Fed parsers. On the Fed gold set it found 13 of 15 same bets with no false one, including "cut >25 bps" against "50+ bps decrease", which agree only on the 25 bps grid. It missed two because, within one answer, it dated a Polymarket market by the first day of a two-day meeting and its siblings by the second. The parser gets all 15 every time, its terms label the Fed gold set for free, and Kalshi's custom Fed strikes give the deterministic strike check nothing to compare.

**How a family graduates.** The model's reads show where a parser pays off: a family with many cross-venue same bets and regular wording on both venues. In the full read, exact scores were about 58% of the model-read same bets (439 of 752, in the eight score series among the 25 largest). Kalshi publishes each score as fields (`home_score`, `away_score`), and Polymarket writes every one as "Exact Score: <home> <h> - <a> <away>", so exact scores are the first candidate. A family with a handful of markets, such as an arrest list or one award, stays with the model. Once a family has a parser, its readings become free gold labels for the model's evals, as the Fed parsers' are.

**The model as a cross-check.** Reading a parser family with the model too flags every pair where the two disagree: a parser that misses a rewording, or a model that misreads. Exact scores, below, are the first family read both ways.

## Exact scores: a parser, checked by the model

Exact scores were 58% of the model's same bets in the full read (D60), so they were the first family to get a parser on each venue (D61):

- **Kalshi.** The event is "<home> vs <away>: Correct Score" (or "1st Half Correct Score"), and `custom_strike` holds `home_score` and `away_score`. The parser also requires the rules to name the match in that order, state the period ("after 90 minutes plus stoppage time (does not include extra time or penalties)", or "at the end of the 1st Half") and state the same score, winner first: "If Coventry City wins 2-1".
- **Polymarket.** `sportsMarketType` says `soccer_exact_score` or `soccer_first_half_exact_score`, the event's `teams` say which side is home, and the question must read "Exact Score: <home> <h> - <a> <away>?", home first. The description must state the period and the match. Its postponement, cancellation and no-data rules become fallback rules; "Any Other Score" gets no terms, since the venues list different scores.
- **Team names** (D62). Accents, case, punctuation, club words and Brazilian state codes are dropped and "St." reads "Saint", so "Coventry City" is "Coventry City FC" and "CR Flamengo RJ" is "CR Flamengo". Four names still differed in the model's score pairs, and `adapters/team_aliases.json` maps them ("PSV Eindhoven" is "PSV"). A wrong merge would need both teams and the date to collide.
- **Source** (D63). Score markets have no `resolutionSource` of their own, so they take their event's (premierleague.com, uefa.com).

Both parsers give one terms shape: subject "coventry city vs newcastle united", measure `full_time_score_2_1` (home goals first), observed on the day the match was "originally scheduled for", as an indicator. The same pair rules then decide, so 2-1 against 1-2, or the first half against full time, is a different bet.

**The live refresh.** On 2026-10-12 at 02:29 UTC a refresh read 265,944 markets and found 733 outcomes that are the same bet by their contract terms: the 15 Fed outcomes and 718 exact scores. Every one of Kalshi's 1,175 score markets got terms; of Polymarket's 46,439, 44,942 did. Of the 1,497 without, 1,340 are "Any Other Score" and 157 are markets the parser refuses because a name is written two ways (the question says "CDPJuniorFC" where the event's teams spell it out), which fails safe: they stay unclear. Thirty of the 718 pairs, picked at random and read against both venues' rules, were all right.

**Against the model.** Of the model's 456 score same bets from the full read, the parser found 355 again; 95 belonged to matches that had closed before the refresh; 6 it read as different bets. In all 6 the parser is right. Checked against Kalshi's score fields and Polymarket's titles, all 456 hold **7 false same-bets**, each a reversed score: Kalshi's "Racing Club De Lens wins 4-1" (home 4, away 1) against Polymarket's "Racing Club de Lens 1 - 4 Sporting CP" (home 1, away 4). Kalshi writes the winner's goals first and Polymarket the home team's; the model sometimes gave one market the other's order. The 30-pair hand check had missed them: at 1.5%, a sample of 30 more likely than not shows none. The eval gate would have let them route; read again two at a time, the model repeats the mistake on 3 of 6, so feat-12 adds them as gold traps with a stronger reader. The parser also finds 363 same bets the model didn't: 273 that titles never paired (mostly draws, "Final score Draw 0-0?" against two team names) and 90 the model read as different.

**Pricing.** A parser's pair outside the loaded families is priced from the catalog like a model-read one, but without the eval gate or the model flag (D65). Live on 2026-10-12, 10 YES on Coventry City 2-1 Newcastle United routed to Polymarket at $0.84 against $0.86 on Kalshi, and 10 YES on RB Leipzig 2-1 PSV (an alias) at $1.05 against $1.17. Both are Medium confidence: Kalshi settles by ESPN and Polymarket by the league's statistics, and the trace says so with the venues' different postponement rules.

**The cross-check** (D64). A refresh keeps the parser's pairs whose terms differ but whose titles alone would have left them unclear, as "different", with both markets' texts. `catalog check --limit N` reads them and the parser's same bets with the model, decides them with the same rules, and lists every pair the two decide differently, changing nothing. On the 2026-10-12 catalog that is 4,051 markets in 221 requests, about $0.47 at Haiku's prices (28 requests already cached); it hasn't been run. The comparison above did its job for free, from the full read's answers.

**Gold labels.** The parsers label a fourth eval set for free: three groups from `snapshot-2026-10-11-scores` (Coventry City v Newcastle United at full time, its first half against full time, and RB Leipzig v PSV), 68 pairs with 13 same bets. The model found 9 with no false same-bet; it missed three first-half pairs and one away win.

## How strong the setup is

Every gold set is scored twice (D66): **raw**, from every reading the model makes that forms valid terms, which says how often the model alone is right; and **guarded**, after the checks, which is what can route. Each false same-bet rate gets a one-sided 95% upper bound over the pairs labelled different, so a small clean set says how little it shows. The baseline, recorded on 2026-10-11 with prompt feat-10.7:

| Set | Pairs labelled different | False same-bets, raw | False same-bets, guarded | Same bets found (raw) |
|---|---|---|---|---|
| Fed meetings | 60 | 0 (under 4.9%) | 0 | 13 of 15 |
| Labelled pairs | 22 | 0 (under 12.7%) | 0 | 8 of 13 |
| Held-out pairs | 14 | 0 (under 19.3%) | 0 | 3 of 4 |
| Scores (fixture) | 55 | 0 (under 5.3%) | 0 | 9 of 13 |
| Traps | 7 | **3** (under 77.5%) | 0 (under 34.8%) | none labelled |
| Score groups, tuning half | 720 | 0 (under 0.4%) | 0 | 80 of 80 |
| Score groups, judging half | 720 | 0 (under 0.4%) | 0 | 73 of 80 |

The **traps** are the 7 reversed scores from the full read; read again two at a time, the model still reverses 3. The score-order check (D67) refuses those readings, so guarded they are 0. The **score groups** are 16 live catalog requests labelled by the parsers, one per match, split by match into a half the reader may be tuned on and a half it is only judged on (D68). On them the model makes no false same-bet; its order mix-up shows instead as 7 missed same bets, all away wins in one match (Al-Ittihad v Shabab Al Ahli). A better reader should bring the traps to 0 raw and the misses down, without a new false same-bet anywhere.

**Upkeep.** Each catalog market records the parser family meant to read it (D69). `catalog check --drift --limit N` reads only a family's markets that got no terms and says which still look like the family, the sign that a venue reworded them, and which don't.

**After the reader change** (D71, prompt feat-12.1). The model now reads a score in parts, working out which team is at home and how the market writes its score before the goals, and code writes the score's terms from them, as the parsers do. The same sets, read again:

| Set | Before: false raw, same bets found | After: false raw, same bets found |
|---|---|---|
| Fed meetings | 0, 13 of 15 | 0, **15 of 15** |
| Labelled pairs | 0, 8 of 13 | 0, 8 of 13 |
| Held-out pairs | 0, 3 of 4 | 0, 3 of 4 |
| Scores (fixture) | 0, 9 of 13 | 0, **13 of 13** |
| Traps | **3** of 7 | **0** of 7 |
| Score groups, tuning half | 0, 80 of 80 | 0, 80 of 80 |
| Score groups, judging half | 0, 73 of 80 | 0, **80 of 80** |

Guarded, no set has a false same-bet before or after. It took two fixes found on the tuning half and the fixture set: the model had named a score's settling body two ways for one match, and one stray quote in an answer had dropped a whole request's records (D72). The fixture set also now shows Kalshi's strike fields, as live reads do (D73). Strict tool mode was tried and refused: the API calls the tool's schema too complex.

**Upkeep, live.** On the 2026-10-12 catalog, 157 markets of the exact-score family got no terms from the parser. Read by the model, all 157 look like exact scores. They fall in two groups (D74). Some write a team two ways in one event ("CDPJuniorFC" in the question, spelled out in the event's teams): the parser should learn those. The others use a new Polymarket wording, "considering the final score regardless of format (e.g. two halves totaling 90 minutes plus stoppage time, or four periods totaling 120 minutes)", which counts extra time: a different bet from Kalshi's 90 minutes, which the parser was right to refuse. None of them is paired with another market today; a period for extra time is on the cut list.

**The cross-check, live.** Every parser pair in the catalog (3,978 markets, 2,461 pairs) read by the new reader: the model agrees on 2,404, leaves 43 undecided, and disagrees on 14. Thirteen are Chapecoense v CA Paranaense, where the parsers keyed Polymarket's "Associação Chapecoense de Futebol" apart from Kalshi's "Chapecoense SC": the model was right, and the name is now in the alias table. The fourteenth is a 0-0 draw the model read without the score parts, a missed same bet. The model raised no false same-bet against the parsers. It cost $0.68.

**The re-read, live.** With the new reader the whole catalog's unclear pairs were read again on 2026-10-12: 8,637 markets in 837 requests, 8,069 readings accepted and 568 refused. It decided 229 same bets, 5,096 different and left 1,089 unclear; none of the same bets touches an exact score, which the parsers read. Twenty-five picked at random were all the same bet when read against both venues' rules (the closest call, "hear" against "accepts" an AI-copyright case, is a grant of certiorari in both). It cost $1.16; the run hit the API's limit of 80,000 output tokens a minute once and was resumed from the cache. Pricing one exposed a feat-10 bug, fixed here (D75): a model-read pair is priced with readings of its markets that agree. On 10 YES on Lamine Yamal winning the 2026 Ballon d'Or, the trace says the terms were read by a model and routes to Polymarket at $2.97 against $3.15 on Kalshi. A Polymarket market that names no resolution source, on itself or its event (127 of the 229 have none on the market), is now built for pricing with "an unnamed source" and the trace says so (D76): 10 YES on Taylor Swift as Time's 2026 Person of the Year routes to Kalshi at $0.43 against $0.49, flagged that Polymarket names no source.

## Third venue: the Meridian fit check

Two venues can't show that the design generalizes. Meridian, a planned binary-stock-outcome venue on Solana devnet, is **not integrated** (D26). Instead, architecture §9 maps it onto the canonical model on paper, and hand-built Meridian-style markets go through the real matcher and router in the test suite.

The example is "Will Apple close above $330 on October 12, 2026?":

- Polymarket market `5455686`: YES if Pyth's AAPL close is **strictly above** $330 (S3).
- Meridian-style `AAPL-330-2026-10-12`: YES if the close is **at or above** $330 (M1, M2).

Both state the same measure (`close_price`), source (`pyth_regular_close`), date and instant (the 4:00 PM ET close). They differ in strictness and in edge-case rules, so the matcher says:

> EQUIVALENT. Tie rule differs: at exactly 330 USD, Polymarket pays No and Meridian pays Yes. Edge-case rules differ: …

The same tests show the other rules working on a new venue's data:

- $335 is a different outcome (DISTINCT).
- October 13 is a different event (DISTINCT).
- A copy measured on the official close instead of Pyth is AMBIGUOUS.

The matcher needed no change for any of it, and the layering test proves it names no venue. Only the terms model had to be general enough: "close at or above $330 per Pyth" couldn't be expressed in terms shaped around the Fed alone (D22).

Meridian settles in devnet USDC, which has no monetary value (M5). That is a routing question, not an equivalence one: see [ROUTING.md](ROUTING.md).

## Limits

- One event family has a term parser: Fed rate decisions. Other markets are read by a model when they are in an unclear pair (D57); a model reading is checked against the venue's text but can still name one thing two ways, which leaves the pair unclear.
- The catalog is as fresh as its last refresh, and its title candidates depend on the index's blocking rules: dates within 3 days, two shared informative words (D50).
- No Kalshi and Polymarket stock or index pair is strictly equivalent today: they differ in comparison, tie rule, price source or underlying (S5).
- Strictness is a choice. Some pairs a person would call the same bet are AMBIGUOUS here, for example two markets that differ only in whether they state an observation instant. AMBIGUOUS pairs are shown with their reasons, so the cost of strictness is visible.
