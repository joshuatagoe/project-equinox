"""Title fallback for markets without contract terms (architecture section 6.3, D15).

It says DISTINCT or AMBIGUOUS, never EQUIVALENT, so nothing it finds is routed.

- A candidate is a cross-venue pair whose title-word Jaccard score (shared words over all words,
  stop words removed) is at least 0.3. `text_matches` returns only the candidates; `text_match`
  scores any pair and calls one below the bar DISTINCT.
- Vetoes, each making a candidate DISTINCT: the numbers differ (four-digit years from 1900 to
  2099 are ignored); a known entity differs (US state names, month names); or the titles lean
  opposite ways on a pair from a small list, such as "cut" vs "hike".
- Every other candidate is AMBIGUOUS, with its score.
"""

import re
from collections.abc import Iterable
from decimal import Decimal
from itertools import combinations

from equinox.models import CanonicalMarket, EquivalenceStatus, MatchResult

CANDIDATE_SCORE = Decimal("0.3")

STOP_WORDS = frozenset(
    "a about after an and are as at be before by do does for from has have in into is it its of "
    "on or s than that the their there this to was what when which who will with".split()
)

US_STATES = tuple(
    name.strip()
    for name in (
        "alabama, alaska, arizona, arkansas, california, colorado, connecticut, delaware, "
        "florida, georgia, hawaii, idaho, illinois, indiana, iowa, kansas, kentucky, louisiana, "
        "maine, maryland, massachusetts, michigan, minnesota, mississippi, missouri, montana, "
        "nebraska, nevada, new hampshire, new jersey, new mexico, new york, north carolina, "
        "north dakota, ohio, oklahoma, oregon, pennsylvania, rhode island, south carolina, "
        "south dakota, tennessee, texas, utah, vermont, virginia, washington, west virginia, "
        "wisconsin, wyoming"
    ).split(",")
)

MONTHS = frozenset(
    "january february march april may june july august september october november december".split()
)

OPPOSITES: tuple[tuple[frozenset[str], frozenset[str]], ...] = (
    (
        frozenset({"cut", "cuts", "decrease", "decreases", "lower", "lowers"}),
        frozenset({"hike", "hikes", "increase", "increases", "raise", "raises"}),
    ),
    (frozenset({"above", "over"}), frozenset({"below", "under"})),
    (frozenset({"win", "wins"}), frozenset({"lose", "loses"})),
)
"""Word pairs that point opposite ways. A title leans to a side if it uses only that side."""

_WORD = re.compile(r"[a-z0-9]+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_YEAR = re.compile(r"(?:19|20)\d\d")
# Longest names first, so "west virginia" is found as itself and not as "virginia".
_STATE = re.compile(r"\b(" + "|".join(sorted(US_STATES, key=len, reverse=True)) + r")\b")


def text_match(a: CanonicalMarket, b: CanonicalMarket) -> MatchResult:
    """Compare two markets by title. AMBIGUOUS at most."""
    words_a, words_b = _words(a.title), _words(b.title)
    shared, total = len(words_a & words_b), len(words_a | words_b)
    score = Decimal(shared) / Decimal(total) if total else Decimal(0)
    lacking = "Neither market has" if a.terms is None and b.terms is None else "One market has no"
    overlap = (
        f"{lacking} contract terms, so only titles are compared: "
        f"they share {shared} of {total} words (score {score:.2f})."
    )

    if score < CANDIDATE_SCORE:
        reasons = (overlap, f"That is below the candidate score of {CANDIDATE_SCORE}.")
        return _result(a, b, EquivalenceStatus.DISTINCT, reasons, score)
    vetoes = [
        *_differs("Numbers", _numbers(a.title), _numbers(b.title), " (years ignored)"),
        *_differs("States", _states(a.title), _states(b.title)),
        *_differs("Months", words_a & MONTHS, words_b & MONTHS),
        *_opposites(words_a, words_b),
    ]
    if vetoes:
        return _result(a, b, EquivalenceStatus.DISTINCT, (overlap, *vetoes), score)
    ambiguous = "Similar titles are AMBIGUOUS at most: a pair without terms is never routed."
    return _result(a, b, EquivalenceStatus.AMBIGUOUS, (overlap, ambiguous), score)


def text_matches(markets: Iterable[CanonicalMarket]) -> list[MatchResult]:
    """The candidates among cross-venue pairs of markets without terms, sorted by market ID."""
    term_less = sorted((m for m in markets if m.terms is None), key=lambda m: m.market_id)
    results = (text_match(a, b) for a, b in combinations(term_less, 2) if a.venue != b.venue)
    return [result for result in results if result.text_score >= CANDIDATE_SCORE]


def _result(
    a: CanonicalMarket,
    b: CanonicalMarket,
    status: EquivalenceStatus,
    reasons: tuple[str, ...],
    score: Decimal,
) -> MatchResult:
    return MatchResult(
        market_a=a.market_id,
        market_b=b.market_id,
        status=status,
        method="text",
        reasons=reasons,
        text_score=score,
    )


def _words(title: str) -> set[str]:
    return set(_WORD.findall(title.lower())) - STOP_WORDS


def _numbers(title: str) -> set[Decimal]:
    found = (match.replace(",", "") for match in _NUMBER.findall(title))
    return {Decimal(number) for number in found if not _YEAR.fullmatch(number)}


def _states(title: str) -> set[str]:
    return set(_STATE.findall(title.lower()))


def _differs(kind: str, found_a: set, found_b: set, note: str = "") -> list[str]:
    if found_a == found_b:
        return []
    return [f"{kind} differ: {_listed(found_a)} vs {_listed(found_b)}{note}."]


def _opposites(words_a: set[str], words_b: set[str]) -> list[str]:
    found = []
    for pair in OPPOSITES:
        lean_a, lean_b = _lean(words_a, pair), _lean(words_b, pair)
        if lean_a is not None and lean_b is not None and lean_a != lean_b:
            used_a, used_b = words_a & pair[lean_a], words_b & pair[lean_b]
            found.append(f"Opposite words: {_listed(used_a)} vs {_listed(used_b)}.")
    return found


def _lean(words: set[str], pair: tuple[frozenset[str], frozenset[str]]) -> int | None:
    """Which side of the pair the title uses (0 or 1), or None if it uses neither or both."""
    sides = [index for index, side in enumerate(pair) if words & side]
    return sides[0] if len(sides) == 1 else None


def _listed(values: set) -> str:
    return ", ".join(str(value).title() for value in sorted(values)) or "none"
