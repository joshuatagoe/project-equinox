"""An event's page (Jordan): every outcome both venues list, with each venue's prices (D86).

Each outcome says what YES pays, how the two markets were matched, what YES and NO cost on each
venue, and has Buy YES and Buy NO buttons that open the order ticket.
"""

from html import escape

from equinox.catalog.events import Event, event_of
from equinox.models.catalog import CatalogRow
from equinox.web import home, shell, words
from equinox.web.shell import Context, href

NOT_LISTED = (
    "That isn't a bet both venues list. Equinox shows only bets it has matched on both venues; "
    "search for it from Markets."
)


def page(ctx: Context, params: dict[str, str]) -> str:
    if ctx.found is None:
        return shell.layout("Markets", home.missing(), ctx)
    event = event_of(ctx.found, params.get("m", ""))
    if event is None:
        return shell.layout("Not found", f"<h1>Not found</h1>{shell.empty(NOT_LISTED)}", ctx)
    return shell.layout(event.title, body(event), ctx)


def body(event: Event) -> str:
    count = len(event.outcomes)
    closes = f" Closes {words.when(event.closes_at)}." if event.closes_at else ""
    crumbs = (
        f'<div class="crumbs"><a href="/">Markets</a> / '
        f'<a href="{escape(href("/", topic=event.topic))}">{escape(event.topic)}</a></div>'
    )
    lead = (
        f"{count} outcome{'' if count == 1 else 's'} listed on both venues.{closes} A YES share "
        "pays $1 if the outcome happens and a NO share pays $1 if it doesn't. Prices are what one "
        "share costs on each venue, as of the last refresh; – means no one is selling."
    )
    legend = (
        "<p class='small muted'><span class='tag high'>Exact match</span> Equinox's own reader "
        "read both venues' terms. <span class='tag medium'>Read by a model</span> A model read "
        "them and Equinox checked the readings: Medium confidence at most.</p>"
    )
    rows = "".join(_row(row) for row in event.outcomes)
    return (
        f"{crumbs}<h1>{escape(event.title)}</h1><p class='lead'>{escape(lead)}</p>{legend}"
        f'<section class="panel">{rows}</section>'
    )


def _row(row: CatalogRow) -> str:
    other = row.partner.split(":", 1)[0] if row.partner else ""  # IDs read "<venue>:<native>"
    quotes = [(row.venue, row.yes_ask, row.no_ask), (other, row.partner_yes, row.partner_no)]
    pills = "".join(
        f'<span class="pill">{escape(words.venue(venue))} YES <b>{_cents(yes)}</b> · '
        f"NO <b>{_cents(no)}</b></span>"
        for venue, yes, no in quotes
    )
    buy = (
        '<span class="buys">'
        + "".join(
            f'<a class="btn {side.lower()}" '
            f'href="{escape(href("/bet", m=row.market_id, side=side))}">Buy {side}</a>'
            for side in ("YES", "NO")
        )
        + "</span>"
    )
    pays = words.yes_pays(row.terms_key, row.event_title)
    said = f'<div class="small">{escape(pays)}</div>' if pays != words.GENERIC else ""
    badge, style = words.badge(row)
    return (
        f'<div class="row"><div><div class="what">{escape(words.outcome(row))} '
        f'<span class="tag {style}">{badge}</span></div>{said}</div>'
        f'<div class="side">{pills}{buy}</div></div>'
    )


def _cents(price) -> str:
    return words.cents(price) if price is not None else "–"
