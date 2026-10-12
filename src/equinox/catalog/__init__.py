"""Every open market on both venues, compared and saved for search (D48, D50; architecture 5.1).

`refresh` reads each venue's listing of open markets page by page (`list_open`), compares every
market (`matcher.compare`), and saves the result in the cache folder (`store.py`); a model's
decisions in the previous catalog are kept where both markets' rules are unchanged (`carry.py`).
A refresh that fails, on any page of either venue, raises CatalogError and leaves the previous
catalog in place;
live data is never mixed with the snapshot here. `load_latest` opens the newest catalog for the
command line and the web page.

A snapshot holds a sample of each venue's listing, two pages of 20 events, so a refresh from the
fixtures reads that sample; a live refresh reads every page.
"""

import sqlite3
import time
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from equinox.adapters.base import FetchError, VenueAdapter
from equinox.adapters.fetch import FixtureFetcher, HttpFetcher
from equinox.catalog import carry, store
from equinox.catalog.store import Catalog
from equinox.catalog.texts import TextStage
from equinox.matcher.compare import compare
from equinox.models.catalog import CatalogEntry, CatalogPage, CatalogSummary
from equinox.sources import ADAPTERS, LiveFetchers, Settings

__all__ = [
    "REFRESH_COMMAND",
    "Catalog",
    "CatalogError",
    "TextStage",
    "build",
    "load_latest",
    "refresh",
]

REFRESH_COMMAND = "python -m equinox catalog refresh"

SAMPLE_PAGE_SIZE, SAMPLE_PAGES = 20, 2
"""The catalog sample in a snapshot: two pages of 20 events per venue."""

PROGRESS_EVERY = 10  # pages between progress lines
RETRIES = 2  # per request, for timeouts, dropped connections, 429 and 5xx (D55)


class CatalogError(Exception):
    """A catalog that couldn't be refreshed or read, said in words for the user."""


@dataclass(frozen=True)
class _Paging:
    page_size: int | None
    max_pages: int | None

    def options(self) -> dict[str, int]:
        given = {"page_size": self.page_size, "max_pages": self.max_pages}
        return {name: value for name, value in given.items() if value is not None}


def refresh(
    settings: Settings,
    live_fetcher: LiveFetchers | None = None,
    progress: Callable[[str], None] = lambda line: None,
    page_size: int | None = None,
    max_pages: int | None = None,
) -> CatalogSummary:
    """Read every open market, compare them and save the catalog, keeping the model's decisions
    where both markets' rules are unchanged (D91). Raises CatalogError."""
    started, read_at = time.perf_counter(), datetime.now(UTC)
    kept = carry.keep(settings.cache_dir)
    if settings.source != "live":
        page_size, max_pages = page_size or SAMPLE_PAGE_SIZE, max_pages or SAMPLE_PAGES
        read_at = FixtureFetcher(settings.snapshot).captured_at
    source = "live" if settings.source == "live" else settings.snapshot.name
    with TextStage(settings.cache_dir) as stage:
        paging = _Paging(page_size, max_pages)
        entries, skipped = _read_venues(settings, live_fetcher, paging, stage, progress)
        seconds = time.perf_counter() - started
        summary = build(
            entries, skipped, settings.cache_dir, seconds, read_at, source=source, texts=stage
        )
    carried = carry.apply(kept, settings.cache_dir)
    if carried:
        plural = "" if carried == 1 else "s"
        progress(f"Kept {carried:,} model decision{plural} from the previous catalog.")
    return summary


def _read_venues(
    settings: Settings,
    live_fetcher: LiveFetchers | None,
    paging: _Paging,
    stage: TextStage,
    progress: Callable[[str], None],
) -> tuple[list[CatalogEntry], int]:
    """Every venue's listing, page by page; each page's texts go to the stage on disk."""
    entries: list[CatalogEntry] = []
    skipped = 0
    for venue, pages in _listings(settings, live_fetcher, paging):
        listed = 0
        try:
            for number, page in enumerate(pages, start=1):
                entries += page.entries
                stage.add(page.texts)
                skipped, listed = skipped + page.skipped, listed + len(page.entries)
                if number % PROGRESS_EVERY == 0:
                    progress(f"{venue}: {number} pages read, {listed:,} markets so far")
        except FetchError as error:
            kept = f"{_hint(settings)} The previous catalog is kept."
            raise CatalogError(f"{venue}: {error}.{kept}") from error
        progress(f"{venue}: {listed:,} markets")
    return entries, skipped


def build(
    entries: Sequence[CatalogEntry],
    skipped: int,
    cache_dir: Path,
    seconds: float,
    refreshed_at: datetime | None = None,
    source: str = "entries",
    texts: TextStage | None = None,
) -> CatalogSummary:
    """Compare the markets and save them as the newest catalog. `seconds` is the time spent
    reading them. A market listed twice (a listing that shifted while paging) is kept once.
    With `texts`, the catalog keeps the rules text of every market in an unclear pair."""
    started = time.perf_counter()
    unique = list({entry.market_id: entry for entry in entries}.values())
    found = compare(unique)
    summary = CatalogSummary(
        refreshed_at=refreshed_at or datetime.now(UTC),
        source=source,
        read_seconds=round(seconds, 1),
        compare_seconds=round(time.perf_counter() - started, 1),
        entries=dict(sorted(Counter(entry.venue for entry in unique).items())),
        skipped=skipped,
        same_bet_groups=found.same_bet_groups,
        candidates=found.candidates,
        distinct=found.distinct,
        ambiguous=found.ambiguous,
        vetoes=dict(found.vetoes.most_common()),
    )
    try:
        store.save(cache_dir, unique, found, summary, texts)
    except (OSError, sqlite3.Error) as error:
        raise CatalogError(
            f"the catalog couldn't be saved in {cache_dir} ({error}). The previous one is kept."
        ) from error
    return summary


def load_latest(cache_dir: Path) -> Catalog | None:
    """The newest catalog in `cache_dir`, or None if there is none. Raises CatalogError."""
    path = store.latest(cache_dir)
    if path is None:
        return None
    try:
        return Catalog(path)
    except (sqlite3.Error, ValueError, TypeError) as error:
        raise CatalogError(f"{path} can't be read ({error}); refresh the catalog.") from error


def _hint(settings: Settings) -> str:
    if settings.source == "live":
        return ""
    return " Pick a snapshot that holds a sample of every venue's listing with --snapshot."


def _listings(
    settings: Settings, live_fetcher: LiveFetchers | None, paging: _Paging
) -> Iterator[tuple[str, Iterator[CatalogPage]]]:
    """Each venue's pages, from the venue itself or from the snapshot's sample."""
    for venue, adapter_class in ADAPTERS.items():
        try:
            adapter = _adapter(venue, adapter_class, settings, live_fetcher)
        except FetchError as error:
            raise CatalogError(f"{venue}: {error}") from error
        yield venue, adapter.list_open(**paging.options())


def _adapter(
    venue: str,
    adapter_class: type[VenueAdapter],
    settings: Settings,
    live_fetcher: LiveFetchers | None,
) -> VenueAdapter:
    options = settings.venue_options.get(venue, {})
    if settings.source == "live":
        fetch = (live_fetcher or (lambda _venue: HttpFetcher(settings.timeout, RETRIES)))(venue)
        return adapter_class(fetch, [], "live", lambda: datetime.now(UTC), **options)
    snapshot = FixtureFetcher(settings.snapshot)
    return adapter_class(snapshot, [], "fixture", lambda: snapshot.captured_at, **options)
