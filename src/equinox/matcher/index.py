"""Finding title candidates among hundreds of thousands of markets (D50; architecture 6.3).

Comparing every market on one venue with every market on another would be about 28 billion pairs
for the full catalog. The index narrows that down: a cross-venue pair is a candidate only when the
two markets close within a few days of each other and share at least two informative title words.
A word is informative unless it is a stop word or appears in too many of one venue's titles to tell
markets apart. Each candidate is then decided by the title fallback (`text.py`), which never says
EQUIVALENT.
"""

import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from itertools import combinations
from typing import Protocol

from equinox.matcher.text import STOP_WORDS

COMMON_SHARE = 0.02  # a word in more than 2% of a venue's titles says little...
COMMON_FLOOR = 50  # ...unless the venue lists so few markets that 2% is under 50 titles
WINDOW_DAYS = 3
MIN_SHARED = 2
_WORD = re.compile(r"[a-z0-9]+")


class Titled(Protocol):
    """What the index reads from a market: any listing with these fields will do."""

    venue: str
    title: str
    outcome_label: str
    closes_at: datetime | None


@dataclass(frozen=True, slots=True)
class IndexedTitle:
    position: int  # where the market sits in the list given to `index_titles`
    venue: str
    words: frozenset[str]  # its informative words
    day: date | None  # the day it closes


def title_words(text: str) -> set[str]:
    """Lowercase words without stop words. Each word is interned: a catalog repeats the same few
    hundred thousand words millions of times, and one copy of each saves hundreds of megabytes."""
    return {sys.intern(word) for word in _WORD.findall(text.lower())} - STOP_WORDS


def index_titles(markets: Sequence[Titled]) -> list[IndexedTitle]:
    """Each market's informative words (title and outcome label) and closing day."""
    common = _common_words(markets)
    return [
        IndexedTitle(i, m.venue, frozenset(_words(m) - common[m.venue]), _day(m.closes_at))
        for i, m in enumerate(markets)
    ]


def candidates(
    items: Sequence[IndexedTitle], window_days: int = WINDOW_DAYS, min_shared: int = MIN_SHARED
) -> Iterator[tuple[int, int]]:
    """Cross-venue pairs (by position) that close within `window_days` and share `min_shared`
    informative words. Markets without a closing day are never candidates."""
    by_venue = defaultdict(list)
    for item in items:
        if item.day is not None:
            by_venue[item.venue].append(item)
    for left_venue, right_venue in combinations(sorted(by_venue), 2):
        index = _word_day_index(by_venue[right_venue])
        for left in by_venue[left_venue]:
            day, hits = left.day.toordinal(), Counter()
            for word in left.words:
                days = index.get(word)
                if days:
                    for shift in range(-window_days, window_days + 1):
                        hits.update(days.get(day + shift, ()))
            yield from ((left.position, right) for right, n in hits.items() if n >= min_shared)


def _words(market: Titled) -> set[str]:
    return title_words(f"{market.title} {market.outcome_label}")


def _common_words(markets: Sequence[Titled]) -> dict[str, set[str]]:
    """Per venue, the words in too many of its titles to tell markets apart."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for market in markets:
        counts[market.venue].update(_words(market))
    sizes = Counter(market.venue for market in markets)
    return {
        venue: {w for w, n in counter.items() if n > max(COMMON_FLOOR, COMMON_SHARE * sizes[venue])}
        for venue, counter in counts.items()
    }


def _word_day_index(items: list[IndexedTitle]) -> dict[str, dict[int, list[int]]]:
    """word -> closing day (as an ordinal) -> the positions of the markets with both."""
    index: dict[str, dict[int, list[int]]] = defaultdict(dict)
    for item in items:
        day = item.day.toordinal()
        for word in item.words:
            index[word].setdefault(day, []).append(item.position)
    return index


def _day(moment: datetime | None) -> date | None:
    return moment.date() if moment else None
