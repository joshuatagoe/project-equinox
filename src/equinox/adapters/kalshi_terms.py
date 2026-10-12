"""Reading Kalshi's wording as contract terms (architecture 5.2, D15), and the texts the term
reader reads (D57).

Two families have a parser. A Fed decision's five markets carry one of five `custom_strike`
shapes (K8). An exact score's event is "<home> vs <away>: Correct Score" (or "1st Half Correct
Score") and its goals are in `custom_strike` (D61). For every other market, the term reader gets
the rules text and Kalshi's own strike fields (S2), which the checks compare with what the model
read.
"""

import json
import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from equinox.adapters.scores import exact_score, scheduled_day
from equinox.models import ContractTerms

NEW_YORK = ZoneInfo("America/New_York")
FED_DECISION = "fed_decision"
FAMILY_SERIES = {FED_DECISION: "KXFEDDECISION"}  # K13
# The five custom_strike shapes of a KXFEDDECISION event (K8), as (comparison, bps).
FED_STRIKES = (
    ({"Cut": ">25"}, "lt", "-25"),
    ({"Cut": "25"}, "eq", "-25"),
    ({"Hike": "0"}, "eq", "0"),
    ({"Hike": "25"}, "eq", "25"),
    ({"Hike": ">25"}, "gt", "25"),
)
FED_FALLBACK = ("If the meeting is cancelled, 'Fed maintains rate' resolves Yes.",)
STRIKE_FIELDS = ("strike_type", "floor_strike", "cap_strike", "custom_strike")
SCORE_EVENT = re.compile(r"^(?P<home>.+) vs (?P<away>.+): (?P<half>1st Half )?Correct Score$")
FULL_TIME = "after 90 minutes plus stoppage time (does not include extra time or penalties)"
FIRST_HALF = "If the score at the end of the 1st Half is"

Parser = Callable[[dict[str, Any], dict[str, Any]], ContractTerms | None]


def parser_for(event: dict[str, Any], family: str = "") -> Parser | None:
    """The parser for an event's markets: the family's, when the event was tracked for a family
    (None if the family has none); else by what the event is, as for a catalog market (D65)."""
    if family:
        return fed_decision_terms if family == FED_DECISION else None
    if event.get("series_ticker") == FAMILY_SERIES[FED_DECISION]:
        return fed_decision_terms
    if SCORE_EVENT.match(event.get("title") or ""):
        return score_terms
    return None


def fed_decision_terms(raw: dict[str, Any], event: dict[str, Any]) -> ContractTerms | None:
    """Terms from custom_strike in one of the five known shapes; None for any other shape."""
    for shape, comparison, threshold in FED_STRIKES:
        if raw.get("custom_strike") == shape:
            return ContractTerms(
                subject="FOMC",
                measure="fed_upper_bound_change",
                measured_by="fomc_statement",
                observed_on=new_york_date(event["strike_date"]),
                comparison=comparison,
                threshold=Decimal(threshold),
                unit="bps",
                fallback_rules=FED_FALLBACK,
            )
    return None


def score_terms(raw: dict[str, Any], event: dict[str, Any]) -> ContractTerms | None:
    """Terms from `custom_strike`'s home and away goals, when the rules name the match in the
    event's order, state the period and state the same score; else None (D61)."""
    named = SCORE_EVENT.match(event.get("title") or "")
    strike = raw.get("custom_strike") or {}
    goals = (strike.get("home_score"), strike.get("away_score"))
    if named is None or not all(isinstance(g, str) and g.isdigit() for g in goals):
        return None
    home, away, half = named["home"], named["away"], bool(named["half"])
    home_goals, away_goals = int(goals[0]), int(goals[1])
    rules = rules_text(raw)
    stated = (
        f"{FIRST_HALF} {home} {home_goals}, {away} {away_goals} "
        if half
        else _full_time_result(home, away, home_goals, away_goals)
    )
    day = scheduled_day(rules)
    match_named = f" the {home} vs {away} professional " in rules
    if stated not in rules or not match_named or day is None or not (half or FULL_TIME in rules):
        return None
    return exact_score(home, away, (home_goals, away_goals), half, day)


def _full_time_result(home: str, away: str, home_goals: int, away_goals: int) -> str:
    """How Kalshi states a full-time score: "If Coventry City wins 2-1", "If the result is a 1-1
    draw". The winner's goals come first."""
    if home_goals == away_goals:
        return f"If the result is a {home_goals}-{away_goals} draw "
    winner = home if home_goals > away_goals else away
    high, low = max(home_goals, away_goals), min(home_goals, away_goals)
    return f"If {winner} wins {high}-{low} "


def rules_text(raw: dict[str, Any]) -> str:
    parts = (raw.get("rules_primary"), raw.get("rules_secondary"))
    return "\n".join(part for part in parts if part)


def strike_text(raw: dict[str, Any]) -> str:
    """Kalshi's own comparison and threshold (S2), as JSON with numbers as written; "" if none."""
    if not raw.get("strike_type"):
        return ""
    return json.dumps({k: raw[k] for k in STRIKE_FIELDS if raw.get(k) is not None}, default=str)


def new_york_date(text: str) -> date:
    instant = datetime.fromisoformat(text)
    if instant.tzinfo is None:
        raise ValueError(f"strike_date {text!r} has no time zone")
    return instant.astimezone(NEW_YORK).date()
