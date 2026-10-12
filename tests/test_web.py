"""feat-07 acceptance tests that outlive its pages: the server, and venue names only from data.

feat-14 replaced the pages themselves (tests/test_web_app.py); the user agreed to retire the
tests that pinned them (2026-10-12).
"""

import json
import re
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

import pytest

from equinox.cli import Settings
from equinox.server import make_handler
from equinox.web import App

WEB = Path(__file__).resolve().parents[1] / "src" / "equinox" / "web"


@contextmanager
def serving(app):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


@pytest.fixture(scope="module")
def site():
    with serving(App(Settings())) as base:
        yield base


def get(base, path, **params):
    url = f"{base}{path}" + (f"?{urlencode(params)}" if params else "")
    try:
        with urllib.request.urlopen(url) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


# Test 14: the health check, and a path the app doesn't serve.


def test_14_health_and_unknown_paths(site):
    status, body = get(site, "/health")
    assert status == 200 and json.loads(body)["status"] == "ok"
    assert get(site, "/missing")[0] == 404


# Test 15: the UI names venues only from the data.


def test_15_web_code_names_no_venue():
    for path in WEB.glob("*.py"):
        found = re.findall("kalshi|polymarket|meridian", path.read_text(encoding="utf-8"), re.I)
        assert not found, f"{path.name} names a venue: {found}"
