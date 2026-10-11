"""feat-08 tests 11-12: the web UI on discovered meetings, books on demand, and plain bps."""

import html
import re

from equinox.adapters.fetch import DEFAULT_SNAPSHOT, FixtureFetcher
from equinox.sources import Settings
from equinox.web import App

NEW = DEFAULT_SNAPSHOT.parent / "snapshot-2026-10-11"
DEC_HOLD = "FOMC|fed_upper_bound_change|fomc_statement|2026-12-09|eq|0|bps"


def words(page):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


class Recorder:
    def __init__(self, fetch):
        self.fetch, self.urls, self.captured_at = fetch, [], fetch.captured_at

    def __call__(self, url):
        self.urls.append(url)
        return self.fetch(url)


def test_11_board_has_one_table_per_meeting_and_offers_every_snapshot():
    page = App(Settings()).respond("/board", f"data={NEW.name}")
    text = words(page)
    for day in ("October 28, 2026", "December 9, 2026", "January 27, 2027", "January 26, 2028"):
        assert f"Fed rate decision, {day}" in text
    assert page.count("<table>") == 11
    assert "Only on Kalshi" in text
    for option in ("snapshot-2026-10-10", NEW.name, "live"):
        assert f'value="{option}"' in page


def test_11_board_fetches_books_only_for_groups_on_both_venues():
    fetchers = []

    def live(venue):
        fetchers.append(Recorder(FixtureFetcher(NEW)))
        return fetchers[-1]

    App(Settings(), live_fetcher=live).respond("/board", "data=live")
    books = [u for f in fetchers for u in f.urls if u.endswith("/orderbook") or "/book?" in u]
    assert len(books) == 45  # 3 shared meetings x (5 Kalshi + 10 Polymarket)
    assert not [u for u in books if "27MAR" in u or "28JAN" in u]


def test_11_a_december_order_is_priced_on_the_new_snapshot():
    query = f"data={NEW.name}&outcome={DEC_HOLD}&side=YES&quantity=100"
    text = words(App(Settings()).respond("/", query))
    assert "Buy on Polymarket: $23.89 for 100 YES contracts" in text
    assert "less than Kalshi at $27.63" in text


def test_12_bps_is_explained_in_plain_words():
    app = App(Settings())
    order, board, match = (words(app.respond(path, "")) for path in ("/", "/board", "/match"))
    assert "Cut 25 bps (0.25 percentage points)" in order
    assert "Cut 50 bps or more (0.50 percentage points or more)" in board
    note = (
        "bps means basis points: 1 bp is 0.01 percentage point, so 25 bps is a quarter of a point"
    )
    assert all(note in page for page in (order, board, match))
