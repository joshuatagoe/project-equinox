"""Save raw, unedited API responses as a snapshot fixture. Read-only public GETs.

Two modes:

    python docs/research/capture_snapshot.py src/equinox/fixtures/snapshot-YYYY-MM-DD
    python docs/research/capture_snapshot.py --discover src/equinox/fixtures/snapshot-YYYY-MM-DD

The first captures the pinned events (Kalshi KXFEDDECISION-26OCT, Polymarket's October Fed event
and its "AAPL closes above ___ on October 12" event, the Meridian fit-check pair); it made
snapshot-2026-10-10. `--discover` captures what discovery finds (D47): every open Fed-decision
event on both venues, through the same requests the adapters make, with every order book, plus
two short pages of each venue's full listing for the catalog tests (feat-09).

Write into a new dated directory: never overwrite an existing snapshot, because tests read it.
"""

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

KALSHI = "https://external-api.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
KALSHI_SERIES, KALSHI_EVENT = "KXFEDDECISION", "KXFEDDECISION-26OCT"
POLY_EVENT_SLUGS = [
    "fed-decision-in-october-20260617190323537",
    "aapl-close-above-on-october-12-2026",
]


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "project-equinox-research"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def save(out: Path, name: str, url: str) -> bytes:
    body = get(url)
    (out / name).write_bytes(body)
    time.sleep(0.2)
    return body


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    index = {"captured_at": datetime.now(UTC).isoformat(), "files": {}}

    def record(name: str, url: str) -> bytes:
        index["files"][name] = url
        return save(out, name, url)

    record("kalshi_series_KXFEDDECISION.json", f"{KALSHI}/series/{KALSHI_SERIES}")
    event = json.loads(
        record(
            "kalshi_event_KXFEDDECISION-26OCT.json",
            f"{KALSHI}/events/{KALSHI_EVENT}?with_nested_markets=true",
        )
    )
    for market in event["event"]["markets"]:
        ticker = market["ticker"]
        record(f"kalshi_orderbook_{ticker}.json", f"{KALSHI}/markets/{ticker}/orderbook")

    for slug in POLY_EVENT_SLUGS:
        events = json.loads(record(f"polymarket_event_{slug}.json", f"{GAMMA}/events?slug={slug}"))
        for market in events[0]["markets"]:
            tokens = json.loads(market["clobTokenIds"])
            for side, token in zip(("yes", "no"), tokens, strict=True):
                name = f"polymarket_book_{market['id']}_{side}.json"
                record(name, f"{CLOB}/book?token_id={token}")

    (out / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"saved {len(index['files'])} responses to {out} at {index['captured_at']}")


FED_TITLE = re.compile(r"^Fed Decision in [A-Za-z]+\?$", re.IGNORECASE)
CATALOG_PAGE = 20


def query(base: str, params: dict) -> str:
    return f"{base}?{urllib.parse.urlencode(params)}"


def discover_main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    index = {"captured_at": datetime.now(UTC).isoformat(), "files": {}}

    def record(name: str, url: str) -> dict:
        index["files"][name] = url
        return json.loads(save(out, name, url))

    capture_kalshi_meetings(record)
    capture_polymarket_meetings(record)
    capture_catalog_sample(record)
    (out / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"saved {len(index['files'])} responses to {out} at {index['captured_at']}")


def capture_kalshi_meetings(record) -> None:
    """Every open meeting in the series (K13), then each event, its series and its books."""
    discovery = query(f"{KALSHI}/events", {"series_ticker": KALSHI_SERIES, "status": "open"})
    found = record("kalshi_discovery_KXFEDDECISION.json", discovery)
    record(f"kalshi_series_{KALSHI_SERIES}.json", f"{KALSHI}/series/{KALSHI_SERIES}")
    for event in found["events"]:
        ticker = event["event_ticker"]
        url = query(f"{KALSHI}/events/{ticker}", {"with_nested_markets": "true"})
        for market in record(f"kalshi_event_{ticker}.json", url)["event"]["markets"]:
            name = f"kalshi_orderbook_{market['ticker']}.json"
            record(name, f"{KALSHI}/markets/{market['ticker']}/orderbook")


def capture_polymarket_meetings(record) -> None:
    """The fed-rates tag, paged with after_cursor (P11); decision events and their books (P12)."""
    params, page, events = {"closed": "false", "limit": 100, "tag_slug": "fed-rates"}, 1, []
    while True:
        name = f"polymarket_discovery_fed-rates_{page}.json"
        data = record(name, query(f"{GAMMA}/events/keyset", params))
        events += data.get("events", [])
        if not data.get("next_cursor"):
            break
        params, page = {**params, "after_cursor": data["next_cursor"]}, page + 1
    for event in filter(is_fed_decision, events):
        slug = event["slug"]
        listing = record(f"polymarket_event_{slug}.json", query(f"{GAMMA}/events", {"slug": slug}))
        for market in listing[0]["markets"]:
            tokens = json.loads(market["clobTokenIds"])
            for side, token in zip(("yes", "no"), tokens, strict=True):
                url = query(f"{CLOB}/book", {"token_id": token})
                record(f"polymarket_book_{market['id']}_{side}.json", url)


def is_fed_decision(event: dict) -> bool:
    title = event.get("title", "")
    return not event.get("closed") and bool(event.get("negRisk")) and bool(FED_TITLE.match(title))


def capture_catalog_sample(record) -> None:
    """Two short pages of each venue's full listing, for the catalog tests (feat-09)."""
    kalshi = {"status": "open", "with_nested_markets": "true", "limit": CATALOG_PAGE}
    first = record("kalshi_catalog_1.json", query(f"{KALSHI}/events", kalshi))
    second = {**kalshi, "cursor": first["cursor"]}
    record("kalshi_catalog_2.json", query(f"{KALSHI}/events", second))
    poly = {"closed": "false", "limit": CATALOG_PAGE}
    first = record("polymarket_catalog_1.json", query(f"{GAMMA}/events/keyset", poly))
    second = {**poly, "after_cursor": first["next_cursor"]}
    record("polymarket_catalog_2.json", query(f"{GAMMA}/events/keyset", second))


if __name__ == "__main__":
    if sys.argv[1] == "--discover":
        discover_main(Path(sys.argv[2]))
    else:
        main(Path(sys.argv[1]))
