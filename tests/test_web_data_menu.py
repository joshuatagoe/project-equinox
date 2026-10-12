"""feat-13 commit 3: the data menu offers whole snapshots and live prices, not test captures.

A capture named for what it tests ("-pair", "-scores") holds a few markets for one test. Offered
beside the dated snapshots, it reads as another day's data and shows nearly empty pages. It can
still be opened by name, and then the menu names it, so the page never hides where its data
comes from.
"""

import re

from equinox.adapters.fetch import DEFAULT_SNAPSHOT
from equinox.sources import Settings, offered_snapshots, snapshot_names
from equinox.web import App

PAIR = DEFAULT_SNAPSHOT.parent / "snapshot-2026-10-11-pair"
TESTS_ONLY = ("snapshot-2026-10-11-pair", "snapshot-2026-10-11-scores")


def options(page):
    menu = re.search(r'<select name="data">(.*?)</select>', page, re.S).group(1)
    return re.findall(r'<option value="([^"]+)"', menu)


def test_the_menu_offers_dated_snapshots_and_live_prices_only():
    page = App(Settings()).respond("/", "")
    assert options(page) == ["snapshot-2026-10-10", "snapshot-2026-10-11", "live"]
    assert offered_snapshots() == ["snapshot-2026-10-10", "snapshot-2026-10-11"]


def test_a_test_capture_can_still_be_opened_by_name():
    assert set(TESTS_ONLY) <= set(snapshot_names())
    page = App(Settings()).respond("/", f"data={PAIR.name}")
    assert re.search(rf'<option value="{PAIR.name}" selected>', page)


def test_a_server_started_on_a_test_capture_names_it_in_the_menu():
    page = App(Settings(snapshot=PAIR)).respond("/", "")
    assert re.search(rf'<option value="{PAIR.name}" selected>', page)
    assert "snapshot-2026-10-11-scores" not in options(page)
