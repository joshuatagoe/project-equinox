"""The web app's routes (feat-14, D86; architecture section 8.3).

Every page reads the catalog of every open market. The order ticket also reads the venues'
listings and order books for the one pair it prices, from where the catalog was read (D78). The
pages only present what the catalog, matcher and router decide; they add no matching or routing
logic and name venues only from each market's `venue` field.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import parse_qs

from equinox import catalog
from equinox.catalog.background import Status
from equinox.models import EquivalenceCluster
from equinox.reader import pricing
from equinox.sources import FIXTURES, LiveFetchers, Settings, ensure_books, snapshot_names
from equinox.web import event, home, matches, ticket, words
from equinox.web.shell import Context

ROUTES = {
    "/": home.page,
    "/index.html": home.page,
    "/event": event.page,
    "/bet": ticket.page,
    "/matches": matches.page,
}


class App:
    def __init__(
        self,
        settings: Settings,
        *,
        live_fetcher: LiveFetchers | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        refresher=None,
    ) -> None:
        """`refresher` keeps the catalog fresh (`catalog.background.Refresher`); without one,
        the catalog is refreshed from the command line."""
        self.settings = settings
        self.refresher = refresher
        self.live_fetcher = live_fetcher
        self._clock = clock

    def respond(self, path: str, query: str) -> str | None:
        """The page for a GET request, or None for a path the app doesn't serve."""
        page = ROUTES.get(path)
        if page is None:
            return None
        params = {k: v[-1] for k, v in parse_qs(query, keep_blank_values=True).items()}
        found, now = self._catalog(), self._clock()
        status = self.refresher.status() if self.refresher else Status()
        ctx = Context(
            found,
            now,
            self.settings.stale_after,
            _fresh(found, now, status),
            self._pricer(found),
            status=status,
            can_refresh=self.refresher is not None,
            updating=_updating(found, now, status),
            age=max((now - found.summary.refreshed_at).total_seconds(), 0) if found else 0.0,
        )
        return page(ctx, params)

    def refresh(self) -> bool:
        """Ask for a refresh now; False when this app has no refresher."""
        if self.refresher is None:
            return False
        self.refresher.request()
        return True

    def _catalog(self) -> catalog.Catalog | None:
        """The newest catalog, or None when there is none or it can't be read."""
        try:
            return catalog.load_latest(self.settings.cache_dir)
        except catalog.CatalogError:
            return None

    def _pricer(self, found: catalog.Catalog | None) -> Callable[[str], EquivalenceCluster]:
        def price(market_id: str) -> EquivalenceCluster:
            if found is None:
                raise pricing.PricingError("there is no catalog")
            settings = self._read_from(found.summary.source)
            cluster, loaded = pricing.priced_group(found, market_id, settings, self.live_fetcher)
            return ensure_books(cluster, loaded)

        return price

    def _read_from(self, source: str) -> Settings:
        """Where the catalog was read: live, or a snapshot (D78). A catalog built from given
        markets, as in the tests, is priced from the app's own settings."""
        if source == "live":
            return replace(self.settings, source="live")
        if source in snapshot_names():
            return replace(self.settings, source="fixtures", snapshot=FIXTURES / source)
        return self.settings


def _updating(found: catalog.Catalog | None, now: datetime, status: Status) -> str:
    """While a refresh runs, the pages keep the markets they have and say so (D95)."""
    if found is None or not status.running:
        return ""
    old = words.age(max((now - found.summary.refreshed_at).total_seconds(), 0))
    return (
        f"Updating markets from both venues. You're seeing them as of {old} ago; the new "
        "ones appear when the update finishes, in about three minutes."
    )


def _fresh(found: catalog.Catalog | None, now: datetime, status: Status) -> str:
    """The top bar's line on the data: how old the prices are, and any refresh going on."""
    if found is None:
        return "Getting every open market…" if status.running else ""
    # Never less than none: a clock a little behind the catalog's isn't a catalog from the future.
    old = words.age(max((now - found.summary.refreshed_at).total_seconds(), 0))
    line = f"Prices as of the last refresh, {old} ago"
    if status.running:
        return f"Refreshing now. {line}"
    return f"{line}. The last refresh failed" if status.problem else line
