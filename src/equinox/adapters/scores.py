"""Exact-score terms, in one shape for every venue (D61).

A score market pays Yes on one score of one match: subject "<home> vs <away>" as team keys
(`teams.py`), measure `full_time_score_<home goals>_<away goals>` or `first_half_score_…`, observed
on the day the match was "originally scheduled for", as an indicator. Each venue's parser checks
that its own wording states the match, the period and the score before it builds them.
"""

import re
from datetime import date
from decimal import Decimal

from equinox.adapters.teams import team_key
from equinox.models import ContractTerms

EXACT_SCORE = "exact_score"  # the family's name in the catalog (feat-12)
MEASURED_BY = "official_match_score"
_MONTHS = {
    name: number
    for number, name in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)
}
_SCHEDULED = re.compile(r"originally scheduled for ([A-Za-z]+)\.? (\d{1,2}), (\d{4})")


def exact_score(
    home: str,
    away: str,
    goals: tuple[int, int],
    first_half: bool,
    day: date,
    fallback_rules: tuple[str, ...] = (),
) -> ContractTerms:
    period = "first_half" if first_half else "full_time"
    return ContractTerms(
        subject=f"{team_key(home)} vs {team_key(away)}",
        measure=f"{period}_score_{goals[0]}_{goals[1]}",
        measured_by=MEASURED_BY,
        observed_on=day,
        comparison="eq",
        threshold=Decimal(1),
        unit="indicator",
        fallback_rules=fallback_rules,
    )


def scheduled_day(text: str) -> date | None:
    """The day in "originally scheduled for Oct 12, 2026" (Kalshi) or "October 12, 2026"
    (Polymarket); None when the text states no such day."""
    found = _SCHEDULED.search(text)
    month = _MONTHS.get(found[1][:3].lower()) if found else None
    if month is None:
        return None
    try:
        return date(int(found[3]), month, int(found[2]))
    except ValueError:
        return None
