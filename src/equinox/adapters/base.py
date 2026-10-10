"""The adapter contract (architecture section 5.1)."""

import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Literal

from equinox.models import CanonicalMarket

Fetcher = Callable[[str], Any]
"""URL -> parsed JSON (parse_float=Decimal). Raises FetchError."""

Clock = Callable[[], datetime]
"""The time a response was read, time-zone aware (D37)."""

DataSource = Literal["live", "fixture"]

TRACKED_EVENTS = Path(__file__).resolve().parents[1] / "tracked_events.json"


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
    def fetch_markets(self) -> AdapterResult: ...


def load_tracked_events(path: Path = TRACKED_EVENTS) -> dict[str, list[TrackedEvent]]:
    """The configured events per venue (D28): {"kalshi": [TrackedEvent, ...], ...}."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {venue: [TrackedEvent(**event) for event in events] for venue, events in raw.items()}
