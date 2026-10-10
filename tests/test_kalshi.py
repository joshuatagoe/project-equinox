"""feat-02a acceptance tests: the Kalshi adapter on the 2026-10-10 snapshot (architecture 5.2).

Tests 1-9 are the lane PRD's table. The rest cover the adapter contract (5.1, D37) and the
golden file. Edited responses live in a copy of the snapshot under tmp_path; the fixture itself
is never changed.
"""

import json
import shutil
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from equinox.adapters.base import FetchError, TrackedEvent
from equinox.adapters.fetch import DEFAULT_SNAPSHOT, FixtureFetcher
from equinox.adapters.kalshi import KalshiAdapter
from equinox.models import Collateral, ContractTerms, FeeSchedule

D = Decimal
EVENT = "KXFEDDECISION-26OCT"
TICKERS = [f"{EVENT}-{suffix}" for suffix in ("C26", "C25", "H0", "H25", "H26")]
BASE = "https://external-api.kalshi.com/trade-api/v2"
EVENT_FILE = f"kalshi_event_{EVENT}.json"
CAPTURED_AT = datetime(2026, 10, 10, 20, 44, 29, 495262, tzinfo=UTC)
FED = [TrackedEvent(EVENT, "fed_decision")]


def run(snapshot=DEFAULT_SNAPSHOT, family="fed_decision", data_source="fixture"):
    fetch = FixtureFetcher(snapshot)
    tracked = [TrackedEvent(EVENT, family)]
    return KalshiAdapter(fetch, tracked, data_source, lambda: fetch.captured_at).fetch_markets()


def by_ticker(result):
    return {market.native_id: market for market in result.markets}


def edited_snapshot(tmp_path, filename, edit):
    """A copy of the snapshot in tmp_path with one response changed in place by edit(data)."""
    snapshot = tmp_path / "snapshot"
    shutil.copytree(DEFAULT_SNAPSHOT, snapshot)
    path = snapshot / filename
    data = json.loads(path.read_text(encoding="utf-8"))  # these files hold no JSON floats
    edit(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return snapshot


def market_in(event_response, ticker):
    return next(m for m in event_response["event"]["markets"] if m["ticker"] == ticker)


@pytest.fixture(scope="module")
def result():
    return run()


# Test 1


def test_1_reads_the_five_fed_markets_without_warnings(result):
    assert [market.market_id for market in result.markets] == [f"kalshi:{t}" for t in TICKERS]
    assert result.warnings == []


# Test 2: the Kalshi rows of the architecture 4.4 table.


@pytest.mark.parametrize(
    "suffix, comparison, threshold",
    [("C26", "lt", "-25"), ("C25", "eq", "-25"), ("H0", "eq", "0"), ("H25", "eq", "25")]
    + [("H26", "gt", "25")],
)
def test_2_terms_are_the_kalshi_rows_of_the_terms_table(result, suffix, comparison, threshold):
    assert by_ticker(result)[f"{EVENT}-{suffix}"].terms == ContractTerms(
        subject="FOMC",
        measure="fed_upper_bound_change",
        measured_by="fomc_statement",
        observed_on=date(2026, 10, 28),
        observed_at=None,
        comparison=comparison,
        threshold=D(threshold),
        unit="bps",
        fallback_rules=("If the meeting is cancelled, 'Fed maintains rate' resolves Yes.",),
    )


# Tests 3-4: Kalshi lists bids only, ascending with the best last (K4); asks are 1 - p (K5).


def test_3_h0_asks_are_the_opposite_bids_at_one_minus_p_cheapest_first(result):
    books = by_ticker(result)[f"{EVENT}-H0"].books
    best = {outcome: (book.asks[0], book.bids[0]) for outcome, book in books.items()}
    assert (best["YES"][0].price, best["YES"][0].quantity) == (D("0.8500"), D("60329.95"))
    assert (best["NO"][0].price, best["NO"][0].quantity) == (D("0.1600"), D("534.49"))
    assert (best["YES"][1].price, best["YES"][1].quantity) == (D("0.8400"), D("534.49"))
    assert (best["NO"][1].price, best["NO"][1].quantity) == (D("0.1500"), D("60329.95"))
    assert sum(level.quantity for level in books["YES"].asks) == D("4649443.27")
    assert len(books["YES"].asks) == 15 and len(books["NO"].asks) == 53


def test_4_c25_has_no_no_asks_because_the_snapshot_has_no_yes_bids(result):
    books = by_ticker(result)[f"{EVENT}-C25"].books
    assert books["NO"].asks == () and books["YES"].bids == ()
    assert books["YES"].asks[0].price == D("0.0100") and books["NO"].bids[0].price == D("0.9900")


# Test 5


def test_5_fees_are_0_07_times_the_series_multiplier(result):
    expected = FeeSchedule(coefficient=D("0.07"), exponent=1, rounding_step=D("0.01"))
    assert [market.fees for market in result.markets] == [expected] * 5


# Test 6


@pytest.mark.parametrize("data_source", ["fixture", "live"])
def test_6_source_collateral_times_and_data_source(data_source):
    markets = run(data_source=data_source).markets
    assert len(markets) == 5
    for market in markets:
        assert market.venue == "kalshi" and market.event_id == EVENT
        assert market.resolution_source.institution == "federalreserve.gov"
        assert market.collateral == Collateral(asset="USD", has_value=True)
        assert market.tradable is True
        assert market.trading_closes_at == datetime(2026, 10, 28, 17, 59, tzinfo=UTC)
        assert market.resolves_at == datetime(2026, 10, 28, 18, 5, tzinfo=UTC)
        assert market.data_source == data_source
        assert market.venue_metadata == {}


def test_6_a_market_that_is_not_active_is_not_tradable(tmp_path):
    ticker = f"{EVENT}-H0"
    snapshot = edited_snapshot(
        tmp_path, EVENT_FILE, lambda data: market_in(data, ticker).update(status="closed")
    )
    tradable = {t: m.tradable for t, m in by_ticker(run(snapshot)).items()}
    assert tradable == {t: t != ticker for t in TICKERS}


# Test 7: only the five shapes in 5.2 parse; anything else leaves terms empty, with a warning.


@pytest.mark.parametrize(
    "custom_strike",
    [{"Cut": "50"}, {"Hold": "0"}, {"Cut": "25", "Hike": "0"}, {}, None],
    ids=["cut-50", "unknown-key", "two-keys", "empty", "null"],
)
def test_7_an_unknown_custom_strike_gives_no_terms_and_a_warning(tmp_path, custom_strike):
    ticker = f"{EVENT}-C25"
    snapshot = edited_snapshot(
        tmp_path,
        EVENT_FILE,
        lambda data: market_in(data, ticker).update(custom_strike=custom_strike),
    )
    result = run(snapshot)
    markets = by_ticker(result)
    assert list(markets) == TICKERS
    assert markets[ticker].terms is None
    assert all(m.terms is not None for t, m in markets.items() if t != ticker)
    assert len(result.warnings) == 1 and ticker in result.warnings[0]


# Test 8: an event's fee_multiplier_override wins over the series' fee_multiplier (K9).


@pytest.mark.parametrize("override, coefficient", [(0.5, "0.035"), (None, "0.07")])
def test_8_an_event_fee_override_replaces_the_series_multiplier(tmp_path, override, coefficient):
    snapshot = edited_snapshot(
        tmp_path, EVENT_FILE, lambda data: data["event"].update(fee_multiplier_override=override)
    )
    result = run(snapshot)  # the fetcher reads the JSON 0.5 as Decimal("0.5")
    assert result.warnings == []
    assert [market.fees.coefficient for market in result.markets] == [D(coefficient)] * 5


# Test 9 and D37: Kalshi's orderbook has no timestamp, so captured_at is the clock's.


def test_9_captured_at_is_the_snapshot_capture_time(result):
    assert [market.captured_at for market in result.markets] == [CAPTURED_AT] * 5


def test_the_clock_is_read_as_each_orderbook_arrives():
    fixture = FixtureFetcher(DEFAULT_SNAPSHOT)
    log = []

    def fetch(url):
        log.append(url)
        return fixture(url)

    def clock():
        log.append("clock")
        return CAPTURED_AT + timedelta(seconds=log.count("clock"))

    markets = KalshiAdapter(fetch, FED, "live", clock).fetch_markets().markets
    books = [f"{BASE}/markets/{ticker}/orderbook" for ticker in TICKERS]
    assert log == [
        f"{BASE}/events/{EVENT}?with_nested_markets=true",
        f"{BASE}/series/KXFEDDECISION",
        *[step for url in books for step in (url, "clock")],
    ]
    assert [m.captured_at for m in markets] == [
        CAPTURED_AT + timedelta(seconds=n) for n in range(1, 6)
    ]


# The adapter contract (5.1): requests go only through the injected fetcher.


def test_the_base_url_comes_from_the_constructor():
    fixture = FixtureFetcher(DEFAULT_SNAPSHOT)
    mirror = "https://mirror.example/kalshi/v2"
    seen = []

    def fetch(url):
        seen.append(url)
        return fixture(url.replace(mirror, BASE))

    adapter = KalshiAdapter(fetch, FED, "live", lambda: CAPTURED_AT, base_url=mirror)
    assert len(adapter.fetch_markets().markets) == 5
    assert len(seen) == 7 and all(url.startswith(mirror + "/") for url in seen)


def test_a_failed_request_is_left_to_the_caller():
    fixture = FixtureFetcher(DEFAULT_SNAPSHOT)

    def fetch(url):
        if url.endswith("-H0/orderbook"):
            raise FetchError(f"{url}: timed out")
        return fixture(url)

    with pytest.raises(FetchError, match="H0/orderbook"):
        KalshiAdapter(fetch, FED, "live", lambda: CAPTURED_AT).fetch_markets()


def zero_quantity(book):
    book["orderbook_fp"]["yes_dollars"][-1][1] = "0.00"


def bid_at_one_dollar(book):
    book["orderbook_fp"]["no_dollars"].append(["1.0000", "5.00"])  # a YES ask at 0


@pytest.mark.parametrize("edit", [zero_quantity, bid_at_one_dollar])
def test_a_market_that_fails_validation_is_skipped_and_the_rest_return(tmp_path, edit):
    ticker = f"{EVENT}-H25"
    result = run(edited_snapshot(tmp_path, f"kalshi_orderbook_{ticker}.json", edit))
    assert [market.native_id for market in result.markets] == [t for t in TICKERS if t != ticker]
    assert len(result.warnings) == 1
    assert result.warnings[0].startswith(f"kalshi: market {ticker} skipped: ")


def test_an_unreadable_event_response_is_skipped_with_a_warning(tmp_path):
    snapshot = edited_snapshot(
        tmp_path, EVENT_FILE, lambda data: data["event"].pop("series_ticker")
    )
    result = run(snapshot)
    assert result.markets == []
    assert len(result.warnings) == 1
    assert result.warnings[0].startswith(f"kalshi: event {EVENT} skipped: ")


def test_an_event_of_another_family_has_no_terms_and_one_warning():
    result = run(family="rate_level")
    assert len(result.markets) == 5
    assert all(market.terms is None for market in result.markets)
    assert len(result.warnings) == 1
    assert EVENT in result.warnings[0] and "rate_level" in result.warnings[0]


# Field fallbacks from the 5.2 table.


def test_a_market_without_a_title_uses_the_event_title_and_its_outcome(tmp_path):
    ticker = f"{EVENT}-H0"
    snapshot = edited_snapshot(
        tmp_path, EVENT_FILE, lambda data: market_in(data, ticker).pop("title")
    )
    market = by_ticker(run(snapshot))[ticker]
    assert market.title == "Fed decision in Oct 2026? Fed maintains rate"
    assert market.outcome_label == "Fed maintains rate"


def test_rules_text_leaves_out_an_empty_rules_secondary(tmp_path):
    ticker = f"{EVENT}-H0"
    snapshot = edited_snapshot(
        tmp_path, EVENT_FILE, lambda data: market_in(data, ticker).update(rules_secondary="")
    )
    assert by_ticker(run(snapshot))[ticker].rules_text == (
        "If the Federal Reserve does a Hike of 0bps on October 28, 2026, then the market resolves"
        " to Yes."
    )


# The golden markets (feat-01) that the matcher and router tests build on.

GOLDEN_FIELDS = (
    "title",
    "outcome_label",
    "rules_text",
    "terms",
    "resolution_source",
    "collateral",
    "tradable",
    "trading_closes_at",
    "resolves_at",
    "captured_at",
    "data_source",
    "fees",
)


def test_markets_agree_with_the_golden_file(result, golden_markets):
    compared = set()
    for market in result.markets:
        golden = golden_markets.get(market.market_id)
        if golden is None:
            continue
        compared.add(market.native_id)
        for field in GOLDEN_FIELDS:
            assert getattr(market, field) == getattr(golden, field), (market.market_id, field)
        for outcome, book in golden.books.items():  # golden books keep only 3 levels a side
            for side in ("asks", "bids"):
                ours = getattr(market.books[outcome], side)[:3]
                assert ours == getattr(book, side)[:3], (market.market_id, outcome, side)
    assert {f"{EVENT}-{suffix}" for suffix in ("C26", "C25", "H0", "H26")} <= compared
