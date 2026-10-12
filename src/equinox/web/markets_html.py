"""HTML for the All markets page. Every string passed in is escaped here, as in `pages.py`."""

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

from equinox.catalog import REFRESH_COMMAND
from equinox.web.pages import href

MEANINGS = (
    "High confidence: both venues' terms, rules and sources agree.",
    "Medium confidence: the same bet, but a source or a rule for rare events differs, or a model "
    "read the terms.",
    "Looks alike, not checked: only the titles are similar, so Equinox never prices it.",
)


@dataclass
class Search:
    words: str
    venue: str
    status: str
    page: int
    venues: Sequence[str]
    statuses: Sequence[tuple[str, str]]  # (value, label)
    data: str  # the data source the other pages are on
    landing: bool = False  # opened with no search: the same bets you can price


@dataclass
class Bet:
    """One row: a market, or a same bet shown once for both venues (feat-13)."""

    title: str
    label: str  # the outcome, when the title doesn't say it
    event: str
    market_id: str
    pays: str  # what a share of YES pays, for a same bet
    prices: Sequence[tuple[str, str, str]]  # (venue, YES, NO), this market's venue first
    status: str
    note: str  # how it matched, how sure, or why it isn't priced
    reasons: Sequence[str]
    price: str | None  # the comparison's link, for a same bet
    partner: str  # "on <venue>: <title>", the matching market


def body(search: Search, bets: Sequence[Bet], total: int, per_page: int, counts: str) -> str:
    intro = (
        "<h1>All markets</h1><p class='muted'>Every open market on both venues. Two markets are "
        "the same bet only when their contract terms match; titles that look alike are never "
        f"enough to route an order. {escape(counts)}</p>"
    )
    legend = "<ul class='muted'>" + "".join(f"<li>{escape(m)}</li>" for m in MEANINGS) + "</ul>"
    landing = (
        "<p>Showing the same bets you can price. Choose another status to see markets that only "
        "look alike, or that have no match.</p>"
        if search.landing
        else ""
    )
    first = (search.page - 1) * per_page + 1
    shown = (
        f"<p>Markets {first:,}–{first + len(bets) - 1:,} of {total:,}.</p>"
        "<p class='muted'>Cost to buy one share now; – means no one is selling.</p>"
        if bets
        else "<p>No market matches that search.</p>"
    )
    rows = "".join(_bet(bet) for bet in bets)
    pager = _pager(search, total, per_page)
    return f"{intro}{legend}{_form(search)}{landing}{shown}{rows}{pager}"


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


def _bet(bet: Bet) -> str:
    parts = [f"<strong>{escape(bet.title)}</strong>"]
    if bet.label:
        parts.append(f" ({escape(bet.label)})")
    if bet.event:
        parts.append(f"<br><span class='muted'>In: {escape(bet.event)}</span>")
    if bet.pays:
        parts.append(f"<br>{escape(bet.pays)}")
    prices = "".join(
        f"<tr><td>{escape(venue)}</td><td>YES {escape(yes)}</td><td>NO {escape(no)}</td></tr>"
        for venue, yes, no in bet.prices
    )
    parts.append(f"<table class='prices'>{prices}</table>")
    parts.append(f"<strong>{escape(bet.status)}</strong>")
    if bet.partner:
        parts.append(f" {escape(bet.partner)}")
    parts.append(f"<br><span class='muted'>{escape(bet.note)}</span>")
    if bet.reasons:  # the evidence, one click away so the row stays short
        shown = "How it matched" if bet.price else "Why the titles look alike"
        listed = "".join(f"<li>{escape(r)}</li>" for r in bet.reasons)
        parts.append(f"<details><summary>{shown}</summary><ul>{listed}</ul></details>")
    if bet.price:
        parts.append(
            f'<br><a class="button" href="{escape(bet.price)}">Compare the cost on both venues</a>'
        )
    parts.append(f"<br><span class='muted'>{escape(bet.market_id)}</span>")
    return f'<div class="bet">{"".join(parts)}</div>'


def _form(search: Search) -> str:
    venues = _options([("", "Every venue"), *((v, v.capitalize()) for v in search.venues)])
    statuses = _options(search.statuses)
    return f"""<form class="order" method="get" action="/markets">
<label>Words in the title<input name="q" value="{escape(search.words)}"></label>
<label>Venue<select name="venue">{venues(search.venue)}</select></label>
<label>Show<select name="status">{statuses(search.status)}</select></label>
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
