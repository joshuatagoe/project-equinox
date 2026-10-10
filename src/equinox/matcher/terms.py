"""Contract-terms rules for one pair of markets (architecture section 6.1; D8, D18, D20, D23).

The rules run in order, and the first that applies decides:

1. Either market has no terms: the text fallback decides, and it says AMBIGUOUS at most (D15).
2. Subject, measure, unit or observed_on differ, or both markets state an observation instant
   (observed_at) and the instants differ: DISTINCT, a different event (D23).
3. After normalizing on the measure's grid, the direction, threshold or upper bound differ:
   DISTINCT, a different outcome.
4. measured_by differs: AMBIGUOUS, the same outcome measured another way. It is never routed.
5. Only one market states an observation instant: AMBIGUOUS, since the other may observe at
   another time. It is never routed.
6. Otherwise EQUIVALENT, with a risk flag for each rule that still differs.

`evaluate_pair` compares terms only; it does not check that the markets are on two venues.
Venue names reach the text only through `market.venue`.
"""

from datetime import UTC
from decimal import Decimal
from typing import NamedTuple

from equinox.matcher.text import text_match
from equinox.models import CanonicalMarket, ContractTerms, EquivalenceStatus, MatchResult

MEASURE_GRIDS: dict[str, Decimal] = {"fed_upper_bound_change": Decimal(25)}
"""The step a measure moves in. On its grid, `lt t` is `le t - step` and `gt t` is `ge t + step`."""

DIRECTIONS: dict[str, str] = {
    "gt": "above",
    "ge": "above",
    "lt": "below",
    "le": "below",
    "eq": "eq",
    "between": "between",
}

_STRICT = frozenset({"gt", "lt"})
_STRICTNESS_PAIRS = ({"gt", "ge"}, {"lt", "le"})
_WORDS = {
    "gt": "above",
    "ge": "at or above",
    "lt": "below",
    "le": "at or below",
    "eq": "exactly",
    "between": "between",
}
_UNITS = {"usd": "USD", "bps": "bps"}
_EVENT_FIELDS = ("subject", "measure", "unit", "observed_on")
_OUTCOME_FIELDS = ("direction", "threshold", "upper")


class _Normalized(NamedTuple):
    """The terms after grid normalization, each field as text. EQUIVALENT exactly when equal."""

    subject: str
    measure: str
    measured_by: str
    observed_on: str
    observed_at: str | None
    direction: str
    threshold: str
    upper: str | None
    unit: str


def terms_key(terms: ContractTerms) -> str:
    """The normalized terms as text: the cluster key in section 6.2, used as `cluster_id`.

    The fields are subject|measure|measured_by|observed_on|observed_at|direction|threshold|upper|
    unit. `observed_at` is written only when the market states an instant, in UTC
    ("2026-10-12T20:00:00Z"), and `upper` only for a range ("between"). Fields that are None are
    left out, so a key reads "...|2026-10-28|eq|0|bps" or "...|2026-10-12T20:00:00Z|above|330|usd",
    and a range reads "...|between|330|340|usd". Numbers are written in plain notation without
    trailing zeros, so 330 and 330.00 give the same key.
    """
    return "|".join(field for field in _normalize(terms) if field is not None)


def evaluate_pair(a: CanonicalMarket, b: CanonicalMarket) -> MatchResult:
    """Decide whether YES on `a` pays out under exactly the same conditions as YES on `b` (D8)."""
    if a.terms is None or b.terms is None:
        return text_match(a, b)
    ta, tb = a.terms, b.terms
    na, nb = _normalize(ta), _normalize(tb)

    event = [field for field in _EVENT_FIELDS if getattr(na, field) != getattr(nb, field)]
    if None not in (na.observed_at, nb.observed_at) and na.observed_at != nb.observed_at:
        event.append("observed_at")
    if event:
        details = "; ".join(f"{f} {getattr(ta, f)} vs {getattr(tb, f)}" for f in event)
        return _result(a, b, EquivalenceStatus.DISTINCT, f"Different event: {details}.")
    if any(getattr(na, field) != getattr(nb, field) for field in _OUTCOME_FIELDS):
        reason = f"Different outcome: {ta.measure} {_bound(ta)} vs {_bound(tb)}."
        return _result(a, b, EquivalenceStatus.DISTINCT, reason)
    if na.measured_by != nb.measured_by:
        reason = (
            f"Measured differently: {ta.measured_by} vs {tb.measured_by}, "
            "so the pair is never routed."
        )
        return _result(a, b, EquivalenceStatus.AMBIGUOUS, reason)
    if (na.observed_at is None) != (nb.observed_at is None):
        stated = a if na.observed_at is not None else b
        reason = (
            f"The observation time is stated by only one market: {_venue(stated)} observes at "
            f"{stated.terms.observed_at.isoformat()}, so the pair is never routed."
        )
        return _result(a, b, EquivalenceStatus.AMBIGUOUS, reason)

    bounds = _bound(ta) if _bound(ta) == _bound(tb) else f"{_bound(ta)} vs {_bound(tb)}"
    reason = (
        f"Same event and outcome: {ta.subject} {ta.measure} on {ta.observed_on}, {bounds}, "
        f"measured by {ta.measured_by}."
    )
    return _result(a, b, EquivalenceStatus.EQUIVALENT, reason, _risk_flags(a, b))


def _normalize(terms: ContractTerms) -> _Normalized:
    comparison, threshold = terms.comparison, terms.threshold
    grid = MEASURE_GRIDS.get(terms.measure)
    if grid is not None and comparison == "lt":
        comparison, threshold = "le", threshold - grid
    elif grid is not None and comparison == "gt":
        comparison, threshold = "ge", threshold + grid
    return _Normalized(
        subject=terms.subject,
        measure=terms.measure,
        measured_by=terms.measured_by,
        observed_on=terms.observed_on.isoformat(),
        observed_at=_instant(terms),
        direction=DIRECTIONS[comparison],
        threshold=_number(threshold),
        upper=None if terms.upper is None else _number(terms.upper),
        unit=terms.unit,
    )


def _result(
    a: CanonicalMarket,
    b: CanonicalMarket,
    status: EquivalenceStatus,
    reason: str,
    risk_flags: tuple[str, ...] = (),
) -> MatchResult:
    return MatchResult(
        market_a=a.market_id,
        market_b=b.market_id,
        status=status,
        method="terms",
        reasons=(reason,),
        risk_flags=risk_flags,
    )


def _risk_flags(a: CanonicalMarket, b: CanonicalMarket) -> tuple[str, ...]:
    """What still differs in an EQUIVALENT pair. The text is the same whichever market is `a`."""
    first, second = sorted((a, b), key=lambda market: market.market_id)
    flags = (
        _tie_flag(first, second),
        _grid_flag(first, second),
        _edge_case_flag(first, second),
        _source_flag(first, second),
    )
    return tuple(flag for flag in flags if flag)


def _tie_flag(a: CanonicalMarket, b: CanonicalMarket) -> str | None:
    """Only the strictness differs (gt vs ge, or lt vs le) at the same threshold (D23)."""
    ta, tb = a.terms, b.terms
    if ta.threshold != tb.threshold or {ta.comparison, tb.comparison} not in _STRICTNESS_PAIRS:
        return None
    strict, inclusive = (a, b) if ta.comparison in _STRICT else (b, a)
    return (
        f"Tie rule differs: at exactly {_number(ta.threshold)} {_unit(ta)}, "
        f"{_venue(strict)} pays No and {_venue(inclusive)} pays Yes."
    )


def _grid_flag(a: CanonicalMarket, b: CanonicalMarket) -> str | None:
    """The terms agree only after normalizing on the measure's grid (D20)."""
    ta, tb = a.terms, b.terms
    grid = MEASURE_GRIDS.get(ta.measure)
    if grid is None or (ta.comparison, ta.threshold) == (tb.comparison, tb.threshold):
        return None
    step = f"{_number(grid)} {_unit(ta)}"
    return (
        f"Equal only on the {step} grid: {_venue(a)} pays Yes {_bound(ta)} and "
        f"{_venue(b)} {_bound(tb)}, which agree only for moves in {step} steps."
    )


def _edge_case_flag(a: CanonicalMarket, b: CanonicalMarket) -> str | None:
    """The venues' fallback procedures differ: holds, overrides, holidays (D23)."""
    if set(a.terms.fallback_rules) == set(b.terms.fallback_rules):
        return None
    return f"Edge-case rules differ: {_rules(a)} {_rules(b)}"


def _rules(market: CanonicalMarket) -> str:
    return f"{_venue(market)}: {' '.join(market.terms.fallback_rules) or 'none stated.'}"


def _source_flag(a: CanonicalMarket, b: CanonicalMarket) -> str | None:
    """The resolution sources are different institutions; URLs alone don't count (D18)."""
    source_a, source_b = a.resolution_source.institution, b.resolution_source.institution
    if source_a == source_b:
        return None
    return (
        f"Resolution sources differ: {_venue(a)} uses {source_a} and {_venue(b)} uses {source_b}."
    )


def _bound(terms: ContractTerms) -> str:
    """The condition YES pays on, in words: "exactly 0 bps", "at or above 330 USD"."""
    value = _number(terms.threshold)
    if terms.upper is not None:
        value = f"{value} and {_number(terms.upper)}"
    return f"{_WORDS[terms.comparison]} {value} {_unit(terms)}"


def _instant(terms: ContractTerms) -> str | None:
    """The stated observation instant in UTC, so one instant written in two zones compares equal."""
    if terms.observed_at is None:
        return None
    return terms.observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _number(value: Decimal) -> str:
    """Plain notation without trailing zeros, so 330 and 330.00 are written the same way."""
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _unit(terms: ContractTerms) -> str:
    return _UNITS.get(terms.unit, terms.unit)


def _venue(market: CanonicalMarket) -> str:
    return market.venue.capitalize()
