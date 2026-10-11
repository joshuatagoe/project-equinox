"""Where markets come from: settings, data sources and loading (architecture sections 2 and 11).

Both interfaces, the command line and the web UI, load markets through this module, so neither
depends on the other (D52). A live venue that fails is read from the snapshot instead (D17).
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
from equinox.models import CanonicalMarket

ADAPTERS: dict[str, type[VenueAdapter]] = {
    "kalshi": KalshiAdapter,
    "polymarket": PolymarketAdapter,
}
"""One line per venue: a new venue is an adapter class here, plus its events and a fixture."""

LiveFetchers = Callable[[str], Fetcher]
"""venue -> the fetcher for a live run. Tests inject one; the default is HttpFetcher."""


class SettingsError(ValueError):
    """A setting from the environment that can't be used, reported to the user as bad input."""


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
        return cls(
            source=env.get("EQUINOX_SOURCE", "live"),
            stale_after=stale,
            timeout=timeout,
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


def load_markets(
    settings: Settings,
    live_fetcher: LiveFetchers | None = None,
    tracked: Path = TRACKED_EVENTS,
) -> Loaded:
    """Every tracked venue's markets, with the warnings to show alongside them."""
    loaded = Loaded(markets=[], warnings=[])
    for venue, events in load_tracked_events(tracked).items():
        adapter = ADAPTERS.get(venue)
        if adapter is None:
            loaded.warnings.append(f"{venue.capitalize()}: no adapter, so it is not read.")
            continue
        result = _read_venue(venue, adapter, events, settings, live_fetcher)
        loaded.markets += result.markets
        loaded.warnings += result.warnings
    return loaded


def _read_venue(
    venue: str,
    adapter: type[VenueAdapter],
    events: list[TrackedEvent],
    settings: Settings,
    live_fetcher: LiveFetchers | None,
) -> AdapterResult:
    """One venue's markets: live if asked and it answers, otherwise from the snapshot."""
    options = settings.venue_options.get(venue, {})
    notes: list[str] = []
    if settings.source == "live":
        fetch = (live_fetcher or (lambda _venue: HttpFetcher(settings.timeout)))(venue)
        live_clock = lambda: datetime.now(UTC)  # noqa: E731
        try:
            return adapter(fetch, events, "live", live_clock, **options).fetch_markets()
        except FetchError as error:
            notes.append(f"{venue.capitalize()}: live data unavailable ({error})")
    try:
        snapshot = FixtureFetcher(settings.snapshot)
        clock = lambda: snapshot.captured_at  # noqa: E731  the snapshot's own clock (D37)
        result = adapter(snapshot, events, "fixture", clock, **options).fetch_markets()
    except FetchError as error:
        return AdapterResult([], [*notes, f"{venue.capitalize()}: no markets loaded ({error})."])
    if notes:
        captured = snapshot.captured_at.strftime("%Y-%m-%d %H:%M:%SZ")
        notes = [f"{notes[0]}, so its markets come from the snapshot captured {captured}."]
    return AdapterResult(result.markets, notes + result.warnings)
