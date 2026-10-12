"""Save the raw responses Equinox reads to price one pair of catalog markets, as a snapshot.

    python docs/research/capture_pair.py src/equinox/fixtures/snapshot-YYYY-MM-DD-pair \
        kalshi:KXBALLONDOR-26-KMBA polymarket:608540

It loads the markets the way pricing does (`sources.load_by_id`: each market's event, then the
event's listing) and fetches both order books, recording every request and its raw response. The
pricing tests (feat-10) replay the folder. Write into a new directory; never overwrite a snapshot.
"""

import gzip
import json
import re
import sys
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from equinox.adapters.fetch import HEADERS
from equinox.sources import Settings, load_by_id


class Recording:
    """A live fetcher that keeps each URL's raw response bytes, unedited, for the snapshot."""

    def __init__(self) -> None:
        self.seen: dict[str, bytes] = {}

    def __call__(self, url: str):
        request = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read()
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                body = gzip.decompress(body)
        self.seen[url] = body
        return json.loads(body, parse_float=Decimal)


def main(out: Path, market_ids: list[str]) -> None:
    if out.exists():
        raise SystemExit(f"{out} exists: snapshots are never overwritten")
    recording = Recording()
    loaded = load_by_id(Settings(source="live"), market_ids, lambda venue: recording)
    for market in loaded.markets:
        loaded.readers[market.venue].fetch_books(market)
    out.mkdir(parents=True)
    files = {}
    for number, (url, body) in enumerate(recording.seen.items(), start=1):
        name = f"{number:02d}_{re.sub(r'[^A-Za-z0-9]+', '_', url.split('//', 1)[1])[:80]}.json"
        (out / name).write_bytes(body)
        files[name] = url
    index = {"captured_at": datetime.now(UTC).isoformat(), "files": files}
    (out / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(f"{len(files)} responses saved in {out}: {[m.market_id for m in loaded.markets]}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2:])
