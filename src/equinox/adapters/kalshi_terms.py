"""Reading Kalshi's wording as contract terms (architecture 5.2, D15), and the texts the term
reader reads (D57).

Only the Fed-decision family has a parser: each meeting's five markets carry one of five
`custom_strike` shapes (K8). For every other market, the term reader gets the rules text and
Kalshi's own strike fields (S2), which the checks compare with what the model read.
"""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

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
