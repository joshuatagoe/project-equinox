"""The app's frame, what every page is given, and the HTML helpers (feat-14, D86, D89).

Every string from the venues or the person is escaped where a page writes it; these helpers take
text, except `table`, which takes cells a page has already escaped.
"""

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from urllib.parse import urlencode

from equinox.catalog.background import Status
from equinox.catalog.store import Catalog
from equinox.models import EquivalenceCluster
from equinox.web.script import SCRIPT
from equinox.web.style import CSS

NAV = (("/", "Markets"),)
BPS_NOTE = (
    "bps means basis points: 1 bp is 0.01 percentage point, so 25 bps is a quarter of a point."
)


@dataclass(frozen=True)
class Context:
    """What a page is given: the catalog, the time, and a way to price one pair."""

    found: Catalog | None  # the newest catalog; None when there is none yet
    now: datetime
    stale_after: timedelta
    fresh: str  # how old the catalog's prices are, for the top bar
    price: Callable[[str], EquivalenceCluster]
    """market ID -> its same bet with order books, from the venues; raises PricingError or
    FetchError (`reader.pricing`)."""
    status: Status = Status()  # the background refresh, when the server runs one
    can_refresh: bool = False


def href(path: str, **params: str) -> str:
    query = urlencode({k: v for k, v in params.items() if v})
    return f"{path}?{query}" if query else path


def layout(
    title: str, body: str, ctx: Context, *, active: str = "/", words: str = "", reload: int = 0
) -> str:
    """The page in the app's frame; `reload` seconds, when given, load it again."""
    nav = "".join(
        f'<a href="{path}"{" class=on" if path == active else ""}>{escape(label)}</a>'
        for path, label in NAV
    )
    fresh = _data_line(ctx)
    again = f'<meta http-equiv="refresh" content="{reload}">' if reload else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{again}
<title>{escape(title)} · Project Equinox</title>
<style>{CSS}</style>
</head>
<body>
<header class="top"><div class="in">
<a class="brand" href="/"><span class="mark" aria-hidden="true"></span>Equinox</a>
<nav>{nav}</nav>
<form class="find" method="get" action="/" role="search">
<input name="q" value="{escape(words)}" placeholder="Search bets on both venues"
 aria-label="Search bets on both venues"></form>{fresh}
</div></header>
<main>
{body}
<footer>Equinox compares what the same bet costs on each venue and simulates the order; it never
places one. Prices come from each venue's public listings and order books. {escape(BPS_NOTE)}
</footer>
</main>
<script>{SCRIPT}</script>
</body>
</html>
"""


def _data_line(ctx: Context) -> str:
    """The top bar's word on the data, and Refresh when the server keeps the catalog fresh."""
    line = f'<span class="fresh">{escape(ctx.fresh)}</span>' if ctx.fresh else ""
    if ctx.can_refresh and not ctx.status.running:
        line += (
            '<form class="refresh" method="post" action="/refresh">'
            '<button class="link" type="submit">Refresh</button></form>'
        )
    return line


def empty(message: str) -> str:
    return f'<p class="empty">{escape(message)}</p>'


def table(
    columns: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    out: Sequence[bool] = (),
    numeric: Collection[int] = (),
) -> str:
    """A table of cells the page has already escaped; `out` greys a row, `numeric` aligns."""
    head = "".join(
        f"<th{' class=num' if j in numeric else ''}>{escape(c)}</th>" for j, c in enumerate(columns)
    )
    body = "".join(
        f"<tr{' class=out' if i < len(out) and out[i] else ''}>"
        + "".join(
            f"<td{' class=num' if j in numeric else ''}>{cell}</td>" for j, cell in enumerate(row)
        )
        + "</tr>"
        for i, row in enumerate(rows)
    )
    grid = f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    return f'<div class="wrap">{grid}</div>'
