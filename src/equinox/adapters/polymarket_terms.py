"""Reading Polymarket's wording as contract terms, one parser per family (architecture 5.3, D15).

Two families have a parser. A Fed decision's bracket is in `groupItemTitle` ("25 bps decrease")
and its meeting date in the description ("scheduled for October 27-28, 2026") (P6). An exact
score is a market whose `sportsMarketType` says so; its event's `teams` say which team is home, and
its question reads "Exact Score: <home> <h> - <a> <away>?" (D61).
"""

import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from equinox.adapters.scores import exact_score, scheduled_day
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

# sportsMarketType -> (first half?, the question's start, how the description states the period)
SCORE_TYPES = {
    "soccer_exact_score": (
        False,
        "Exact Score: ",
        "considering only the result at the end of 90 minutes of regulation plus stoppage time",
    ),
    "soccer_first_half_exact_score": (
        True,
        "1st Half Exact Score: ",
        "considering only goals scored within the first 45 minutes of regular play plus "
        "first-half stoppage time",
    ),
}
# What a score market's description says happens in edge cases, and the rule in plain words.
SCORE_FALLBACKS = (
    (
        "If the match is postponed, the market will remain open until it is completed",
        "A postponed match keeps the market open until it is played.",
    ),
    (
        'if it is canceled with no make-up game, the market resolves to "0-0."',
        "A match cancelled with no make-up game resolves as 0-0.",
    ),
    (
        "If no acceptable data is available within 24 hours of the event's conclusion, this "
        "market will resolve 50-50",
        "With no acceptable data within 24 hours of the match, it resolves 50-50.",
    ),
)

TermParser = Callable[[dict[str, Any], list[str]], ContractTerms | None]
# A family is found by its tag and an event title; only open, neg-risk events count (P12).
FAMILY_TAGS = {"fed_decision": ("fed-rates", re.compile(r"^Fed Decision in [A-Za-z]+\?$", re.I))}


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


def event_parser(event: dict[str, Any]) -> TermParser | None:
    """The parser for an event read without a family, by what it is: a catalog listing, or a
    catalog market loaded for pricing (D65)."""
    tag, title = FAMILY_TAGS["fed_decision"]
    if event.get("negRisk") and title.match(event.get("title") or ""):
        return fed_terms
    if any(m.get("sportsMarketType") in SCORE_TYPES for m in event.get("markets") or []):
        return lambda raw, notes: score_terms(raw, event, notes)
    return None


def score_terms(
    raw: dict[str, Any], event: dict[str, Any], notes: list[str]
) -> ContractTerms | None:
    """An exact score's terms, when its question names the event's home and away teams and its
    description states the period and the match; None for any other market. "Any Other Score"
    has none: the venues list different scores."""
    kind = SCORE_TYPES.get(raw.get("sportsMarketType") or "")
    question = raw.get("question") or ""
    if kind is None or question.endswith("Any Other Score?"):
        return None
    first_half, start, period = kind
    teams = {team.get("ordering"): team.get("name") for team in event.get("teams") or []}
    home, away = teams.get("home") or "", teams.get("away") or ""
    pattern = rf"{re.escape(start)}{re.escape(home)} (\d+) - (\d+) {re.escape(away)}\?"
    goals = re.fullmatch(pattern, question) if home and away else None
    text = raw.get("description") or ""
    day = scheduled_day(text)
    if goals is None or period not in text or f"{home} vs. {away}" not in text or day is None:
        notes.append(f"polymarket: market {raw['id']}: no terms for the score {question!r}")
        return None
    rules = tuple(rule for phrase, rule in SCORE_FALLBACKS if phrase in text)
    return exact_score(home, away, (int(goals[1]), int(goals[2])), first_half, day, rules)


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
