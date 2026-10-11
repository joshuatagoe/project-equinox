"""feat-08: discovery (D47), listings without books and books on demand (D49), snapshots (D51).

Expected values come from the raw responses in snapshot-2026-10-11, read by hand: 11 open Kalshi
meetings, 3 Polymarket decision events among 37 `fed-rates` events, and the December books.
"""

import json
import shutil
from decimal import Decimal

import pytest

from equinox import cli, sources
from equinox.adapters.base import TrackedEvent
from equinox.adapters.fetch import DEFAULT_SNAPSHOT, FixtureFetcher
from equinox.adapters.kalshi import KalshiAdapter
from equinox.adapters.polymarket import PolymarketAdapter
from equinox.matcher import build_clusters
from equinox.models import OrderRequest
from equinox.router import simulate
from equinox.sources import Settings

NEW = DEFAULT_SNAPSHOT.parent / "snapshot-2026-10-11"
KALSHI_MEETINGS = [
    f"KXFEDDECISION-{m}"
    for m in ("26OCT", "26DEC", "27JAN", "27MAR", "27APR", "27JUN", "27JUL", "27SEP", "27OCT")
] + ["KXFEDDECISION-27DEC", "KXFEDDECISION-28JAN"]
POLY_OCT = "fed-decision-in-october-20260617190323537"
POLY_DEC = "fed-decision-in-december-20260729232808632"
POLY_JAN = "fed-decision-in-january-20260729233815502"
FED = "fed_decision"


class Recorder:
    """A fetcher that remembers every URL it was asked for."""

    def __init__(self, fetch):
        self.fetch, self.urls = fetch, []
        self.captured_at = fetch.captured_at

    def __call__(self, url):
        self.urls.append(url)
        return self.fetch(url)


def make(cls, fetch, tracked=()):
    return cls(fetch, list(tracked), "fixture", lambda: fetch.captured_at)


def copy_snapshot(tmp_path):
    target = tmp_path / NEW.name
    shutil.copytree(NEW, target)
    return target


def books_requested(urls):
    return [u for u in urls if u.endswith("/orderbook") or "/book?" in u]


# Tests 1-3: discovery.


def test_1_kalshi_discovers_every_open_meeting_in_date_order():
    kalshi = make(KalshiAdapter, FixtureFetcher(NEW))
    assert kalshi.discover(FED) == [TrackedEvent(t, FED) for t in KALSHI_MEETINGS]
    assert kalshi.discover("stock_close_above") == []


def test_2_polymarket_keeps_only_open_neg_risk_decision_events(tmp_path):
    snapshot = copy_snapshot(tmp_path)
    page = snapshot / "polymarket_discovery_fed-rates_1.json"
    data = json.loads(page.read_text(encoding="utf-8"))
    assert len(data["events"]) == 37  # 34 of them are other Fed and Treasury events
    closed = {"slug": "fed-decision-in-december", "title": "Fed decision in December?"}
    not_neg_risk = {"slug": "fed-decision-in-march-x", "title": "Fed Decision in March?"}
    data["events"] += [
        closed | {"closed": True, "negRisk": True, "endDate": "2025-12-10T00:00:00Z"},
        not_neg_risk | {"closed": False, "negRisk": False, "endDate": "2027-03-18T00:00:00Z"},
    ]
    page.write_text(json.dumps(data), encoding="utf-8")
    poly = make(PolymarketAdapter, FixtureFetcher(snapshot))
    assert poly.discover(FED) == [TrackedEvent(s, FED) for s in (POLY_OCT, POLY_DEC, POLY_JAN)]
    assert poly.discover("stock_close_above") == []


def test_3_polymarket_discovery_pages_with_after_cursor(tmp_path):
    snapshot = copy_snapshot(tmp_path)
    first = snapshot / "polymarket_discovery_fed-rates_1.json"
    data = json.loads(first.read_text(encoding="utf-8"))
    january = next(e for e in data["events"] if e["slug"] == POLY_JAN)
    data["events"].remove(january)
    data["next_cursor"] = "page-two"
    first.write_text(json.dumps(data), encoding="utf-8")
    second = {"events": [january], "next_cursor": None}
    (snapshot / "polymarket_discovery_fed-rates_2.json").write_text(json.dumps(second))
    index = json.loads((snapshot / "index.json").read_text(encoding="utf-8"))
    url = index["files"]["polymarket_discovery_fed-rates_1.json"] + "&after_cursor=page-two"
    index["files"]["polymarket_discovery_fed-rates_2.json"] = url
    (snapshot / "index.json").write_text(json.dumps(index), encoding="utf-8")

    fetch = Recorder(FixtureFetcher(snapshot))
    found = make(PolymarketAdapter, fetch).discover(FED)
    assert [e.event_id for e in found] == [POLY_OCT, POLY_DEC, POLY_JAN]
    assert len(fetch.urls) == 2 and "after_cursor=page-two" in fetch.urls[1]


# Tests 4-5: listings without books, books on demand.


@pytest.mark.parametrize("cls", [KalshiAdapter, PolymarketAdapter], ids=["kalshi", "polymarket"])
def test_4_listing_requests_no_books_and_prices_from_the_listing(cls):
    fetch = Recorder(FixtureFetcher(NEW))
    adapter = make(cls, fetch)
    adapter.tracked = adapter.discover(FED)
    listed = adapter.list_markets()
    assert listed.markets and books_requested(fetch.urls) == []
    for market in listed.markets:
        assert market.books is None
        booked = adapter.fetch_books(market)
        for side in ("YES", "NO"):
            asks = booked.books[side].asks
            assert market.best_asks[side] == (asks[0].price if asks else None), market.market_id


def test_5_pricing_one_outcome_fetches_only_that_groups_books():
    fetchers = {}

    def live(venue):
        fetchers[venue] = Recorder(FixtureFetcher(NEW))
        return fetchers[venue]

    loaded = sources.load_markets(Settings(source="live"), live, with_books=False)
    before = {venue: len(f.urls) for venue, f in fetchers.items()}
    assert all(books_requested(f.urls) == [] for f in fetchers.values())
    cluster = next(
        c for c in build_clusters(loaded.markets) if "2026-12-09|eq|0|bps" in c.cluster_id
    )
    booked = sources.ensure_books(cluster, loaded)
    assert all(m.books is not None for m in booked.markets)
    new_urls = [u for venue, f in fetchers.items() for u in f.urls[before[venue] :]]
    assert sorted(new_urls) == sorted(books_requested(new_urls))
    assert len(new_urls) == 3  # one Kalshi orderbook, two Polymarket token books


# Tests 6-8: clusters across meetings, the old snapshot, a failed live discovery.


def test_6_every_shared_meeting_forms_cross_venue_clusters():
    loaded = sources.load_markets(Settings(source="fixtures", snapshot=NEW), with_books=False)
    clusters = build_clusters(loaded.markets)
    shared = [c for c in clusters if len({m.venue for m in c.markets}) == 2]
    alone = [c for c in clusters if len(c.markets) == 1]
    assert len(shared) == 15 and len(alone) == 40
    assert {c.cluster_id.split("|")[3] for c in shared} == {
        "2026-10-28",
        "2026-12-09",
        "2027-01-27",
    }
    assert all(c.markets[0].venue == "kalshi" for c in alone)


def test_7_a_snapshot_without_discovery_uses_the_pinned_events():
    loaded = sources.load_markets(Settings(source="fixtures"))
    assert len(loaded.markets) == 10
    notes = [w for w in loaded.warnings if "couldn't discover" in w]
    assert len(notes) == 2 and all("pinned" in w for w in notes)


def test_8_a_failed_live_discovery_keeps_the_live_data():
    loaded = sources.load_markets(
        Settings(source="live"), lambda venue: FixtureFetcher(DEFAULT_SNAPSHOT)
    )
    assert len(loaded.markets) == 10
    assert {m.data_source for m in loaded.markets} == {"live"}
    assert not any("live data unavailable" in w for w in loaded.warnings)
    assert any("couldn't discover" in w for w in loaded.warnings)


# Test 9: the router refuses a market without books.


def test_9_simulate_refuses_a_market_without_books():
    loaded = sources.load_markets(Settings(source="fixtures", snapshot=NEW), with_books=False)
    cluster = next(c for c in build_clusters(loaded.markets) if len(c.markets) == 2)
    order = OrderRequest(market_id=cluster.markets[0].market_id, outcome="YES", quantity=Decimal(1))
    with pytest.raises(ValueError, match=cluster.markets[0].market_id):
        simulate(order, cluster, cluster.markets[0].captured_at)


# Test 10: the command line on the new snapshot.


def run(capsys, *argv):
    code = cli.main([*argv, "--source", "fixtures", "--snapshot", NEW.name, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_10_markets_lists_every_discovered_market(capsys):
    code, listing = run(capsys, "markets")
    venues = [m["venue"] for m in listing["markets"]]
    assert code == 0 and (venues.count("kalshi"), venues.count("polymarket")) == (55, 15)


@pytest.mark.parametrize(
    "side, winner, totals",
    [
        ("YES", "polymarket:3215007", {"polymarket:3215007": "23.8855", "kalshi": "27.63"}),
        (
            "NO",
            "kalshi:KXFEDDECISION-26DEC-H0",
            {"polymarket:3215007": "78.858", "kalshi": "76.9691"},
        ),
    ],
)
def test_10_a_december_order_routes_with_hand_computed_totals(capsys, side, winner, totals):
    market = "kalshi:KXFEDDECISION-26DEC-H0"
    code, trace = run(
        capsys, "simulate", "--market", market, "--outcome", side, "--quantity", "100"
    )
    assert (code, trace["status"], trace["decision"]["winner"]) == (0, "ROUTED", winner)
    found = {q["market_id"]: Decimal(q["total_cost"]) for q in trace["quotes"]}
    assert found["polymarket:3215007"] == Decimal(totals["polymarket:3215007"])
    assert found[market] == Decimal(totals["kalshi"])


def test_10_an_unknown_snapshot_is_invalid_input(capsys):
    code = cli.main(
        ["markets", "--source", "fixtures", "--snapshot", "snapshot-1999-01-01", "--json"]
    )
    assert code == 4 and json.loads(capsys.readouterr().out)["status"] == "INVALID_INPUT"
