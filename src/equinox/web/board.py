"""The market board (Jordan): every outcome, both venues side by side, and the best venue."""

from decimal import Decimal

from equinox.adapters.base import FetchError
from equinox.matcher import cluster_confidence
from equinox.models import CanonicalMarket, EquinoxTrace, OrderRequest, RoutingStatus
from equinox.router import simulate
from equinox.router.rationale import CENT, dollars
from equinox.web import pages, words
from equinox.web.view import Outcome, PageContext, View, data_param, with_books

BOARD_ORDER = Decimal(100)


def page(view: View, params: dict[str, str], ctx: PageContext) -> str:
    tables: dict[str, pages.Table] = {}
    for outcome in view.outcomes:
        venues = _event_venues(view, outcome.event)
        if outcome.event not in tables:
            tables[outcome.event] = pages.Table(outcome.event, _columns(venues), [], [])
        tables[outcome.event].rows.append(_row(view, outcome, venues, ctx))
        tables[outcome.event].links.append(
            pages.href("/", outcome=outcome.key, data=data_param(view))
        )
    termless = [
        f"{words.venue(m.venue)}: {m.title}" for m in view.loaded.markets if m.terms is None
    ]
    body = pages.board_body(list(tables.values()), termless, view.source)
    return pages.layout("Market board", "/board", view.source, ctx.banner, body)


def _columns(venues: list[str]) -> list[str]:
    columns = ["Outcome"]
    for venue in venues:
        columns += [f"{words.venue(venue)} YES", f"{words.venue(venue)} NO"]
    return columns + ["Same bet?", "Best for 100 YES", "Best for 100 NO"]


def _row(view: View, outcome: Outcome, venues: list[str], ctx: PageContext) -> list[str]:
    """The outcome's name, each venue's prices, the match, and the best venue each way.

    Only a group listed on more than one venue has its books fetched; one alone has nothing to
    compare (D49)."""
    members = {m.venue: m for m in outcome.cluster.markets}
    cells = [outcome.name]
    for venue in venues:
        market = members.get(venue)
        cells += [_ask(market, "YES"), _ask(market, "NO")] if market else ["Not listed"] * 2
    if not outcome.cluster.pairs:
        return [*cells, f"Only on {words.venue(outcome.cluster.markets[0].venue)}", "–", "–"]
    cells.append(f"Yes ({cluster_confidence(outcome.cluster).level} confidence)")
    try:
        cluster = with_books(view, outcome.cluster)
    except FetchError:
        return [*cells, "Books unavailable", "Books unavailable"]
    for side in ("YES", "NO"):
        order = OrderRequest(
            market_id=cluster.markets[0].market_id, outcome=side, quantity=BOARD_ORDER
        )
        cells.append(_best(simulate(order, cluster, ctx.now, ctx.stale_after)))
    return cells


def _event_venues(view: View, event: str) -> list[str]:
    return sorted({m.venue for o in view.outcomes if o.event == event for m in o.cluster.markets})


def _best(trace: EquinoxTrace) -> str:
    if trace.status != RoutingStatus.ROUTED:
        return "No venue can fill it"
    winner = next(q for q in trace.quotes if q.market_id == trace.decision.winner)
    return f"{words.venue(winner.venue)} {dollars(winner.total_cost, CENT)}"


def _ask(market: CanonicalMarket, side: str) -> str:
    price = market.best_asks.get(side)
    return words.cents(price) if price is not None else "–"
