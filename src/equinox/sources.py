"""Where markets come from: settings, data sources, discovery and books (architecture 2, 5.1, 11).

Both interfaces, the command line and the web UI, load markets through this module, so neither
depends on the other (D52). For each venue it discovers the events of the families Equinox can
read, falling back to the pinned events when discovery can't run (D47); lists their markets without
order books; and fetches books only for the group being priced (D49). A live venue that fails is
read from the snapshot instead (D17). Every snapshot folder is a data source (D51).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from equinox.adapters.base import (
    TRACKED_EVENTS,
    AdapterResult,
    Fetcher,
    FetchError,
    TrackedEvent,
    VenueAdapter,
    load_tracked_events,
)
from equinox.adapters.fetch import DEFAULT_SNAPSHOT, FixtureFetcher, HttpFetcher
from equinox.adapters.kalshi import DEFAULT_BASE_URL, KalshiAdapter
from equinox.adapters.polymarket import CLOB_URL, GAMMA_URL, PolymarketAdapter
from equinox.models import CanonicalMarket, EquivalenceCluster

ADAPTERS: dict[str, type[VenueAdapter]] = {
    "kalshi": KalshiAdapter,
    "polymarket": PolymarketAdapter,
}
"""One line per venue: a new venue is an adapter class here, plus a fixture."""

FAMILIES = ("fed_decision",)
"""The event families every adapter is asked to discover: the ones with a term parser."""

FIXTURES = DEFAULT_SNAPSHOT.parent

LiveFetchers = Callable[[str], Fetcher]
"""venue -> the fetcher for a live run. Tests inject one; the default is HttpFetcher."""


class SettingsError(ValueError):
    """A setting that can't be used, reported to the user as bad input."""


def snapshot_names() -> list[str]:
    """Every snapshot folder, oldest first."""
    return sorted(p.name for p in FIXTURES.iterdir() if (p / "index.json").is_file())


def snapshot_path(name: str) -> Path:
    if name not in snapshot_names():
        raise SettingsError(f"no snapshot named {name!r}; there are {', '.join(snapshot_names())}")
    return FIXTURES / name


@dataclass(frozen=True)
class Settings:
    source: str = "live"
    stale_after: timedelta = timedelta(seconds=300)
    timeout: float = 10.0
    snapshot: Path = DEFAULT_SNAPSHOT
    venue_options: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        """Architecture section 11: environment variables, each with a default."""
        try:
            stale = timedelta(seconds=float(env.get("EQUINOX_STALE_AFTER_SECONDS", "300")))
            timeout = float(env.get("EQUINOX_HTTP_TIMEOUT_SECONDS", "10"))
        except ValueError as error:
            raise SettingsError(f"bad setting: {error}") from error
        snapshot = env.get("EQUINOX_SNAPSHOT")
        return cls(
            source=env.get("EQUINOX_SOURCE", "live"),
            stale_after=stale,
            timeout=timeout,
            snapshot=snapshot_path(snapshot) if snapshot else DEFAULT_SNAPSHOT,
            venue_options={
                "kalshi": {"base_url": env.get("KALSHI_BASE_URL", DEFAULT_BASE_URL)},
                "polymarket": {
                    "gamma_url": env.get("POLYMARKET_GAMMA_URL", GAMMA_URL),
                    "clob_url": env.get("POLYMARKET_CLOB_URL", CLOB_URL),
                },
            },
        )


@dataclass
class Loaded:
    markets: list[CanonicalMarket]
    warnings: list[str]
    readers: dict[str, VenueAdapter] = field(default_factory=dict)  # who fetches each venue's books


def load_markets(
    settings: Settings,
    live_fetcher: LiveFetchers | None = None,
    tracked: Path = TRACKED_EVENTS,
    with_books: bool = True,
) -> Loaded:
    """Every venue's discovered markets, with or without their books, and the warnings to show."""
    pinned = load_tracked_events(tracked)
    loaded = Loaded(markets=[], warnings=[])
    for venue in pinned.keys() - ADAPTERS.keys():
        loaded.warnings.append(f"{venue.capitalize()}: no adapter, so it is not read.")
    for venue, adapter_class in ADAPTERS.items():
        venue_pins = pinned.get(venue, [])
        result, reader = _read_venue(
            venue, adapter_class, venue_pins, settings, live_fetcher, with_books
        )
        loaded.markets += result.markets
        loaded.warnings += result.warnings
        if reader is not None:
            loaded.readers[venue] = reader
    return loaded


def ensure_books(cluster: EquivalenceCluster, loaded: Loaded) -> EquivalenceCluster:
    """The cluster with every market's order books, fetched now for those without (D49)."""
    if all(market.books is not None for market in cluster.markets):
        return cluster
    booked = tuple(
        market if market.books is not None else loaded.readers[market.venue].fetch_books(market)
        for market in cluster.markets
    )
    return cluster.model_copy(update={"markets": booked})


def _read_venue(
    venue: str,
    adapter_class: type[VenueAdapter],
    pinned: list[TrackedEvent],
    settings: Settings,
    live_fetcher: LiveFetchers | None,
    with_books: bool,
) -> tuple[AdapterResult, VenueAdapter | None]:
    """One venue's markets: live if asked and it answers, otherwise from the snapshot."""
    options = settings.venue_options.get(venue, {})
    notes: list[str] = []
    if settings.source == "live":
        fetch = (live_fetcher or (lambda _venue: HttpFetcher(settings.timeout)))(venue)
        adapter = adapter_class(fetch, [], "live", lambda: datetime.now(UTC), **options)
        try:
            return _load(adapter, pinned, with_books), adapter
        except FetchError as error:
            notes.append(f"{venue.capitalize()}: live data unavailable ({error})")
    try:
        snapshot = FixtureFetcher(settings.snapshot)
        clock = lambda: snapshot.captured_at  # noqa: E731  the snapshot's own clock (D37)
        adapter = adapter_class(snapshot, [], "fixture", clock, **options)
        result = _load(adapter, pinned, with_books)
    except FetchError as error:
        return AdapterResult(
            [], [*notes, f"{venue.capitalize()}: no markets loaded ({error})."]
        ), None
    if notes:
        captured = snapshot.captured_at.strftime("%Y-%m-%d %H:%M:%SZ")
        notes = [f"{notes[0]}, so its markets come from the snapshot captured {captured}."]
    return AdapterResult(result.markets, notes + result.warnings), adapter


def _load(adapter: VenueAdapter, pinned: list[TrackedEvent], with_books: bool) -> AdapterResult:
    adapter.tracked, notes = _discover(adapter, pinned)
    result = adapter.fetch_markets() if with_books else adapter.list_markets()
    return AdapterResult(result.markets, notes + result.warnings)


def _discover(
    adapter: VenueAdapter, pinned: list[TrackedEvent]
) -> tuple[list[TrackedEvent], list[str]]:
    """The venue's open events for every family; the pinned events if discovery can't run."""
    venue = adapter.venue.capitalize()
    try:
        events = [event for family in FAMILIES for event in adapter.discover(family)]
    except FetchError as error:
        return pinned, [
            f"{venue}: couldn't discover events ({error}), so the pinned events are used."
        ]
    if not events:
        return [], [f"{venue}: discovery found no open events for {', '.join(FAMILIES)}."]
    return events, []
