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

from equinox import sources
from equinox.adapters.base import FetchError
from equinox.adapters.fetch import FixtureFetcher
from equinox.sources import LiveFetchers, Loaded, Settings
from equinox.web import board, match, order, pages
from equinox.web.view import PageContext, View, build_view

SOURCES = ("snapshot", "live")
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
        page = ROUTES.get(path)
        if page is None:
            return None
        params = {k: v[-1] for k, v in parse_qs(query, keep_blank_values=True).items()}
        source = params.get("data") if params.get("data") in SOURCES else "snapshot"
        view = self._view(source)
        ctx = PageContext(
            self._clock(), self.settings.stale_after, self._banner(view, path, params)
        )
        return page(view, params, ctx)

    def _load_markets(self, source: str) -> Loaded:
        settings = replace(self.settings, source="fixtures" if source == "snapshot" else "live")
        return sources.load_markets(settings, self.live_fetcher)

    def _view(self, source: str) -> View:
        """The snapshot loads once; live data is read again after `live_for`."""
        with self._lock:
            now = self._clock()
            view = self._views.get(source)
            if view and (source == "snapshot" or now - view.read_at < self._live_for):
                return view
            view = build_view(source, self._load(source), now)
            self._views[source] = view
            return view

    def _banner(self, view: View, path: str, params: dict[str, str]) -> pages.Banner:
        other = "live" if view.source == "snapshot" else "snapshot"
        switch = pages.href(path, **{**params, "data": other if other == "live" else ""})
        if view.source == "snapshot":
            try:
                taken = FixtureFetcher(self.settings.snapshot).captured_at
                summary = f"Snapshot taken {taken:%Y-%m-%d %H:%M} UTC."
            except FetchError:
                summary = "Snapshot data."
            label = "Use live prices instead"
        else:
            age = int((self._clock() - view.read_at).total_seconds())
            summary = f"Live prices, read at {view.read_at:%H:%M:%S} UTC ({age} s ago)."
            label = "Use the snapshot instead"
        return pages.Banner(summary, label, switch, view.loaded.warnings)
