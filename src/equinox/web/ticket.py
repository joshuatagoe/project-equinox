"""The order ticket (Jordan): price an order for one outcome on both venues (feat-14, D86).

The answer comes first: which venue to buy on and what it costs. Then the cost on each venue, why,
the notes on the data, and beside it the panel that says whether it's really the same bet. The
pair is priced from the venues' listings and order books for this outcome only (D58, D65).
"""

from html import escape

from equinox.adapters.base import FetchError
from equinox.catalog.events import event_of
from equinox.models import OrderRequest
from equinox.reader.pricing import PricingError
from equinox.router import simulate
from equinox.web import event, home, order, same_bet, shell, words
from equinox.web.shell import Context, href

DOWN = "The venues can't be reached right now, so this order can't be priced."


def page(ctx: Context, params: dict[str, str]) -> str:
    if ctx.found is None:
        return shell.layout("Order", home.missing(), ctx)
    market = params.get("m", "")
    found = event_of(ctx.found, market)
    if found is None:
        return shell.layout("Not found", f"<h1>Not found</h1>{shell.empty(event.NOT_LISTED)}", ctx)
    row = next(o for o in found.outcomes if market in (o.market_id, o.partner))
    side = params.get("side", "YES").strip().upper()
    quantity_text = params.get("quantity", "100").strip()
    budget_text = params.get("budget", "").strip()
    quantity = order.amount(quantity_text)
    budget = order.amount(budget_text) if budget_text else None
    errors = order.form_errors(side, quantity, budget_text, budget)
    cluster, answer = None, ""
    if not errors:
        try:
            cluster = ctx.price(market)
        except (PricingError, FetchError) as error:
            answer = _not_priced(error)
    if cluster is not None:
        request = OrderRequest(market_id=market, outcome=side, quantity=quantity, max_budget=budget)
        answer = _answer(
            order.result(cluster, simulate(request, cluster, ctx.now, ctx.stale_after))
        )
    form = _form(market, side, quantity_text, budget_text)
    problems = "".join(f"<p class='errors'>{escape(e)}</p>" for e in errors)
    header = (
        f'<div class="crumbs"><a href="/">Markets</a> / '
        f'<a href="{escape(href("/event", m=found.key))}">{escape(found.title)}</a></div>'
        f"<h1>{escape(words.outcome(row))}</h1>"
        f"<p class='lead'>{escape(words.yes_pays(row.terms_key, row.event_title))}</p>"
    )
    left = f'<section class="panel">{form}<div id="result">{problems}{answer}</div></section>'
    aside = f"<aside>{same_bet.panel(row, cluster)}</aside>"
    body = f'{header}<div class="ticket"><div>{left}</div>{aside}</div>'
    return shell.layout(words.outcome(row), body, ctx)


def _form(market: str, side: str, quantity: str, budget: str) -> str:
    sides = "".join(
        f'<label><input type="radio" name="side" value="{s}"{" checked" if side == s else ""}>'
        f'<span class="{s[0].lower()}">Buy {s}</span></label>'
        for s in ("YES", "NO")
    )
    return f"""<form class="order" method="get" action="/bet" data-live>
<input type="hidden" name="m" value="{escape(market)}">
<label>Order<span class="seg">{sides}</span></label>
<label>Contracts<input name="quantity" value="{escape(quantity)}" inputmode="decimal"></label>
<label>Budget, optional ($)
<input name="budget" value="{escape(budget)}" inputmode="decimal"></label>
<button class="btn" type="submit">Price my order</button>
</form>"""


def _answer(r: order.Result) -> str:
    rows = [[escape(cell) for cell in row] for row in r.rows]
    costs = shell.table(order.COLUMNS, rows, out=r.excluded, numeric={3, 4, 5})
    warnings = "".join(f"<li>{escape(w)}</li>" for w in r.warnings)
    assumptions = "".join(f"<li>{escape(a)}</li>" for a in r.assumptions)
    return (
        f'<p class="answer{"" if r.routed else " no"}">{escape(r.headline)}</p>'
        f"<h2>Cost on each venue</h2>{costs}"
        f"<h2 style='margin-top:16px'>Why</h2><p>{escape(r.rationale)}</p>"
        + (f"<h2>About the prices</h2><ul class='notes'>{warnings}</ul>" if warnings else "")
        + f"<details><summary>Assumptions behind every price</summary>"
        f"<ul class='notes'>{assumptions}</ul></details>"
    )


def _not_priced(error: Exception) -> str:
    if isinstance(error, FetchError) or isinstance(error.__cause__, FetchError):
        return f'<p class="answer down">{escape(DOWN)}</p><p class="muted">{escape(str(error))}</p>'
    return f'<p class="answer down">{escape(f"This bet can't be priced: {error}")}</p>'
