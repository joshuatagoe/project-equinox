"""feat-02b acceptance tests: the Polymarket adapter, run on the snapshot through FixtureFetcher.

Tests that need a changed response copy the snapshot into tmp_path and edit the copy. The snapshot
itself is never edited.
"""

import json
import shutil
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from equinox.adapters.base import FetchError, TrackedEvent, load_tracked_events
from equinox.adapters.fetch import DEFAULT_SNAPSHOT, FixtureFetcher
from equinox.adapters.polymarket import PolymarketAdapter
from equinox.models import ContractTerms

D = Decimal
FED_SLUG = "fed-decision-in-october-20260617190323537"
AAPL_SLUG = "aapl-close-above-on-october-12-2026"
FED_EVENT_FILE = f"polymarket_event_{FED_SLUG}.json"
FED_IDS = ["2589810", "2589811", "2589812", "2589813", "2589814"]
AAPL_IDS = ["5455685", "5455686", "5455687", "5455688", "5455690"]
FED_FALLBACKS = (
    "A change not shown in the brackets is rounded up to the nearest 25 bps.",
    "If no statement is released by the end date of the next scheduled meeting, "
    "'No change' resolves Yes.",
)


def fixed_clock() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)  # far from the book timestamps, so a misuse shows


def adapter(fetch=None, tracked=None, **urls) -> PolymarketAdapter:
    return PolymarketAdapter(
        fetch or FixtureFetcher(DEFAULT_SNAPSHOT),
        tracked if tracked is not None else load_tracked_events()["polymarket"],
        "fixture",
        fixed_clock,
        **urls,
    )


def by_id(result) -> dict:
    return {market.native_id: market for market in result.markets}


def snapshot_copy(tmp_path):
    copy = tmp_path / "snapshot"
    shutil.copytree(DEFAULT_SNAPSHOT, copy)
    return copy


def edit_json(path, change) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def edit_fed_market(snapshot, native_id, **fields) -> None:
    def change(events):
        (market,) = [m for m in events[0]["markets"] if m["id"] == native_id]
        market.update(fields)

    edit_json(snapshot / FED_EVENT_FILE, change)


def fed_market_field(native_id, field):
    events = json.loads((DEFAULT_SNAPSHOT / FED_EVENT_FILE).read_text(encoding="utf-8"))
    (market,) = [m for m in events[0]["markets"] if m["id"] == native_id]
    return market[field]


def fed_terms(comparison, threshold) -> ContractTerms:
    return ContractTerms(
        subject="FOMC",
        measure="fed_upper_bound_change",
        measured_by="fomc_statement",
        observed_on=date(2026, 10, 28),
        comparison=comparison,
        threshold=D(threshold),
        unit="bps",
        fallback_rules=FED_FALLBACKS,
    )


# 1-5: the snapshot as captured.


def test_1_default_tracked_events_give_the_five_fed_markets_and_no_warnings():
    result = adapter().fetch_markets()
    assert [m.native_id for m in result.markets] == FED_IDS
    assert [m.market_id for m in result.markets] == [f"polymarket:{i}" for i in FED_IDS]
    assert {m.venue for m in result.markets} == {"polymarket"}
    assert {m.event_id for m in result.markets} == {"606422"}
    assert result.warnings == []


def test_2_fed_terms_match_the_polymarket_rows_of_the_terms_table():
    markets = by_id(adapter().fetch_markets())
    assert {native_id: markets[native_id].terms for native_id in FED_IDS} == {
        "2589810": fed_terms("le", "-50"),
        "2589811": fed_terms("eq", "-25"),
        "2589812": fed_terms("eq", "0"),
        "2589813": fed_terms("eq", "25"),
        "2589814": fed_terms("ge", "50"),
    }


def test_3_books_come_from_each_token_sorted_best_first_and_never_merged():
    market = by_id(adapter().fetch_markets())["2589812"]
    yes, no = market.books["YES"], market.books["NO"]
    assert (yes.asks[0].price, yes.asks[0].quantity) == (D("0.84"), D("295850.63"))
    assert (no.asks[0].price, no.asks[0].quantity) == (D("0.17"), D("67936.43"))
    assert sum(level.quantity for level in yes.asks) == D("3453123.38")
    assert (yes.bids[0].price, no.bids[0].price) == (D("0.83"), D("0.16"))
    # Each side holds only its own token's levels: 16 and 66 asks, nothing mirrored on top (P5).
    assert (len(yes.asks), len(yes.bids), len(no.asks), len(no.bids)) == (16, 66, 66, 16)


def test_4_fees_come_from_fee_schedule_as_exact_decimals():
    markets = adapter().fetch_markets().markets
    assert len(markets) == 5
    for market in markets:
        assert market.fees.coefficient == D("0.05")
        assert isinstance(market.fees.coefficient, Decimal)
        assert market.fees.exponent == 1
        assert market.fees.rounding_step == D("0.00001")


def test_5_captured_at_is_the_book_timestamp_not_the_clock():
    market = by_id(adapter().fetch_markets())["2589812"]
    assert market.captured_at == datetime(2026, 10, 10, 20, 44, 32, 57000, tzinfo=UTC)
    assert market.data_source == "fixture"


def test_5b_captured_at_is_the_earlier_of_the_two_books(tmp_path):
    snapshot = snapshot_copy(tmp_path)
    earlier = 1791665000123  # an int this time: the timestamp may arrive as a number or a string
    edit_json(
        snapshot / "polymarket_book_2589812_no.json",
        lambda book: book.update(timestamp=earlier),
    )
    market = by_id(adapter(FixtureFetcher(snapshot)).fetch_markets())["2589812"]
    assert market.captured_at == datetime(2026, 10, 10, 20, 43, 20, 123000, tzinfo=UTC)


# 6-8: edited copies of the snapshot.


def test_6_a_market_whose_outcomes_are_not_yes_no_is_skipped_with_a_warning(tmp_path):
    snapshot = snapshot_copy(tmp_path)
    edit_fed_market(snapshot, "2589812", outcomes='["Up", "Down"]')
    result = adapter(FixtureFetcher(snapshot)).fetch_markets()
    assert [m.native_id for m in result.markets] == ["2589810", "2589811", "2589813", "2589814"]
    assert len(result.warnings) == 1
    assert "2589812" in result.warnings[0]
    assert result.warnings[0].startswith("polymarket: market 2589812 skipped")


@pytest.mark.parametrize(
    "fields",
    [
        {"feesEnabled": False, "feeSchedule": None},
        {"feesEnabled": False},  # the schedule is still there, but fees are off
        {"feeSchedule": None},  # fees on, but no schedule to read
    ],
    ids=["disabled-no-schedule", "disabled-with-schedule", "enabled-no-schedule"],
)
def test_7_fees_disabled_or_unscheduled_means_coefficient_zero(tmp_path, fields):
    snapshot = snapshot_copy(tmp_path)
    edit_fed_market(snapshot, "2589812", **fields)
    markets = by_id(adapter(FixtureFetcher(snapshot)).fetch_markets())
    fees = markets["2589812"].fees
    assert (fees.coefficient, fees.exponent, fees.rounding_step) == (D(0), 1, D("0.00001"))
    assert markets["2589811"].fees.coefficient == D("0.05")


def test_8_without_the_meeting_text_observed_on_is_end_date_in_new_york(tmp_path):
    snapshot = snapshot_copy(tmp_path)
    description = fed_market_field("2589812", "description")
    stripped = description.replace("meeting scheduled for October 27-28, 2026 according", "meeting")
    assert stripped != description and "scheduled for" not in stripped
    edit_fed_market(snapshot, "2589812", description=stripped)
    result = adapter(FixtureFetcher(snapshot)).fetch_markets()
    market = by_id(result)["2589812"]
    # endDate is 2026-10-29T03:59:00Z, which is still the 28th in New York.
    assert market.terms.observed_on == date(2026, 10, 28)
    assert market.terms.comparison == "eq" and market.terms.threshold == 0
    assert len(result.warnings) == 1 and "2589812" in result.warnings[0]


def test_8b_the_meeting_text_is_read_for_any_month_and_days(tmp_path):
    snapshot = snapshot_copy(tmp_path)
    description = fed_market_field("2589812", "description")
    moved = description.replace("October 27-28, 2026", "December 8-9, 2026")
    edit_fed_market(snapshot, "2589812", description=moved)
    result = adapter(FixtureFetcher(snapshot)).fetch_markets()
    assert by_id(result)["2589812"].terms.observed_on == date(2026, 12, 9)
    assert result.warnings == []


# 9: a family with no term parser.


def test_9_a_family_with_no_parser_gives_markets_without_terms_and_one_warning():
    tracked = [TrackedEvent(event_id=AAPL_SLUG, family="stock_close_above")]
    result = adapter(tracked=tracked).fetch_markets()
    assert [m.native_id for m in result.markets] == AAPL_IDS
    assert {m.event_id for m in result.markets} == {"1158886"}
    for market in result.markets:
        assert market.terms is None
        assert market.fees.coefficient == D("0.04")
        assert market.books["YES"].asks and market.books["NO"].asks
        assert market.tradable
    assert len(result.warnings) == 1
    assert "stock_close_above" in result.warnings[0]


# Agreement with the golden markets (tests/golden/canonical_markets.json).

FULL_FIELDS = (
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
FIT_CHECK_FIELDS = ("fees", "tradable")  # the golden fit-check markets carry hand-built terms


def assert_matches_golden(market, golden, fields) -> None:
    for field in fields:
        assert getattr(market, field) == getattr(golden, field), f"{market.market_id}: {field}"
    for outcome in ("YES", "NO"):
        ours, theirs = market.books[outcome], golden.books[outcome]
        assert ours.asks[:3] == theirs.asks[:3], f"{market.market_id}: {outcome} asks"
        assert ours.bids[:3] == theirs.bids[:3], f"{market.market_id}: {outcome} bids"


def test_fed_markets_agree_with_the_golden_file(golden_markets):
    markets = adapter().fetch_markets().markets
    compared = [m for m in markets if m.market_id in golden_markets]
    assert [m.native_id for m in compared] == FED_IDS
    for market in compared:
        assert_matches_golden(market, golden_markets[market.market_id], FULL_FIELDS)


def test_aapl_fit_check_markets_agree_with_the_golden_books_and_fees(golden_markets):
    tracked = [TrackedEvent(event_id=AAPL_SLUG, family="stock_close_above")]
    markets = by_id(adapter(tracked=tracked).fetch_markets())
    for native_id in ("5455686", "5455687"):
        market = markets[native_id]
        assert_matches_golden(market, golden_markets[market.market_id], FIT_CHECK_FIELDS)


# The rest of the contract (architecture section 5.1, 5.3).


def test_requests_go_through_the_fetcher_to_the_configured_hosts():
    real = FixtureFetcher(DEFAULT_SNAPSHOT)
    seen = []

    def fetch(url):
        seen.append(url)
        url = url.replace("https://gamma.test", "https://gamma-api.polymarket.com")
        return real(url.replace("https://clob.test", "https://clob.polymarket.com"))

    result = adapter(fetch, gamma_url="https://gamma.test", clob_url="https://clob.test/")
    assert len(result.fetch_markets().markets) == 5
    assert seen[0] == f"https://gamma.test/events?slug={FED_SLUG}"
    books = seen[1:]
    assert len(books) == 10 and all(u.startswith("https://clob.test/book?token_id=") for u in books)


def test_v2_markets_read_token_ids_from_position_ids(tmp_path):
    snapshot = snapshot_copy(tmp_path)
    tokens = json.loads(fed_market_field("2589812", "clobTokenIds"))
    edit_fed_market(snapshot, "2589812", version="v2", clobTokenIds=None, positionIds=tokens)
    result = adapter(FixtureFetcher(snapshot)).fetch_markets()
    market = by_id(result)["2589812"]
    assert market.books["YES"].asks[0].price == D("0.84")
    assert market.books["NO"].asks[0].price == D("0.17")
    assert result.warnings == []


@pytest.mark.parametrize(
    ("label", "comparison", "threshold"),
    [
        ("75 bps decrease", "eq", "-75"),
        ("100+ bps decrease", "le", "-100"),
        ("50 bps increase", "eq", "50"),
        ("75+ bps increase", "ge", "75"),
    ],
)
def test_fed_brackets_parse_for_any_size(tmp_path, label, comparison, threshold):
    snapshot = snapshot_copy(tmp_path)
    edit_fed_market(snapshot, "2589812", groupItemTitle=label)
    result = adapter(FixtureFetcher(snapshot)).fetch_markets()
    terms = by_id(result)["2589812"].terms
    assert (terms.comparison, terms.threshold) == (comparison, D(threshold))
    assert result.warnings == []


def test_an_unknown_fed_bracket_gets_no_terms_and_a_warning(tmp_path):
    snapshot = snapshot_copy(tmp_path)
    edit_fed_market(snapshot, "2589812", groupItemTitle="Emergency cut")
    result = adapter(FixtureFetcher(snapshot)).fetch_markets()
    markets = by_id(result)
    assert markets["2589812"].terms is None
    assert markets["2589811"].terms is not None
    assert len(result.warnings) == 1 and "2589812" in result.warnings[0]


def bad_price(snapshot):
    edit_json(
        snapshot / "polymarket_book_2589812_yes.json",
        lambda book: book["asks"].append({"price": "1.5", "size": "10"}),
    )


def no_source(snapshot):
    edit_fed_market(snapshot, "2589812", resolutionSource="")


@pytest.mark.parametrize("damage", [bad_price, no_source], ids=["price-above-1", "no-source"])
def test_a_market_that_cannot_be_built_is_skipped_and_the_rest_return(tmp_path, damage):
    snapshot = snapshot_copy(tmp_path)
    damage(snapshot)
    result = adapter(FixtureFetcher(snapshot)).fetch_markets()
    assert [m.native_id for m in result.markets] == ["2589810", "2589811", "2589813", "2589814"]
    assert len(result.warnings) == 1
    assert result.warnings[0].startswith("polymarket: market 2589812 skipped: ")


def test_an_event_the_venue_does_not_return_gives_a_warning_and_no_markets():
    result = adapter(lambda url: []).fetch_markets()
    assert result.markets == []
    assert len(result.warnings) == 1 and FED_SLUG in result.warnings[0]


def test_a_failed_request_is_not_caught_by_the_adapter():
    real = FixtureFetcher(DEFAULT_SNAPSHOT)

    def fetch(url):
        if "token_id=" in url:
            raise FetchError(f"{url}: timed out")
        return real(url)

    with pytest.raises(FetchError):
        adapter(fetch).fetch_markets()
