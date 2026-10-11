"""The adapter contract (architecture section 5.1).

An adapter finds a family's events (`discover`), lists their markets without order books
(`list_markets`), and fetches one market's books when it is priced (`fetch_books`). `fetch_markets`
does both, for callers that want every book at once (D47, D49).
"""

import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import ValidationError

from equinox.models import CanonicalMarket, OutcomeBook

Fetcher = Callable[[str], Any]
"""URL -> parsed JSON (parse_float=Decimal). Raises FetchError."""

Clock = Callable[[], datetime]
"""The time a response was read, time-zone aware (D37)."""

DataSource = Literal["live", "fixture"]

TRACKED_EVENTS = Path(__file__).resolve().parents[1] / "tracked_events.json"

BOOKS_PENDING = datetime(1970, 1, 1, tzinfo=UTC)
"""The listing time in `fetch_markets`, replaced at once by `fetch_books` with the real one."""

BAD_DATA = (LookupError, TypeError, ValueError, ArithmeticError)
"""A response that isn't shaped as expected; a validation error is a ValueError. Not FetchError."""


class FetchError(Exception):
    """A venue request failed, or a fixture has no response for the URL."""


@dataclass(frozen=True)
class TrackedEvent:
    event_id: str  # a Kalshi event ticker or a Polymarket slug
    family: str  # "fed_decision" is the only family with a term parser


@dataclass(frozen=True)
class AdapterResult:
    markets: list[CanonicalMarket]
    warnings: list[str]  # one line each, e.g. "kalshi: market X has no terms: ..."


Listed = tuple[CanonicalMarket | None, list[str]]
"""A listed market and the notes about it, or None and why it (or its event) was skipped."""


class VenueAdapter(ABC):
    venue: ClassVar[str]

    def __init__(
        self,
        fetch: Fetcher,
        tracked: list[TrackedEvent],
        data_source: DataSource,
        clock: Clock,
    ) -> None:
        self.fetch = fetch
        self.tracked = tracked
        self.data_source = data_source
        self.clock = clock

    @abstractmethod
    def discover(self, family: str) -> list[TrackedEvent]:
        """The open events of a family, in date order; [] for a family this venue can't find."""

    @abstractmethod
    def fetch_books(self, market: CanonicalMarket) -> CanonicalMarket:
        """The same market with both order books; raises FetchError if a request fails."""

    @abstractmethod
    def listings(self, read_at: Clock) -> list[Listed]:
        """The tracked events' markets, without books, in order; `read_at` dates each listing."""

    def list_markets(self) -> AdapterResult:
        listed = self.listings(self.clock)
        markets = [market for market, _ in listed if market is not None]
        return AdapterResult(markets, [note for _, notes in listed for note in notes])

    def fetch_markets(self) -> AdapterResult:
        """Every listed market with its books. A market whose books are malformed is skipped,
        with one warning in place of its notes; a failed request (FetchError) is not caught."""
        result = AdapterResult([], [])
        for market, notes in self.listings(lambda: BOOKS_PENDING):
            if market is None:
                result.warnings.extend(notes)
                continue
            try:
                result.markets.append(self.fetch_books(market))
            except BAD_DATA as error:
                result.warnings.append(
                    f"{self.venue}: market {market.native_id} skipped: {describe(error)}"
                )
                continue
            result.warnings.extend(notes)
        return result


def with_books(
    market: CanonicalMarket, books: dict[str, OutcomeBook], captured_at: datetime
) -> CanonicalMarket:
    """A validated copy of the market with its books, and best asks read from them."""
    best = {side: (book.asks[0].price if book.asks else None) for side, book in books.items()}
    fields = market.model_dump() | {"books": books, "best_asks": best, "captured_at": captured_at}
    return CanonicalMarket.model_validate(fields)


def listed_ask(value: Any) -> Decimal | None:
    """A listing's best ask as an exact price, or None when nobody is selling (0, 1 or blank)."""
    if value is None or isinstance(value, float) or value == "":
        return None
    price = Decimal(str(value))
    return price if 0 < price < 1 else None


def describe(error: Exception) -> str:
    """One line for a warning."""
    if isinstance(error, ValidationError):
        return "; ".join(
            f"{'.'.join(map(str, item['loc'])) or error.title}: {item['msg']}"
            for item in error.errors()
        )
    if isinstance(error, KeyError):
        return f"missing field {error}"
    return " ".join(str(error).split()) or type(error).__name__


def load_tracked_events(path: Path = TRACKED_EVENTS) -> dict[str, list[TrackedEvent]]:
    """The pinned events per venue, used when discovery can't run (D47)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {venue: [TrackedEvent(**event) for event in events] for venue, events in raw.items()}
