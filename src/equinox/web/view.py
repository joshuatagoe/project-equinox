"""The data every page shares: the loaded markets, their clusters, and each outcome's name."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from equinox.matcher import build_clusters
from equinox.models import CanonicalMarket, ContractTerms, EquivalenceCluster
from equinox.sources import Loaded, ensure_books
from equinox.web import pages, words

INCLUSIVE = ("eq", "le", "ge", "between")


@dataclass(frozen=True)
class Outcome:
    """One cluster, named for people."""

    cluster: EquivalenceCluster
    event: str
    name: str

    @property
    def key(self) -> str:
        return self.cluster.cluster_id


@dataclass
class View:
    """Everything one data source gives the pages, loaded once and shared."""

    source: str
    loaded: Loaded
    clusters: list[EquivalenceCluster]
    outcomes: list[Outcome]
    read_at: datetime
    param: str = ""  # the `data` query value that keeps links on this source ("" for the default)
    booked: dict[str, EquivalenceCluster] = field(default_factory=dict)  # books fetched so far

    @property
    def markets(self) -> dict[str, CanonicalMarket]:
        return {m.market_id: m for m in self.loaded.markets}


@dataclass(frozen=True)
class PageContext:
    """What a page needs besides the data: the time, the staleness limit and the banner."""

    now: datetime
    stale_after: timedelta
    banner: pages.Banner


def build_view(source: str, loaded: Loaded, read_at: datetime, param: str = "") -> View:
    clusters = build_clusters(loaded.markets)
    return View(source, loaded, clusters, _outcomes(clusters), read_at, param)


def with_books(view: View, cluster: EquivalenceCluster) -> EquivalenceCluster:
    """The cluster with its order books, fetched once per view (D49). Raises FetchError."""
    if cluster.cluster_id not in view.booked:
        view.booked[cluster.cluster_id] = ensure_books(cluster, view.loaded)
    return view.booked[cluster.cluster_id]


def find(view: View, key: str) -> Outcome | None:
    return next((o for o in view.outcomes if o.key == key), None)


def choices(view: View) -> list[pages.Choice]:
    return [pages.Choice(o.key, o.name, o.event) for o in view.outcomes]


def favorite(view: View) -> str:
    """The outcome the markets think most likely: the highest price to buy YES."""

    def best_yes(outcome: Outcome) -> Decimal:
        asks = [m.best_asks.get("YES") or Decimal(0) for m in outcome.cluster.markets]
        return max(asks, default=Decimal(0))

    return max(view.outcomes, key=best_yes).key if view.outcomes else ""


def data_param(view: View) -> str:
    """The `data` query value that keeps a link on the same data source."""
    return view.param


def _outcomes(clusters: list[EquivalenceCluster]) -> list[Outcome]:
    named = []
    for cluster in clusters:
        terms = _representative(cluster)
        sort = (terms.observed_on, terms.subject, terms.measure, terms.threshold, terms.comparison)
        named.append((sort, Outcome(cluster, words.event_name(terms), words.outcome_name(terms))))
    return [outcome for _, outcome in sorted(named, key=lambda pair: pair[0])]


def _representative(cluster: EquivalenceCluster) -> ContractTerms:
    """The member whose terms read most simply: "50 bps or more" rather than "more than 25"."""
    members = sorted(
        cluster.markets, key=lambda m: (m.terms.comparison not in INCLUSIVE, m.market_id)
    )
    return members[0].terms
