"""feat-01 acceptance tests: fees, model validation, fixture fetching and the golden file."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from equinox.adapters.base import FetchError, TrackedEvent, load_tracked_events
from equinox.adapters.fetch import DEFAULT_SNAPSHOT, FixtureFetcher
from equinox.models import (
    EXIT_CODES,
    CanonicalMarket,
    Collateral,
    ContractTerms,
    EquinoxTrace,
    EquivalenceCluster,
    EquivalenceStatus,
    FeeSchedule,
    Fill,
    MatchResult,
    OrderBookLevel,
    OrderRequest,
    OutcomeBook,
    QuoteReason,
    ResolutionSource,
    RoutingStatus,
    VenueQuote,
)

GOLDEN = Path(__file__).parent / "golden" / "canonical_markets.json"
D = Decimal


def fills(*levels):
    return [Fill(price=D(p), quantity=D(q)) for p, q in levels]


# Tests 1-4: one fee formula, summed per level, rounded up once (D5, D13).


def test_1_kalshi_fee_rounds_up_to_the_cent():
    fees = FeeSchedule(coefficient=D("0.07"), rounding_step=D("0.01"))
    assert fees.fee(fills(("0.85", "100"))) == D("0.90")  # raw 0.8925


def test_2_polymarket_fee_rounds_to_five_places():
    fees = FeeSchedule(coefficient=D("0.05"), rounding_step=D("0.00001"))
    assert fees.fee(fills(("0.84", "100"))) == D("0.672")


def test_3_kalshi_fee_over_two_levels():
    fees = FeeSchedule(coefficient=D("0.07"), rounding_step=D("0.01"))
    assert fees.fee(fills(("0.16", "534.49"), ("0.17", "4465.51"))) == D("49.14")  # 49.13432419


def test_4_fee_per_level_differs_from_fee_on_the_average_price():
    fees = FeeSchedule(coefficient=D("0.07"), rounding_step=D("0.01"))
    per_level = fees.fee(fills(("0.10", "100"), ("0.90", "100")))
    on_average = fees.fee(fills(("0.50", "200")))
    assert per_level == D("1.26")
    assert on_average == D("3.50")  # why D5 exists: the curve p(1-p) isn't a straight line


def test_fee_with_no_fills_or_no_coefficient_is_zero():
    assert FeeSchedule(coefficient=D("0.07"), rounding_step=D("0.01")).fee([]) == 0
    assert FeeSchedule(coefficient=D("0"), rounding_step=D("0.01")).fee(fills(("0.5", "9"))) == 0


# Test 5: each validation rule in architecture section 4.5 rejects its bad input.


def level(price="0.5", quantity="10"):
    return {"price": D(price), "quantity": D(quantity)}


def book():
    return {"asks": [level("0.52")], "bids": [level("0.48")]}


def terms(**overrides):
    base = {
        "subject": "FOMC",
        "measure": "fed_upper_bound_change",
        "measured_by": "fomc_statement",
        "observed_on": date(2026, 10, 28),
        "comparison": "eq",
        "threshold": D("0"),
        "unit": "bps",
    }
    return base | overrides


def market(**overrides):
    base = {
        "market_id": "venue_a:M1",
        "venue": "venue_a",
        "native_id": "M1",
        "event_id": "E1",
        "title": "A test market",
        "outcome_label": "Yes",
        "terms": terms(),
        "resolution_source": {"name": "Federal Reserve", "url": "https://www.federalreserve.gov"},
        "collateral": {"asset": "USD", "has_value": True},
        "tradable": True,
        "trading_closes_at": None,
        "resolves_at": None,
        "captured_at": datetime(2026, 10, 10, 20, 44, 29, tzinfo=UTC),
        "data_source": "fixture",
        "fees": {"coefficient": D("0.07"), "rounding_step": D("0.01")},
        "books": {"YES": book(), "NO": book()},
    }
    return base | overrides


def quote(**overrides):
    base = {
        "market_id": "venue_a:M1",
        "venue": "venue_a",
        "eligible": True,
        "reasons": (),
        "warnings": (),
        "fills": (),
        "filled_quantity": D("0"),
        "best_ask": None,
        "average_price": None,
        "slippage": None,
        "base_cost": D("0"),
        "fee": D("0"),
        "total_cost": D("0"),
    }
    return base | overrides


REJECTED = {
    "price at zero": (OrderBookLevel, level(price="0")),
    "price at one": (OrderBookLevel, level(price="1")),
    "price in cents": (OrderBookLevel, level(price="85")),
    "zero quantity": (OrderBookLevel, level(quantity="0")),
    "price as float (D3)": (OrderBookLevel, {"price": 0.85, "quantity": D("1")}),
    "asks falling": (OutcomeBook, {"asks": [level("0.6"), level("0.5")]}),
    "asks repeating a price": (OutcomeBook, {"asks": [level("0.5"), level("0.5")]}),
    "bids rising": (OutcomeBook, {"bids": [level("0.4"), level("0.5")]}),
    "NO book missing": (CanonicalMarket, market(books={"YES": book()})),
    "market_id not venue:native_id": (CanonicalMarket, market(market_id="venue_b:M1")),
    "naive datetime": (CanonicalMarket, market(captured_at=datetime(2026, 10, 10, 20, 44))),
    "unknown field": (CanonicalMarket, market(spread="0.01")),
    "between without upper": (ContractTerms, terms(comparison="between")),
    "upper without between": (ContractTerms, terms(upper=D("25"))),
    "upper not above threshold": (
        ContractTerms,
        terms(comparison="between", threshold=D("25"), upper=D("25")),
    ),
    "negative coefficient": (FeeSchedule, {"coefficient": D("-0.01"), "rounding_step": D("0.01")}),
    "zero exponent": (
        FeeSchedule,
        {"coefficient": D("0.07"), "exponent": 0, "rounding_step": D("0.01")},
    ),
    "zero rounding step": (FeeSchedule, {"coefficient": D("0.07"), "rounding_step": D("0")}),
    "zero order quantity": (OrderRequest, {"market_id": "a:1", "outcome": "YES", "quantity": D(0)}),
    "zero budget": (
        OrderRequest,
        {"market_id": "a:1", "outcome": "YES", "quantity": D(1), "max_budget": D(0)},
    ),
    "unknown outcome": (OrderRequest, {"market_id": "a:1", "outcome": "MAYBE", "quantity": D(1)}),
    "text match marked EQUIVALENT (D15)": (
        MatchResult,
        {"market_a": "a:1", "market_b": "b:1", "status": "EQUIVALENT", "method": "text"},
    ),
    "cluster with no markets": (EquivalenceCluster, {"cluster_id": "k", "markets": ()}),
    "eligible quote with a reason": (VenueQuote, quote(reasons=("EMPTY_BOOK",))),
    "excluded quote with no reason": (VenueQuote, quote(eligible=False)),
    "ROUTED trace without a decision": (
        EquinoxTrace,
        {
            "trace_id": "t",
            "created_at": datetime(2026, 10, 10, tzinfo=UTC),
            "status": "ROUTED",
            "order": None,
            "cluster": None,
            "rationale": "",
        },
    ),
}


@pytest.mark.parametrize("model, data", REJECTED.values(), ids=REJECTED.keys())
def test_5_validation_rules_reject_bad_input(model, data):
    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_5_valid_inputs_pass_and_models_are_frozen():
    built = CanonicalMarket.model_validate(market())
    assert built.captured_at.tzinfo is not None
    with pytest.raises(ValidationError):
        built.title = "changed"
    eastern = datetime.fromisoformat("2026-10-28T14:00:00-04:00")
    assert CanonicalMarket.model_validate(market(captured_at=eastern)).captured_at == datetime(
        2026, 10, 28, 18, 0, tzinfo=UTC
    )
    between = ContractTerms.model_validate(terms(comparison="between", upper=D("25")))
    assert between.upper == 25
    assert VenueQuote.model_validate(quote(eligible=False, reasons=(QuoteReason.EMPTY_BOOK,)))


def test_resolution_source_institution_ignores_path_and_www():
    kalshi_style = ResolutionSource(name="Federal Reserve", url="https://www.federalreserve.gov")
    poly_style = ResolutionSource(
        name="www.federalreserve.gov",
        url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    )
    assert kalshi_style.institution == poly_style.institution == "federalreserve.gov"
    assert ResolutionSource(name="Associated Press").institution == "associated press"


def test_exit_codes_follow_d27():
    assert {status.value: code for status, code in EXIT_CODES.items()} == {
        "ROUTED": 0,
        "MARKET_NOT_FOUND": 1,
        "INSUFFICIENT_LIQUIDITY": 2,
        "BUDGET_EXCEEDED": 3,
        "INVALID_INPUT": 4,
        "NO_ELIGIBLE_VENUE": 5,
    }
    assert set(EXIT_CODES) == set(RoutingStatus)


# Tests 6, 7 and 10: the fixture fetcher.

H0_BOOK = "https://external-api.kalshi.com/trade-api/v2/markets/KXFEDDECISION-26OCT-H0/orderbook"
FED_EVENT = "https://gamma-api.polymarket.com/events?slug=fed-decision-in-october-20260617190323537"


def test_6_fixture_fetcher_serves_the_raw_response_with_decimals():
    fetch = FixtureFetcher(DEFAULT_SNAPSHOT)
    raw = (DEFAULT_SNAPSHOT / "kalshi_orderbook_KXFEDDECISION-26OCT-H0.json").read_text("utf-8")
    assert fetch(H0_BOOK) == json.loads(raw, parse_float=Decimal)

    event = fetch(FED_EVENT)
    rate = event[0]["markets"][0]["feeSchedule"]["rate"]
    assert type(rate) is Decimal and rate == Decimal("0.05")


def test_6_fixture_fetcher_ignores_query_parameter_order(tmp_path):
    (tmp_path / "page.json").write_text('{"n": 1.5}', encoding="utf-8")
    index = {"captured_at": "2026-10-10T20:44:29+00:00", "files": {}}
    index["files"]["page.json"] = "https://venue.test/v1/page?a=1&b=2"
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    assert FixtureFetcher(tmp_path)("https://venue.test/v1/page?b=2&a=1") == {"n": Decimal("1.5")}


def test_7_fixture_fetcher_rejects_an_unknown_url():
    fetch = FixtureFetcher(DEFAULT_SNAPSHOT)
    with pytest.raises(FetchError):
        fetch("https://external-api.kalshi.com/trade-api/v2/markets/NOPE/orderbook")


def test_7_fixture_fetcher_rejects_a_missing_snapshot(tmp_path):
    with pytest.raises(FetchError):
        FixtureFetcher(tmp_path / "absent")


def test_10_fixture_fetcher_exposes_the_capture_time():
    captured = FixtureFetcher(DEFAULT_SNAPSHOT).captured_at
    assert captured == datetime(2026, 10, 10, 20, 44, 29, 495262, tzinfo=UTC)
    assert captured.utcoffset().total_seconds() == 0


def test_tracked_events_list_the_snapshot_events():
    assert load_tracked_events() == {
        "kalshi": [TrackedEvent(event_id="KXFEDDECISION-26OCT", family="fed_decision")],
        "polymarket": [
            TrackedEvent(
                event_id="fed-decision-in-october-20260617190323537", family="fed_decision"
            )
        ],
    }


# Test 8: the golden canonical markets that the matcher and router lanes test against.

FED = {
    "kalshi:KXFEDDECISION-26OCT-C26": ("lt", "-25"),
    "kalshi:KXFEDDECISION-26OCT-C25": ("eq", "-25"),
    "kalshi:KXFEDDECISION-26OCT-H0": ("eq", "0"),
    "kalshi:KXFEDDECISION-26OCT-H26": ("gt", "25"),
    "polymarket:2589810": ("le", "-50"),
    "polymarket:2589811": ("eq", "-25"),
    "polymarket:2589812": ("eq", "0"),
    "polymarket:2589813": ("eq", "25"),
    "polymarket:2589814": ("ge", "50"),
}
FIT_CHECK = {
    "polymarket:5455686",
    "polymarket:5455687",
    "meridian:AAPL-330-2026-10-12",
    "meridian:AAPL-320-2026-10-12",
    "meridian:AAPL-330-2026-10-13",
    "meridian:AAPL-330-2026-10-12-OC",
}
TERMLESS = {f"{v}:{case}" for v in ("kalshi", "polymarket") for case in ("E11", "E12", "E13")}


def test_8_golden_markets_load_and_books_are_sorted():
    markets = TypeAdapter(list[CanonicalMarket]).validate_json(GOLDEN.read_bytes())
    assert {m.market_id for m in markets} == set(FED) | FIT_CHECK | TERMLESS
    for m in markets:
        assert set(m.books) == {"YES", "NO"}
        for side in m.books.values():
            assert [lvl.price for lvl in side.asks] == sorted(lvl.price for lvl in side.asks)
            assert [lvl.price for lvl in side.bids] == sorted(
                (lvl.price for lvl in side.bids), reverse=True
            )


def test_8_golden_terms_match_the_architecture_table(golden_markets):
    for market_id, (comparison, threshold) in FED.items():
        t = golden_markets[market_id].terms
        assert (t.subject, t.measure, t.measured_by, t.unit) == (
            "FOMC",
            "fed_upper_bound_change",
            "fomc_statement",
            "bps",
        )
        assert (t.observed_on, t.comparison, t.threshold) == (
            date(2026, 10, 28),
            comparison,
            Decimal(threshold),
        )
    for market_id in TERMLESS:
        assert golden_markets[market_id].terms is None
    for market_id in FIT_CHECK:
        assert golden_markets[market_id].venue_metadata == {"fit_check": True}
    meridian = golden_markets["meridian:AAPL-330-2026-10-12"]
    assert meridian.collateral == Collateral(asset="devnet USDC", has_value=False)
    assert meridian.terms.comparison == "ge"
    assert golden_markets["polymarket:5455686"].terms.comparison == "gt"
    official = golden_markets["meridian:AAPL-330-2026-10-12-OC"].terms
    assert official.measured_by == "official_close"


def test_8_golden_running_example_books(golden_markets):
    h0 = golden_markets["kalshi:KXFEDDECISION-26OCT-H0"]
    no_change = golden_markets["polymarket:2589812"]
    assert h0.books["YES"].asks[0] == OrderBookLevel(price=D("0.85"), quantity=D("60329.95"))
    assert h0.books["NO"].asks[0] == OrderBookLevel(price=D("0.16"), quantity=D("534.49"))
    assert h0.books["NO"].asks[1].price == D("0.17")  # 5000 NO spills onto this level (section 1)
    yes_best = OrderBookLevel(price=D("0.84"), quantity=D("295850.63"))
    assert no_change.books["YES"].asks[0] == yes_best
    assert no_change.books["NO"].asks[0] == OrderBookLevel(price=D("0.17"), quantity=D("67936.43"))
    assert golden_markets["kalshi:KXFEDDECISION-26OCT-C25"].books["NO"].asks == ()
    assert h0.fees == FeeSchedule(coefficient=D("0.07"), exponent=1, rounding_step=D("0.01"))
    assert no_change.fees == FeeSchedule(coefficient=D("0.05"), rounding_step=D("0.00001"))


def test_8_golden_markets_feed_the_equivalence_model(golden_markets):
    pair = (golden_markets["kalshi:KXFEDDECISION-26OCT-H0"], golden_markets["polymarket:2589812"])
    cluster = EquivalenceCluster(cluster_id="example", markets=pair)
    assert [m.market_id for m in cluster.markets] == [m.market_id for m in pair]
    result = MatchResult(
        market_a=pair[0].market_id,
        market_b=pair[1].market_id,
        status=EquivalenceStatus.EQUIVALENT,
        method="terms",
    )
    assert result.status == "EQUIVALENT"
