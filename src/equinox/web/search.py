"""Finding any same bet in the catalog by its words, from the order page (feat-13).

Jordan types "coventry 2-1" or "ballon d'or" and gets each same bet once, with the venues that list
it, linked to the comparison of its cost on both venues. A pair is shown once, not once per venue
market. Markets that only look alike are left to the All markets page.
"""

from dataclasses import dataclass
from html import escape

from equinox.catalog import REFRESH_COMMAND, Catalog
from equinox.models.catalog import SAME_BET, CatalogRow
from equinox.web import pages, words

LIMIT = 20  # same bets shown for one search


@dataclass(frozen=True)
class Found:
    name: str  # the market's question, with its outcome when the question doesn't say it
    venues: str  # the venues that list it, from the markets themselves: "A and B"
    market_id: str  # opened as a catalog outcome


@dataclass(frozen=True)
class Search:
    text: str
    found: tuple[Found, ...] = ()
    problem: str = ""  # instead of results: no catalog, or nothing matches
    source: str = ""  # where the catalog was read: its pairs are priced from there, not the page's


def search(catalog: Catalog | None, text: str) -> Search:
    """Each same bet whose titles hold every word, once per pair."""
    if catalog is None:
        return Search(text, problem=f"No catalog yet. Build one with {REFRESH_COMMAND}.")
    rows = catalog.search(text, status=SAME_BET, per_page=LIMIT * 4)
    found, seen = [], set()
    for row in rows:
        pair = frozenset((row.market_id, row.partner))
        if pair in seen:
            continue
        seen.add(pair)
        found.append(Found(_name(row), _venues(row), row.market_id))
    if not found:
        problem = f"No same bet on two venues matches “{text}”."
        return Search(text, problem=problem + " Markets that only look alike are on All markets.")
    origin = catalog.summary.source
    source = origin if origin == "live" or origin.startswith("snapshot-") else ""
    return Search(text, tuple(found[:LIMIT]), source=source)


def html(result: Search | None, data: str) -> str:
    """The search box, and its results when there are any."""
    value = escape(result.text) if result else ""
    hidden = f'<input type="hidden" name="data" value="{escape(data)}">' if data else ""
    box = (
        '<form class="find" method="get" action="/"><label>Find any bet on both venues '
        f'<input name="find" value="{value}" placeholder="coventry 2-1, ballon d\'or">'
        f'</label>{hidden} <button type="submit">Find</button></form>'
    )
    if result is None:
        return box
    if result.problem:
        return f'{box}<p class="muted">{escape(result.problem)}</p>'
    priced = result.source or data
    items = "".join(
        f'<li><a href="{escape(pages.href("/", outcome=f"catalog:{f.market_id}", data=priced))}">'
        f'{escape(f.name)}</a> <span class="muted">{escape(f.venues)}</span></li>'
        for f in result.found
    )
    return f'{box}<ul class="found">{items}</ul>'


def _name(row: CatalogRow) -> str:
    label = row.outcome_label
    return f"{row.title} ({label})" if label and label not in row.title else row.title


def _venues(row: CatalogRow) -> str:
    other = row.partner.split(":", 1)[0] if row.partner else ""
    return " and ".join(words.venue(v) for v in sorted({row.venue, other} - {""}))
