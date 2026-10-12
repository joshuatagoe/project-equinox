"""Comparing every open market at once: same bet, unclear, or no match (D50, D54; arch. 6.3).

- Markets with contract terms are grouped by their terms key (section 6.2). A group that spans two
  venues is the same bet, and only such a group can be priced.
- Every other cross-venue pair that the index finds (`index.py`) is decided by the title fallback,
  which says DISTINCT or AMBIGUOUS and never EQUIVALENT. AMBIGUOUS pairs are shown as unclear and
  are never routed. A pair where both markets have terms is left to the terms; when the terms make
  it a different bet but the titles alone would have left it unclear, it is kept as "different",
  so the model can read it as a cross-check of the parsers (D64). It changes no market's status.
- The catalog adds one veto, because its listings carry outcome labels: two markets that each name
  an outcome the other's title never mentions ("Keria" and "Eddie" for the same MVP award) are
  different bets (D54). In the 2026-10-11 refresh, 73% of the unclear pairs were such pairs.
- A market in neither is "no match": no market on another venue was found to be the same bet.

The title compared is the market's title plus its outcome label when the label adds words, since
some titles leave the outcome out ("Who will the next Pope be?" with the label "Pietro Parolin").
"""

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations

from equinox.matcher.index import candidates, index_titles, title_words
from equinox.matcher.terms import decide, terms_key
from equinox.matcher.text import CANDIDATE_SCORE, text_match
from equinox.models import ContractTerms, EquivalenceStatus
from equinox.models.catalog import (
    DIFFERENT,
    NO_MATCH,
    SAME_BET,
    STATUSES,
    UNCLEAR,
    CatalogEntry,
)

SCORE_PLACES = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Pair:
    a: int  # positions in the list of entries
    b: int
    status: str  # SAME_BET, UNCLEAR, or DIFFERENT for a parser pair kept for the cross-check
    score: Decimal | None  # the title score, for a pair compared by title
    reasons: tuple[str, ...]


@dataclass
class Comparison:
    pairs: list[Pair] = field(default_factory=list)  # same bet and unclear; distinct are counted
    best: dict[int, Pair] = field(default_factory=dict)  # each matched entry's best pair
    same_bet_groups: int = 0
    candidates: int = 0
    distinct: int = 0
    ambiguous: int = 0
    vetoes: Counter = field(default_factory=Counter)

    def status(self, position: int) -> str:
        pair = self.best.get(position)
        return NO_MATCH if pair is None else pair.status

    def partner(self, position: int) -> int | None:
        pair = self.best.get(position)
        if pair is None:
            return None
        return pair.b if pair.a == position else pair.a

    def add(self, pair: Pair) -> None:
        self.pairs.append(pair)
        for position in (pair.a, pair.b):
            if _better(pair, self.best.get(position)):
                self.best[position] = pair


@dataclass(frozen=True, slots=True)
class _Described:
    """An entry as the title fallback sees it."""

    market_id: str
    title: str
    terms: ContractTerms | None


def compare(entries: Sequence[CatalogEntry]) -> Comparison:
    found = Comparison()
    _by_terms(entries, found)
    _by_titles(entries, found)
    return found


def described_title(entry: CatalogEntry) -> str:
    """The title, plus the outcome label when the label has words the title lacks."""
    label = entry.outcome_label.strip()
    if not label or title_words(label) <= title_words(entry.title):
        return entry.title
    return f"{entry.title} ({label})"


def _by_terms(entries: Sequence[CatalogEntry], found: Comparison) -> None:
    groups: dict[str, list[int]] = defaultdict(list)
    for position, entry in enumerate(entries):
        if entry.terms is not None:
            groups[terms_key(entry.terms)].append(position)
    for key, members in groups.items():
        if len({entries[p].venue for p in members}) < 2:
            continue
        found.same_bet_groups += 1
        reason = (f"Both markets have the same contract terms: {key}.",)
        for a, b in combinations(members, 2):
            if entries[a].venue != entries[b].venue:
                found.add(Pair(a, b, SAME_BET, None, reason))


def _by_titles(entries: Sequence[CatalogEntry], found: Comparison) -> None:
    for a, b in candidates(index_titles(entries)):
        if entries[a].terms is not None and entries[b].terms is not None:
            _keep_for_the_check(entries, a, b, found)  # the terms decide
            continue
        result = text_match(_described(entries[a]), _described(entries[b]))
        found.candidates += 1
        unclear = result.status == EquivalenceStatus.AMBIGUOUS
        if unclear and _outcomes_differ(entries[a], entries[b]):
            found.distinct += 1
            found.vetoes["Outcomes"] += 1
        elif unclear:
            found.ambiguous += 1
            score = result.text_score.quantize(SCORE_PLACES)
            found.add(Pair(a, b, UNCLEAR, score, result.reasons))
        else:
            found.distinct += 1
            found.vetoes.update(_veto_kinds(result.text_score, result.reasons))


def _keep_for_the_check(entries: Sequence[CatalogEntry], a: int, b: int, found: Comparison) -> None:
    """A pair the parsers' terms make a different bet, kept when its titles alone would have left
    it unclear: the pairs the model read before the parsers did (D64). Counted nowhere, and no
    market's best pair."""
    first, second = entries[a], entries[b]
    names = (first.venue.capitalize(), second.venue.capitalize())
    decision = decide(first.terms, second.terms, names)
    if decision.status != EquivalenceStatus.DISTINCT:
        return  # the same bet, found by its terms; or measured differently, never routed
    result = text_match(_described(first), _described(second))
    if result.status == EquivalenceStatus.AMBIGUOUS and not _outcomes_differ(first, second):
        score = result.text_score.quantize(SCORE_PLACES)
        found.pairs.append(Pair(a, b, DIFFERENT, score, (decision.reason,)))


def _described(entry: CatalogEntry) -> _Described:
    return _Described(entry.market_id, described_title(entry), entry.terms)


def _outcomes_differ(a: CatalogEntry, b: CatalogEntry) -> bool:
    """Both markets name an outcome, and neither name appears in the other's title: "Will Keria
    win Finals MVP at League of Legends Worlds?" (Keria) and "Will Eddie win Worlds 2026 Finals
    MVP?" (Eddie). A label the other title mentions, such as a year, is not a different outcome."""
    named_a, named_b = title_words(a.outcome_label), title_words(b.outcome_label)
    if not named_a or not named_b:
        return False
    in_b, in_a = title_words(described_title(b)), title_words(described_title(a))
    return not (named_a & in_b or named_b & in_a)


def _veto_kinds(score: Decimal, reasons: tuple[str, ...]) -> set[str]:
    """Why a candidate is distinct: "Low score", or the first word of each veto ("Numbers")."""
    if score < CANDIDATE_SCORE:
        return {"Low score"}
    return {reason.split(" ", 1)[0] for reason in reasons[1:]}


def _better(pair: Pair, held: Pair | None) -> bool:
    """Same bet beats unclear; between unclear pairs, the higher title score wins."""
    if held is None:
        return True
    rank, held_rank = STATUSES.index(pair.status), STATUSES.index(held.status)
    return rank < held_rank or (rank == held_rank and (pair.score or 0) > (held.score or 0))
