# Equivalence: when two markets are the same bet

The brief asks what "equivalent" means and why. This is Equinox's answer, how the matcher applies it, and where it stops. The design is architecture §6; the decisions are D8, D15, D18, D20, D22, D23 and D42.

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

- One event family has a term parser: Fed rate decisions. Every other market is matched by title only and is never routed. Adding a family means one parser per adapter; the matcher doesn't change.
- No Kalshi and Polymarket stock or index pair is strictly equivalent today: they differ in comparison, tie rule, price source or underlying (S5).
- Strictness is a choice. Some pairs a person would call the same bet are AMBIGUOUS here, for example two markets that differ only in whether they state an observation instant. AMBIGUOUS pairs are shown with their reasons, so the cost of strictness is visible.
