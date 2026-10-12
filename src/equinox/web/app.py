"""The web UI's routes, data cache and banner (feat-07, D45; architecture section 8.3).

Each page lives in its own module (`order`, `board`, `match`). The pages only present what the
adapters, matcher and router decide; the UI adds no matching or routing logic and names venues
only from each market's `venue` field.
"""

import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

from equinox import catalog, sources
from equinox.adapters.base import FetchError
from equinox.adapters.fetch import FixtureFetcher
from equinox.models import EquivalenceCluster
from equinox.reader import pricing
from equinox.reader.pricing import PricingError
from equinox.sources import FIXTURES, LiveFetchers, Loaded, Settings, snapshot_names
from equinox.web import board, catalog_order, markets, match, order, pages, search, words
from equinox.web.view import PageContext, View, build_view, holding

ROUTES = {"/": order.page, "/index.html": order.page, "/board": board.page, "/match": match.page}


class App:
    def __init__(
        self,
        settings: Settings,
        *,
        live_fetcher: LiveFetchers | None = None,
        load: Callable[[str], Loaded] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        live_for: timedelta = timedelta(seconds=60),
    ) -> None:
        self.settings = settings
        self.live_fetcher = live_fetcher
        self._load = load or self._load_markets
        self._clock = clock
        self._live_for = live_for
        self._views: dict[str, View] = {}
        self._lock = threading.Lock()

    def respond(self, path: str, query: str) -> str | None:
        """The page for a GET request, or None for a path the UI doesn't serve."""
        params = {k: v[-1] for k, v in parse_qs(query, keep_blank_values=True).items()}
        data = params.get("data", "")
        data = data if data in [*snapshot_names(), "live"] else ""
        if path == "/markets":  # the saved catalog, whatever the data source
            return markets.page(self.settings.cache_dir, params, data, self._clock())
        page = ROUTES.get(path)
        if page is None:
            return None
        view = self._view(data or self.settings.snapshot.name)
        outcome = params.get("outcome", "")
        if page is order.page and outcome.startswith(catalog_order.CATALOG):
            loaded = holding(view, outcome.removeprefix(catalog_order.CATALOG))
            if loaded is not None:  # a loaded family's market (Fed): its usual outcome
                params = {**params, "outcome": loaded.key}
            else:  # a same bet in the catalog (D58, D65)
                page = catalog_order.page
        ctx = PageContext(
            self._clock(),
            self.settings.stale_after,
            self._banner(view, path, params),
            lambda market_id: self._price_catalog(view.source, market_id),
            lambda text: search.search(self._catalog(), text),
        )
        return page(view, params, ctx)

    def _load_markets(self, source: str) -> Loaded:
        """Listings only; each page fetches the books it prices (D49)."""
        return sources.load_markets(self._source(source), self.live_fetcher, with_books=False)

    def _price_catalog(self, source: str, market_id: str) -> tuple[EquivalenceCluster, Loaded]:
        """A same bet in the catalog, loaded from `source` for pricing (D58, D65)."""
        found = catalog.load_latest(self.settings.cache_dir)
        if found is None:
            raise PricingError("there is no catalog")
        return pricing.priced_group(found, market_id, self._source(source), self.live_fetcher)

    def _catalog(self) -> catalog.Catalog | None:
        """The newest catalog, or None when there is none or it can't be read."""
        try:
            return catalog.load_latest(self.settings.cache_dir)
        except catalog.CatalogError:
            return None

    def _source(self, source: str) -> Settings:
        if source == "live":
            return replace(self.settings, source="live")
        return replace(self.settings, source="fixtures", snapshot=FIXTURES / source)

    def _view(self, source: str) -> View:
        """The snapshot loads once; live data is read again after `live_for`."""
        with self._lock:
            now = self._clock()
            view = self._views.get(source)
            if view and (source == "snapshot" or now - view.read_at < self._live_for):
                return view
            param = "" if source == self.settings.snapshot.name else source
            view = build_view(source, self._load(source), now, param)
            self._views[source] = view
            return view

    def _banner(self, view: View, path: str, params: dict[str, str]) -> pages.Banner:
        choices = [
            (name, f"Snapshot {name.removeprefix('snapshot-')}") for name in snapshot_names()
        ]
        choices.append(("live", "Live prices"))
        if view.source == "live":
            age = int((self._clock() - view.read_at).total_seconds())
            summary = f"Live prices, read at {view.read_at:%H:%M:%S} UTC ({age} s ago)."
        else:
            try:
                taken = FixtureFetcher(FIXTURES / view.source).captured_at
                old = words.age((self._clock() - taken).total_seconds())
                summary = (
                    f"Snapshot taken {taken:%Y-%m-%d %H:%M} UTC, {old} ago: prices are as "
                    "they were then."
                )
            except FetchError:
                summary = "Snapshot data."
        return pages.Banner(summary, path, view.source, choices, view.loaded.warnings)
