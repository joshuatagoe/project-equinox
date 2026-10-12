"""The command line's catalog commands: `catalog refresh`, `catalog status` and `match --catalog`.

Exit codes: 0 when the command did what it says, 1 when there is no catalog or a refresh failed
(the previous catalog is kept), and 4 for bad arguments, as for every command (D27, D44).
"""

import argparse
import os
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime

from equinox import catalog
from equinox.catalog import CatalogError
from equinox.catalog.readings import OldCatalogError
from equinox.models import EquivalenceCluster
from equinox.models.catalog import CatalogSummary
from equinox.reader import client, pricing, run
from equinox.reader.client import Ask, ReaderError
from equinox.sources import LiveFetchers, Loaded, Settings

REFRESH = catalog.REFRESH_COMMAND
SHOWN_PAIRS = 20


def command(
    args: argparse.Namespace,
    settings: Settings,
    live_fetcher: LiveFetchers | None = None,
    ask: Ask | None = None,
) -> int:
    if args.action == "refresh":
        return refresh(settings, live_fetcher)
    if args.action == "read":
        return read(settings, args.limit, args.model, args.workers, ask)
    return status(settings)


def refresh(settings: Settings, live_fetcher: LiveFetchers | None = None) -> int:
    if settings.source == "live":
        print("Reading every open market on both venues, live...", flush=True)
    else:
        print(f"Reading the sample of every venue's listing in {settings.snapshot.name}...")
    try:
        summary = catalog.refresh(settings, live_fetcher, lambda line: print(line, flush=True))
    except CatalogError as error:
        print(f"Catalog not refreshed: {error}")
        return 1
    print(f"Catalog saved in {settings.cache_dir}.")
    print("\n".join(_summary(summary)))
    return 0


def read(settings: Settings, limit: int, model: str, workers: int, ask: Ask | None) -> int:
    """Read the terms of at most `limit` markets in unclear pairs, and say what it cost (D57)."""
    key = client.load_key(os.environ)
    if key is None:
        print(f"No {client.KEY_NAME} in the environment or in .env at the repository root.")
        print("Nothing was read.")
        return 1
    found = _latest(settings)
    if found is None:
        return 1
    ask = ask or client.Cached(client.Claude(key), settings.cache_dir / "readings.sqlite")
    print(f"Reading at most {limit:,} markets of unclear pairs with {model}...", flush=True)
    try:
        report = run.read_catalog(found, ask, model, limit, _say, workers)
    except (ReaderError, OldCatalogError) as error:
        print(f"Nothing was recorded: {error}. Answers already received are cached.")
        return 1
    r = report
    print(
        f"{r.markets:,} markets read in {_count(r.calls, 'request')}: {r.accepted:,} readings "
        f"accepted, {r.rejected:,} rejected by the checks."
    )
    print(
        f"Pairs decided: {r.same_bet:,} same bet, {r.different:,} different, "
        f"{r.unclear:,} still unclear."
    )
    if isinstance(ask, client.Cached):
        print(
            f"Spent on {_count(ask.sent, 'new request')}: {ask.input_tokens:,} input tokens and "
            f"{ask.output_tokens:,} output tokens. {_count(ask.reused, 'request')} answered "
            "from the cache at no cost."
        )
    else:
        print(f"Used {r.input_tokens:,} input tokens and {r.output_tokens:,} output tokens.")
    return 0


def model_read(
    settings: Settings, market_id: str, live_fetcher: LiveFetchers | None
) -> tuple[EquivalenceCluster, Loaded] | str:
    """The market's same bet as read by a model, ready to route (D58); else why not, or "" when
    the catalog has none for it."""
    try:
        found = catalog.load_latest(settings.cache_dir)
        return pricing.priced_group(found, market_id, settings, live_fetcher) if found else ""
    except (CatalogError, pricing.NotModelRead, sqlite3.Error):
        return ""
    except pricing.PricingError as error:
        return str(error)


def status(settings: Settings) -> int:
    found = _latest(settings)
    if found is None:
        return 1
    print("\n".join(_summary(found.summary)))
    return 0


def unclear_pairs(settings: Settings) -> int:
    """The catalog's summary and its most similar title pairs, which are never routed."""
    found = _latest(settings)
    if found is None:
        return 1
    print("\n".join(_summary(found.summary)))
    pairs = found.unclear_pairs(SHOWN_PAIRS)
    if pairs:
        print(f"\nUnclear pairs, most similar titles first (the first {len(pairs)}; never routed):")
    for a, b, score, reasons in pairs:
        print(f"  {a} ~ {b} (title score {score}): {reasons[0]}")
    return 0


def as_json(settings: Settings) -> dict:
    """The catalog's summary and unclear pairs for `match --catalog --json`."""
    try:
        found = catalog.load_latest(settings.cache_dir)
    except CatalogError as error:
        return {"error": f"{error} Build a new one with: {REFRESH}"}
    if found is None:
        return {"error": f"No catalog in {settings.cache_dir}. Build one with: {REFRESH}"}
    summary = {**asdict(found.summary), "refreshed_at": found.summary.refreshed_at.isoformat()}
    pairs = [
        {"market_a": a, "market_b": b, "title_score": str(score), "reasons": reasons}
        for a, b, score, reasons in found.unclear_pairs(SHOWN_PAIRS)
    ]
    return {"summary": summary, "unclear": pairs}


def _latest(settings: Settings) -> catalog.Catalog | None:
    try:
        found = catalog.load_latest(settings.cache_dir)
    except CatalogError as error:
        print(f"{error}\nBuild a new one with: {REFRESH}")
        return None
    if found is None:
        print(f"No catalog in {settings.cache_dir}. Build one with: {REFRESH}")
    return found


def _summary(s: CatalogSummary) -> list[str]:
    vetoes = ", ".join(f"{kind} {count:,}" for kind, count in s.vetoes.items()) or "none"
    return [
        f"Catalog: {s.describe(datetime.now(UTC))}.",
        f"  Left out: {s.skipped:,} markets that aren't Yes/No or couldn't be read.",
        f"  Same bet on two venues, by contract terms: {s.same_bet_groups:,} outcomes.",
        f"  Title candidates: {s.candidates:,}. Unclear, never routed: {s.ambiguous:,}. "
        f"Different bets: {s.distinct:,} ({vetoes}).",
        f"  Took {s.read_seconds:,.1f} s to read and {s.compare_seconds:,.1f} s to compare.",
    ]


def _say(line: str) -> None:
    print(line, flush=True)


def _count(n: int, noun: str) -> str:
    return f"{n:,} {noun}{'' if n == 1 else 's'}"
