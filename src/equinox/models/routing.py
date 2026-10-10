"""Orders, quotes and routing outcomes (architecture sections 7.1, 7.2 and 8.1)."""

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from equinox.models.canonical import Exact, Fill, Frozen, Outcome


class QuoteReason(StrEnum):
    """Why a venue is excluded. Every reason that applies is recorded."""

    NOT_TRADABLE = "NOT_TRADABLE"
    TEST_MONEY = "TEST_MONEY"
    EMPTY_BOOK = "EMPTY_BOOK"
    PARTIAL_FILL = "PARTIAL_FILL"
    OVER_BUDGET = "OVER_BUDGET"


class QuoteWarning(StrEnum):
    """Shown on a quote; the venue stays eligible."""

    STALE_DATA = "STALE_DATA"
    FIXTURE_DATA = "FIXTURE_DATA"
    DEPTH_INCOMPLETE = "DEPTH_INCOMPLETE"


class RoutingStatus(StrEnum):
    ROUTED = "ROUTED"
    MARKET_NOT_FOUND = "MARKET_NOT_FOUND"
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    INVALID_INPUT = "INVALID_INPUT"
    NO_ELIGIBLE_VENUE = "NO_ELIGIBLE_VENUE"


EXIT_CODES: dict[RoutingStatus, int] = {
    RoutingStatus.ROUTED: 0,
    RoutingStatus.MARKET_NOT_FOUND: 1,
    RoutingStatus.INSUFFICIENT_LIQUIDITY: 2,
    RoutingStatus.BUDGET_EXCEEDED: 3,
    RoutingStatus.INVALID_INPUT: 4,
    RoutingStatus.NO_ELIGIBLE_VENUE: 5,
}
"""One exit code per status (D27)."""


class OrderRequest(Frozen):
    market_id: str
    outcome: Outcome
    quantity: Exact = Field(gt=0)
    max_budget: Annotated[Exact, Field(gt=0)] | None = None


class VenueQuote(Frozen):
    market_id: str
    venue: str
    eligible: bool
    reasons: tuple[QuoteReason, ...]
    warnings: tuple[QuoteWarning, ...]
    fills: tuple[Fill, ...]
    filled_quantity: Exact
    best_ask: Exact | None
    average_price: Exact | None
    slippage: Exact | None
    base_cost: Exact
    fee: Exact
    total_cost: Exact

    @model_validator(mode="after")
    def _eligible_means_no_reasons(self) -> "VenueQuote":
        if self.eligible == bool(self.reasons):
            raise ValueError("a quote is eligible exactly when it has no exclusion reasons")
        return self


class Decision(Frozen):
    winner: str  # market_id
    runner_up: str | None
    savings: Exact | None
    savings_percent: Exact | None
