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
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
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
_UNITS = {"usd": "USD", "bps": "bps", "percent": "percent", "count": "", "indicator": ""}
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
    decision = decide(a.terms, b.terms, (_venue(a), _venue(b)))
    flags = _risk_flags(a, b) if decision.status == EquivalenceStatus.EQUIVALENT else ()
    return _result(a, b, decision.status, decision.reason, flags)


class Decision(NamedTuple):
    status: EquivalenceStatus
    reason: str
    flags: tuple[str, ...] = ()  # what still differs in an EQUIVALENT pair's terms


def decide(
    ta: ContractTerms, tb: ContractTerms, names: tuple[str, str] = ("One market", "the other")
) -> Decision:
    """Rules 2-6 on two sets of terms, however they were read: by a parser or by a model (D57).

    `names` say which market is which in the reasons. The flags cover the terms only; a pair of
    canonical markets also gets the edge-case and resolution-source flags (`evaluate_pair`).
    """
    na, nb = _normalize(ta), _normalize(tb)
    event = [field for field in _EVENT_FIELDS if getattr(na, field) != getattr(nb, field)]
    if None not in (na.observed_at, nb.observed_at) and na.observed_at != nb.observed_at:
        event.append("observed_at")
    if event:
        details = "; ".join(f"{f} {getattr(ta, f)} vs {getattr(tb, f)}" for f in event)
        return Decision(EquivalenceStatus.DISTINCT, f"Different event: {details}.")
    if any(getattr(na, field) != getattr(nb, field) for field in _OUTCOME_FIELDS):
        reason = f"Different outcome: {ta.measure} {_bound(ta)} vs {_bound(tb)}."
        return Decision(EquivalenceStatus.DISTINCT, reason)
    if na.measured_by != nb.measured_by:
        reason = (
            f"Measured differently: {ta.measured_by} vs {tb.measured_by}, "
            "so the pair is never routed."
        )
        return Decision(EquivalenceStatus.AMBIGUOUS, reason)
    if (na.observed_at is None) != (nb.observed_at is None):
        name, stated = (names[0], ta) if na.observed_at is not None else (names[1], tb)
        reason = (
            f"The observation time is stated by only one market: {name} observes at "
            f"{stated.observed_at.isoformat()}, so the pair is never routed."
        )
        return Decision(EquivalenceStatus.AMBIGUOUS, reason)
    bounds = _bound(ta) if _bound(ta) == _bound(tb) else f"{_bound(ta)} vs {_bound(tb)}"
    reason = (
        f"Same event and outcome: {ta.subject} {ta.measure} on {ta.observed_on}, {bounds}, "
        f"measured by {ta.measured_by}."
    )
    flags = (_tie_flag(ta, tb, names), _grid_flag(ta, tb, names))
    return Decision(EquivalenceStatus.EQUIVALENT, reason, tuple(f for f in flags if f))


def _normalize(terms: ContractTerms) -> _Normalized:
    comparison, threshold = terms.comparison, terms.threshold
    grid = MEASURE_GRIDS.get(terms.measure)
    if grid is not None and comparison == "lt":
        comparison, threshold = "le", threshold - grid
    elif grid is not None and comparison == "gt":
        comparison, threshold = "ge", threshold + grid
    elif terms.unit == "count":  # whole numbers: above 1.5 is at least 2 (D56)
        comparison, threshold = _whole_count(comparison, threshold)
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


def _whole_count(comparison: str, threshold: Decimal) -> tuple[str, Decimal]:
    """A count's bound as an inclusive whole number: gt 1.5 and gt 1 are ge 2; lt 3 is le 2."""
    whole = threshold == threshold.to_integral_value()
    if comparison in ("gt", "ge"):
        step = 1 if comparison == "gt" and whole else 0
        return "ge", (threshold + step).to_integral_value(ROUND_CEILING)
    if comparison in ("lt", "le"):
        step = 1 if comparison == "lt" and whole else 0
        return "le", (threshold - step).to_integral_value(ROUND_FLOOR)
    return comparison, threshold


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
    names = (_venue(first), _venue(second))
    flags = (
        _tie_flag(first.terms, second.terms, names),
        _grid_flag(first.terms, second.terms, names),
        _edge_case_flag(first, second),
        _source_flag(first, second),
    )
    return tuple(flag for flag in flags if flag)


def _tie_flag(ta: ContractTerms, tb: ContractTerms, names: tuple[str, str]) -> str | None:
    """Only the strictness differs (gt vs ge, or lt vs le) at the same threshold (D23)."""
    if ta.threshold != tb.threshold or {ta.comparison, tb.comparison} not in _STRICTNESS_PAIRS:
        return None
    strict, inclusive = names if ta.comparison in _STRICT else names[::-1]
    return (
        f"Tie rule differs: at exactly {_amount(ta.threshold, ta)}, "
        f"{strict} pays No and {inclusive} pays Yes."
    )


def _grid_flag(ta: ContractTerms, tb: ContractTerms, names: tuple[str, str]) -> str | None:
    """The terms agree only after normalizing on the measure's grid (D20)."""
    grid = MEASURE_GRIDS.get(ta.measure)
    if grid is None or (ta.comparison, ta.threshold) == (tb.comparison, tb.threshold):
        return None
    step = _amount(grid, ta)
    return (
        f"Equal only on the {step} grid: {names[0]} pays Yes {_bound(ta)} and "
        f"{names[1]} {_bound(tb)}, which agree only for moves in {step} steps."
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
    return f"{_WORDS[terms.comparison]} {value} {_unit(terms)}".rstrip()


def _amount(value: Decimal, terms: ContractTerms) -> str:
    return f"{_number(value)} {_unit(terms)}".rstrip()


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
