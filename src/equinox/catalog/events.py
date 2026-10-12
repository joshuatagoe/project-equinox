"""The events both venues list, from the catalog: what the web app shows (feat-14, D86).

Each same bet is shown once, as the market whose ID sorts first, under that market's event; its
match on the other venue gives the second price. A search finds a pair by either market's words.
Pairs whose titles only look alike are never here: they are never priced (D15).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from equinox.catalog.store import Catalog
from equinox.models.catalog import SAME_BET, CatalogRow

OTHER = "Other"  # the topic of an event neither venue gives one (D87)
_EVERY = 1_000_000  # a page size that holds every same bet (about 1,000 on 2026-10-12)
_NEVER = datetime.max.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Event:
    key: str  # a market of the event, which opens its page
    title: str
    topic: str
    closes_at: datetime | None  # when its first outcome stops trading
    outcomes: list[CatalogRow]  # most likely first

    def has(self, market_id: str) -> bool:
        return any(market_id in (o.market_id, o.partner) for o in self.outcomes)


def events(found: Catalog, words: str = "", topic: str = "") -> list[Event]:
    """Every event with a same bet, soonest to close first. With `words`, only the outcomes whose
    market or its match has every word in its title; with `topic`, only that topic's events."""
    rows = found.search(status=SAME_BET, per_page=_EVERY, pairs_once=True)
    if words.strip():
        hits = {r.market_id for r in found.search(words, status=SAME_BET, per_page=_EVERY)}
        rows = [r for r in rows if r.market_id in hits or r.partner in hits]
    grouped: dict[tuple[str, str], list[CatalogRow]] = {}
    for row in rows:
        grouped.setdefault((row.venue, row.event_title), []).append(row)
    found_events = [_event(outcomes) for outcomes in grouped.values()]
    if topic:
        found_events = [e for e in found_events if e.topic == topic]
    return sorted(found_events, key=lambda e: (e.closes_at or _NEVER, e.title))


def event_of(found: Catalog, market_id: str) -> Event | None:
    """The event that holds this market, or its match; None if it isn't a same bet."""
    return next((e for e in events(found) if e.has(market_id)), None)


def topics(found: Catalog) -> dict[str, int]:
    """How many events each topic has, the biggest first."""
    counted: dict[str, int] = {}
    for event in events(found):
        counted[event.topic] = counted.get(event.topic, 0) + 1
    return dict(sorted(counted.items(), key=lambda item: (-item[1], item[0])))


def likelihood(row: CatalogRow) -> Decimal:
    """The cheapest price to buy YES on either venue: what the markets think of the outcome. A
    thin book's high ask doesn't count, and a venue nobody sells on is skipped (D88)."""
    return min((p for p in (row.yes_ask, row.partner_yes) if p is not None), default=Decimal(0))


def _event(outcomes: list[CatalogRow]) -> Event:
    closes = [o.closes_at for o in outcomes if o.closes_at]
    return Event(
        key=min(o.market_id for o in outcomes),
        title=outcomes[0].event_title,
        topic=next((o.topic for o in outcomes if o.topic), OTHER),
        closes_at=min(closes, default=None),
        outcomes=sorted(outcomes, key=lambda o: (-likelihood(o), o.market_id)),
    )
