"""Polymarket adapter (architecture section 5.3): Gamma events and CLOB books -> canonical markets.

Venue facts it relies on (docs/research/venue_facts.md): discovery pages the family's tag with
`after_cursor` (P11, P12); Gamma sends `outcomes` and `clobTokenIds` as strings that contain JSON
(P1); event listings carry each market's best ask and bid (P11); CLOB lists the best price last
(P4); the YES and NO token books are the same liquidity shown twice (P5); fees come from the
market's `feeSchedule`, never from `takerBaseFee` (P7), rounded to 5 decimal places (P8).
"""

import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode, urlsplit

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
from equinox.adapters.polymarket_terms import TERM_PARSERS, TermParser, fed_terms, utc
from equinox.models import (
    CanonicalMarket,
    Collateral,
    FeeSchedule,
    OrderBookLevel,
    OutcomeBook,
    ResolutionSource,
)
from equinox.models.catalog import CatalogEntry, CatalogPage

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"
FEE_STEP = Decimal("0.00001")  # P8
# A family is found by its tag and an event title; only open, neg-risk events count (P12).
FAMILY_TAGS = {"fed_decision": ("fed-rates", re.compile(r"^Fed Decision in [A-Za-z]+\?$", re.I))}


class PolymarketAdapter(VenueAdapter):
    venue = "polymarket"

    def __init__(
        self,
        fetch: Fetcher,
        tracked: list[TrackedEvent],
        data_source: DataSource,
        clock: Clock,
        *,
        gamma_url: str = GAMMA_URL,
        clob_url: str = CLOB_URL,
    ) -> None:
        super().__init__(fetch, tracked, data_source, clock)
        self.gamma_url = gamma_url.rstrip("/")
        self.clob_url = clob_url.rstrip("/")

    def discover(self, family: str) -> list[TrackedEvent]:
        """The family's open, neg-risk events, by end date; closed look-alikes are dropped (P12)."""
        if family not in FAMILY_TAGS:
            return []
        tag, title = FAMILY_TAGS[family]
        params, events = {"closed": "false", "limit": 100, "tag_slug": tag}, []
        while True:
            page = self.fetch(f"{self.gamma_url}/events/keyset?{urlencode(params)}")
            events += page.get("events") or []
            if not page.get("next_cursor"):
                break
            params = {**params, "after_cursor": page["next_cursor"]}
        found = [
            e
            for e in events
            if not e.get("closed") and e.get("negRisk") and title.match(e.get("title") or "")
        ]
        found.sort(key=lambda e: (e.get("endDate") or "", e["slug"]))
        return [TrackedEvent(e["slug"], family) for e in found]

    def listings(self, read_at: Clock) -> list[Listed]:
        listed: list[Listed] = []
        for tracked in self.tracked:
            events = self.fetch(f"{self.gamma_url}/events?{urlencode({'slug': tracked.event_id})}")
            if not events:
                listed.append((None, [f"polymarket: event {tracked.event_id} not found"]))
                continue
            listed_at = read_at()
            parse_terms = TERM_PARSERS.get(tracked.family)
            if parse_terms is None:
                note = (
                    f"polymarket: event {tracked.event_id}: no term parser for family "
                    f"{tracked.family!r}, so its markets have no terms"
                )
                listed.append((None, [note]))
            for raw in events[0].get("markets") or []:
                listed.append(self._listed(events[0], raw, parse_terms, listed_at))
        return listed

    def fetch_books(self, market: CanonicalMarket) -> CanonicalMarket:
        yes_token, no_token = market.venue_metadata["tokens"]
        yes_book = self.fetch(f"{self.clob_url}/book?{urlencode({'token_id': yes_token})}")
        no_book = self.fetch(f"{self.clob_url}/book?{urlencode({'token_id': no_token})}")
        books = {"YES": _book(yes_book), "NO": _book(no_book)}  # never merged (P5)
        return with_books(market, books, _read_time(yes_book, no_book))

    def list_open(
        self, page_size: int = 100, max_pages: int | None = None
    ) -> Iterator[CatalogPage]:
        """Every open market, page by page, paged with `after_cursor`, never by offset (P11)."""
        params, pages = {"closed": "false", "limit": page_size}, 0
        while True:
            page = self.fetch(f"{self.gamma_url}/events/keyset?{urlencode(params)}")
            listed = [_catalog_entries(event) for event in page.get("events") or []]
            yield CatalogPage(
                [e for entries, _ in listed for e in entries], sum(n for _, n in listed)
            )
            pages += 1
            if not page.get("next_cursor") or (max_pages is not None and pages >= max_pages):
                return
            params = {**params, "after_cursor": page["next_cursor"]}

    def _listed(
        self,
        event: dict[str, Any],
        raw: dict[str, Any],
        parse_terms: TermParser | None,
        listed_at: datetime,
    ) -> Listed:
        notes: list[str] = []
        try:
            market = self._market(event, raw, parse_terms, notes, listed_at)
        except BAD_DATA as error:  # not FetchError: sources.py owns that
            return None, [f"polymarket: market {raw.get('id')} skipped: {describe(error)}"]
        return market, notes

    def _market(
        self,
        event: dict[str, Any],
        raw: dict[str, Any],
        parse_terms: TermParser | None,
        notes: list[str],
        listed_at: datetime,
    ) -> CanonicalMarket:
        native_id = str(raw["id"])
        outcomes = _json_list(raw["outcomes"])
        if outcomes != ["Yes", "No"]:
            raise ValueError(f"outcomes are {outcomes}, not ['Yes', 'No']")
        best_bid = listed_ask(raw.get("bestBid"))
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
            resolves_at=utc(raw["endDate"]) if raw.get("endDate") else None,
            captured_at=listed_at,
            data_source=self.data_source,
            fees=_fees(raw),
            best_asks={
                "YES": listed_ask(raw.get("bestAsk")),
                "NO": None if best_bid is None else 1 - best_bid,  # a YES bid is a NO ask (P5)
            },
            venue_metadata={"tokens": _token_ids(raw)},
        )


def _catalog_entries(event: dict[str, Any]) -> tuple[list[CatalogEntry], int]:
    """An event's open Yes/No markets as catalog entries, and how many were left out."""
    tag, title = FAMILY_TAGS["fed_decision"]
    fed = bool(event.get("negRisk")) and bool(title.match(event.get("title") or ""))
    entries, skipped = [], 0
    for raw in event.get("markets") or []:
        if raw.get("closed"):
            continue
        try:
            if _json_list(raw["outcomes"]) != ["Yes", "No"]:
                raise ValueError("not a Yes/No market")
            best_bid = listed_ask(raw.get("bestBid"))
            entries.append(
                CatalogEntry(
                    market_id=f"polymarket:{raw['id']}",
                    venue="polymarket",
                    event_title=event.get("title") or "",
                    title=raw["question"],
                    outcome_label=raw.get("groupItemTitle") or "",
                    closes_at=_maybe_utc(raw.get("endDate")),
                    tradable=bool(raw.get("active") and raw.get("acceptingOrders")),
                    yes_ask=listed_ask(raw.get("bestAsk")),
                    no_ask=None if best_bid is None else 1 - best_bid,
                    terms=fed_terms(raw, []) if fed else None,
                )
            )
        except BAD_DATA:
            skipped += 1
    return entries, skipped


def _maybe_utc(text: str | None) -> datetime | None:
    """endDate comes in several formats (P3); one we can't read leaves the close date blank."""
    try:
        return utc(text) if text else None
    except ValueError:
        return None


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
