"""An order's answer in words (Jordan): which venue to buy on, what it costs, and why.

The ticket (`ticket.py`) prices the order with the router; this module turns its trace into the
headline, the cost on each venue and the notes, and checks what the person typed.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from equinox.matcher import cluster_confidence
from equinox.models import (
    CanonicalMarket,
    EquinoxTrace,
    EquivalenceCluster,
    OrderRequest,
    QuoteReason,
    RoutingStatus,
    VenueQuote,
)
from equinox.router.rationale import CENT, contracts, dollars, money_step
from equinox.web import words

NOT_REAL = {QuoteReason.NOT_TRADABLE, QuoteReason.TEST_MONEY}
COLUMNS = ["Venue", "Can take it", "Would buy", "Average price", "Fee", "Total", "Why not"]


@dataclass
class Result:
    headline: str
    routed: bool
    rationale: str
    rows: list[list[str]]
    excluded: list[bool]
    verdict: str
    risks: tuple[str, ...]
    warnings: list[str]
    assumptions: tuple[str, ...]


def amount(text: str) -> Decimal | None:
    """A positive, finite number typed by a person ("1,000" allowed), else None."""
    try:
        value = Decimal(text.replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() and value > 0 else None


def form_errors(side: str, quantity: Decimal | None, budget_text: str, budget) -> list[str]:
    checks = (
        (side not in ("YES", "NO"), "Choose Buy YES or Buy NO."),
        (quantity is None, "Contracts must be a number greater than 0."),
        (
            bool(budget_text) and budget is None,
            "The budget must be a dollar amount greater than 0.",
        ),
    )
    return [message for failed, message in checks if failed]


def result(cluster: EquivalenceCluster, trace: EquinoxTrace) -> Result:
    """The page's answer to one order."""
    markets = {m.market_id: m for m in cluster.markets}
    quotes = sorted(trace.quotes, key=lambda q: (not q.eligible, q.total_cost, q.market_id))
    return Result(
        headline=headline(trace),
        routed=trace.status == RoutingStatus.ROUTED,
        rationale=trace.rationale,
        rows=_cost_rows(quotes, markets, trace.order),
        excluded=[not q.eligible for q in quotes],
        verdict=verdict(cluster),
        risks=cluster.risk_flags,
        warnings=[words.plain_note(w) for w in dict.fromkeys(trace.warnings)],
        assumptions=trace.assumptions,
    )


def _cost_rows(
    quotes: list[VenueQuote], markets: dict[str, CanonicalMarket], order: OrderRequest
) -> list[list[str]]:
    """One row per venue: what it would buy, at what average price, fee and total, or why not."""
    budget = dollars(order.max_budget, CENT) if order.max_budget else ""
    step = money_step([q.total_cost for q in quotes if q.filled_quantity])

    def row(q: VenueQuote) -> list[str]:
        filled = bool(q.filled_quantity)
        return [
            words.venue(q.venue),
            "Yes" if q.eligible else "No",
            words.fills(q),
            words.cents(q.average_price) if q.average_price is not None else "–",
            dollars(q.fee, step) if filled else "–",
            dollars(q.total_cost, step) if filled else "–",
            words.why_not(q, markets[q.market_id], order, budget) or "–",
        ]

    return [row(q) for q in quotes]


def verdict(cluster: EquivalenceCluster) -> str:
    if not cluster.pairs:
        only = words.venue(cluster.markets[0].venue)
        return f"Only {only} lists this outcome, so there is nothing to compare it with."
    level = cluster_confidence(cluster)
    reason = re.sub(r" \(D\d+\)", "", level.reason)  # decision numbers are for the docs
    return f"Same bet. Confidence: {level.level}. {reason}"


def headline(trace: EquinoxTrace) -> str:
    """The answer in one sentence, worded for the status (architecture section 8.3)."""
    if trace.status == RoutingStatus.ROUTED:
        return _routed(trace)
    order, size = trace.order, contracts(trace.order.quantity)
    real = [q for q in trace.quotes if not NOT_REAL.intersection(q.reasons)]
    if trace.status == RoutingStatus.BUDGET_EXCEEDED:
        full = [q for q in real if QuoteReason.OVER_BUDGET in q.reasons]
        cheapest = min(full, key=lambda q: q.total_cost)
        return (
            f"No venue can fill {size} {order.outcome} contracts within "
            f"{dollars(order.max_budget, CENT)}. The cheapest full fill is "
            f"{words.venue(cheapest.venue)} at {dollars(cheapest.total_cost, CENT)}."
        )
    if trace.status == RoutingStatus.INSUFFICIENT_LIQUIDITY:
        most = max(real, key=lambda q: q.filled_quantity)
        on_offer = (
            f"The most on offer is {contracts(most.filled_quantity)} on {words.venue(most.venue)}."
            if most.filled_quantity
            else f"Nobody is selling {order.outcome} on any open venue."
        )
        return f"No venue has {size} {order.outcome} contracts for sale. {on_offer}"
    return "No venue can take this order."


def _routed(trace: EquinoxTrace) -> str:
    order, decision = trace.order, trace.decision
    by_id = {q.market_id: q for q in trace.quotes}
    winner, runner_up = by_id[decision.winner], by_id.get(decision.runner_up or "")
    step = money_step([q.total_cost for q in (winner, runner_up) if q])
    text = (
        f"Buy on {words.venue(winner.venue)}: {dollars(winner.total_cost, step)} for "
        f"{contracts(order.quantity)} {order.outcome} contracts, including "
        f"{dollars(winner.fee, step)} in fees."
    )
    if runner_up is None:
        return f"{text} {words.venue(winner.venue)} is the only venue that can take this order."
    other = f"{words.venue(runner_up.venue)} at {dollars(runner_up.total_cost, step)}"
    saved = f"{dollars(decision.savings, step)} ({decision.savings_percent}%)"
    return f"{text} That's {saved} less than {other}."
