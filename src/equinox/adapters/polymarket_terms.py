"""Reading Polymarket's wording as contract terms, one parser per family (architecture 5.3, D15).

Only the Fed-decision family has a parser: its bracket is in `groupItemTitle` ("25 bps decrease")
and its meeting date in the description ("scheduled for October 27-28, 2026") (P6).
"""

import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from equinox.models import ContractTerms

NEW_YORK = ZoneInfo("America/New_York")
FED_FALLBACK_RULES = (
    "A change not shown in the brackets is rounded up to the nearest 25 bps.",
    "If no statement is released by the end date of the next scheduled meeting, "
    "'No change' resolves Yes.",
)
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
BRACKET = re.compile(r"(\d+)(\+?) bps (decrease|increase)", re.IGNORECASE)
MEETING = re.compile(rf"scheduled for ({'|'.join(MONTHS)}) (\d{{1,2}})-(\d{{1,2}}), (\d{{4}})")

TermParser = Callable[[dict[str, Any], list[str]], ContractTerms | None]


def utc(text: str) -> datetime:
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError(f"{text!r} has no time zone")
    return moment.astimezone(UTC)


def fed_terms(raw: dict[str, Any], notes: list[str]) -> ContractTerms | None:
    label = raw.get("groupItemTitle") or ""
    bracket = _fed_bracket(label)
    if bracket is None:
        notes.append(f"polymarket: market {raw['id']}: no terms for the bracket {label!r}")
        return None
    comparison, threshold = bracket
    return ContractTerms(
        subject="FOMC",
        measure="fed_upper_bound_change",
        measured_by="fomc_statement",
        observed_on=_meeting_day(raw, notes),
        comparison=comparison,
        threshold=threshold,
        unit="bps",
        fallback_rules=FED_FALLBACK_RULES,
    )


def _fed_bracket(label: str) -> tuple[str, Decimal] | None:
    """A bracket as (comparison, change): "50+ bps decrease" -> le -50, "No change" -> eq 0."""
    label = label.strip()
    if label.lower() == "no change":
        return "eq", Decimal(0)
    match = BRACKET.fullmatch(label)
    if match is None:
        return None
    size, plus, direction = match.groups()
    change = Decimal(size) if direction.lower() == "increase" else -Decimal(size)
    if not plus:
        return "eq", change
    return ("ge" if change > 0 else "le"), change


def _meeting_day(raw: dict[str, Any], notes: list[str]) -> date:
    """The last day of "scheduled for October 27-28, 2026"; else endDate's New York date."""
    match = MEETING.search(raw.get("description") or "")
    if match:
        month, _first, last, year = match.groups()
        return date(int(year), MONTHS.index(month) + 1, int(last))
    notes.append(
        f"polymarket: market {raw['id']}: no 'scheduled for' meeting date in the description, "
        "so observed_on is endDate in New York"
    )
    return utc(raw["endDate"]).astimezone(NEW_YORK).date()


TERM_PARSERS: dict[str, TermParser] = {"fed_decision": fed_terms}
