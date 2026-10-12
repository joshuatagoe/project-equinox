"""The model's decisions, kept across a refresh (feat-14, D91).

A refresh writes a new catalog and removes the old one, and every pair starts unclear again. So,
before the refresh, `keep` takes each pair a model decided, its readings, and both markets' rules;
after it, `apply` records the same decision in the new catalog for each pair that is still an
unclear pair of the same two markets, with both markets' rules and strike fields unchanged. A
pair whose rules changed stays unclear until `catalog read` reads it again. Nothing here calls the
model.
"""

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from equinox.catalog import readings
from equinox.catalog.store import Catalog, latest
from equinox.models.catalog import UNCLEAR

_READER = re.compile(r"^(?P<model>.+) \(prompt (?P<prompt>[^)]+)\)$")


@dataclass
class Kept:
    """What a catalog's model decided, and what it read to decide it."""

    pairs: list[tuple[str, str, str, tuple[str, ...], str]] = field(default_factory=list)
    """(market, market, status, reasons, read_by)"""
    readings: dict[str, list[tuple]] = field(default_factory=dict)  # market -> reading rows
    texts: dict[str, tuple[str, str]] = field(default_factory=dict)  # market -> (rules, strike)


def keep(cache_dir: Path) -> Kept:
    """The model's decisions in the newest catalog, before a refresh replaces it."""
    path = latest(cache_dir)
    if path is None:
        return Kept()
    try:
        with Catalog(path).connect() as db:
            pairs = db.execute(
                "SELECT market_a, market_b, status, reasons, read_by FROM pairs "
                "WHERE read_by IS NOT NULL"
            ).fetchall()
            markets = sorted({m for a, b, *_ in pairs for m in (a, b)})
            return Kept(
                pairs=[(a, b, s, tuple(json.loads(r)), by) for a, b, s, r, by in pairs],
                readings=_rows(db, "SELECT * FROM readings", markets),
                texts=_texts(db, markets),
            )
    except (sqlite3.Error, ValueError):  # an older or unreadable catalog: nothing to keep
        return Kept()


def apply(kept: Kept, cache_dir: Path) -> int:
    """Record the kept decisions in the newest catalog; how many pairs were carried."""
    path = latest(cache_dir)
    if path is None or not kept.pairs:
        return 0
    found = Catalog(path)
    with found.connect() as db:
        unclear = {
            frozenset(pair): pair
            for pair in db.execute(
                "SELECT market_a, market_b FROM pairs WHERE status = ? AND read_by IS NULL",
                (UNCLEAR,),
            )
        }
        texts = _texts(db, sorted(kept.texts))
    by_reader = _decisions(kept, unclear, texts)
    for (model, prompt), (rows, decisions) in by_reader.items():
        flat = [row for market_rows in rows.values() for row in market_rows]
        readings.record(found, model, prompt, flat, decisions)
    return sum(len(decisions) for _, decisions in by_reader.values())


def _decisions(kept: Kept, unclear: dict, texts: dict) -> dict[tuple[str, str], tuple]:
    """By (model, prompt): each market's readings, once, and the decisions to record."""
    by_reader: dict[tuple[str, str], tuple[dict, list]] = {}
    for a, b, status, reasons, read_by in kept.pairs:
        now, named = unclear.get(frozenset((a, b))), _READER.match(read_by)
        same_rules = all(m in kept.texts and texts.get(m) == kept.texts[m] for m in (a, b))
        if now is None or named is None or not same_rules:
            continue
        reader = (named["model"], named["prompt"])
        rows, decisions = by_reader.setdefault(reader, ({}, []))
        for market in (a, b):
            rows.setdefault(
                market,
                [
                    readings.ReadingRow(market, call, terms, problem, evidence)
                    for _, call, terms, problem, evidence, *by in kept.readings.get(market, [])
                    if tuple(by) == reader
                ],
            )
        decisions.append(readings.PairDecision(*now, status, reasons, read_by))
    return by_reader


def _rows(db: sqlite3.Connection, query: str, markets: list[str]) -> dict[str, list[tuple]]:
    """Each market's rows, read in one pass rather than one query per market."""
    wanted, found = set(markets), {market: [] for market in markets}
    for row in db.execute(query):
        if row[0] in wanted:
            found[row[0]].append(row)
    return found


def _texts(db: sqlite3.Connection, markets: list[str]) -> dict[str, tuple[str, str]]:
    wanted = set(markets)
    found = db.execute("SELECT market_id, rules, strike FROM texts")
    return {market: (rules, strike) for market, rules, strike in found if market in wanted}
