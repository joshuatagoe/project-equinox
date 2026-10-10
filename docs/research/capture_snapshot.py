"""Save raw, unedited API responses for the fixture events.

Fixtures then don't depend on when they're built: the events close on 2026-10-12 and 2026-10-28.

Captures Kalshi KXFEDDECISION-26OCT and Polymarket's matching Fed event, plus Polymarket's
"AAPL closes above ___ on October 12" event (the Meridian fit-check pair). Read-only public GETs.

    python docs/research/capture_snapshot.py docs/research/samples/snapshot-2026-10-10
"""

import json
import sys
import time
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


if __name__ == "__main__":
    main(Path(sys.argv[1]))
