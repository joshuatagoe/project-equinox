"""The catalog's file: one SQLite database per refresh, searchable by title words (D48, D50).

The file holds three tables: every market with its status and best match (`entries`), every
matched pair (`pairs`), and the refresh summary (`summary`). An FTS5 index on the titles makes
word search fast. A new catalog is written under a temporary name and renamed when complete, so a
reader never sees half a file and a failed write leaves the previous catalog in place. Older
catalogs are then removed, except one still open elsewhere, which the next refresh removes.
"""

import json
import os
import re
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from equinox.catalog.texts import TextStage, keep_texts
from equinox.matcher import terms_key
from equinox.matcher.compare import Comparison, described_title
from equinox.models.catalog import (
    STATUSES,
    CatalogEntry,
    CatalogRow,
    CatalogSummary,
    MarketText,
)

PATTERN = "catalog-*.sqlite"

_SCHEMA = """
PRAGMA journal_mode = OFF;
PRAGMA synchronous = OFF;
CREATE TABLE entries (
    market_id TEXT PRIMARY KEY, venue TEXT NOT NULL, event_title TEXT NOT NULL,
    title TEXT NOT NULL, outcome_label TEXT NOT NULL, described TEXT, closes_at TEXT,
    tradable INTEGER NOT NULL, yes_ask TEXT, no_ask TEXT, terms_key TEXT, status TEXT NOT NULL,
    rank INTEGER NOT NULL, partner TEXT, score TEXT, reasons TEXT NOT NULL, read_by TEXT
);
CREATE TABLE pairs (
    market_a TEXT NOT NULL, market_b TEXT NOT NULL, status TEXT NOT NULL, score TEXT,
    reasons TEXT NOT NULL, read_by TEXT
);
CREATE TABLE readings (
    market_id TEXT NOT NULL, call INTEGER NOT NULL, terms TEXT, problem TEXT NOT NULL,
    evidence TEXT NOT NULL, model TEXT NOT NULL, prompt TEXT NOT NULL
);
CREATE TABLE summary (body TEXT NOT NULL);
CREATE TABLE texts (market_id TEXT PRIMARY KEY, rules TEXT NOT NULL, strike TEXT NOT NULL);
CREATE VIRTUAL TABLE words USING fts5(
    title, event_title, outcome_label, content = 'entries', content_rowid = 'rowid'
);
"""
_INDEXES = """
INSERT INTO words (rowid, title, event_title, outcome_label)
    SELECT rowid, title, event_title, outcome_label FROM entries;
CREATE INDEX entries_order ON entries (rank);
CREATE INDEX pairs_order ON pairs (status, score DESC);
"""
_ROW = """
SELECT e.market_id, e.venue, e.event_title, e.title, e.outcome_label, e.yes_ask, e.no_ask,
       e.terms_key, e.status, e.partner, coalesce(p.described, p.title), e.score, e.reasons,
       e.read_by
FROM entries e LEFT JOIN entries p ON p.market_id = e.partner
"""
_TOKEN = re.compile(r"\w+")


def save(
    cache_dir: Path,
    entries: Sequence[CatalogEntry],
    found: Comparison,
    summary: CatalogSummary,
    texts: TextStage | None = None,
) -> Path:
    """Write the catalog to a new file in `cache_dir` and return its path. Raises OSError or
    sqlite3.Error, leaving the previous catalog as it was."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    final = cache_dir / f"catalog-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.sqlite"
    temp = final.with_suffix(".tmp")
    try:
        with closing(sqlite3.connect(temp)) as db:
            db.executescript(_SCHEMA)
            db.executemany(f"INSERT INTO entries VALUES ({_marks(17)})", _entries(entries, found))
            db.executemany(f"INSERT INTO pairs VALUES ({_marks(6)})", _pairs(entries, found))
            db.execute("INSERT INTO summary VALUES (?)", (_dump(summary),))
            db.commit()
            if texts is not None:
                keep_texts(db, texts.path)
            db.executescript(_INDEXES)
        os.replace(temp, final)
    finally:
        temp.unlink(missing_ok=True)
    for older in cache_dir.glob(PATTERN):
        if older.name < final.name:
            try:
                older.unlink()
            except OSError:  # open in another process, such as the web server: removed next time
                pass
    return final


def latest(cache_dir: Path) -> Path | None:
    found = sorted(cache_dir.glob(PATTERN)) if cache_dir.is_dir() else []
    return found[-1] if found else None


class Catalog:
    """A saved catalog, opened read-only for each question."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self.connect() as db:
            self.summary = _load(db.execute("SELECT body FROM summary").fetchone()[0])

    def search(
        self, words: str = "", venue: str = "", status: str = "", page: int = 1, per_page: int = 50
    ) -> list[CatalogRow]:
        """Markets whose titles contain every word (as a prefix), best status first, then in
        the order the venues listed them, which keeps each event's markets together."""
        where, args = _where(words, venue, status)
        order = "ORDER BY e.rank, e.rowid LIMIT ? OFFSET ?"  # in listing order, by event
        with self.connect() as db:
            found = db.execute(
                f"{_ROW} {where} {order}", (*args, per_page, (max(page, 1) - 1) * per_page)
            )
            return [_row(values) for values in found]

    def count(self, words: str = "", venue: str = "", status: str = "") -> int:
        where, args = _where(words, venue, status)
        with self.connect() as db:
            return db.execute(f"SELECT count(*) FROM entries e {where}", args).fetchone()[0]

    def unclear_pairs(self, limit: int) -> list[tuple[str, str, Decimal, list[str]]]:
        """The title pairs most likely to be the same bet: (market, market, score, reasons)."""
        query = "SELECT market_a, market_b, score, reasons FROM pairs WHERE status = ?"
        with self.connect() as db:
            found = db.execute(
                f"{query} ORDER BY score DESC, market_a LIMIT ?", (STATUSES[1], limit)
            )
            return [(a, b, Decimal(score), json.loads(reasons)) for a, b, score, reasons in found]

    def texts(self) -> dict[str, MarketText]:
        """The rules text and strike fields of every market in an unclear pair."""
        with self.connect() as db:
            found = db.execute("SELECT market_id, rules, strike FROM texts")
            return {market: MarketText(rules, strike) for market, rules, strike in found}

    def readings(self) -> dict[str, str]:
        """Why each market's latest reading was rejected, by market; "" when it was accepted."""
        with self.connect() as db:
            found = db.execute("SELECT market_id, problem FROM readings ORDER BY rowid")
            return dict(found.fetchall())

    def pair_counts(self) -> dict[tuple[str, bool], int]:
        """How many pairs have each status, split by whether a model read them."""
        with self.connect() as db:
            query = "SELECT status, read_by IS NOT NULL, count(*) FROM pairs GROUP BY 1, 2"
            found = db.execute(query)
            return {(status, bool(read)): n for status, read, n in found}

    def venues(self) -> list[str]:
        return sorted(self.summary.entries)

    def connect(self, write: bool = False) -> closing[sqlite3.Connection]:
        """A connection to the file: read-only unless `write`, which only `catalog read` uses."""
        if write:
            return closing(sqlite3.connect(self.path))
        return closing(sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True))


def _entries(entries: Sequence[CatalogEntry], found: Comparison):
    for position, e in enumerate(entries):
        status, pair = found.status(position), found.best.get(position)
        partner = found.partner(position)
        yield (
            e.market_id,
            e.venue,
            e.event_title,
            e.title,
            e.outcome_label,
            _unless_same(described_title(e), e.title),
            e.closes_at.isoformat() if e.closes_at else None,
            int(e.tradable),
            _text(e.yes_ask),
            _text(e.no_ask),
            terms_key(e.terms) if e.terms else None,
            status,
            STATUSES.index(status),
            None if partner is None else entries[partner].market_id,
            _text(pair.score) if pair else None,
            json.dumps(list(pair.reasons) if pair else []),
            None,  # read_by: set when a model reads the pair (D57)
        )


def _pairs(entries: Sequence[CatalogEntry], found: Comparison):
    for pair in found.pairs:
        ids = (entries[pair.a].market_id, entries[pair.b].market_id)
        yield (*ids, pair.status, _text(pair.score), json.dumps(list(pair.reasons)), None)


def _where(words: str, venue: str, status: str) -> tuple[str, list]:
    clauses, args = [], []
    tokens = _TOKEN.findall(words.lower())
    if tokens:
        clauses.append("e.rowid IN (SELECT rowid FROM words WHERE words MATCH ?)")
        args.append(" ".join(f'"{token}"*' for token in tokens))
    if venue:
        clauses.append("e.venue = ?")
        args.append(venue)
    if status in STATUSES:
        clauses.append("e.rank = ?")
        args.append(STATUSES.index(status))
    return ("WHERE " + " AND ".join(clauses) if clauses else ""), args


def _row(values: tuple) -> CatalogRow:
    market_id, venue, event, title, label, yes, no, key, status, partner, named, score, why, by = (
        values
    )
    return CatalogRow(
        market_id,
        venue,
        event,
        title,
        label,
        _decimal(yes),
        _decimal(no),
        key,
        status,
        partner,
        named,
        _decimal(score),
        tuple(json.loads(why)),
        by,
    )


def _dump(summary: CatalogSummary) -> str:
    return json.dumps({**asdict(summary), "refreshed_at": summary.refreshed_at.isoformat()})


def _load(body: str) -> CatalogSummary:
    fields = json.loads(body)
    return CatalogSummary(
        **{**fields, "refreshed_at": datetime.fromisoformat(fields["refreshed_at"])}
    )


def _unless_same(described: str, title: str) -> str | None:
    """The title as compared, stored only where the outcome label added to it."""
    return None if described == title else described


def _marks(n: int) -> str:
    return ", ".join("?" * n)


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)
