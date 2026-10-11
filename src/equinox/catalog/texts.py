"""The market texts the term reader reads (D57): staged on disk while a refresh reads the
venues, then kept in the catalog only for the markets in unclear pairs.

A refresh reads about 287,000 markets, and their rules texts would need hundreds of megabytes in
memory. The stage writes each page's texts to a temporary SQLite file as it arrives; the catalog
copies the few thousand it needs; the stage is removed on exit, whether the refresh worked or not.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from equinox.models.catalog import UNCLEAR, MarketText


class TextStage:
    """Market texts written to disk as listing pages arrive, so 287,000 rules texts never sit in
    memory. The catalog keeps only those of markets in unclear pairs (D57). Removed on exit."""

    def __init__(self, cache_dir: Path) -> None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.path = cache_dir / f"texts-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.tmp"
        self._db = sqlite3.connect(self.path)
        self._db.executescript(
            "PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF; "
            "CREATE TABLE texts (market_id TEXT PRIMARY KEY, rules TEXT, strike TEXT);"
        )

    def add(self, texts: dict[str, MarketText]) -> None:
        rows = ((market, text.rules, text.strike) for market, text in texts.items())
        self._db.executemany("INSERT OR REPLACE INTO texts VALUES (?, ?, ?)", rows)
        self._db.commit()

    def __enter__(self) -> "TextStage":
        return self

    def __exit__(self, *exc: object) -> None:
        self._db.close()
        self.path.unlink(missing_ok=True)


def keep_texts(db: sqlite3.Connection, staged: Path) -> None:
    """Copy from the stage the texts of the markets the term reader may read (D57)."""
    db.execute("ATTACH DATABASE ? AS staged", (str(staged),))
    db.execute(
        "INSERT INTO texts SELECT market_id, rules, strike FROM staged.texts WHERE market_id IN "
        "(SELECT market_a FROM pairs WHERE status = ? "
        "UNION SELECT market_b FROM pairs WHERE status = ?)",
        (UNCLEAR, UNCLEAR),
    )
    db.commit()
    db.execute("DETACH DATABASE staged")
