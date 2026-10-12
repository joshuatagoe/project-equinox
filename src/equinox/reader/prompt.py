"""What the term reader asks the model, and how its answer is read back (D57).

One request reads a group of markets that may be about the same events, so the model gives equal
things equal names. The answer is forced through one tool, `record_terms`, whose input is one
terms record per market. The whole request is the cache key, so changing the prompt, the model
or a market's text reads it again; the prompt version is recorded with each reading.
"""

import json
import re
from collections.abc import Sequence
from typing import Any

from equinox.models.catalog import ReadableMarket

PROMPT_VERSION = "feat-12.1"
MODEL = "claude-haiku-5-5"
MAX_TOKENS = 8192
MAX_RULES = 1500  # characters of rules text per market; the condition is stated early
_RECORD = re.compile(r"(?=\{\s*\"id\"\s*:)")  # where each record starts
_STRAY_QUOTE = re.compile(r',\s*"\s*\}$')  # `...","}` at a record's end

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
example subject "time_person_of_the_year_2026" with measure "named_taylor_swift".

An exact score (one score of one match) is read in parts. First write score_order: which team is \
at home (the first team in the event or rules: "Lens vs Sporting" puts Lens at home), how this \
market writes its score ("Sporting wins 4-1" gives the winner's goals first; "Lens 1 - 4 \
Sporting" gives the home team's first), and so the home and away goals. Then fill home_team, \
away_team, home_goals, away_goals and period; code writes the subject and measure from them. \
Take each market's teams and goals from its own text only, never from another market in the \
request: two markets about one match are often different scores.

Known names, to use when they apply: Fed rate decisions are subject "fomc", measure \
"fed_upper_bound_change", measured_by "fomc_statement", unit bps. Use known names exactly.
"""

_FIELD = {"type": "string"}
COMPARISONS = ["gt", "ge", "lt", "le", "eq", "between"]
UNITS = ["bps", "usd", "percent", "count", "indicator"]


def _field(kind: str, description: str, enum: list[str] | None = None) -> dict[str, Any]:
    return {"type": kind, "description": description} | ({"enum": enum} if enum else {})


# One record's fields, in the order the model fills them: an exact score's order is worked out
# before its goals, and both before the measure (feat-12).
FIELDS = {
    "id": _FIELD,
    "readable": _field(
        "boolean", "false when it isn't a yes/no question on one condition that fits these fields"
    ),
    "reason": _field("string", "why it isn't readable, when readable is false"),
    "score_order": _field(
        "string",
        "exact score only, before its goals: which team is at home and why, how this market "
        "writes its score (winner first, or home team first), and so the home and away goals",
    ),
    "home_team": _field("string", "exact score only: the home team, named as in this request"),
    "away_team": _field("string", "exact score only: the away team, named as in this request"),
    "home_goals": _field("integer", "exact score only: the home team's goals in this score"),
    "away_goals": _field("integer", "exact score only: the away team's goals in this score"),
    "period": _field(
        "string",
        "exact score only: full_time (90 minutes and stoppage time) or first_half",
        ["full_time", "first_half"],
    ),
    "subject": _field("string", "what the outcome is about, in snake_case; not for a score"),
    "measure": _field(
        "string",
        "what decides it, as narrow as the rules define it, in snake_case; not for a score",
    ),
    "measured_by": _field("string", "the institution whose result or record settles it"),
    "observed_on": _field("string", "YYYY-MM-DD in New York: the day the deciding event happens"),
    "comparison": _field("string", "how the threshold is compared", COMPARISONS),
    "threshold": _field("string", "the number as the market states it; '1' for an indicator"),
    "upper": _field("string", "the top of a range, for between only"),
    "unit": _field("string", "the unit of the threshold", UNITS),
    "evidence": _field(
        "string",
        "one phrase copied exactly from one field of this market that states its condition",
    ),
}
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
                    "properties": FIELDS,
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
    When the list doesn't parse, each record is read on its own, so one broken record loses only
    itself (seen live: `"evidence":"...","}`, a stray quote). Every record still goes through the
    checks."""
    try:
        found, _ = json.JSONDecoder().raw_decode(text.strip())
    except ValueError:
        return _one_by_one(text)
    return found if isinstance(found, list) else []


def _one_by_one(text: str) -> list:
    """Each record that parses, after one repair: a stray quote before a record's last brace."""
    records = []
    for piece in _RECORD.split(text):
        piece = piece.strip().rstrip(",]").strip()
        for candidate in (piece, _STRAY_QUOTE.sub("}", piece)):
            try:
                found = json.loads(candidate)
            except ValueError:
                continue
            if isinstance(found, dict):
                records.append(found)
            break
    return records
