"""The pairs Equinox kept, for review (feat-14, D94): what Morgan audits.

Four kinds: same bets whose terms Equinox's own readers matched (exact), same bets a model read,
pairs whose titles only look alike (never priced), and pairs a model read and ruled different.
Pairs a parser ruled different (two scores of one match) are not listed: their terms say why.
"""

import json
import re
from dataclasses import dataclass
from decimal import Decimal

from equinox.catalog.store import Catalog
from equinox.matcher import terms_key
from equinox.models import ContractTerms
from equinox.models.catalog import DIFFERENT, SAME_BET, UNCLEAR

EXACT, MODEL, ALIKE, RULED = "exact", "model", "alike", "different"
KINDS = {
    EXACT: "Exact matches",
    MODEL: "Read by a model",
    ALIKE: "Look alike, never priced",
    RULED: "Ruled different by a model",
}
_WHERE = {  # (status, whether a model read it), or None for either
    EXACT: (SAME_BET, False),
    MODEL: (SAME_BET, True),
    ALIKE: (UNCLEAR, None),
    RULED: (DIFFERENT, True),
}
_EVERY = 1_000_000
_READER = re.compile(r"^(?P<model>.+) \(prompt (?P<prompt>[^)]+)\)$")
_PAIRS = """
SELECT p.market_a, a.venue, coalesce(a.described, a.title), a.event_title, a.terms_key,
       p.market_b, b.venue, coalesce(b.described, b.title), b.event_title,
       p.score, p.reasons, p.read_by
FROM pairs p JOIN entries a ON a.market_id = p.market_a JOIN entries b ON b.market_id = p.market_b
WHERE p.status = ?
ORDER BY CAST(p.score AS REAL) DESC, p.market_a
"""


@dataclass(frozen=True)
class Side:
    market_id: str
    venue: str
    title: str
    event: str  # its event's title, which names the match a score market leaves out


@dataclass(frozen=True)
class Pair:
    a: Side
    b: Side
    kind: str
    score: Decimal | None  # the title score, for a pair compared by title
    reasons: tuple[str, ...]
    read_by: str | None
    key: str | None = None  # the first market's terms key, which says the pair in words (D99)


def listed(found: Catalog, kind: str, words: str = "") -> list[Pair]:
    """The pairs of one kind, most similar titles first; with `words`, those where either
    market's title has every word."""
    status, by_model = _WHERE[kind]
    with found.connect() as db:
        rows = db.execute(_PAIRS, (status,)).fetchall()
    kept = [
        _pair(row, kind) for row in rows if by_model is None or (row[11] is not None) == by_model
    ]
    if not words.strip():
        return kept
    hits = {row.market_id for row in found.search(words, per_page=_EVERY)}
    return [p for p in kept if p.a.market_id in hits or p.b.market_id in hits]


def counts(found: Catalog) -> dict[str, int]:
    """How many pairs each kind has, in the order of KINDS."""
    by_status = found.pair_counts()
    return {
        kind: sum(
            n
            for (status, read), n in by_status.items()
            if status == _WHERE[kind][0] and _WHERE[kind][1] in (None, read)
        )
        for kind in KINDS
    }


def _pair(row: tuple, kind: str) -> Pair:
    a, venue_a, title_a, event_a, key, b, venue_b, title_b, event_b, score, reasons, read_by = row
    return Pair(
        Side(a, venue_a, title_a, event_a),
        Side(b, venue_b, title_b, event_b),
        kind,
        Decimal(score) if score else None,
        tuple(json.loads(reasons)),
        read_by,
        key,
    )


def keys_of(found: Catalog, pair: Pair) -> tuple[str | None, str | None]:
    """Each market's terms as Equinox compared them, as terms keys: the parsers' for an exact
    match, else the model's accepted readings (for a same bet, the latest that agree); None for a
    market without terms (D99)."""
    if pair.read_by is None:
        return (pair.key, _entry_key(found, pair.b.market_id)) if pair.key else (None, None)
    named = _READER.match(pair.read_by)
    if named is None:
        return None, None
    read = [_read_keys(found, m, named["model"], named["prompt"]) for m in (pair.a, pair.b)]
    agreeing = [key for key in read[0] if key in read[1]]
    if pair.kind == MODEL and agreeing:
        return agreeing[0], agreeing[0]
    return (read[0][0] if read[0] else None), (read[1][0] if read[1] else None)


def _entry_key(found: Catalog, market_id: str) -> str | None:
    with found.connect() as db:
        row = db.execute(
            "SELECT terms_key FROM entries WHERE market_id = ?", (market_id,)
        ).fetchone()
    return row[0] if row else None


def _read_keys(found: Catalog, side: Side, model: str, prompt: str) -> list[str]:
    """The market's accepted readings by this model and prompt, as terms keys, latest first."""
    query = (
        "SELECT terms FROM readings WHERE market_id = ? AND model = ? AND prompt = ? "
        "AND terms IS NOT NULL ORDER BY rowid DESC"
    )
    with found.connect() as db:
        rows = db.execute(query, (side.market_id, model, prompt)).fetchall()
    return [terms_key(ContractTerms.model_validate_json(body)) for (body,) in rows]
