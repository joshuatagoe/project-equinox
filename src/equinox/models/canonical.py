"""The canonical market: books, fees, contract terms (architecture section 4).

No I/O and no venue names. Money and quantities are Decimal (D3), and every datetime carries a
time zone and is stored in UTC.
"""

from collections.abc import Sequence
from datetime import UTC, date
from decimal import ROUND_CEILING, Decimal
from itertools import pairwise
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("floats are not exact: pass a Decimal or a numeric string (D3)")
    return value


Exact = Annotated[Decimal, BeforeValidator(_reject_float)]
"""A Decimal that refuses floats, for money, quantities and thresholds."""

UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(UTC))]
"""Rejects a naive datetime and stores an aware one in UTC."""

Outcome = Literal["YES", "NO"]
Comparison = Literal["gt", "ge", "lt", "le", "eq", "between"]


class OrderBookLevel(Frozen):
    price: Exact = Field(gt=0, lt=1)  # dollars per contract
    quantity: Exact = Field(gt=0)  # contracts; fractional allowed


class OutcomeBook(Frozen):
    asks: tuple[OrderBookLevel, ...] = ()  # what it costs to buy this outcome: cheapest first
    bids: tuple[OrderBookLevel, ...] = ()  # what you'd get to sell it: highest first
    depth_complete: bool = True  # False if the venue returned only part of the book

    @model_validator(mode="after")
    def _best_first(self) -> "OutcomeBook":
        if any(later.price <= earlier.price for earlier, later in pairwise(self.asks)):
            raise ValueError("asks must be strictly rising, cheapest first")
        if any(later.price >= earlier.price for earlier, later in pairwise(self.bids)):
            raise ValueError("bids must be strictly falling, highest first")
        return self


class Fill(Frozen):
    price: Exact
    quantity: Exact


class FeeSchedule(Frozen):
    coefficient: Exact = Field(ge=0)  # 0 means no fee
    exponent: int = Field(default=1, ge=1)
    rounding_step: Exact = Field(gt=0)

    def fee(self, fills: Sequence[Fill]) -> Decimal:
        """Round up, once, the sum over fills of coefficient x quantity x (p x (1 - p)) ** exponent.

        Summing per level matters because the curve isn't a straight line (D5, D13).
        """
        raw = sum(
            (self.coefficient * f.quantity * (f.price * (1 - f.price)) ** self.exponent)
            for f in fills
        )
        steps = (raw / self.rounding_step).to_integral_value(rounding=ROUND_CEILING)
        return steps * self.rounding_step


class Collateral(Frozen):
    asset: str  # "USD", "USDC", "devnet USDC"
    has_value: bool  # False for test money (D24)


class ResolutionSource(Frozen):
    name: str
    url: str | None = None

    @property
    def institution(self) -> str:
        """Who resolves it: the URL's host without "www.", else the name (D18)."""
        host = urlsplit(self.url).hostname if self.url else None
        if host:
            return host.removeprefix("www.")
        return self.name.lower()


class ContractTerms(Frozen):
    """What a market pays on, in one venue-neutral shape (D22)."""

    subject: str  # "FOMC", "AAPL"
    measure: str  # "fed_upper_bound_change", "close_price"
    measured_by: str  # "fomc_statement", "pyth_regular_close", "official_close"
    observed_on: date  # the date in New York
    observed_at: UtcDatetime | None = None  # the exact instant, when the venue states one
    comparison: Comparison
    threshold: Exact
    upper: Exact | None = None  # required for "between", forbidden otherwise
    unit: Literal["bps", "usd"]
    fallback_rules: tuple[str, ...] = ()  # the venue's edge-case rules in plain words

    @model_validator(mode="after")
    def _range(self) -> "ContractTerms":
        if (self.comparison == "between") != (self.upper is not None):
            raise ValueError("upper is required for 'between' and forbidden otherwise")
        if self.upper is not None and self.upper <= self.threshold:
            raise ValueError("upper must be greater than threshold")
        return self


class CanonicalMarket(Frozen):
    market_id: str  # "<venue>:<native_id>"
    venue: str  # for display only
    native_id: str
    event_id: str
    title: str
    outcome_label: str
    rules_text: str = ""
    terms: ContractTerms | None  # None when the adapter has no parser for this family
    resolution_source: ResolutionSource
    collateral: Collateral
    tradable: bool  # can an order be placed right now (D25)
    trading_closes_at: UtcDatetime | None
    resolves_at: UtcDatetime | None
    captured_at: UtcDatetime  # when the book was read
    data_source: Literal["live", "fixture"]
    fees: FeeSchedule
    books: dict[Outcome, OutcomeBook]  # both "YES" and "NO" (D14)
    venue_metadata: dict[str, Any] = {}

    @model_validator(mode="after")
    def _identity_and_books(self) -> "CanonicalMarket":
        if self.market_id != f"{self.venue}:{self.native_id}":
            raise ValueError("market_id must be '<venue>:<native_id>'")
        if set(self.books) != {"YES", "NO"}:
            raise ValueError("books must hold both YES and NO")
        return self
