"""Plain words for the pages: event and outcome names, rules, prices and reasons.

Everything here is written from the canonical model and keyed by measure, never by venue, so a
new venue needs no change. Venue names come only from each market's `venue` field.
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from equinox.models import (
    CanonicalMarket,
    ContractTerms,
    EquivalenceStatus,
    OrderRequest,
    QuoteReason,
    VenueQuote,
)
from equinox.router.rationale import contracts

FED_CHANGE = "fed_upper_bound_change"
COMPARISONS = {
    "gt": "above",
    "ge": "at or above",
    "lt": "below",
    "le": "at or below",
    "eq": "exactly",
    "between": "between",
}
MEASURED_BY = {
    "fomc_statement": "The FOMC statement",
    "pyth_regular_close": "Pyth's regular-session closing price",
    "official_close": "The exchange's official closing price",
}
VERDICTS = {
    EquivalenceStatus.EQUIVALENT: "Same bet",
    EquivalenceStatus.AMBIGUOUS: "Unclear",
    EquivalenceStatus.DISTINCT: "Different",
}
UNITS = {"bps": "bps", "usd": "USD"}


def venue(name: str) -> str:
    return name.capitalize()


def number(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def day(value: date) -> str:
    return f"{value:%B} {value.day}, {value.year}"


def moment(value: datetime | None) -> str:
    return f"{value:%Y-%m-%d %H:%M} UTC" if value else "Not stated"


def cents(price: Decimal) -> str:
    return f"{number((price * 100).quantize(Decimal('0.01'), ROUND_HALF_UP))}¢"


def event_name(terms: ContractTerms) -> str:
    if terms.measure == FED_CHANGE:
        return f"Fed rate decision, {day(terms.observed_on)}"
    return f"{terms.subject} {terms.measure.replace('_', ' ')}, {day(terms.observed_on)}"


def outcome_name(terms: ContractTerms) -> str:
    """ "No change", "Cut 25 bps", "Hike 50 bps or more"; otherwise the terms in words."""
    move = _fed_move(terms)
    if move is None:
        return f"{terms.subject} {terms.measure.replace('_', ' ')} {_bound(terms)}"
    direction, size, how = move
    verb = "Cut" if direction == "cut" else "Hike"
    return {
        "unchanged": "No change",
        "exactly": f"{verb} {size} bps",
        "or more": f"{verb} {size} bps or more",
        "more than": f"{verb} more than {size} bps",
    }[how]


def pays_if(terms: ContractTerms) -> str:
    """When YES pays, as the end of the sentence "Pays YES if ..."."""
    move = _fed_move(terms)
    if move is None:
        return f"the {terms.measure.replace('_', ' ')} is {_bound(terms)}"
    direction, size, how = move
    if how == "unchanged":
        return "the Fed leaves its target rate unchanged"
    verb = "cuts" if direction == "cut" else "raises"
    amount = {"exactly": f"by exactly {size} bps", "or more": f"by {size} bps or more"}
    return f"the Fed {verb} its target rate {amount.get(how, f'by more than {size} bps')}"


def _fed_move(terms: ContractTerms) -> tuple[str, str, str] | None:
    """A Fed-change market read as a move: (cut or hike, size, how), or None if it isn't one."""
    t, comparison = terms.threshold, terms.comparison
    if terms.measure != FED_CHANGE or comparison == "between":
        return None
    direction, size = ("cut" if t < 0 else "hike"), number(abs(t))
    if comparison == "eq":
        return direction, size, "unchanged" if t == 0 else "exactly"
    if t == 0 or (comparison in ("le", "lt")) != (t < 0):
        return None  # e.g. "at or below +25": not a single move, so say it in plain terms
    return direction, size, "or more" if comparison in ("le", "ge") else "more than"


def measured_by(terms: ContractTerms) -> str:
    return MEASURED_BY.get(terms.measured_by, terms.measured_by.replace("_", " ").capitalize())


def observed(terms: ContractTerms) -> str:
    stated = f" at {terms.observed_at:%H:%M} UTC" if terms.observed_at else ""
    return f"{day(terms.observed_on)}{stated}"


def edge_cases(terms: ContractTerms) -> str:
    return " ".join(terms.fallback_rules) or "None stated"


def fills(quote: VenueQuote) -> str:
    if not quote.fills:
        return "None for sale"
    return ", ".join(f"{contracts(f.quantity)} at {cents(f.price)}" for f in quote.fills)


def why_not(quote: VenueQuote, market: CanonicalMarket, order: OrderRequest, budget: str) -> str:
    """The reasons a venue can't take the order, in words. Empty when it can."""
    words = {
        QuoteReason.NOT_TRADABLE: "the market isn't open for trading now",
        QuoteReason.TEST_MONEY: f"it settles in {market.collateral.asset}, which has no value",
        QuoteReason.EMPTY_BOOK: f"nobody is selling {order.outcome}",
        QuoteReason.PARTIAL_FILL: (
            f"only {contracts(quote.filled_quantity)} of {contracts(order.quantity)} "
            "contracts are for sale"
        ),
        QuoteReason.OVER_BUDGET: f"it costs more than the {budget} budget",
    }
    reasons = list(quote.reasons)
    if QuoteReason.EMPTY_BOOK in reasons and QuoteReason.PARTIAL_FILL in reasons:
        reasons.remove(QuoteReason.PARTIAL_FILL)  # an empty book says it already
    return "; ".join(words[reason] for reason in reasons)


def _bound(terms: ContractTerms) -> str:
    unit = UNITS.get(terms.unit, terms.unit)
    if terms.comparison == "between":
        return f"between {number(terms.threshold)} and {number(terms.upper)} {unit}"
    return f"{COMPARISONS[terms.comparison]} {number(terms.threshold)} {unit}"
