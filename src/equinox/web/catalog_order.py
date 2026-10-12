"""Pricing a same bet from the catalog, from the All markets page (D58, D65).

The app sends the order page's requests here when the outcome key starts with `catalog:` and the
market isn't in a loaded family. The group comes from the catalog through `reader.pricing`: a
parser's pair as it is, a model's only while the committed evals allow routing model-read pairs.
The books are fetched for this group only, and the result is rendered exactly as the order page
renders a loaded outcome.
"""

from equinox.adapters.base import FetchError
from equinox.models import CanonicalMarket, OrderRequest
from equinox.reader.pricing import PricingError
from equinox.router import simulate
from equinox.sources import ensure_books
from equinox.web import order, pages
from equinox.web.view import Outcome, PageContext, View, data_param

CATALOG = "catalog:"
GROUP = "From the catalog of every open market"


def page(view: View, params: dict[str, str], ctx: PageContext) -> str:
    key = params["outcome"]
    market_id = key.removeprefix(CATALOG)
    form = pages.OrderForm(
        choices=[pages.Choice(key, market_id, GROUP)],  # named once the venue is read
        outcome=key,
        side=params.get("side", "YES").strip().upper(),
        quantity=params.get("quantity", "100").strip(),
        budget=params.get("budget", "").strip(),
        data=data_param(view),
    )
    quantity = order.amount(form.quantity)
    budget = order.amount(form.budget) if form.budget else None
    form.errors = order.form_errors(form, True, quantity, budget)
    result = None
    if not form.errors:
        try:
            cluster, loaded = ctx.price_catalog(market_id)
            cluster = ensure_books(cluster, loaded)
        except (PricingError, FetchError) as error:
            form.errors = [f"This pair can't be priced: {error}"]
    if not form.errors:
        request = OrderRequest(
            market_id=market_id, outcome=form.side, quantity=quantity, max_budget=budget
        )
        trace = simulate(request, cluster, ctx.now, ctx.stale_after)
        markets = {m.market_id: m for m in cluster.markets}
        name = _named(markets[market_id])
        form.choices = [pages.Choice(key, name, GROUP)]
        found = pages.href("/markets", q=markets[market_id].title, data=data_param(view))
        result = order.result(Outcome(cluster, GROUP, name), trace, markets, found)
    body = pages.order_body(form, result, empty=False)
    return pages.layout("Price an order", "/", view.source, ctx.banner, body)


def _named(market: CanonicalMarket) -> str:
    """The market as the All markets page names it: its title, and its outcome when the title
    doesn't say it ("Who will win the Ballon d'Or in 2026? (Kylian Mbappe)")."""
    label = market.outcome_label
    return f"{market.title} ({label})" if label and label not in market.title else market.title
