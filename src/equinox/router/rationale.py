"""The plain-words parts of a trace: rationale, assumptions and warnings (section 7.2).

Venue display names come only from each market's `venue` field, capitalized.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import combinations

from equinox.models import (
    CanonicalMarket,
    Decision,
    EquivalenceCluster,
    OrderRequest,
    QuoteReason,
    QuoteWarning,
    RoutingStatus,
    VenueQuote,
)

CENT = Decimal("0.01")
FINE = Decimal("0.00001")  # used when two amounts would otherwise read the same (section 4.6)

ASSUMPTIONS: tuple[str, ...] = (
    "One US dollar is worth one USDC, with no transfer cost or delay, so costs on venues that "
    "settle in either are compared directly. This applies only to collateral with monetary "
    "value.",
    "Order books are treated as frozen at the moment they were captured. Real books move in "
    "milliseconds, and this simulation is not live.",
    "Where a venue's fee rounding depends on the account type, fees are rounded up to the cent, "
    "as for FCM-cleared accounts. A direct-member account may pay up to 1 cent less per order; "
    "rounding up never understates the cost.",
    "Costs use list fees. Taker rebates and builder fees are ignored, so a venue that pays "
    "rebates can be cheaper in practice than shown.",
)


def name(quote: VenueQuote) -> str:
    return quote.venue.capitalize()


def contracts(quantity: Decimal) -> str:
    return f"{quantity.normalize():,f}"


def dollars(amount: Decimal, step: Decimal) -> str:
    return f"${amount.quantize(step, rounding=ROUND_HALF_UP):,f}"


def money_step(amounts: Sequence[Decimal]) -> Decimal:
    """Cents, unless two of the amounts shown would round to the same cent (section 4.6)."""
    cents = [amount.quantize(CENT, rounding=ROUND_HALF_UP) for amount in amounts]
    return FINE if any(a == b for a, b in combinations(cents, 2)) else CENT


def explain(
    status: RoutingStatus,
    order: OrderRequest,
    cluster: EquivalenceCluster,
    quotes: Sequence[VenueQuote],
    decision: Decision | None,
) -> str:
    """The lead sentence, a tie-break note, one sentence per excluded venue, then match risks."""
    by_id = {q.market_id: q for q in quotes}
    markets = {m.market_id: m for m in cluster.markets}
    excluded = [q for q in quotes if not q.eligible]
    step = money_step(_amounts_shown(order, quotes, decision))
    want = f"all {contracts(order.quantity)} {order.outcome} contracts"

    sentences: list[str] = []
    if decision is not None:
        sentences += _routed(want, by_id, decision, step)
    elif status == RoutingStatus.BUDGET_EXCEEDED:
        budget = dollars(order.max_budget, step)
        sentences.append(f"No open, real-money venue can fill {want} within the {budget} budget.")
    elif status == RoutingStatus.INSUFFICIENT_LIQUIDITY:
        sentences.append(f"No open, real-money venue can fill {want}.")
    else:
        sentences.append(
            "No venue can take this order: each one is closed to orders or settles in money "
            "with no value."
        )
    sentences += [_excluded(q, markets[q.market_id], order, step) for q in excluded]
    if cluster.risk_flags:
        flags = " ".join(_sentence(flag) for flag in cluster.risk_flags)
        sentences.append(f"Match risks: {flags}")
    return " ".join(sentences)


def warning_lines(
    markets: Sequence[CanonicalMarket],
    quotes: Sequence[VenueQuote],
    order: OrderRequest,
    now: datetime,
    stale_after: timedelta,
) -> tuple[str, ...]:
    """Each quote warning in plain words, prefixed by the venue's display name."""
    lines: list[str] = []
    for market, q in zip(markets, quotes, strict=True):
        for warning in q.warnings:
            if warning == QuoteWarning.STALE_DATA:
                age = (now - market.captured_at) // timedelta(seconds=1)
                limit = stale_after // timedelta(seconds=1)
                captured = market.captured_at.isoformat().replace("+00:00", "Z")
                text = (
                    f"its order book is {age} seconds old (captured {captured}), past the "
                    f"{limit}-second limit."
                )
            elif warning == QuoteWarning.FIXTURE_DATA:
                text = "prices come from a saved snapshot, not a live request."
            else:
                text = (
                    f"the venue returned only part of its {order.outcome} book, so more "
                    "contracts may be available than this simulation filled."
                )
            lines.append(f"{name(q)}: {text}")
    return tuple(lines)


def _routed(
    want: str, by_id: dict[str, VenueQuote], decision: Decision, step: Decimal
) -> list[str]:
    winner = by_id[decision.winner]
    lead = f"{dollars(winner.total_cost, step)} including {dollars(winner.fee, step)} in fees"
    if decision.runner_up is None:
        return [f"{name(winner)} is the only eligible venue that can fill {want}: {lead}."]
    runner_up = by_id[decision.runner_up]
    sentences = [
        f"{name(winner)} is the cheapest venue that can fill {want}: {lead}, versus "
        f"{dollars(runner_up.total_cost, step)} on {name(runner_up)} "
        f"({dollars(decision.savings, step)} or {decision.savings_percent}% less)."
    ]
    if decision.savings == 0:
        if winner.fee == runner_up.fee:
            sentences.append("The totals and fees are equal, so the lower market ID decides.")
        else:
            sentences.append("The totals are equal, so the lower fee decides.")
    return sentences


def _excluded(q: VenueQuote, market: CanonicalMarket, order: OrderRequest, step: Decimal) -> str:
    fully_filled = q.filled_quantity == order.quantity
    parts: list[str] = []
    for reason in q.reasons:
        if reason == QuoteReason.NOT_TRADABLE:
            parts.append("it is not accepting orders right now")
        elif reason == QuoteReason.TEST_MONEY:
            parts.append(f"it settles in {market.collateral.asset}, which has no monetary value")
        elif reason == QuoteReason.EMPTY_BOOK:
            parts.append(f"nobody is selling {order.outcome}")
        elif reason == QuoteReason.PARTIAL_FILL:
            if QuoteReason.EMPTY_BOOK not in q.reasons:  # an empty book already says it
                parts.append(
                    f"only {contracts(q.filled_quantity)} of {contracts(order.quantity)} "
                    "contracts are available"
                )
        else:
            parts.append(
                f"it would cost {dollars(q.total_cost, step)}, over the "
                f"{dollars(order.max_budget, step)} budget"
            )
    cost = ""
    if fully_filled and QuoteReason.OVER_BUDGET not in q.reasons:
        cost = f" (it would cost {dollars(q.total_cost, step)})"
    return f"{name(q)} was not eligible: {'; '.join(parts)}{cost}."


def _amounts_shown(
    order: OrderRequest, quotes: Sequence[VenueQuote], decision: Decision | None
) -> list[Decimal]:
    """The totals the rationale prints, plus the budget when an over-budget cost is printed."""
    shown = [q for q in quotes if q.filled_quantity == order.quantity]
    amounts = [q.total_cost for q in shown if not q.eligible]
    if decision is not None:
        by_id = {q.market_id: q for q in quotes}
        amounts += [by_id[m].total_cost for m in (decision.winner, decision.runner_up) if m]
    if any(QuoteReason.OVER_BUDGET in q.reasons for q in quotes):
        amounts.append(order.max_budget)
    return amounts


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else f"{text}."
