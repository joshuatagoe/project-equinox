"""Markets, the home page (Jordan): every event both venues list, by topic, and a search (D86).

A card is one event: its topic, when it closes, its likeliest outcomes with what YES costs on each
venue, and how many outcomes both venues list. It opens the event's page.
"""

from html import escape

from equinox.catalog import REFRESH_COMMAND
from equinox.catalog.events import Event, events, topics
from equinox.models.catalog import CatalogRow
from equinox.web import shell, words
from equinox.web.shell import Context, href

PER_PAGE = 24
SHOWN = 3  # outcomes on a card
LEAD = (
    "Bets listed on both venues, with what one YES share costs on each. A YES share pays $1 if the "
    "outcome happens. Pick a bet to see every outcome and price an order."
)


def page(ctx: Context, params: dict[str, str]) -> str:
    asked = params.get("q", "").strip()[:200]
    if ctx.found is None:
        return no_catalog(ctx, asked)
    topic = "" if asked else params.get("topic", "")
    found = events(ctx.found, asked, topic)
    number = page_number(params.get("page", "1"))
    shown = found[(number - 1) * PER_PAGE : number * PER_PAGE]
    if asked:
        heading = f"<h1>Bets matching “{escape(asked)}”</h1>"
        chips = ""
    else:
        heading = f"<h1>Markets</h1><p class='lead'>{escape(LEAD)}</p>"
        chips = _chips(topics(ctx.found), topic)  # every topic, Other too (D97)
    cards = "".join(card(event, ctx) for event in shown)
    listing = f'<div class="grid">{cards}</div>' if cards else shell.empty(_none(asked, topic))
    pager = _pager(len(found), number, asked, topic)
    again = 30 if ctx.updating else 0  # until the new markets are in (D95)
    return shell.layout(
        "Markets", heading + chips + listing + pager, ctx, words=asked, reload=again
    )


def card(event: Event, ctx: Context) -> str:
    lines = "".join(_line(row) for row in event.outcomes[:SHOWN])
    count = len(event.outcomes)
    closes = f"<span>Closes {words.when(event.closes_at)}</span>" if event.closes_at else ""
    return (
        f'<a class="card" href="{escape(href("/event", m=event.key))}">'
        f'<div class="meta"><span class="tag">{escape(event.topic)}</span>{closes}</div>'
        f"<h3>{escape(event.title)}</h3>{lines}"
        f'<span class="more">{count} outcome{"" if count == 1 else "s"} on both venues →</span>'
        "</a>"
    )


BUILDING = (
    "Getting every open market from both venues. This takes about three minutes; the page "
    "updates itself."
)
DOWN = (
    "The venues can't be reached right now, so there are no markets to show. Equinox tries "
    "again every minute; press Refresh to try now."
)


def no_catalog(ctx: Context, words: str = "") -> str:
    """The page before there is a catalog: being built, the venues down, or how to build one."""
    if ctx.status.running:
        return shell.layout("Markets", f"<h1>Markets</h1>{shell.empty(BUILDING)}", ctx, reload=15)
    if ctx.status.problem:
        detail = f"<p class='muted small'>{escape(ctx.status.problem)}</p>"
        return shell.layout("Markets", f"<h1>Markets</h1>{shell.empty(DOWN)}{detail}", ctx)
    command = shell.empty(
        "No markets yet. Equinox reads every open market on both venues into a catalog, "
        f"which takes about three minutes: run {REFRESH_COMMAND}."
    )
    return shell.layout("Markets", f"<h1>Markets</h1>{command}", ctx, words=words)


def _line(row: CatalogRow) -> str:
    return (
        f'<div class="line"><span class="name">{escape(words.outcome(row))}</span>'
        f'<span class="prices">{prices(row)}</span></div>'
    )


def prices(row: CatalogRow, side: str = "YES") -> str:
    """What one share costs on each venue, the cheaper one marked, in the row's venue order."""
    other = row.partner.split(":", 1)[0] if row.partner else ""  # IDs read "<venue>:<native>"
    asks = [(row.venue, row.yes_ask if side == "YES" else row.no_ask)]
    asks.append((other, row.partner_yes if side == "YES" else row.partner_no))
    known = [ask for _, ask in asks if ask is not None]
    best = min(known) if len(known) == 2 and known[0] != known[1] else None
    return "".join(
        f'<span class="pill{" best" if ask is not None and ask == best else ""}">'
        f"{escape(words.venue(venue))} <b>{words.cents(ask) if ask is not None else '–'}</b></span>"
        for venue, ask in asks
    )


def _chips(counts: dict[str, int], chosen: str) -> str:
    total = sum(counts.values())
    links = [f'<a href="/"{" class=on" if not chosen else ""}>All<span>{total}</span></a>']
    links += [
        f'<a href="{escape(href("/", topic=name))}"{" class=on" if name == chosen else ""}>'
        f"{escape(name)}<span>{n}</span></a>"
        for name, n in counts.items()
    ]
    return f'<nav class="chips" aria-label="Topics">{"".join(links)}</nav>'


def _none(asked: str, topic: str) -> str:
    if asked:
        return (
            f"No bet on both venues matches “{asked}”. Equinox lists only bets it has matched on "
            "both venues; try fewer or other words."
        )
    return f"No events in {topic} right now." if topic else "No bets on both venues right now."


def _pager(total: int, number: int, asked: str, topic: str) -> str:
    last = max((total + PER_PAGE - 1) // PER_PAGE, 1)
    if last == 1:
        return ""

    def link(to: int, text: str) -> str:
        return f'<a href="{escape(href("/", q=asked, topic=topic, page=str(to)))}">{text}</a>'

    back = link(number - 1, "← Previous") if number > 1 else ""
    ahead = link(number + 1, "Next →") if number < last else ""
    return f'<p class="pager">{back}<span class="muted">Page {number} of {last}</span>{ahead}</p>'


def page_number(text: str) -> int:
    return int(text) if text.isdigit() and int(text) > 0 else 1
