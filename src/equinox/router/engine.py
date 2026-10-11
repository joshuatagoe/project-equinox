"""Quotes, the decision and the trace (sections 7.1, 7.2 and 8.1).

Every market in the cluster is simulated, including ones that are excluded, so the trace can
show what each venue would have cost. The time comes in as an argument.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from equinox.models import (
    CanonicalMarket,
    Decision,
    EquinoxTrace,
    EquivalenceCluster,
    OrderRequest,
    QuoteReason,
    QuoteWarning,
    RoutingStatus,
    VenueQuote,
)
from equinox.router.depth import walk
from equinox.router.rationale import ASSUMPTIONS, CENT, explain, warning_lines

STALE_AFTER = timedelta(seconds=300)
FAILURES = (RoutingStatus.MARKET_NOT_FOUND, RoutingStatus.INVALID_INPUT)
NOT_REAL = {QuoteReason.NOT_TRADABLE, QuoteReason.TEST_MONEY}


def quote(
    market: CanonicalMarket, order: OrderRequest, now: datetime, stale_after: timedelta
) -> VenueQuote:
    """Walk the book, add the fee, and record every reason and warning that applies."""
    book = market.books[order.outcome]
    fills, filled = walk(book, order.quantity)
    base = sum((f.price * f.quantity for f in fills), Decimal(0))
    fee = market.fees.fee(fills)
    total = base + fee
    best_ask = book.asks[0].price if book.asks else None
    average = base / filled if filled else None

    reasons = _reasons(market, order, book.asks == (), filled, total)
    warnings = _warnings(
        market, now, stale_after, filled < order.quantity and not book.depth_complete
    )
    return VenueQuote(
        market_id=market.market_id,
        venue=market.venue,
        eligible=not reasons,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
        fills=tuple(fills),
        filled_quantity=filled,
        best_ask=best_ask,
        average_price=average,
        slippage=None if average is None else average - best_ask,
        base_cost=base,
        fee=fee,
        total_cost=total,
    )


def _reasons(
    market: CanonicalMarket, order: OrderRequest, empty: bool, filled: Decimal, total: Decimal
) -> list[QuoteReason]:
    """Every reason this venue can't take the order (section 7.1, step 3)."""
    checks = (
        (not market.tradable, QuoteReason.NOT_TRADABLE),
        (not market.collateral.has_value, QuoteReason.TEST_MONEY),
        (empty, QuoteReason.EMPTY_BOOK),
        (filled < order.quantity, QuoteReason.PARTIAL_FILL),
        (
            filled >= order.quantity and order.max_budget is not None and total > order.max_budget,
            QuoteReason.OVER_BUDGET,
        ),
    )
    return [reason for applies, reason in checks if applies]


def _warnings(
    market: CanonicalMarket, now: datetime, stale_after: timedelta, ran_out_of_partial_book: bool
) -> list[QuoteWarning]:
    """What the reader should know about this quote's data (section 7.1, step 4)."""
    checks = (
        (now - market.captured_at > stale_after, QuoteWarning.STALE_DATA),
        (market.data_source == "fixture", QuoteWarning.FIXTURE_DATA),
        (ran_out_of_partial_book, QuoteWarning.DEPTH_INCOMPLETE),
    )
    return [warning for applies, warning in checks if applies]


def simulate(
    order: OrderRequest,
    cluster: EquivalenceCluster,
    now: datetime,
    stale_after: timedelta = STALE_AFTER,
    trace_id: str | None = None,
) -> EquinoxTrace:
    """Quote every market in the cluster, pick the cheapest eligible one, and explain it."""
    if order.market_id not in {m.market_id for m in cluster.markets}:
        raise ValueError(f"the order's market {order.market_id} is not in the cluster")
    quotes = tuple(quote(m, order, now, stale_after) for m in cluster.markets)
    status, decision = decide(quotes)
    return EquinoxTrace(
        trace_id=trace_id or uuid4().hex,
        created_at=now,
        status=status,
        order=order,
        cluster=cluster,
        quotes=quotes,
        decision=decision,
        rationale=explain(status, order, cluster, quotes, decision),
        assumptions=ASSUMPTIONS,
        warnings=warning_lines(cluster.markets, quotes, order, now, stale_after),
    )


def decide(quotes: Sequence[VenueQuote]) -> tuple[RoutingStatus, Decision | None]:
    """The status table in section 7.2, and the winner with its savings when one is eligible."""
    ranked = sorted(
        (q for q in quotes if q.eligible), key=lambda q: (q.total_cost, q.fee, q.market_id)
    )
    if ranked:
        winner = ranked[0]
        if len(ranked) == 1:
            return RoutingStatus.ROUTED, Decision(
                winner=winner.market_id, runner_up=None, savings=None, savings_percent=None
            )
        runner_up = ranked[1]
        savings = runner_up.total_cost - winner.total_cost
        percent = (savings / runner_up.total_cost * 100).quantize(CENT, rounding=ROUND_HALF_UP)
        return RoutingStatus.ROUTED, Decision(
            winner=winner.market_id,
            runner_up=runner_up.market_id,
            savings=savings,
            savings_percent=percent,
        )
    real = [q for q in quotes if not NOT_REAL.intersection(q.reasons)]
    if not real:
        return RoutingStatus.NO_ELIGIBLE_VENUE, None
    if any(QuoteReason.OVER_BUDGET in q.reasons for q in real):  # only a full fill is over budget
        return RoutingStatus.BUDGET_EXCEEDED, None
    return RoutingStatus.INSUFFICIENT_LIQUIDITY, None


def failure_trace(
    status: RoutingStatus, message: str, order: OrderRequest | None = None, *, now: datetime
) -> EquinoxTrace:
    """A trace for a failure found before routing: no cluster, no quotes and no decision."""
    if status not in FAILURES:
        raise ValueError(f"{status} is decided by simulate(), not reported as a failure")
    return EquinoxTrace(
        trace_id=uuid4().hex,
        created_at=now,
        status=status,
        order=order,
        cluster=None,
        rationale=message,
        assumptions=ASSUMPTIONS,
    )
