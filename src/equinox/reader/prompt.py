"""What the term reader asks the model, and how its answer is read back (D57).

One request reads a group of markets that may be about the same events, so the model gives equal
things equal names. The answer is forced through one tool, `record_terms`, whose input is one
terms record per market. The whole request is the cache key, so changing the prompt, the model
or a market's text reads it again; the prompt version is recorded with each reading.
"""

import json
from collections.abc import Sequence
from typing import Any

from equinox.models.catalog import ReadableMarket

PROMPT_VERSION = "feat-10.7"
MODEL = "claude-haiku-5-5"
MAX_TOKENS = 8192
MAX_RULES = 1500  # characters of rules text per market; the condition is stated early

SYSTEM = """\
You read prediction-market contracts into structured terms. You do not decide whether two \
markets are the same bet: code compares your terms. Be literal. Write what each market's own \
text says, and nothing it doesn't.

The markets you get may be about the same events. Use one vocabulary for all of them: when two \
markets refer to the same person, team, event, quantity or source, give them identical names, \
even when the venues spell them differently ("Los Angeles R" and "Rams"); when they differ, give \
them different names. Use the plainest common name, without sponsor, city or region suffixes.

Fill one record per market:
- id: the market's id from the input.
- readable: false when the market isn't a yes/no question on one condition that fits these \
fields, for example several conditions joined; then say why in reason and leave the rest out.
- subject: the one person, team, match, body or thing the outcome is about, in snake_case: \
"fomc", "kylian_mbappe", "al_wasl_fc_vs_al_ahli_saudi_fc". For a player in a game, the player.
- measure: the quantity or event that decides it, in snake_case, exactly as narrow as the rules \
define it: "touchdowns" when any touchdown counts, "rushing_or_receiving_touchdowns" when only \
those do; "fed_upper_bound_change", "core_pce_monthly_change". Read the rules, not the title: \
when two markets' rules define what makes it happen differently (a different trigger, step, \
deadline or what counts), their measures must differ and say how, even if their titles match. \
For a number (a change, a count, a price), the measure names only the quantity; the comparison \
and threshold carry the outcome, never the measure.
- measured_by: the institution whose decision, result or record settles it in the real world, \
in snake_case. Name it even when the rules only imply it, and name the institution, not a web \
page: "fomc_statement" for a Fed decision, "official_match_result" for a game's score or winner, \
"official_league_statistics" for a player's statistics, otherwise the organization that \
announces or publishes the outcome. Write "unstated" only when nothing implies who settles it.
- observed_on: the date of the real-world event that decides it, YYYY-MM-DD, New York time: the \
game, the decision, the announcement or the release. Never the market's close or expiry date. \
For an event that spans several days, the last day: a meeting "scheduled for December 8-9, \
2026" is decided on 2026-12-09. When the text gives only a period, such as a year or a season, \
the period's last day: "Person of the Year for 2026" is 2026-12-31.
- comparison: gt (above, more than), ge (at least, or more, N+), lt (below, less than), \
le (at most, or less), eq (exactly, or a named outcome), between (a range; give upper).
- threshold and upper: numbers as the title or outcome states them, as strings ("2+" is ge 2). \
A decrease is negative: "cut 25 bps" is eq -25, "cut >25bps" is lt -25 and "50+ bps decrease" \
is le -50. Keep the comparison and number the text states; never restate ">25" as "50 or more".
- unit: bps, usd, percent, count or indicator.
- evidence: one phrase, copied character for character from a single field of that market (its \
title, outcome or rules), that states its condition. Never join fields or add words.

A yes/no outcome that isn't a number (a person is named, a team wins, an exact score happens) is \
an indicator: comparison eq, threshold "1", unit indicator, and the outcome in measure, for \
example subject "time_person_of_the_year_2026" with measure "named_taylor_swift". An exact score \
is subject "<home team>_vs_<away team>" and measure "final_score_<home goals>_<away goals>", \
home team first. "<Team> wins 1-0" gives the winner's goals first, so find which side is at \
home in the event or rules before writing it.

Known names, to use when they apply: Fed rate decisions are subject "fomc", measure \
"fed_upper_bound_change", measured_by "fomc_statement", unit bps. Use known names exactly.
"""

_FIELD = {"type": "string"}
COMPARISONS = ["gt", "ge", "lt", "le", "eq", "between"]
UNITS = ["bps", "usd", "percent", "count", "indicator"]
TOOL = {
    "name": "record_terms",
    "description": "Record the terms of every market in the input, one record each.",
    "input_schema": {
        "type": "object",
        "properties": {
            "markets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": _FIELD,
                        "readable": {"type": "boolean"},
                        "reason": _FIELD,
                        "subject": _FIELD,
                        "measure": _FIELD,
                        "measured_by": _FIELD,
                        "observed_on": _FIELD,
                        "comparison": {"type": "string", "enum": COMPARISONS},
                        "threshold": _FIELD,
                        "upper": _FIELD,
                        "unit": {"type": "string", "enum": UNITS},
                        "evidence": _FIELD,
                    },
                    "required": ["id", "readable"],
                },
            }
        },
        "required": ["markets"],
    },
}


def request(markets: Sequence[ReadableMarket], model: str) -> dict[str, Any]:
    """The Messages API request that reads these markets."""
    listed = [
        {
            "id": f"m{number}",
            "venue": market.venue,
            "event": market.event_title,
            "title": market.title,
            "outcome": market.outcome_label,
            "closes": market.closes_at.date().isoformat() if market.closes_at else None,
            "rules": market.text.rules[:MAX_RULES],
            "strike": market.text.strike or None,
        }
        for number, market in enumerate(markets, start=1)
    ]
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "tools": [TOOL],
        "tool_choice": {"type": "tool", "name": TOOL["name"]},
        "messages": [{"role": "user", "content": json.dumps({"markets": listed})}],
    }


def answers(response: dict[str, Any], markets: Sequence[ReadableMarket]) -> dict[str, dict]:
    """Each market's record from the model's answer, by market ID. A market the answer leaves
    out gets a record that says so, and is rejected like any unreadable market."""
    records = {}
    for block in response.get("content") or []:
        if block.get("type") == "tool_use" and block.get("name") == TOOL["name"]:
            listed = block.get("input", {}).get("markets") or []
            if isinstance(listed, str):  # a list sent as JSON text
                listed = _json_list(listed)
            records = {str(r.get("id")): r for r in listed if isinstance(r, dict)}
    missing = {"readable": False, "reason": "the answer has no record for it."}
    return {m.market_id: records.get(f"m{n}", missing) for n, m in enumerate(markets, start=1)}


def usage(response: dict[str, Any]) -> tuple[int, int]:
    used = response.get("usage") or {}
    return int(used.get("input_tokens") or 0), int(used.get("output_tokens") or 0)


def _json_list(text: str) -> list:
    """The list at the start of the text; anything after it is ignored (seen live: a stray brace).
    Every record it yields still goes through the checks."""
    try:
        found, _ = json.JSONDecoder().raw_decode(text.strip())
    except ValueError:
        return []
    return found if isinstance(found, list) else []
