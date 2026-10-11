"""HTML for the All markets page. Every string passed in is escaped here, as in `pages.py`."""

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

from equinox.catalog import REFRESH_COMMAND
from equinox.web.pages import href, html_table

COLUMNS = ("Market", "Venue", "YES ask", "NO ask", "Status", "Best match on another venue")


@dataclass
class Search:
    words: str
    venue: str
    status: str
    page: int
    venues: Sequence[str]
    statuses: Sequence[tuple[str, str]]  # (value, label)
    data: str  # the data source the other pages are on


@dataclass
class Match:
    title: str  # the other market, and its venue
    note: str  # the verdict and confidence in a sentence
    reasons: Sequence[str]  # why the titles look alike, for an unclear pair
    price: str | None  # the order page's link, for the same bet


def body(
    search: Search,
    cells: Sequence[Sequence[str]],
    matches: Sequence[Match | None],
    total: int,
    per_page: int,
    counts: str,
) -> str:
    """`cells` per row: title, outcome label, event title, market ID, venue, YES and NO ask,
    status. Blank label and event cells are left out."""
    intro = (
        "<h1>All markets</h1><p class='muted'>Every open market on both venues. Two markets are "
        "the same bet only when their contract terms match; titles that look alike are never "
        f"enough to route an order. {escape(counts)}</p>"
    )
    first = (search.page - 1) * per_page + 1
    shown = (
        f"<p>Markets {first:,}–{first + len(cells) - 1:,} of {total:,}.</p>"
        if cells
        else "<p>No market matches that search.</p>"
    )
    rows = [
        [_market(row), escape(row[4]), escape(row[5]), escape(row[6]), escape(row[7]), _match(m)]
        for row, m in zip(cells, matches, strict=True)
    ]
    table = html_table(COLUMNS, rows, raw=True, numeric={2, 3}) if rows else ""
    return f"{intro}{_form(search)}{shown}{table}{_pager(search, total, per_page)}"


def missing(problem: str) -> str:
    """The page when there is no catalog to show, with the command that builds one."""
    return (
        f"<h1>All markets</h1><p>{escape(problem)}</p><p>Build the catalog with "
        f"<code>{escape(REFRESH_COMMAND)}</code>. It reads every open market on both venues: "
        "about 290,000 markets, a 150 MB download that takes about three minutes and 400 MB of "
        "memory. Add "
        "<code>--source fixtures --snapshot snapshot-2026-10-11</code> to build it from that "
        "snapshot's small sample instead.</p>"
    )


def _form(search: Search) -> str:
    venues = _options([("", "Every venue"), *((v, v.capitalize()) for v in search.venues)])
    statuses = _options([("", "Any status"), *search.statuses])
    return f"""<form class="order" method="get" action="/markets">
<label>Words in the title<input name="q" value="{escape(search.words)}"></label>
<label>Venue<select name="venue">{venues(search.venue)}</select></label>
<label>Status<select name="status">{statuses(search.status)}</select></label>
<input type="hidden" name="data" value="{escape(search.data)}">
<button type="submit">Search</button></form>"""


def _options(choices: Sequence[tuple[str, str]]):
    def render(selected: str) -> str:
        return "".join(
            f'<option value="{escape(value)}"{" selected" if value == selected else ""}>'
            f"{escape(label)}</option>"
            for value, label in choices
        )

    return render


def _market(row: Sequence[str]) -> str:
    title, label, event, market_id = row[:4]
    parts = [escape(title)]
    if label:
        parts.append(f"<br>Outcome: {escape(label)}")
    if event:
        parts.append(f"<br><span class='muted'>In: {escape(event)}</span>")
    parts.append(f"<br><span class='muted'>{escape(market_id)}</span>")
    return "".join(parts)


def _match(match: Match | None) -> str:
    if match is None:
        return "–"
    parts = [escape(match.title), f"<br><span class='muted'>{escape(match.note)}</span>"]
    if match.reasons:
        parts.append("<ul>" + "".join(f"<li>{escape(r)}</li>" for r in match.reasons) + "</ul>")
    if match.price:
        parts.append(f'<br><a href="{escape(match.price)}">Price an order</a>')
    return "".join(parts)


def _pager(search: Search, total: int, per_page: int) -> str:
    last = max((total + per_page - 1) // per_page, 1)
    if last == 1:
        return ""

    def link(number: int, text: str) -> str:
        query = {"q": search.words, "venue": search.venue, "status": search.status}
        target = href("/markets", **query, page=str(number), data=search.data)
        return f'<a href="{escape(target)}">{escape(text)}</a>'

    previous = link(search.page - 1, "← Previous") if search.page > 1 else ""
    following = link(search.page + 1, "Next →") if search.page < last else ""
    return f"<p>{previous} Page {search.page:,} of {last:,} {following}</p>"
