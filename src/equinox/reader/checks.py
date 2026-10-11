"""Checking a model's reading against the venue's own text (D57).

The model only fills in the terms; this module decides whether to believe them. A reading is
rejected, with the reason, when:

- the model says the market isn't one yes/no condition;
- its evidence phrase is not in the market's text;
- its threshold or upper bound is not a number in that text (an indicator is exempt; a threshold
  of 0 is allowed when the evidence states the condition in words, as in "no change", even if it
  names a year);
- its comparison disagrees with the evidence's words: "above" is gt, "at least" or "+" is ge,
  "below" is lt, "at most" is le, none of them is eq or between. A negative threshold mirrors
  the words, so "50+ bps decrease" is le -50. On a count only the side must agree;
- an indicator is anything but eq (its threshold is always 1);
- its date doesn't parse, or falls more than 7 days after the market closes;
- the venue's strike fields say otherwise. On a count, "above 29.5" and "at least 30" agree;
- the terms don't validate.
"""

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from equinox.models import ContractTerms
from equinox.models.catalog import ReadableMarket

DAYS_AFTER_CLOSE = 7
_NUMBER = re.compile(r"(\d+(?:,\d{3})*(?:\.\d+)?)(?:([kmb])(?![a-z]))?", re.IGNORECASE)
_SCALES = {"k": Decimal(1000), "m": Decimal(10**6), "b": Decimal(10**9)}
_YEARS = {Decimal(year) for year in range(1900, 2100)}
_DIRECTIONS = (  # the first group whose words appear in the evidence decides
    ("ge", r"at least|or more|or above|or higher|or greater|\d\s*\+|≥|no less than|minimum of"),
    ("le", r"at most|or less|or below|or lower|or fewer|≤|no more than|maximum of"),
    ("gt", r"\babove\b|more than|greater than|\bover\b|exceed\w*|higher than|>"),
    ("lt", r"\bbelow\b|less than|fewer than|\bunder\b|lower than|<"),
)
_MIRROR = {"ge": "le", "le": "ge", "gt": "lt", "lt": "gt"}
_STRIKES = {
    "greater": ("gt", "floor_strike"),
    "greater_or_equal": ("ge", "floor_strike"),
    "less": ("lt", "cap_strike"),
    "less_or_equal": ("le", "cap_strike"),
}


@dataclass(frozen=True)
class Reading:
    market_id: str
    terms: ContractTerms | None  # None when the reading was rejected or the market unreadable
    problem: str = ""  # why it was rejected, in words
    evidence: str = ""


def accept(raw: dict[str, Any], market: ReadableMarket) -> Reading:
    """The terms the model read, or the first reason not to believe them."""
    evidence = str(raw.get("evidence") or "")
    if not raw.get("readable"):
        reason = raw.get("reason") or "no reason given."
        return Reading(market.market_id, None, f"The model could not read it: {reason}", evidence)
    try:
        terms = _terms(raw)
    except (ValidationError, ValueError, InvalidOperation, TypeError) as error:
        return Reading(market.market_id, None, f"The terms don't validate: {error}", evidence)
    for check in (_quoted, _numbers_stated, _direction, _indicator, _dated, _strike_agrees):
        problem = check(terms, evidence, market)
        if problem:
            return Reading(market.market_id, None, problem, evidence)
    return Reading(market.market_id, terms, "", evidence)


def _terms(raw: dict[str, Any]) -> ContractTerms:
    """The record as terms. An indicator's threshold is 1 by definition, whatever the record says:
    the outcome it names is in its measure."""
    indicator = raw.get("unit") == "indicator"
    upper = None if indicator else raw.get("upper")
    return ContractTerms(
        subject=_snake(raw["subject"]),
        measure=_snake(raw["measure"]),
        measured_by=_snake(raw["measured_by"]),
        observed_on=date.fromisoformat(raw["observed_on"]),
        comparison=raw["comparison"],
        threshold=Decimal(1) if indicator else _decimal(raw["threshold"]),
        upper=None if upper in (None, "") else _decimal(upper),
        unit=raw["unit"],
    )


def _quoted(terms: ContractTerms, evidence: str, market: ReadableMarket) -> str:
    if len(evidence.strip()) < 3 or _plain(evidence) not in _plain(market.full_text):
        return f"The evidence {evidence!r} is not in the market's text."
    return ""


def _numbers_stated(terms: ContractTerms, evidence: str, market: ReadableMarket) -> str:
    if terms.unit == "indicator":
        return ""
    stated = _numbers(market.full_text) | _numbers(market.text.strike)
    for value in (terms.threshold, terms.upper):
        if value is None or abs(value) in stated:
            continue
        if value == 0 and not _numbers(evidence) - _YEARS:
            continue  # "no change" states zero in words; "after the December 2026 meeting" too
        return f"{_plain_number(value)} is not a number in the market's text."
    return ""


def _direction(terms: ContractTerms, evidence: str, market: ReadableMarket) -> str:
    for comparison, words in _DIRECTIONS:
        found = re.search(words, evidence.lower())
        if found:
            expected = _MIRROR[comparison] if terms.threshold < 0 else comparison
            if _side(terms.comparison, terms.unit) != _side(expected, terms.unit):
                return (
                    f"The evidence {evidence!r} says {found.group(0)}, so {expected}, "
                    f"not {terms.comparison}."
                )
            return ""
    if terms.comparison not in ("eq", "between"):
        return f"The evidence {evidence!r} states no direction, so eq, not {terms.comparison}."
    return ""


def _indicator(terms: ContractTerms, evidence: str, market: ReadableMarket) -> str:
    if terms.unit == "indicator" and (terms.comparison, terms.threshold) != ("eq", 1):
        return "A yes/no outcome is an indicator, and an indicator is eq 1."
    return ""


def _dated(terms: ContractTerms, evidence: str, market: ReadableMarket) -> str:
    if market.closes_at is None:
        return ""
    last = market.closes_at.date() + timedelta(days=DAYS_AFTER_CLOSE)
    if terms.observed_on > last:
        return (
            f"It is observed on {terms.observed_on}, after the market closes on "
            f"{market.closes_at.date()}."
        )
    return ""


def _strike_agrees(terms: ContractTerms, evidence: str, market: ReadableMarket) -> str:
    """The venue's own comparison and threshold, when it publishes them, must agree (S2)."""
    strike = json.loads(market.text.strike) if market.text.strike else {}
    kind = _STRIKES.get(strike.get("strike_type"))
    if kind is None or strike.get(kind[1]) is None:
        return ""  # "custom", "between" and unknown shapes are not checked
    comparison, threshold = kind[0], Decimal(str(strike[kind[1]]))
    stated = _whole(comparison, threshold, terms.unit)
    if stated != _whole(terms.comparison, terms.threshold, terms.unit) or terms.upper is not None:
        return (
            f"The venue's strike fields say {comparison} {_plain_number(threshold)}, "
            f"not {terms.comparison} {_plain_number(terms.threshold)}."
        )
    return ""


def _side(comparison: str, unit: str) -> str:
    """On a count, a strict bound is an inclusive one at the next whole number, so the words fix
    only the side: "2+" (ge 2) agrees with "greater 1.5". The number is checked on its own."""
    if unit != "count":
        return comparison
    return {"gt": "ge", "lt": "le"}.get(comparison, comparison)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value).replace(",", ""))


def _whole(comparison: str, threshold: Decimal, unit: str) -> tuple[str, Decimal]:
    """On a count, a strict bound is the next whole number: above 29.5 is at least 30."""
    if unit != "count":
        return comparison, threshold
    if comparison in ("gt", "ge"):
        start = threshold.to_integral_value(ROUND_FLOOR) + 1 if comparison == "gt" else threshold
        return "ge", start.to_integral_value(ROUND_CEILING)
    if comparison in ("lt", "le"):
        end = threshold.to_integral_value(ROUND_CEILING) - 1 if comparison == "lt" else threshold
        return "le", end.to_integral_value(ROUND_FLOOR)
    return comparison, threshold


def _numbers(text: str) -> set[Decimal]:
    found = set()
    for digits, scale in _NUMBER.findall(text):
        value = Decimal(digits.replace(",", ""))
        found |= {value, value * _SCALES[scale.lower()]} if scale else {value}
    return found


def _plain(text: str) -> str:
    text = text.lower().translate(str.maketrans("‘’“”", "''\"\""))
    return " ".join(text.split())


def _plain_number(value: Decimal) -> str:
    return format(value.normalize(), "f") if value else "0"


def _snake(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
