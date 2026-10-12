"""The All markets page: search every open market on both venues (feat-09; D48, D50).

It reads the saved catalog and never fetches anything. Each market shows its best asks from the
listing, its status, and its best match on another venue: the same bet, where the contract terms
match and the order page can price it; or unclear, where only the titles look alike, with the
reasons and the title score, never routed.
"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from equinox import catalog
from equinox.catalog import CatalogError
from equinox.matcher import confidence
from equinox.models import EquivalenceStatus, MatchResult
from equinox.models.catalog import NO_MATCH, SAME_BET, STATUSES, UNCLEAR, CatalogRow
from equinox.web import markets_html, pages, words
from equinox.web.markets_html import Match, Search

PER_PAGE = 50
STATUS_LABELS = {SAME_BET: "Same bet", UNCLEAR: "Unclear, never routed", NO_MATCH: "No match found"}


def page(cache_dir: Path, params: dict[str, str], data: str, now: datetime) -> str:
    try:
        found = catalog.load_latest(cache_dir)
    except CatalogError as error:
        return _framed(data, "The catalog can't be read.", markets_html.missing(str(error)))
    if found is None:
        missing = markets_html.missing(f"There is no catalog in {cache_dir} yet.")
        return _framed(data, "No catalog yet.", missing)
    search = Search(
        words=params.get("q", "").strip()[:200],
        venue=params.get("venue", "") if params.get("venue") in found.venues() else "",
        status=params.get("status", "") if params.get("status") in STATUSES else "",
        page=_page_number(params.get("page", "1")),
        venues=found.venues(),
        statuses=list(STATUS_LABELS.items()),
        data=data,
    )
    rows = found.search(search.words, search.venue, search.status, search.page, PER_PAGE)
    total = found.count(search.words, search.venue, search.status)
    summary = found.summary
    body = markets_html.body(
        search,
        [_cells(row) for row in rows],
        [_match(row, summary.source) for row in rows],
        total,
        PER_PAGE,
        _counts(summary.same_bet_groups, found.pair_counts()),
    )
    banner = (
        f"Catalog of every open market: {summary.describe(now)}. "
        f"Refresh it with {catalog.REFRESH_COMMAND}."
    )
    return _framed(data, banner, body)


def _framed(data: str, summary: str, body: str) -> str:
    banner = pages.Banner(summary, "/markets", data, ())
    return pages.layout("All markets", "/markets", data, banner, body)


def _cells(row: CatalogRow) -> list[str]:
    return [
        row.title,
        row.outcome_label if row.outcome_label and row.outcome_label not in row.title else "",
        row.event_title if row.event_title != row.title else "",
        row.market_id,
        words.venue(row.venue),
        _price(row.yes_ask),
        _price(row.no_ask),
        "Same bet, read by a model" if _model_read(row) else STATUS_LABELS[row.status],
    ]


def _match(row: CatalogRow, source: str) -> Match | None:
    """The row's best match on another venue, in words, or None. A same-bet match links to the
    order page on the catalog's own data source (live, or the same snapshot)."""
    if row.partner is None:
        return None
    venue = words.venue(row.partner.split(":", 1)[0])  # IDs read "<venue>:<native ID>"
    title = f"{row.partner_title} on {venue}"
    if _model_read(row):
        note = f"Confidence: Medium at most. The terms were read by {row.read_by} and checked."
        price = pages.href("/", outcome=f"catalog:{row.market_id}", data=source)
        return Match(title, note, row.reasons, price)
    if row.status == SAME_BET:  # by its market: Fed opens its usual outcome (D65)
        price = pages.href("/", outcome=f"catalog:{row.market_id}", data=source)
        note = "Same contract terms. Price an order to see the confidence and the rule differences."
        return Match(title, note, (), price)
    pair = MatchResult(
        market_a=row.market_id,
        market_b=row.partner,
        status=EquivalenceStatus.AMBIGUOUS,
        method="text",
        reasons=row.reasons,
        text_score=row.score,
    )
    level = confidence(pair)
    return Match(title, f"Confidence: {level.level}. {level.reason}", row.reasons, None)


def _counts(same_bet_groups: int, pairs: dict[tuple[str, bool], int]) -> str:
    """`pairs`: how many pairs have each status, split by whether a model read them."""
    read = pairs.get((SAME_BET, True), 0)
    unclear = sum(n for (status, _), n in pairs.items() if status == UNCLEAR)
    return (
        f"{same_bet_groups:,} outcomes are the same bet on two venues by their contract terms "
        f"and can be priced. {read:,} {'outcome is' if read == 1 else 'outcomes are'} the same "
        "bet as read by a model, checked against both venues' texts. "
        f"{unclear:,} pairs of markets have similar titles but no terms that decide them: they "
        "are shown as unclear and never routed. Every other market has no match found."
    )


def _model_read(row: CatalogRow) -> bool:
    """A same bet whose terms a model read: shown apart from one the parsers' terms decided."""
    return row.status == SAME_BET and row.read_by is not None


def _page_number(text: str) -> int:
    return int(text) if text.isdigit() and int(text) > 0 else 1


def _price(ask: Decimal | None) -> str:
    return words.cents(ask) if ask is not None else "–"
