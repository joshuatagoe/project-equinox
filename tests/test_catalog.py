"""feat-09 tests 1-2 and 6-8: reading every open market, the cache, and the command line.

The sample in snapshot-2026-10-11 is two pages of 20 events per venue, captured raw: 371 Kalshi
markets and 553 Polymarket markets, all Yes/No, none of them combos or Fed decisions. 84 of the
Polymarket markets are closed inside events that are still open, so 469 are listed. Edited copies
add the cases the sample lacks.
"""

import json
import shutil
from decimal import Decimal

import pytest

from equinox import catalog, cli
from equinox.adapters.base import FetchError
from equinox.adapters.fetch import DEFAULT_SNAPSHOT, FixtureFetcher
from equinox.adapters.kalshi import KalshiAdapter
from equinox.adapters.polymarket import PolymarketAdapter
from equinox.sources import Settings

NEW = DEFAULT_SNAPSHOT.parent / "snapshot-2026-10-11"


class Recorder:
    def __init__(self, fetch):
        self.fetch, self.urls, self.captured_at = fetch, [], fetch.captured_at

    def __call__(self, url):
        self.urls.append(url)
        return self.fetch(url)


def adapter(cls, fetch):
    return cls(fetch, [], "fixture", lambda: fetch.captured_at)


def sample_pages(cls, fetch):
    return list(adapter(cls, fetch).list_open(page_size=20, max_pages=2))


def copy_snapshot(tmp_path):
    return shutil.copytree(NEW, tmp_path / NEW.name)


def test_1_kalshi_lists_open_events_without_combos_and_pages_with_cursor():
    fetch = Recorder(FixtureFetcher(NEW))
    pages = sample_pages(KalshiAdapter, fetch)
    entries = [e for page in pages for e in page.entries]
    assert len(pages) == 2 and len(entries) == 371
    assert not any(e.market_id.startswith("kalshi:KXMVE") for e in entries)
    assert "cursor=" in fetch.urls[1] and all("with_nested_markets=true" in u for u in fetch.urls)
    mars = next(e for e in entries if e.market_id == "kalshi:KXELONMARS-99")
    assert (mars.yes_ask, mars.no_ask) == (Decimal("0.11"), Decimal("0.91"))
    # Three markets list 1.0000 on both sides: nobody is selling, so they have no asks.
    assert sum(e.yes_ask is None and e.no_ask is None for e in entries) == 3


def test_1_kalshi_fed_markets_in_the_catalog_carry_terms(tmp_path):
    snapshot = copy_snapshot(tmp_path)
    december = json.loads(
        (snapshot / "kalshi_event_KXFEDDECISION-26DEC.json").read_text(encoding="utf-8")
    )["event"]
    page = snapshot / "kalshi_catalog_1.json"
    data = json.loads(page.read_text(encoding="utf-8"))
    data["events"].insert(0, december)
    page.write_text(json.dumps(data), encoding="utf-8")
    entries = [e for p in sample_pages(KalshiAdapter, FixtureFetcher(snapshot)) for e in p.entries]
    fed = [e for e in entries if e.market_id.startswith("kalshi:KXFEDDECISION-26DEC")]
    assert len(fed) == 5 and all(e.terms is not None for e in fed)
    assert {e.terms.observed_on.isoformat() for e in fed} == {"2026-12-09"}


def test_1_a_closed_market_in_an_open_event_is_not_listed(tmp_path):
    # Added after a mutation check: the sample has no closed Kalshi market.
    snapshot = copy_snapshot(tmp_path)
    page = snapshot / "kalshi_catalog_1.json"
    data = json.loads(page.read_text(encoding="utf-8"))
    data["events"][0]["markets"][0]["status"] = "finalized"
    page.write_text(json.dumps(data), encoding="utf-8")
    entries = [e for p in sample_pages(KalshiAdapter, FixtureFetcher(snapshot)) for e in p.entries]
    assert len(entries) == 370 and "kalshi:KXELONMARS-99" not in {e.market_id for e in entries}


def test_2_polymarket_pages_with_after_cursor_and_never_by_offset():
    fetch = Recorder(FixtureFetcher(NEW))
    pages = sample_pages(PolymarketAdapter, fetch)
    assert sum(len(p.entries) for p in pages) == 469 and sum(p.skipped for p in pages) == 0
    assert "after_cursor=" in fetch.urls[1] and not any("offset=" in u for u in fetch.urls)


def test_2_a_market_that_is_not_yes_no_is_counted_not_listed(tmp_path):
    snapshot = copy_snapshot(tmp_path)
    page = snapshot / "polymarket_catalog_1.json"
    data = json.loads(page.read_text(encoding="utf-8"))
    market = next(m for e in data["events"] for m in e["markets"] if not m["closed"])
    market["outcomes"] = '["Up", "Down"]'
    page.write_text(json.dumps(data), encoding="utf-8")
    pages = sample_pages(PolymarketAdapter, FixtureFetcher(snapshot))
    assert sum(len(p.entries) for p in pages) == 468 and sum(p.skipped for p in pages) == 1


def fixture_settings(tmp_path):
    return Settings(source="fixtures", snapshot=NEW, cache_dir=tmp_path / "cache")


def test_7_refresh_then_load_returns_the_same_catalog(tmp_path):
    settings = fixture_settings(tmp_path)
    summary = catalog.refresh(settings)
    assert summary.entries == {"kalshi": 371, "polymarket": 469}
    loaded = catalog.load_latest(settings.cache_dir)
    assert loaded.summary == summary
    kraken = loaded.search(words="Kraken IPO")
    assert kraken and all(r.venue == "polymarket" for r in kraken)
    assert loaded.count(venue="kalshi") == 371


def test_6_a_refresh_that_fails_keeps_the_previous_catalog(tmp_path):
    settings = fixture_settings(tmp_path)
    catalog.refresh(settings)
    before = {p.name: p.read_bytes() for p in settings.cache_dir.iterdir()}
    calls = {"n": 0}

    def failing(venue):
        fixture = FixtureFetcher(NEW)

        def fetch(url):
            calls["n"] += 1
            if calls["n"] == 3:
                raise FetchError(f"{url}: connection reset")
            return fixture(url)

        fetch.captured_at = fixture.captured_at
        return fetch

    live = Settings(source="live", snapshot=NEW, cache_dir=settings.cache_dir)
    with pytest.raises(catalog.CatalogError, match="connection reset"):
        catalog.refresh(live, live_fetcher=failing, page_size=20, max_pages=2)
    after = {p.name: p.read_bytes() for p in settings.cache_dir.iterdir()}
    assert after == before


def test_8_cli_refresh_and_status(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("EQUINOX_CACHE_DIR", str(tmp_path / "cache"))
    flags = ["--source", "fixtures", "--snapshot", NEW.name]
    assert cli.main(["catalog", "refresh", *flags]) == 0
    out = capsys.readouterr().out
    assert "kalshi: 371 markets" in out and "polymarket: 469 markets" in out
    assert "Catalog saved" in out
    assert cli.main(["catalog", "status"]) == 0
    assert "840 markets" in capsys.readouterr().out


def test_8_cli_status_without_a_catalog_says_how_to_build_one(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("EQUINOX_CACHE_DIR", str(tmp_path / "empty"))
    assert cli.main(["catalog", "status"]) == 1
    assert "python -m equinox catalog refresh" in capsys.readouterr().out
