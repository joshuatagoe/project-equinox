"""One key per team, however a venue spells its name (D62).

Kalshi writes "Coventry City", "CR Flamengo RJ" and "Atletico San Luis"; Polymarket writes
"Coventry City FC", "CR Flamengo" and "Atlético San Luis". A key drops accents, case and
punctuation, then club words and Brazilian state codes, and reads "St." as "Saint". The names that
still differ are in `team_aliases.json`, seeded from the exact scores the model read as the same
bet ("PSV Eindhoven" is "PSV").

A wrong merge would need both teams and the date of a match to collide, so the rules can be broad.
A name the rules and the table miss only loses a pair; the cross-check reports it.
"""

import json
import re
import unicodedata
from functools import cache
from pathlib import Path

ALIASES = Path(__file__).with_name("team_aliases.json")
CLUB_WORDS = frozenset(
    "ac afc bc cd cf club cr da de del do ec fbc fc la osc sc se sfc ssc the ud".split()
)
STATES = frozenset("ba mg pr rj rs sp".split())  # after a Brazilian club's name: "Bahia BA"
_WORD = re.compile(r"[a-z0-9]+")


def team_key(name: str) -> str:
    """The team's key: "Coventry City FC" is "coventry city", "PSV Eindhoven" is "psv"."""
    plain = unicodedata.normalize("NFKD", name)
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower()
    words = ["saint" if word == "st" else word for word in _WORD.findall(plain)]
    kept = [word for word in words if word not in CLUB_WORDS | STATES] or words
    key = " ".join(kept)
    return _aliases().get(key, key)


@cache
def _aliases() -> dict[str, str]:
    return json.loads(ALIASES.read_text(encoding="utf-8"))["aliases"]
