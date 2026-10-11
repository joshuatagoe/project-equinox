"""Model readings in the catalog file (D57): which pairs to read, and what reading them decided.

`to_read` lists the unclear pairs, most similar first, with what the reader reads of each market.
`record` saves every reading (accepted or not, with its problem) and each pair's new status: the
same bet, a different bet (kept for the record, shown as no match), or still unclear. Each
affected market then shows its best remaining pair, as after a refresh.
"""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from equinox.catalog.store import Catalog
from equinox.models.catalog import (
    NO_MATCH,
    SAME_BET,
    STATUSES,
    UNCLEAR,
    MarketText,
    ReadableMarket,
)

DIFFERENT = "different"
"""A pair whose readings are different bets. Not a market status: the market shows no match."""


class OldCatalogError(Exception):
    """A catalog saved before term reading existed, which has no texts to read."""


@dataclass(frozen=True)
class PairToRead:
    a: str
    b: str
    score: Decimal


@dataclass(frozen=True)
class PairDecision:
    a: str
    b: str
    status: str  # SAME_BET, DIFFERENT or UNCLEAR
    reasons: tuple[str, ...]
    read_by: str  # the model and prompt that read it, so a newer one reads it again


@dataclass(frozen=True)
class ReadingRow:
    market_id: str
    call: int
    terms: str | None  # the accepted terms as JSON
    problem: str
    evidence: str


def to_read(found: Catalog, reader: str) -> tuple[list[PairToRead], dict[str, ReadableMarket]]:
    """The pairs to read, most similar first: every unclear pair, and every pair another
    `reader` (an older prompt or another model) decided. Then every market in them, with texts."""
    pairs_query = (
        "SELECT market_a, market_b, score FROM pairs "
        "WHERE (status = ? AND read_by IS NULL) OR (read_by IS NOT NULL AND read_by != ?) "
        "ORDER BY CAST(score AS REAL) DESC, market_a, market_b"
    )
    markets_query = (
        "SELECT e.market_id, e.venue, e.event_title, e.title, e.outcome_label, e.closes_at, "
        "t.rules, t.strike FROM entries e JOIN texts t ON t.market_id = e.market_id"
    )
    try:
        with found.connect() as db:
            found_pairs = db.execute(pairs_query, (UNCLEAR, reader))
            pairs = [PairToRead(a, b, Decimal(score)) for a, b, score in found_pairs]
            markets = {row[0]: _market(row) for row in db.execute(markets_query)}
    except sqlite3.OperationalError as error:
        raise OldCatalogError(f"{found.path.name} has no texts to read ({error})") from error
    return pairs, markets


def record(
    found: Catalog,
    model: str,
    prompt: str,
    readings: Sequence[ReadingRow],
    decisions: Sequence[PairDecision],
) -> None:
    """Save the readings and the pairs' new statuses, then each affected market's best pair."""
    rows = [(r.market_id, r.call, r.terms, r.problem, r.evidence, model, prompt) for r in readings]
    with found.connect(write=True) as db:
        db.executemany("INSERT INTO readings VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        for d in decisions:
            db.execute(
                "UPDATE pairs SET status = ?, reasons = ?, read_by = ? "
                "WHERE market_a = ? AND market_b = ?",
                (d.status, json.dumps(list(d.reasons)), d.read_by, d.a, d.b),
            )
        for market in {m for d in decisions for m in (d.a, d.b)}:
            _show_best_pair(db, market)
        db.commit()


def _show_best_pair(db: sqlite3.Connection, market: str) -> None:
    """The market's status, partner and reasons from its best pair: same bet, then unclear."""
    found = db.execute(
        "SELECT market_a, market_b, status, score, reasons, read_by FROM pairs "
        "WHERE (market_a = ? OR market_b = ?) AND status IN (?, ?)",
        (market, market, SAME_BET, UNCLEAR),
    ).fetchall()
    if not found:
        db.execute(
            "UPDATE entries SET status = ?, rank = ?, partner = NULL, score = NULL, "
            "reasons = '[]', read_by = NULL WHERE market_id = ?",
            (NO_MATCH, STATUSES.index(NO_MATCH), market),
        )
        return
    a, b, status, score, reasons, read_by = min(
        found, key=lambda row: (STATUSES.index(row[2]), -Decimal(row[3] or 0))
    )
    db.execute(
        "UPDATE entries SET status = ?, rank = ?, partner = ?, score = ?, reasons = ?, "
        "read_by = ? WHERE market_id = ?",
        (status, STATUSES.index(status), b if a == market else a, score, reasons, read_by, market),
    )


def _market(row: tuple) -> ReadableMarket:
    market_id, venue, event, title, label, closes, rules, strike = row
    closes_at = datetime.fromisoformat(closes) if closes else None
    text = MarketText(rules, strike)
    return ReadableMarket(market_id, venue, event, title, label, closes_at, text)
