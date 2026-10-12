"""The All markets page: search every open market on both venues (feat-09; D48, D50; feat-13).

It reads the saved catalog and never fetches anything. It opens on the same bets that can be
priced, each shown once with both venues' prices, what YES pays and how the match was made; a
search covers every market. A market whose title only looks like another's says it is never
priced; one with no match says what was looked for.
"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from equinox import catalog
from equinox.catalog import CatalogError
from equinox.matcher import confidence
from equinox.matcher.index import WINDOW_DAYS
from equinox.models import EquivalenceStatus, MatchResult
from equinox.models.catalog import NO_MATCH, SAME_BET, STATUSES, UNCLEAR, CatalogRow
from equinox.web import markets_html, pages, words
from equinox.web.markets_html import Bet, Search

PER_PAGE = 50
EVERY = "all"  # the status filter's value for every market
STATUS_LABELS = {
    SAME_BET: "Same bets you can price",
    UNCLEAR: "Look alike, not checked",
    NO_MATCH: "No match found",
}


def page(cache_dir: Path, params: dict[str, str], data: str, now: datetime) -> str:
    try:
        found = catalog.load_latest(cache_dir)
    except CatalogError as error:
        return _framed(data, "The catalog can't be read.", markets_html.missing(str(error)))
    if found is None:
        missing = markets_html.missing(f"There is no catalog in {cache_dir} yet.")
        return _framed(data, "No catalog yet.", missing)
    words_given = params.get("q", "").strip()[:200]
    status = params.get("status", "")
    landing = not words_given and not status  # opens on the same bets you can price
    search = Search(
        words=words_given,
        venue=params.get("venue", "") if params.get("venue") in found.venues() else "",
        status=SAME_BET if landing else (status if status in STATUSES else EVERY),
        page=_page_number(params.get("page", "1")),
        venues=found.venues(),
        statuses=[(EVERY, "Every market"), *STATUS_LABELS.items()],
        data=data,
        landing=landing,
    )
    filtered = "" if search.status == EVERY else search.status
    once = not search.venue  # with a venue chosen, every market of it is its own row
    rows = found.search(search.words, search.venue, filtered, search.page, PER_PAGE, once)
    total = found.count(search.words, search.venue, filtered, once)
    summary = found.summary
    body = markets_html.body(
        search,
        [_bet(row, summary.source) for row in rows],
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


def _bet(row: CatalogRow, source: str) -> Bet:
    """One row: the market, its prices beside its match's, and the match in words."""
    other = row.partner.split(":", 1)[0] if row.partner else ""  # IDs read "<venue>:<native>"
    prices = [(words.venue(row.venue), _price(row.yes_ask), _price(row.no_ask))]
    if row.status == SAME_BET and other:
        prices.append((words.venue(other), _price(row.partner_yes), _price(row.partner_no)))
    status, note, reasons, price = _verdict(row, source)
    return Bet(
        title=row.title,
        label=row.outcome_label if row.outcome_label not in row.title else "",
        event=row.event_title if row.event_title != row.title else "",
        market_id=row.market_id,
        pays=words.yes_pays(row.terms_key, row.event_title) if row.status == SAME_BET else "",
        prices=prices,
        status=status,
        note=note,
        reasons=reasons,
        price=price,
        partner=f"on {words.venue(other)}: {row.partner_title}" if other else "",
    )


def _verdict(row: CatalogRow, source: str) -> tuple[str, str, tuple[str, ...], str | None]:
    """(status, the match in a sentence, its reasons, the comparison's link)."""
    if row.status == SAME_BET:
        price = pages.href("/", outcome=f"catalog:{row.market_id}", data=source)
        if row.read_by is not None:  # D57: shown apart from a match the parsers' terms decided
            note = (
                f"Confidence: Medium at most. The terms were read by {row.read_by} and checked "
                "against both venues' rules."
            )
            return "Same bet, read by a model", note, row.reasons, price
        note = (
            "Both venues' terms were matched exactly by Equinox's reader for this kind of market. "
            "Compare the cost to see the confidence and any rule differences."
        )
        return "Same bet", note, (), price
    if row.status == UNCLEAR:
        pair = MatchResult(
            market_a=row.market_id,
            market_b=row.partner,
            status=EquivalenceStatus.AMBIGUOUS,
            method="text",
            reasons=row.reasons,
            text_score=row.score,
        )
        note = (
            f"Unclear, never routed: only the titles look alike (title score {row.score}), so "
            f"it is never priced. Confidence: {confidence(pair).level}."
        )
        return "Looks alike, not checked", note, row.reasons, None
    note = (  # not "only on": a venue can date the same question a year later (feat-13)
        "No market on another venue has the same terms, or a similar title closing within "
        f"{WINDOW_DAYS} days of this one. Venues sometimes date the same question differently, "
        "so a match can be missed."
    )
    return "No match found", note, (), None


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


def _page_number(text: str) -> int:
    return int(text) if text.isdigit() and int(text) > 0 else 1


def _price(ask: Decimal | None) -> str:
    return words.cents(ask) if ask is not None else "–"
