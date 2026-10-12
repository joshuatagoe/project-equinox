"""Save the raw responses for the exact-score tests (feat-11), as a snapshot.

    python docs/research/capture_scores.py src/equinox/fixtures/snapshot-YYYY-MM-DD-scores \
        kalshi:KXEPLSCORE-26OCT12COVNEW-COV2NEW1 polymarket:5114624 ...

Like `capture_pair.py`, it loads the markets the way pricing does (`sources.load_by_id`: each
market's event, then the event's listing), recording every request and its raw response. It then
fetches both order books of every market named, reading Polymarket's token IDs from the recorded
listing, so a market the adapter can't build yet is still captured. Write into a new directory;
never overwrite a snapshot.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlencode

from capture_pair import Recording, save

from equinox.adapters.polymarket import CLOB_URL, GAMMA_URL, _token_ids
from equinox.sources import Settings, load_by_id


def main(out: Path, market_ids: list[str]) -> None:
    if out.exists():
        raise SystemExit(f"{out} exists: snapshots are never overwritten")
    recording = Recording()
    loaded = load_by_id(Settings(source="live"), market_ids, lambda venue: recording)
    for market in loaded.markets:
        if market.venue == "kalshi":
            loaded.readers["kalshi"].fetch_books(market)
    raw = _polymarket_listing(recording)
    for market_id in market_ids:
        if market_id.startswith("polymarket:"):
            for token in _token_ids(raw[market_id.split(":", 1)[1]]):
                recording(f"{CLOB_URL}/book?{urlencode({'token_id': token})}")
    save(out, recording)
    print(f"loaded by the adapters today: {[m.market_id for m in loaded.markets]}")


def _polymarket_listing(recording: Recording) -> dict[str, dict]:
    """Every Polymarket market in the recorded event listings, by ID."""
    found = {}
    for url, body in recording.seen.items():
        if url.startswith(f"{GAMMA_URL}/events?"):
            for event in json.loads(body):
                found |= {str(m["id"]): m for m in event.get("markets") or []}
    return found


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2:])
