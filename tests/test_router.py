"""feat-04 acceptance tests: the routing simulator (architecture section 7, lane PRD tests 1-13).

Clusters are built directly from golden markets; the router doesn't depend on the matcher.
The injected time is 2026-10-10T20:48:00Z, when every golden book is 208-229 s old.
"""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from equinox.models import (
    EXIT_CODES,
    EquivalenceCluster,
    FeeSchedule,
    Fill,
    OrderBookLevel,
    OrderRequest,
    OutcomeBook,
    QuoteReason,
    QuoteWarning,
    RoutingStatus,
)
from equinox.router import failure_trace, quote, simulate, walk

D = Decimal
NOW = datetime(2026, 10, 10, 20, 48, tzinfo=UTC)
STALE_AFTER = timedelta(seconds=300)

H0 = "kalshi:KXFEDDECISION-26OCT-H0"
NO_CHANGE = "polymarket:2589812"
C25 = "kalshi:KXFEDDECISION-26OCT-C25"
CUT_25 = "polymarket:2589811"
AAPL_330 = "polymarket:5455686"
MERIDIAN_330 = "meridian:AAPL-330-2026-10-12"
MERIDIAN_320 = "meridian:AAPL-320-2026-10-12"
EDGE_FLAG = (
    'Edge-case rules differ: Kalshi: if the meeting is cancelled, "Fed maintains rate" '
    "resolves Yes. Polymarket: a change not shown in the brackets is rounded up to the nearest "
    "25 bps."
)

R = QuoteReason
W = QuoteWarning
S = RoutingStatus


def cluster(*markets, risk_flags=()):
    return EquivalenceCluster(cluster_id="test", markets=markets, risk_flags=risk_flags)


def order(market_id, outcome, quantity, budget=None):
    return OrderRequest(
        market_id=market_id,
        outcome=outcome,
        quantity=D(quantity),
        max_budget=None if budget is None else D(budget),
    )


def quotes(trace):
    return {q.market_id: q for q in trace.quotes}


def with_asks(market, outcome, *levels, depth_complete=True):
    book = OutcomeBook(
        asks=tuple(OrderBookLevel(price=D(p), quantity=D(q)) for p, q in levels),
        depth_complete=depth_complete,
    )
    return market.model_copy(update={"books": {**market.books, outcome: book}})


def incomplete(market, outcome):
    book = market.books[outcome].model_copy(update={"depth_complete": False})
    return market.model_copy(update={"books": {**market.books, outcome: book}})


def fills(*levels):
    return [Fill(price=D(p), quantity=D(q)) for p, q in levels]


@pytest.fixture
def g(golden_markets):
    return golden_markets


@pytest.fixture
def fed(g):
    return cluster(g[H0], g[NO_CHANGE], risk_flags=(EDGE_FLAG,))


# The depth walk (section 7.1, step 1).


def test_walk_fills_from_the_cheapest_level_and_spills_onto_the_next(g):
    taken, filled = walk(g[H0].books["NO"], D("5000"))
    assert taken == fills(("0.16", "534.49"), ("0.17", "4465.51"))
    assert filled == D("5000")


def test_walk_that_ends_exactly_on_a_level_takes_nothing_from_the_next(g):
    taken, filled = walk(g[H0].books["NO"], D("534.49"))
    assert taken == fills(("0.16", "534.49"))
    assert filled == D("534.49")


def test_walk_stops_when_the_levels_run_out(g):
    taken, filled = walk(g[H0].books["YES"], D("5000000"))
    assert len(taken) == 3
    assert filled == D("252118.27")


def test_walk_on_an_empty_book_fills_nothing(g):
    assert walk(g[C25].books["NO"], D("100")) == ([], D("0"))


# Test 1: the running example, 100 YES.


def test_1_100_yes_routes_to_the_lower_total(fed):
    trace = simulate(order(H0, "YES", "100"), fed, NOW)
    q = quotes(trace)
    assert trace.status == S.ROUTED
    assert trace.decision.winner == NO_CHANGE
    assert trace.decision.runner_up == H0
    assert (q[NO_CHANGE].total_cost, q[H0].total_cost) == (D("84.672"), D("85.90"))
    assert (q[NO_CHANGE].fee, q[H0].fee) == (D("0.672"), D("0.90"))
    assert trace.decision.savings == D("1.228")
    assert trace.decision.savings_percent == D("1.43")
    assert all(x.eligible and x.reasons == () for x in trace.quotes)


def test_1_quote_records_fills_cost_average_and_slippage(g):
    q = quote(g[H0], order(H0, "YES", "100"), NOW, STALE_AFTER)
    assert q.market_id == H0 and q.venue == "kalshi"
    assert q.fills == tuple(fills(("0.85", "100")))
    assert q.filled_quantity == D("100")
    assert q.best_ask == D("0.85")
    assert q.base_cost == D("85")
    assert q.average_price == D("0.85")
    assert q.slippage == D("0")


# Test 2: 100 NO goes the other way, even though Kalshi's fee is the higher one.


def test_2_100_no_routes_to_the_lower_total_despite_its_higher_fee(fed):
    trace = simulate(order(H0, "NO", "100"), fed, NOW)
    q = quotes(trace)
    assert trace.status == S.ROUTED
    assert trace.decision.winner == H0
    assert (q[H0].total_cost, q[NO_CHANGE].total_cost) == (D("16.95"), D("17.7055"))
    assert q[H0].fee > q[NO_CHANGE].fee
    assert trace.decision.savings == D("0.7555")
    assert trace.decision.savings_percent == D("4.27")


# Test 3: 5000 NO walks two Kalshi levels, and the answer flips (D5).


def test_3_5000_no_walks_two_levels_and_routes_to_polymarket(fed):
    trace = simulate(order(H0, "NO", "5000"), fed, NOW)
    q = quotes(trace)
    kalshi = q[H0]
    assert trace.status == S.ROUTED
    assert trace.decision.winner == NO_CHANGE
    assert (q[NO_CHANGE].total_cost, kalshi.total_cost) == (D("885.275"), D("893.7951"))
    assert kalshi.fills == tuple(fills(("0.16", "534.49"), ("0.17", "4465.51")))
    assert kalshi.fee == D("49.14")
    assert kalshi.average_price.quantize(D("0.0001")) == D("0.1689")
    assert kalshi.slippage.quantize(D("0.0001")) == D("0.0089")
    assert kalshi.slippage == kalshi.average_price - kalshi.best_ask
    assert trace.decision.savings == D("8.5201")
    assert trace.decision.savings_percent == D("0.95")


# Test 4: the budget (D7).


def test_4_every_full_fill_over_budget_is_budget_exceeded(fed):
    trace = simulate(order(H0, "YES", "100", budget="80"), fed, NOW)
    assert trace.status == S.BUDGET_EXCEEDED
    assert EXIT_CODES[trace.status] == 3
    assert trace.decision is None
    assert all(x.reasons == (R.OVER_BUDGET,) for x in trace.quotes)
    assert (
        "No open, real-money venue can fill all 100 YES contracts within the $80.00 budget."
        in trace.rationale
    )


def test_4_a_total_equal_to_the_budget_is_within_it(fed):
    trace = simulate(order(H0, "YES", "100", budget="84.672"), fed, NOW)
    q = quotes(trace)
    assert trace.status == S.ROUTED
    assert q[NO_CHANGE].eligible
    assert q[H0].reasons == (R.OVER_BUDGET,)
    assert trace.decision.winner == NO_CHANGE
    assert trace.decision.runner_up is None
    assert trace.decision.savings is None and trace.decision.savings_percent is None


# Test 5: depth (D6).


def test_5_no_full_fill_is_insufficient_liquidity_with_depth_incomplete(g):
    thin = cluster(incomplete(g[H0], "YES"), incomplete(g[NO_CHANGE], "YES"))
    trace = simulate(order(H0, "YES", "5000000"), thin, NOW)
    q = quotes(trace)
    assert trace.status == S.INSUFFICIENT_LIQUIDITY
    assert EXIT_CODES[trace.status] == 2
    assert trace.decision is None
    assert all(x.reasons == (R.PARTIAL_FILL,) for x in trace.quotes)
    assert all(W.DEPTH_INCOMPLETE in x.warnings for x in trace.quotes)
    assert q[H0].filled_quantity == D("252118.27")
    assert q[NO_CHANGE].filled_quantity == D("1216380.16")


def test_5_a_complete_book_that_runs_out_has_no_depth_warning(fed):
    trace = simulate(order(H0, "YES", "5000000"), fed, NOW)
    assert trace.status == S.INSUFFICIENT_LIQUIDITY
    assert all(W.DEPTH_INCOMPLETE not in x.warnings for x in trace.quotes)


def test_5_an_incomplete_book_that_fills_the_order_has_no_depth_warning(g):
    q = quote(incomplete(g[H0], "YES"), order(H0, "YES", "100"), NOW, STALE_AFTER)
    assert q.eligible
    assert W.DEPTH_INCOMPLETE not in q.warnings


def test_5_a_partial_fill_is_never_over_budget(fed):
    trace = simulate(order(H0, "YES", "5000000", budget="1"), fed, NOW)
    assert trace.status == S.INSUFFICIENT_LIQUIDITY
    assert all(x.reasons == (R.PARTIAL_FILL,) for x in trace.quotes)


# Test 6: an empty book is simulated and shown, but can't win.


def test_6_empty_book_is_excluded_and_the_other_venue_wins(g):
    trace = simulate(order(C25, "NO", "100"), cluster(g[C25], g[CUT_25]), NOW)
    q = quotes(trace)
    kalshi = q[C25]
    assert trace.status == S.ROUTED
    assert trace.decision.winner == CUT_25
    assert q[CUT_25].total_cost == D("99.61992")
    assert R.EMPTY_BOOK in kalshi.reasons
    assert kalshi.fills == () and kalshi.filled_quantity == 0
    assert kalshi.best_ask is None and kalshi.average_price is None and kalshi.slippage is None
    assert kalshi.base_cost == 0 and kalshi.fee == 0 and kalshi.total_cost == 0


def test_6_empty_book_records_every_reason_that_applies_but_explains_it_once(g):
    trace = simulate(order(C25, "NO", "100"), cluster(g[C25], g[CUT_25]), NOW)
    assert quotes(trace)[C25].reasons == (R.EMPTY_BOOK, R.PARTIAL_FILL)
    assert "Kalshi was not eligible: nobody is selling NO." in trace.rationale
    assert "only 0 of" not in trace.rationale
    assert "Polymarket is the only eligible venue that can fill all 100 NO contracts: $99.62" in (
        trace.rationale
    )


# Tests 7-9: the Meridian fit check (section 9.3, D24).


def test_7_test_money_is_simulated_but_cannot_win(g):
    trace = simulate(order(AAPL_330, "YES", "5"), cluster(g[AAPL_330], g[MERIDIAN_330]), NOW)
    q = quotes(trace)
    assert trace.status == S.ROUTED
    assert trace.decision.winner == AAPL_330
    assert q[AAPL_330].total_cost == D("4.80768")
    assert q[MERIDIAN_330].reasons == (R.TEST_MONEY,)
    assert q[MERIDIAN_330].total_cost == D("4.75")
    assert q[MERIDIAN_330].total_cost < q[AAPL_330].total_cost
    assert "would cost $4.75" in trace.rationale
    assert (
        "Meridian was not eligible: it settles in devnet USDC, which has no monetary value "
        "(it would cost $4.75)." in trace.rationale
    )


def test_8_test_money_that_is_also_too_thin_records_both_reasons(g):
    trace = simulate(order(AAPL_330, "YES", "10"), cluster(g[AAPL_330], g[MERIDIAN_330]), NOW)
    q = quotes(trace)
    assert trace.status == S.ROUTED
    assert trace.decision.winner == AAPL_330
    assert q[AAPL_330].total_cost == D("9.61536")
    assert q[MERIDIAN_330].reasons == (R.TEST_MONEY, R.PARTIAL_FILL)
    assert q[MERIDIAN_330].filled_quantity == D("5")
    assert "only 5 of 10 contracts are available" in trace.rationale
    assert "would cost" not in trace.rationale  # a partial fill has no full-order cost


def test_9_test_money_alone_is_no_eligible_venue(g):
    trace = simulate(order(MERIDIAN_320, "YES", "5"), cluster(g[MERIDIAN_320]), NOW)
    assert trace.status == S.NO_ELIGIBLE_VENUE
    assert EXIT_CODES[trace.status] == 5
    assert trace.decision is None
    assert trace.quotes[0].reasons == (R.TEST_MONEY,)
    assert trace.quotes[0].total_cost == D("4.85")
    assert trace.rationale.startswith("No venue can take this order")
    assert "Meridian was not eligible: it settles in devnet USDC" in trace.rationale


# Test 10: a market that isn't tradable (D25).


def test_10_not_tradable_is_simulated_but_cannot_win(g):
    closed = g[H0].model_copy(update={"tradable": False})
    trace = simulate(order(H0, "YES", "100"), cluster(closed, g[NO_CHANGE]), NOW)
    q = quotes(trace)
    assert trace.status == S.ROUTED
    assert trace.decision.winner == NO_CHANGE
    assert trace.decision.runner_up is None
    assert q[H0].reasons == (R.NOT_TRADABLE,)
    assert q[H0].total_cost == D("85.90")
    assert "Kalshi was not eligible: it is not accepting orders right now" in trace.rationale


# Status rules when no venue is eligible (section 7.2), for the readings that aren't obvious.


def test_status_every_venue_closed_or_test_money_is_no_eligible_venue(g):
    closed = g[H0].model_copy(update={"tradable": False})
    trace = simulate(order(H0, "YES", "5"), cluster(closed, g[MERIDIAN_330]), NOW)
    assert trace.status == S.NO_ELIGIBLE_VENUE


def test_status_a_thin_real_venue_beside_a_full_test_money_venue_is_insufficient(g):
    thin = with_asks(g[AAPL_330], "YES", ("0.96", "3"))
    trace = simulate(order(AAPL_330, "YES", "5"), cluster(thin, g[MERIDIAN_330]), NOW)
    assert quotes(trace)[MERIDIAN_330].reasons == (R.TEST_MONEY,)
    assert trace.status == S.INSUFFICIENT_LIQUIDITY


def test_status_one_real_venue_over_budget_and_one_thin_is_budget_exceeded(g):
    thin = with_asks(g[H0], "YES", ("0.85", "50"))
    trace = simulate(order(H0, "YES", "100", budget="80"), cluster(thin, g[NO_CHANGE]), NOW)
    q = quotes(trace)
    assert (q[H0].reasons, q[NO_CHANGE].reasons) == ((R.PARTIAL_FILL,), (R.OVER_BUDGET,))
    assert trace.status == S.BUDGET_EXCEEDED


def test_status_over_budget_on_a_closed_venue_does_not_count(g):
    closed = g[NO_CHANGE].model_copy(update={"tradable": False})
    thin = with_asks(g[H0], "YES", ("0.85", "50"))
    trace = simulate(order(H0, "YES", "100", budget="80"), cluster(thin, closed), NOW)
    assert quotes(trace)[NO_CHANGE].reasons == (R.NOT_TRADABLE, R.OVER_BUDGET)
    assert trace.status == S.INSUFFICIENT_LIQUIDITY


def test_status_an_empty_real_book_beside_test_money_is_insufficient(g):
    empty = with_asks(g[AAPL_330], "YES")
    trace = simulate(order(AAPL_330, "YES", "5"), cluster(empty, g[MERIDIAN_330]), NOW)
    assert trace.status == S.INSUFFICIENT_LIQUIDITY


# Test 11: tie-breaks (section 7.2).


def test_11_equal_totals_go_to_the_lower_fee(g):
    # The lower fee sits on the higher market_id, so the market_id rule can't pass this by luck.
    free = FeeSchedule(coefficient=D("0"), rounding_step=D("0.01"))
    charged = FeeSchedule(coefficient=D("0.04"), rounding_step=D("0.01"))  # 0.9996 -> 1.00
    low_fee = with_asks(g["polymarket:E11"], "YES", ("0.52", "100")).model_copy(
        update={"fees": free}
    )
    high_fee = with_asks(g["kalshi:E11"], "YES", ("0.51", "100")).model_copy(
        update={"fees": charged}
    )
    trace = simulate(order("kalshi:E11", "YES", "100"), cluster(high_fee, low_fee), NOW)
    q = quotes(trace)
    assert q["kalshi:E11"].total_cost == q["polymarket:E11"].total_cost == D("52")
    assert trace.decision.winner == "polymarket:E11"
    assert trace.decision.savings == 0 and trace.decision.savings_percent == 0
    assert "The totals are equal, so the lower fee decides." in trace.rationale


def test_11_equal_totals_and_fees_go_to_the_lower_market_id(g):
    free = FeeSchedule(coefficient=D("0"), rounding_step=D("0.01"))
    a = g["kalshi:E11"].model_copy(update={"fees": free})
    b = g["polymarket:E11"].model_copy(update={"fees": free})
    trace = simulate(order("kalshi:E11", "YES", "100"), cluster(b, a), NOW)
    assert trace.decision.winner == "kalshi:E11"
    assert trace.decision.runner_up == "polymarket:E11"
    assert "$52.00000" in trace.rationale  # equal at the cent, so shown to 5 places (4.6)
    assert "The totals and fees are equal, so the lower market ID decides." in trace.rationale


def test_11_runner_up_is_the_next_cheapest_eligible_venue(g, fed):
    near = g[NO_CHANGE].model_copy(
        update={"market_id": "polymarket:2589812-b", "native_id": "2589812-b"}
    )
    near = with_asks(near, "YES", ("0.845", "100"))  # 84.5 + fee 0.654875, rounded up: 85.15488
    trace = simulate(order(H0, "YES", "100"), cluster(g[H0], near, g[NO_CHANGE]), NOW)
    assert trace.decision.winner == NO_CHANGE
    assert trace.decision.runner_up == "polymarket:2589812-b"
    assert trace.decision.savings == D("0.48288")


# Test 12: warnings show, and the venue stays eligible (D17).


def test_12_stale_fixture_data_warns_but_stays_eligible(g):
    old = g[H0].model_copy(update={"captured_at": NOW - timedelta(minutes=10)})
    trace = simulate(order(H0, "YES", "100"), cluster(old, g[NO_CHANGE]), NOW)
    q = quotes(trace)[H0]
    assert q.eligible
    assert q.warnings == (W.STALE_DATA, W.FIXTURE_DATA)
    assert any("Kalshi" in w and "600 seconds old" in w for w in trace.warnings)


def test_12_golden_books_are_fresh_and_marked_as_fixture_data(fed):
    trace = simulate(order(H0, "YES", "100"), fed, NOW)
    assert all(x.warnings == (W.FIXTURE_DATA,) for x in trace.quotes)
    assert len(trace.warnings) == 2
    assert all("snapshot" in w for w in trace.warnings)


def test_12_a_book_exactly_at_the_limit_is_not_stale(g):
    edge = g[H0].model_copy(update={"captured_at": NOW - STALE_AFTER, "data_source": "live"})
    q = quote(edge, order(H0, "YES", "100"), NOW, STALE_AFTER)
    assert q.warnings == ()


def test_12_stale_after_is_a_parameter(g, fed):
    trace = simulate(order(H0, "YES", "100"), fed, NOW, stale_after=timedelta(seconds=60))
    assert all(W.STALE_DATA in x.warnings for x in trace.quotes)


# Test 13: the rationale (section 7.2).


def test_13_rationale_for_the_running_example(fed):
    rationale = simulate(order(H0, "YES", "100"), fed, NOW).rationale
    assert "Polymarket is the cheapest venue that can fill all 100 YES contracts" in rationale
    assert "$84.67" in rationale
    assert "$85.90" in rationale
    assert "1.43%" in rationale
    assert "Match risks: Edge-case rules differ" in rationale
    assert "$84.67 including $0.67 in fees, versus $85.90 on Kalshi ($1.23 or 1.43% less)" in (
        rationale
    )


def test_13_totals_equal_at_the_cent_are_shown_to_five_places(g):
    near = g[NO_CHANGE].model_copy(
        update={
            "market_id": "polymarket:2589812-b",
            "native_id": "2589812-b",
            "fees": FeeSchedule(coefficient=D("0.0501"), rounding_step=D("0.00001")),
        }
    )
    trace = simulate(order(NO_CHANGE, "YES", "100"), cluster(near, g[NO_CHANGE]), NOW)
    assert quotes(trace)["polymarket:2589812-b"].total_cost == D("84.67335")
    assert "$84.67200" in trace.rationale
    assert "$84.67335" in trace.rationale


def test_13_insufficient_liquidity_rationale_explains_each_venue(g):
    thin = cluster(incomplete(g[H0], "YES"), incomplete(g[NO_CHANGE], "YES"))
    rationale = simulate(order(H0, "YES", "5000000"), thin, NOW).rationale
    assert "No open, real-money venue can fill all 5,000,000 YES contracts." in rationale
    assert "Kalshi was not eligible: only 252,118.27 of 5,000,000 contracts" in rationale
    assert "Polymarket was not eligible: only 1,216,380.16 of 5,000,000 contracts" in rationale


def test_13_budget_rationale_names_each_cost(fed):
    rationale = simulate(order(H0, "YES", "100", budget="80"), fed, NOW).rationale
    assert "Polymarket was not eligible: it would cost $84.67, over the $80.00 budget." in (
        rationale
    )
    assert "Kalshi was not eligible: it would cost $85.90, over the $80.00 budget." in rationale


def test_13_no_risk_flags_means_no_match_risks_sentence(g):
    rationale = simulate(order(H0, "YES", "100"), cluster(g[H0], g[NO_CHANGE]), NOW).rationale
    assert "Match risks" not in rationale


# The trace (section 8.1).


def test_trace_records_order_cluster_time_and_assumptions(fed):
    o = order(H0, "YES", "100")
    trace = simulate(o, fed, NOW)
    assert trace.order == o
    assert trace.cluster == fed
    assert trace.created_at == NOW
    assert re.fullmatch("[0-9a-f]{32}", trace.trace_id)
    assert len(trace.assumptions) == 4
    text = " ".join(trace.assumptions)
    for words in ("USDC", "frozen", "rounded up", "rebates"):
        assert words in text


def test_trace_id_can_be_given_and_defaults_to_a_new_one(fed):
    o = order(H0, "YES", "100")
    assert simulate(o, fed, NOW, trace_id="t-1").trace_id == "t-1"
    assert simulate(o, fed, NOW).trace_id != simulate(o, fed, NOW).trace_id


def test_quotes_follow_the_cluster_order(fed):
    trace = simulate(order(H0, "YES", "100"), fed, NOW)
    assert [x.market_id for x in trace.quotes] == [H0, NO_CHANGE]


def test_an_order_for_a_market_outside_the_cluster_is_refused(g, fed):
    with pytest.raises(ValueError, match="not in the cluster"):
        simulate(order(C25, "YES", "100"), fed, NOW)


# Failure traces for the CLI (MARKET_NOT_FOUND and INVALID_INPUT).


def test_failure_trace_for_a_missing_market(g):
    o = order("kalshi:NOPE", "YES", "1")
    trace = failure_trace(S.MARKET_NOT_FOUND, "No market kalshi:NOPE was loaded.", o, now=NOW)
    assert trace.status == S.MARKET_NOT_FOUND
    assert EXIT_CODES[trace.status] == 1
    assert trace.order == o
    assert trace.rationale == "No market kalshi:NOPE was loaded."
    assert trace.cluster is None and trace.quotes == () and trace.decision is None
    assert trace.created_at == NOW
    assert len(trace.assumptions) == 4


def test_failure_trace_for_invalid_input_needs_no_order():
    trace = failure_trace(S.INVALID_INPUT, "Quantity must be greater than 0.", now=NOW)
    assert trace.status == S.INVALID_INPUT
    assert EXIT_CODES[trace.status] == 4
    assert trace.order is None and trace.decision is None


@pytest.mark.parametrize("status", [S.ROUTED, S.BUDGET_EXCEEDED, S.NO_ELIGIBLE_VENUE])
def test_failure_trace_refuses_statuses_the_router_decides(status):
    with pytest.raises(ValueError):
        failure_trace(status, "nope", now=NOW)
