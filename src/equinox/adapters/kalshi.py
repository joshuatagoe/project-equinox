"""Kalshi adapter (architecture section 5.2, venue facts K1-K13).

Discovery reads a family's series (K13). Each tracked event is read with its nested markets, which
carry the best asks (K12), then its series. A market's order book is read only when it is priced
(D49). Kalshi's orderbook holds bids only, in ascending order with the best bid last (K4); buying
one outcome means taking the other outcome's bids at 1 - p (K5). The orderbook response has no
timestamp, so captured_at is clock() at the moment each one is read (D37).
"""

import json
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from equinox.adapters.base import (
    BAD_DATA,
    Clock,
    DataSource,
    Fetcher,
    Listed,
    TrackedEvent,
    VenueAdapter,
    describe,
    listed_ask,
    with_books,
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
from equinox.models.catalog import CatalogEntry, CatalogPage

DEFAULT_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"  # K1
NEW_YORK = ZoneInfo("America/New_York")
FEE_RATE = Decimal("0.07")  # times the series multiplier (K9)
FEE_STEP = Decimal("0.01")  # A3

CLOSED = frozenset({"closed", "determined", "finalized", "settled"})  # an open event's past markets
FED_DECISION = "fed_decision"
FAMILY_SERIES = {FED_DECISION: "KXFEDDECISION"}  # K13
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

    def discover(self, family: str) -> list[TrackedEvent]:
        """Every open event in the family's series, by strike date, paged with `cursor`."""
        series = FAMILY_SERIES.get(family)
        if series is None:
            return []
        events, cursor = [], ""
        while True:
            params = {"series_ticker": series, "status": "open"} | (
                {"cursor": cursor} if cursor else {}
            )
            page = self._get(f"/events?{urlencode(params)}")
            events += page.get("events") or []
            cursor = page.get("cursor")
            if not cursor:
                break
        events.sort(key=lambda e: (e.get("strike_date") or "", e["event_ticker"]))
        return [TrackedEvent(e["event_ticker"], family) for e in events]

    def listings(self, read_at: Clock) -> list[Listed]:
        listed: list[Listed] = []
        for tracked in self.tracked:
            try:
                event = self._get(f"/events/{tracked.event_id}?with_nested_markets=true")["event"]
                series = self._get(f"/series/{event['series_ticker']}")["series"]
                shared = _event_fields(event, series)
                markets = list(event["markets"])
                listed_at = read_at()
            except BAD_DATA as error:
                listed.append(
                    (None, [f"kalshi: event {tracked.event_id} skipped: {describe(error)}"])
                )
                continue
            parse_terms = tracked.family == FED_DECISION
            if not parse_terms:
                note = (
                    f"kalshi: event {tracked.event_id} has no term parser for family "
                    f"{tracked.family!r}, so its markets have no terms"
                )
                listed.append((None, [note]))
            shared = shared | {"captured_at": listed_at}
            listed += [self._listed(raw, event, shared, parse_terms) for raw in markets]
        return listed

    def fetch_books(self, market: CanonicalMarket) -> CanonicalMarket:
        orderbook = self._get(f"/markets/{market.native_id}/orderbook")["orderbook_fp"]
        captured_at = self.clock()  # read time: the response carries none (D37)
        return with_books(market, _books(orderbook), captured_at)

    def list_open(
        self, page_size: int = 200, max_pages: int | None = None
    ) -> Iterator[CatalogPage]:
        """Every open market, page by page, from the events listing, which has no combos (K12)."""
        cursor, pages = "", 0
        while True:
            params = {"status": "open", "with_nested_markets": "true", "limit": page_size}
            page = self._get(
                f"/events?{urlencode(params | ({'cursor': cursor} if cursor else {}))}"
            )
            listed = [_catalog_entries(event) for event in page.get("events") or []]
            yield CatalogPage(
                [e for entries, _ in listed for e in entries], sum(n for _, n in listed)
            )
            pages, cursor = pages + 1, page.get("cursor")
            if not cursor or (max_pages is not None and pages >= max_pages):
                return

    def _get(self, path: str) -> Any:
        return self.fetch(f"{self.base_url}{path}")

    def _listed(
        self, raw: dict[str, Any], event: dict[str, Any], shared: dict[str, Any], parse_terms: bool
    ) -> Listed:
        ticker = raw.get("ticker")
        try:
            market = self._market(raw, event, shared, parse_terms)
        except BAD_DATA as error:
            return None, [f"kalshi: market {ticker} skipped: {describe(error)}"]
        if parse_terms and market.terms is None:
            strike = json.dumps(raw.get("custom_strike"), default=str)
            return market, [
                f"kalshi: market {ticker} has no terms: no parser for custom_strike {strike}"
            ]
        return market, []

    def _market(
        self, raw: dict[str, Any], event: dict[str, Any], shared: dict[str, Any], parse_terms: bool
    ) -> CanonicalMarket:
        ticker = raw["ticker"]
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
            data_source=self.data_source,
            best_asks={
                "YES": listed_ask(raw.get("yes_ask_dollars")),
                "NO": listed_ask(raw.get("no_ask_dollars")),
            },
            **shared,
        )


def _catalog_entries(event: dict[str, Any]) -> tuple[list[CatalogEntry], int]:
    """An event's open Yes/No markets as catalog entries, and how many were left out."""
    fed = event.get("series_ticker") == FAMILY_SERIES[FED_DECISION]
    entries, skipped = [], 0
    for raw in event.get("markets") or []:
        if raw.get("status") in CLOSED:
            continue
        try:
            if raw.get("market_type", "binary") != "binary":
                raise ValueError("not a Yes/No market")
            entries.append(
                CatalogEntry(
                    market_id=f"kalshi:{raw['ticker']}",
                    venue="kalshi",
                    event_title=event.get("title") or "",
                    title=raw.get("title") or f"{event.get('title', '')} {raw['yes_sub_title']}",
                    outcome_label=raw.get("yes_sub_title") or "",
                    closes_at=_time(raw.get("close_time")),
                    tradable=raw.get("status") == "active",
                    yes_ask=listed_ask(raw.get("yes_ask_dollars")),
                    no_ask=listed_ask(raw.get("no_ask_dollars")),
                    terms=_fed_decision_terms(raw, event) if fed else None,
                )
            )
        except BAD_DATA:
            skipped += 1
    return entries, skipped


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
