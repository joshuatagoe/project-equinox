"""feat-07 acceptance tests: the web UI, through the real HTTP server on a free local port."""

import html
import json
import re
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from decimal import ROUND_HALF_UP, Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

import pytest

from equinox import cli
from equinox.adapters.base import FetchError
from equinox.adapters.fetch import DEFAULT_SNAPSHOT, FixtureFetcher
from equinox.cli import Loaded, Settings
from equinox.server import make_handler
from equinox.web import App

FED = "FOMC|fed_upper_bound_change|fomc_statement|2026-10-28"
HOLD, CUT25, CUT50 = f"{FED}|eq|0|bps", f"{FED}|eq|-25|bps", f"{FED}|below|-50|bps"
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


def text(page):
    """The page's visible text, with tags removed and spaces collapsed."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def order(site, outcome=HOLD, side="YES", quantity="100", budget=None):
    params = {"outcome": outcome, "side": side, "quantity": quantity}
    params |= {"budget": budget} if budget else {}
    status, page = get(site, "/", **params)
    assert status == 200
    return text(page)


# Tests 1-7: the order screen.


def test_1_home_lists_every_outcome_and_answers_the_default_order(site):
    status, page = get(site, "/")
    assert status == 200 and "Project Equinox" in page
    words = text(page)
    for name in (
        "Cut 50 bps or more",
        "Cut 25 bps",
        "No change",
        "Hike 25 bps",
        "Hike 50 bps or more",
    ):
        assert name in words
    headline = re.search(r"Buy on Polymarket:.*?less than Kalshi at \$85\.90\.", words)
    assert headline, words[:600]
    for part in ("$84.67", "$0.67", "$1.23", "1.43%"):
        assert part in headline.group(0)
    assert "doesn't place them" in words


def test_2_buying_no_routes_to_kalshi(site):
    words = order(site, side="NO")
    assert re.search(r"Buy on Kalshi: \$16\.95 for 100 NO contracts", words)
    assert "$17.71" in words


def test_3_a_large_no_order_spills_onto_kalshis_next_level(site):
    words = order(site, side="NO", quantity="5000")
    assert re.search(r"Buy on Polymarket: \$885\.28 for 5,000 NO contracts", words)
    assert "534.49 at 16¢" in words and "4,465.51 at 17¢" in words


def test_4_over_budget(site):
    words = order(site, budget="80")
    assert "No venue can fill 100 YES contracts within $80.00." in words
    assert "The cheapest full fill is Polymarket at $84.67." in words


def test_5_not_enough_contracts(site):
    words = order(site, quantity="5000000")
    assert "No venue has 5,000,000 YES contracts for sale." in words


def test_6_an_empty_book_is_explained(site):
    words = order(site, outcome=CUT25, side="NO")
    assert re.search(r"Buy on Polymarket: \$99\.62 for 100 NO contracts", words)
    assert "nobody is selling NO" in words


@pytest.mark.parametrize(
    "params, message",
    [
        ({"quantity": "0"}, "Contracts must be a number greater than 0."),
        ({"quantity": "abc"}, "Contracts must be a number greater than 0."),
        ({"side": "MAYBE"}, "Choose Buy YES or Buy NO."),
        ({"outcome": "nope"}, "That outcome isn't among the loaded markets."),
        ({"budget": "-5"}, "The budget must be a dollar amount greater than 0."),
    ],
    ids=["zero", "not a number", "unknown side", "unknown outcome", "negative budget"],
)
def test_7_bad_input_is_explained_next_to_the_form(site, params, message):
    status, page = get(site, "/", **({"outcome": HOLD, "side": "YES", "quantity": "100"} | params))
    words = text(page)
    assert status == 200
    assert message in words
    assert "Buy on" not in words and "Traceback" not in page


# Test 8: the market board.


def test_8_board_shows_both_venues_and_the_best_venue_per_outcome(site):
    status, page = get(site, "/board")
    words = text(page)
    assert status == 200
    names = ["Cut 50 bps or more", "Cut 25 bps", "No change", "Hike 25 bps", "Hike 50 bps or more"]
    positions = [words.index(name) for name in names]
    assert positions == sorted(positions), (
        "outcomes are listed from the deepest cut to the largest hike"
    )
    row = re.search(r"No change .*? Price my order", words).group(0)
    assert "85¢" in row and "84¢" in row
    assert "Polymarket $84.67" in row and "Kalshi $16.95" in row
    assert "Snapshot taken 2026-10-10 20:44 UTC" in words
    assert "Fed rate decision, October 28, 2026" in words


# Test 9: why these match.


def test_9_match_screen_for_no_change(site):
    status, page = get(site, "/match", outcome=HOLD)
    words = text(page)
    assert status == 200
    assert "Will the Federal Reserve Hike rates by 0bps at their October 2026 meeting?" in words
    assert "Will there be no change in Fed interest rates after the October 2026 meeting?" in words
    assert "Same bet" in words and "Confidence: High" in words
    assert "If the meeting is cancelled, 'Fed maintains rate' resolves Yes." in words
    assert "A change not shown in the brackets is rounded up to the nearest 25 bps." in words
    assert 'class="differs"' in page


def test_9_match_screen_for_the_grid_pair(site):
    words = text(get(site, "/match", outcome=CUT50)[1])
    assert "Confidence: Medium" in words and "25 bps steps" in words


# Test 11: a live venue that fails falls back to the snapshot (D17).


def test_11_live_failure_is_shown_in_the_banner():
    def live(venue):
        if venue == "kalshi":

            def fail(url):
                raise FetchError(f"{url}: connection refused")

            return fail
        return FixtureFetcher(DEFAULT_SNAPSHOT)

    with serving(App(Settings(), live_fetcher=live)) as base:
        words = text(get(base, "/", data="live")[1])
    assert "Live prices" in words
    assert "Kalshi: live data unavailable" in words and "snapshot" in words
    assert "Buy on Polymarket" in words


# Test 12: the page and the CLI agree.

ORDERS = [
    (HOLD, "kalshi:KXFEDDECISION-26OCT-H0", "YES", "100", None),
    (HOLD, "kalshi:KXFEDDECISION-26OCT-H0", "NO", "100", None),
    (HOLD, "kalshi:KXFEDDECISION-26OCT-H0", "NO", "5000", None),
    (HOLD, "kalshi:KXFEDDECISION-26OCT-H0", "YES", "100", "80"),
    (CUT25, "kalshi:KXFEDDECISION-26OCT-C25", "NO", "100", None),
]


@pytest.mark.parametrize("outcome, market, side, quantity, budget", ORDERS)
def test_12_page_and_cli_show_the_same_totals(
    site, capsys, outcome, market, side, quantity, budget
):
    argv = ["simulate", "--market", market, "--outcome", side, "--quantity", quantity]
    argv += (["--budget", budget] if budget else []) + ["--source", "fixtures", "--json"]
    cli.main(argv)
    trace = json.loads(capsys.readouterr().out)
    words = order(site, outcome, side, quantity, budget)
    for quote in trace["quotes"]:
        if Decimal(quote["filled_quantity"]) == Decimal(quantity):
            cents = Decimal(quote["total_cost"]).quantize(Decimal("0.01"), ROUND_HALF_UP)
            assert f"${cents:,}" in words, f"{quote['market_id']} ${cents}"


# Test 13: venue text is escaped.


def test_13_venue_text_is_escaped():
    snapshot = cli.load_markets(Settings(source="fixtures"))
    hostile = snapshot.markets[0].model_copy(update={"title": "<script>alert(1)</script>"})
    loaded = Loaded(markets=[hostile, *snapshot.markets[1:]], warnings=["<b>bad</b> warning"])
    app = App(Settings(), load=lambda source: loaded)
    with serving(app) as base:  # the Cut 50 match page shows that market's title
        pages = [get(base, "/")[1], get(base, "/board")[1], get(base, "/match", outcome=CUT50)[1]]
    assert all("<script>alert(1)</script>" not in page for page in pages)
    assert any("&lt;script&gt;alert(1)&lt;/script&gt;" in page for page in pages)
    assert all("<b>bad</b>" not in page for page in pages)


# Test 14: the existing routes are unchanged.


def test_14_health_and_unknown_paths(site):
    status, body = get(site, "/health")
    assert status == 200 and json.loads(body)["status"] == "ok"
    assert get(site, "/missing")[0] == 404


# Test 15: the UI names venues only from the data.


def test_15_web_code_names_no_venue():
    for path in WEB.glob("*.py"):
        found = re.findall("kalshi|polymarket|meridian", path.read_text(encoding="utf-8"), re.I)
        assert not found, f"{path.name} names a venue: {found}"
