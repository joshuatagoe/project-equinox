"""feat-09: the live fetcher asks for gzip, and the catalog refresh retries a transient failure.

A full catalog is about 290 requests and three minutes (D55). Gzip cuts the download from 1.9 GB to
about 150 MB, and the second live refresh on 2026-10-11 failed on one TLS handshake timeout, so the
refresh retries timeouts, dropped connections, 429 and 5xx. The command line and the web UI don't:
for them a failing venue falls back to the snapshot at once (D17).
"""

import gzip
import json
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from equinox import catalog
from equinox.adapters.base import FetchError
from equinox.adapters.fetch import DEFAULT_SNAPSHOT, FixtureFetcher, HttpFetcher
from equinox.sources import Settings

BODY = json.dumps({"events": [{"title": "Kraken IPO by June 30, 2027?", "price": 0.25}]}).encode()
NEW = DEFAULT_SNAPSHOT.parent / "snapshot-2026-10-11"


class _Venue(BaseHTTPRequestHandler):
    """/gzip and /plain answer; /flaky fails with 503 the first time; /missing is a 404."""

    asked: list[str] = []  # each request's Accept-Encoding
    hits: Counter = Counter()

    def do_GET(self):  # noqa: N802  the name http.server calls
        self.asked.append(self.headers.get("Accept-Encoding", ""))
        self.hits[self.path] += 1
        if self.path == "/missing" or (self.path == "/flaky" and self.hits[self.path] == 1):
            self.send_error(404 if self.path == "/missing" else 503)
            return
        gzipped = "gzip" in self.asked[-1] and self.path == "/gzip"
        body = gzip.compress(BODY) if gzipped else BODY
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if gzipped:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def venue():
    _Venue.asked, _Venue.hits = [], Counter()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Venue)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_a_gzipped_response_is_unpacked_and_a_plain_one_still_reads(venue):
    fetch = HttpFetcher(timeout=5)
    assert fetch(f"{venue}/gzip") == fetch(f"{venue}/plain")
    assert _Venue.asked == ["gzip", "gzip"]
    assert str(fetch(f"{venue}/gzip")["events"][0]["price"]) == "0.25"


def test_a_transient_failure_is_retried_only_when_asked(venue):
    with pytest.raises(FetchError, match="503"):
        HttpFetcher(timeout=5)(f"{venue}/flaky")
    _Venue.hits.clear()
    assert HttpFetcher(timeout=5, retries=2, pause=0)(f"{venue}/flaky") == json.loads(BODY)
    assert _Venue.hits["/flaky"] == 2


def test_a_client_error_is_never_retried(venue):
    with pytest.raises(FetchError, match="404"):
        HttpFetcher(timeout=5, retries=2, pause=0)(f"{venue}/missing")
    assert _Venue.hits["/missing"] == 1


def test_a_live_refresh_fetches_with_retries(tmp_path, monkeypatch):
    built = []

    class Recording(FixtureFetcher):
        def __init__(self, timeout, retries=0, pause=0.0):
            built.append(retries)
            super().__init__(NEW)

    monkeypatch.setattr(catalog, "HttpFetcher", Recording)
    live = Settings(source="live", cache_dir=tmp_path)
    catalog.refresh(live, page_size=20, max_pages=2)
    assert built == [catalog.RETRIES, catalog.RETRIES] and catalog.RETRIES >= 1
