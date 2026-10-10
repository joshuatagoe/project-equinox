"""Polymarket adapter (architecture section 5.3): Gamma events and CLOB books -> canonical markets.

Venue facts it relies on (docs/research/venue_facts.md): Gamma sends `outcomes` and `clobTokenIds`
as strings that contain JSON (P1); CLOB lists the best price last (P4); the YES and NO token books
are the same liquidity shown twice (P5); fees come from the market's `feeSchedule`, never from
`takerBaseFee` (P7), rounded to 5 decimal places (P8).
"""

import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

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

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"
NEW_YORK = ZoneInfo("America/New_York")
FEE_STEP = Decimal("0.00001")  # P8

FED_FALLBACK_RULES = (
    "A change not shown in the brackets is rounded up to the nearest 25 bps.",
    "If no statement is released by the end date of the next scheduled meeting, "
    "'No change' resolves Yes.",
)
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
BRACKET = re.compile(r"(\d+)(\+?) bps (decrease|increase)", re.IGNORECASE)
MEETING = re.compile(rf"scheduled for ({'|'.join(MONTHS)}) (\d{{1,2}})-(\d{{1,2}}), (\d{{4}})")

TermParser = Callable[[dict[str, Any], list[str]], ContractTerms | None]


class PolymarketAdapter(VenueAdapter):
    venue = "polymarket"

    def __init__(
        self,
        fetch: Fetcher,
        tracked: list[TrackedEvent],
        data_source: DataSource,
        clock: Clock,  # unused: every CLOB book carries its own timestamp
        *,
        gamma_url: str = GAMMA_URL,
        clob_url: str = CLOB_URL,
    ) -> None:
        super().__init__(fetch, tracked, data_source, clock)
        self.gamma_url = gamma_url.rstrip("/")
        self.clob_url = clob_url.rstrip("/")

    def fetch_markets(self) -> AdapterResult:
        markets: list[CanonicalMarket] = []
        warnings: list[str] = []
        for tracked in self.tracked:
            self._read_event(tracked, markets, warnings)
        return AdapterResult(markets, warnings)

    def _read_event(
        self, tracked: TrackedEvent, markets: list[CanonicalMarket], warnings: list[str]
    ) -> None:
        events = self.fetch(f"{self.gamma_url}/events?{urlencode({'slug': tracked.event_id})}")
        if not events:
            warnings.append(f"polymarket: event {tracked.event_id} not found")
            return
        event = events[0]
        parse_terms = TERM_PARSERS.get(tracked.family)
        if parse_terms is None:
            warnings.append(
                f"polymarket: event {tracked.event_id}: no term parser for family "
                f"{tracked.family!r}, so its markets have no terms"
            )
        for raw in event.get("markets") or []:
            notes: list[str] = []
            try:
                market = self._market(event, raw, parse_terms, notes)
            except (ValueError, KeyError, TypeError) as error:  # not FetchError: the CLI owns that
                warnings.append(f"polymarket: market {raw.get('id')} skipped: {_reason(error)}")
                continue
            markets.append(market)
            warnings.extend(notes)

    def _market(
        self,
        event: dict[str, Any],
        raw: dict[str, Any],
        parse_terms: TermParser | None,
        notes: list[str],
    ) -> CanonicalMarket:
        native_id = str(raw["id"])
        outcomes = _json_list(raw["outcomes"])
        if outcomes != ["Yes", "No"]:
            raise ValueError(f"outcomes are {outcomes}, not ['Yes', 'No']")
        yes_token, no_token = _token_ids(raw)
        yes_book = self.fetch(f"{self.clob_url}/book?{urlencode({'token_id': yes_token})}")
        no_book = self.fetch(f"{self.clob_url}/book?{urlencode({'token_id': no_token})}")
        end = _utc(raw["endDate"]) if raw.get("endDate") else None
        return CanonicalMarket(
            market_id=f"{self.venue}:{native_id}",
            venue=self.venue,
            native_id=native_id,
            event_id=str(event["id"]),
            title=raw["question"],
            outcome_label=raw.get("groupItemTitle") or "",
            rules_text=raw.get("description") or "",
            terms=parse_terms(raw, notes) if parse_terms else None,
            resolution_source=_resolution_source(raw.get("resolutionSource")),
            collateral=Collateral(asset="USDC", has_value=True),
            tradable=bool(
                raw.get("active") and not raw.get("closed") and raw.get("acceptingOrders")
            ),
            trading_closes_at=None,  # Polymarket has no such field; endDate is not it (P3)
            resolves_at=end,
            captured_at=_read_time(yes_book, no_book),
            data_source=self.data_source,
            fees=_fees(raw),
            books={"YES": _book(yes_book), "NO": _book(no_book)},  # never merged (P5)
            venue_metadata={},
        )


def _reason(error: Exception) -> str:
    """One line, so a validation error's report fits in a warning."""
    text = f"missing field {error}" if isinstance(error, KeyError) else str(error)
    return " ".join(text.split())


def _json_list(value: Any) -> list:
    """Gamma sends some arrays as strings that contain JSON (P1); v2 positionIds are real arrays."""
    return json.loads(value) if isinstance(value, str) else list(value)


def _token_ids(raw: dict[str, Any]) -> list[str]:
    """[YES token, NO token]: index 0 is YES (P1)."""
    ids = raw.get("clobTokenIds")
    if ids is None and raw.get("version") == "v2":
        ids = raw.get("positionIds")
    if ids is None:
        raise ValueError("no clobTokenIds")
    tokens = [str(token) for token in _json_list(ids)]
    if len(tokens) != 2:
        raise ValueError(f"expected 2 token IDs, got {len(tokens)}")
    return tokens


def _utc(text: str) -> datetime:
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError(f"{text!r} has no time zone")
    return moment.astimezone(UTC)


def _resolution_source(url: str | None) -> ResolutionSource:
    host = urlsplit(url).hostname if url else None
    if not host:
        raise ValueError(f"resolutionSource {url!r} is not a URL")
    return ResolutionSource(name=host, url=url)


def _fees(raw: dict[str, Any]) -> FeeSchedule:
    schedule = raw.get("feeSchedule")
    if not raw.get("feesEnabled") or schedule is None:
        return FeeSchedule(coefficient=Decimal(0), exponent=1, rounding_step=FEE_STEP)
    # The rate arrives as a Decimal (parse_float=Decimal); the model refuses a float (D39).
    return FeeSchedule(
        coefficient=schedule["rate"], exponent=int(schedule["exponent"]), rounding_step=FEE_STEP
    )


def _book(raw_book: dict[str, Any]) -> OutcomeBook:
    """CLOB lists bids ascending and asks descending, best last (P4): sort best-first explicitly."""
    asks = [_level(level) for level in raw_book.get("asks") or []]
    bids = [_level(level) for level in raw_book.get("bids") or []]
    return OutcomeBook(
        asks=tuple(sorted(asks, key=lambda level: level.price)),
        bids=tuple(sorted(bids, key=lambda level: level.price, reverse=True)),
    )


def _level(raw_level: dict[str, Any]) -> OrderBookLevel:
    return OrderBookLevel(price=raw_level["price"], quantity=raw_level["size"])


def _read_time(*books: dict[str, Any]) -> datetime:
    """The earlier book timestamp. Epoch milliseconds, maybe a string; kept exact (no float)."""
    millis = min(int(book["timestamp"]) for book in books)
    return datetime.fromtimestamp(millis // 1000, UTC) + timedelta(milliseconds=millis % 1000)


def _fed_terms(raw: dict[str, Any], notes: list[str]) -> ContractTerms | None:
    label = raw.get("groupItemTitle") or ""
    bracket = _fed_bracket(label)
    if bracket is None:
        notes.append(f"polymarket: market {raw['id']}: no terms for the bracket {label!r}")
        return None
    comparison, threshold = bracket
    return ContractTerms(
        subject="FOMC",
        measure="fed_upper_bound_change",
        measured_by="fomc_statement",
        observed_on=_meeting_day(raw, notes),
        comparison=comparison,
        threshold=threshold,
        unit="bps",
        fallback_rules=FED_FALLBACK_RULES,
    )


def _fed_bracket(label: str) -> tuple[str, Decimal] | None:
    """A bracket as (comparison, change): "50+ bps decrease" -> le -50, "No change" -> eq 0."""
    label = label.strip()
    if label.lower() == "no change":
        return "eq", Decimal(0)
    match = BRACKET.fullmatch(label)
    if match is None:
        return None
    size, plus, direction = match.groups()
    change = Decimal(size) if direction.lower() == "increase" else -Decimal(size)
    if not plus:
        return "eq", change
    return ("ge" if change > 0 else "le"), change


def _meeting_day(raw: dict[str, Any], notes: list[str]) -> date:
    """The last day of "scheduled for October 27-28, 2026"; else endDate's New York date."""
    match = MEETING.search(raw.get("description") or "")
    if match:
        month, _first, last, year = match.groups()
        return date(int(year), MONTHS.index(month) + 1, int(last))
    notes.append(
        f"polymarket: market {raw['id']}: no 'scheduled for' meeting date in the description, "
        "so observed_on is endDate in New York"
    )
    return _utc(raw["endDate"]).astimezone(NEW_YORK).date()


TERM_PARSERS: dict[str, TermParser] = {"fed_decision": _fed_terms}
