"""Kalshi adapter (architecture section 5.2, venue facts K1-K10).

For each tracked event it reads the event with its markets, then the event's series, then one
orderbook per market, all through the injected fetcher. Kalshi's orderbook holds bids only, in
ascending order with the best bid last (K4). Buying one outcome means taking the other outcome's
bids at 1 - p (K5). The orderbook response has no timestamp, so captured_at is clock() at the
moment each one is read (D37).
"""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from equinox.adapters.base import (
    AdapterResult,
    Clock,
    DataSource,
    Fetcher,
    TrackedEvent,
    VenueAdapter,
)
from equinox.models import (
    CanonicalMarket,
    Collateral,
    ContractTerms,
    FeeSchedule,
    OrderBookLevel,
    OutcomeBook,
    ResolutionSource,
)

DEFAULT_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"  # K1
NEW_YORK = ZoneInfo("America/New_York")
FEE_RATE = Decimal("0.07")  # times the series multiplier (K9)
FEE_STEP = Decimal("0.01")  # A3

# A response that isn't shaped as expected: a missing field, a wrong type, a bad number, or a
# value the models refuse (pydantic's ValidationError is a ValueError). FetchError is not one.
BAD_DATA = (LookupError, TypeError, ValueError, ArithmeticError)

FED_DECISION = "fed_decision"
# The five custom_strike shapes of a KXFEDDECISION event (K8), as (comparison, bps).
FED_STRIKES = (
    ({"Cut": ">25"}, "lt", "-25"),
    ({"Cut": "25"}, "eq", "-25"),
    ({"Hike": "0"}, "eq", "0"),
    ({"Hike": "25"}, "eq", "25"),
    ({"Hike": ">25"}, "gt", "25"),
)
FED_FALLBACK = ("If the meeting is cancelled, 'Fed maintains rate' resolves Yes.",)


class KalshiAdapter(VenueAdapter):
    venue = "kalshi"

    def __init__(
        self,
        fetch: Fetcher,
        tracked: list[TrackedEvent],
        data_source: DataSource,
        clock: Clock,
        *,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        super().__init__(fetch, tracked, data_source, clock)
        self.base_url = base_url

    def fetch_markets(self) -> AdapterResult:
        result = AdapterResult(markets=[], warnings=[])
        for tracked in self.tracked:
            try:
                event = self._get(f"/events/{tracked.event_id}?with_nested_markets=true")["event"]
                series = self._get(f"/series/{event['series_ticker']}")["series"]
                shared = _event_fields(event, series)
                listed = list(event["markets"])
            except BAD_DATA as error:
                result.warnings.append(
                    f"kalshi: event {tracked.event_id} skipped: {_describe(error)}"
                )
                continue
            parse_terms = tracked.family == FED_DECISION
            if not parse_terms:
                result.warnings.append(
                    f"kalshi: event {tracked.event_id} has no term parser for family "
                    f"{tracked.family!r}, so its markets have no terms"
                )
            for raw in listed:
                ticker = raw.get("ticker")
                try:
                    market = self._market(raw, event, shared, parse_terms)
                except BAD_DATA as error:
                    result.warnings.append(f"kalshi: market {ticker} skipped: {_describe(error)}")
                    continue
                result.markets.append(market)
                if parse_terms and market.terms is None:
                    result.warnings.append(
                        f"kalshi: market {ticker} has no terms: no parser for custom_strike "
                        f"{json.dumps(raw.get('custom_strike'), default=str)}"
                    )
        return result

    def _get(self, path: str) -> Any:
        return self.fetch(f"{self.base_url}{path}")

    def _market(
        self, raw: dict[str, Any], event: dict[str, Any], shared: dict[str, Any], parse_terms: bool
    ) -> CanonicalMarket:
        ticker = raw["ticker"]
        orderbook = self._get(f"/markets/{ticker}/orderbook")["orderbook_fp"]
        captured_at = self.clock()  # read time: the response carries none (D37)
        rules = (raw.get("rules_primary"), raw.get("rules_secondary"))
        return CanonicalMarket(
            market_id=f"{self.venue}:{ticker}",
            venue=self.venue,
            native_id=ticker,
            event_id=raw["event_ticker"],
            title=raw.get("title") or f"{event['title']} {raw['yes_sub_title']}",
            outcome_label=raw["yes_sub_title"],
            rules_text="\n\n".join(part for part in rules if part),
            terms=_fed_decision_terms(raw, event) if parse_terms else None,
            tradable=raw.get("status") == "active",
            trading_closes_at=_time(raw.get("close_time")),
            resolves_at=_time(raw.get("expected_expiration_time")),
            captured_at=captured_at,
            data_source=self.data_source,
            books=_books(orderbook),
            **shared,
        )


def _event_fields(event: dict[str, Any], series: dict[str, Any]) -> dict[str, Any]:
    """What every market of one event shares: resolution source, collateral and fees."""
    source = series["settlement_sources"][0]  # K7
    override = event.get("fee_multiplier_override")
    multiplier = series["fee_multiplier"] if override is None else override  # K9
    return {
        "resolution_source": ResolutionSource(name=source["name"], url=source.get("url")),
        "collateral": Collateral(asset="USD", has_value=True),
        "fees": FeeSchedule(
            coefficient=FEE_RATE * _exact(multiplier), exponent=1, rounding_step=FEE_STEP
        ),
    }


def _fed_decision_terms(raw: dict[str, Any], event: dict[str, Any]) -> ContractTerms | None:
    """Terms from custom_strike in one of the five known shapes; None for any other shape."""
    for shape, comparison, threshold in FED_STRIKES:
        if raw.get("custom_strike") == shape:
            return ContractTerms(
                subject="FOMC",
                measure="fed_upper_bound_change",
                measured_by="fomc_statement",
                observed_on=_new_york_date(event["strike_date"]),
                comparison=comparison,
                threshold=Decimal(threshold),
                unit="bps",
                fallback_rules=FED_FALLBACK,
            )
    return None


def _books(orderbook: dict[str, Any]) -> dict[str, OutcomeBook]:
    """Both outcomes' books, best first, from Kalshi's two bid lists (K4, K5)."""
    yes_bids = _levels(orderbook["yes_dollars"])
    no_bids = _levels(orderbook["no_dollars"])
    return {
        "YES": _book(asks=_at_one_minus(no_bids), bids=yes_bids),
        "NO": _book(asks=_at_one_minus(yes_bids), bids=no_bids),
    }


def _levels(raw: list[Any] | None) -> list[tuple[Decimal, Decimal]]:
    """[[price, count], ...] as exact (price, quantity) pairs. An empty side is []."""
    return [(_exact(price), _exact(count)) for price, count in raw or []]


def _at_one_minus(bids: list[tuple[Decimal, Decimal]]) -> list[tuple[Decimal, Decimal]]:
    """One outcome's bids as the other outcome's asks: a bid at p is an ask at 1 - p (K5)."""
    return [(1 - price, quantity) for price, quantity in bids]


def _book(asks: list[tuple[Decimal, Decimal]], bids: list[tuple[Decimal, Decimal]]) -> OutcomeBook:
    """Sorted here, whatever order the venue sent: asks cheapest first, bids highest first."""
    return OutcomeBook(
        asks=tuple(OrderBookLevel(price=p, quantity=q) for p, q in sorted(asks)),
        bids=tuple(OrderBookLevel(price=p, quantity=q) for p, q in sorted(bids, reverse=True)),
    )


def _exact(value: Any) -> Decimal:
    """A numeric string, int or Decimal as an exact Decimal. A float is refused (D3)."""
    if isinstance(value, float):
        raise TypeError(f"{value!r} is a float, not an exact number")
    return Decimal(str(value))


def _time(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _new_york_date(text: str) -> date:
    instant = datetime.fromisoformat(text)
    if instant.tzinfo is None:
        raise ValueError(f"strike_date {text!r} has no time zone")
    return instant.astimezone(NEW_YORK).date()


def _describe(error: Exception) -> str:
    """One line for a warning."""
    if isinstance(error, ValidationError):
        return "; ".join(
            f"{'.'.join(map(str, item['loc'])) or error.title}: {item['msg']}"
            for item in error.errors()
        )
    if isinstance(error, KeyError):
        return f"missing field {error}"
    return str(error) or type(error).__name__
