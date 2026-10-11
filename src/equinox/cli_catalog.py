"""The command line's catalog commands: `catalog refresh`, `catalog status` and `match --catalog`.

Exit codes: 0 when the command did what it says, 1 when there is no catalog or a refresh failed
(the previous catalog is kept), and 4 for bad arguments, as for every command (D27, D44).
"""

from dataclasses import asdict
from datetime import UTC, datetime

from equinox import catalog
from equinox.catalog import CatalogError
from equinox.models.catalog import CatalogSummary
from equinox.sources import LiveFetchers, Settings

REFRESH = catalog.REFRESH_COMMAND
SHOWN_PAIRS = 20


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
