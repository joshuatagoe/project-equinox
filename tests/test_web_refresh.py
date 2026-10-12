"""feat-14 commit 2: fresh data without a command, and the model's decisions kept for free.

The server refreshes the catalog when it has none or it is an hour old, and when someone presses
Refresh. A refresh carries the model's decisions into the new catalog when both markets' rules are
unchanged, so nothing is read twice and the server never calls the model. While the first catalog
is being built the app says so; if the venues can't be reached it says that.
"""

import html
import re
import threading
from datetime import UTC, datetime, timedelta

from test_reader import READINGS, SPRING, FakeModel, entry, mayors
from test_web import get, serving

from equinox import catalog
from equinox.catalog import CatalogError, background, carry
from equinox.models.catalog import MarketText
from equinox.reader import prompt, run
from equinox.sources import Settings
from equinox.web import App

READER = f"claude-haiku-5-5 (prompt {prompt.PROMPT_VERSION})"
RULES = "Resolves by the official count."


def words(page):
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(page)).split())


def smith(tmp_path):
    return {r.market_id: r for r in catalog.load_latest(tmp_path).search(per_page=50)}["alpha:00"]


def rebuild(tmp_path, rules=None):
    """The same two markets read again, as a refresh would, optionally with new rules."""
    entries = [entry("00", "alpha", SPRING[0], day=3), entry("01", "beta", SPRING[1], day=3)]
    texts = {e.market_id: MarketText(RULES) for e in entries} | (rules or {})
    with catalog.TextStage(tmp_path) as stage:
        stage.add(texts)
        catalog.build(entries, skipped=0, cache_dir=tmp_path, seconds=0.0, texts=stage)


def read_once(tmp_path):
    run.read_catalog(mayors(tmp_path), FakeModel(READINGS), "claude-haiku-5-5", limit=10)
    assert smith(tmp_path).status == "same bet"


# The model's decisions, carried into a new catalog.


def test_a_refresh_keeps_the_models_decision_when_both_rules_are_unchanged(tmp_path):
    read_once(tmp_path)
    kept = carry.keep(tmp_path)
    rebuild(tmp_path)
    assert carry.apply(kept, tmp_path) == 1
    row = smith(tmp_path)
    assert (row.status, row.read_by) == ("same bet", READER)
    rows = {r.market_id: r for r in catalog.load_latest(tmp_path).search(per_page=50)}
    assert (rows["beta:01"].status, rows["beta:01"].partner) == ("same bet", "alpha:00")
    assert set(catalog.load_latest(tmp_path).readings()) == {"alpha:00", "beta:01"}


def test_changed_rules_are_read_again_not_carried(tmp_path):
    read_once(tmp_path)
    kept = carry.keep(tmp_path)
    rebuild(tmp_path, {"beta:01": MarketText("Resolves by the court's ruling.")})
    assert carry.apply(kept, tmp_path) == 0
    assert (smith(tmp_path).status, smith(tmp_path).read_by) == ("unclear", None)


def test_the_refresh_itself_carries_them(tmp_path, monkeypatch):
    read_once(tmp_path)

    def listing(settings, live_fetcher, paging, stage, progress):
        entries = [entry("00", "alpha", SPRING[0], day=3), entry("01", "beta", SPRING[1], day=3)]
        stage.add({e.market_id: MarketText(RULES) for e in entries})
        return entries, 0

    monkeypatch.setattr(catalog, "_read_venues", listing)
    lines = []
    catalog.refresh(Settings(source="live", cache_dir=tmp_path), progress=lines.append)
    assert smith(tmp_path).read_by == READER
    assert "Kept 1 model decision from the previous catalog." in lines


def test_a_decision_is_dropped_when_its_markets_are_no_longer_compared(tmp_path):
    """Both markets keep their rules, but one venue moved its closing date (as with D84's pair),
    so each is now compared with another market and not with the other."""
    read_once(tmp_path)
    kept = carry.keep(tmp_path)
    entries = [
        entry("00", "alpha", SPRING[0], day=3),
        entry("02", "beta", SPRING[1], day=3),
        entry("03", "alpha", SPRING[0], day=20),
        entry("01", "beta", SPRING[1], day=20),
    ]
    with catalog.TextStage(tmp_path) as stage:
        stage.add({e.market_id: MarketText(RULES) for e in entries})
        catalog.build(entries, skipped=0, cache_dir=tmp_path, seconds=0.0, texts=stage)
    assert carry.apply(kept, tmp_path) == 0
    assert smith(tmp_path).read_by is None


def test_with_no_previous_catalog_nothing_is_carried(tmp_path):
    kept = carry.keep(tmp_path)
    rebuild(tmp_path)
    assert carry.apply(kept, tmp_path) == 0 and smith(tmp_path).status == "unclear"


# When the server refreshes.


def test_a_refresh_is_due_with_no_catalog_or_an_hour_old_one(tmp_path):
    now = datetime.now(UTC)
    settings = Settings(source="live", cache_dir=tmp_path)
    assert background.Refresher(settings, clock=lambda: now).due()
    rebuild(tmp_path)
    assert not background.Refresher(settings, clock=lambda: now).due()
    later = now + timedelta(hours=1, minutes=1)
    assert background.Refresher(settings, clock=lambda: later).due()


def test_snapshot_data_is_never_refreshed(tmp_path):
    ran = []
    settings = Settings(source="fixtures", cache_dir=tmp_path)
    refresher = background.Refresher(settings, run=ran.append)
    refresher.request()
    refresher.tick()
    assert not refresher.due() and ran == []  # it would replace a live catalog with a sample


def test_refresh_runs_when_asked_even_if_none_is_due(tmp_path):
    rebuild(tmp_path)
    ran = []
    refresher = background.Refresher(Settings(source="live", cache_dir=tmp_path), run=ran.append)
    refresher.tick()
    assert ran == []
    refresher.request()
    refresher.tick()
    assert len(ran) == 1


def test_a_failed_refresh_keeps_the_catalog_and_says_why(tmp_path):
    rebuild(tmp_path)
    before = catalog.store.latest(tmp_path)

    def unreachable(settings):
        raise CatalogError("kalshi: connection refused. The previous catalog is kept.")

    refresher = background.Refresher(Settings(source="live", cache_dir=tmp_path), run=unreachable)
    refresher.run_once()
    assert "connection refused" in refresher.status().problem
    assert catalog.store.latest(tmp_path) == before
    refresher = background.Refresher(Settings(cache_dir=tmp_path), run=lambda settings: None)
    refresher.run_once()
    assert refresher.status() == background.Status()


# What the pages say.


class Stub:
    def __init__(self, **status):
        self.state, self.asked = background.Status(**status), threading.Event()

    def status(self):
        return self.state

    def request(self):
        self.asked.set()


def test_while_the_first_catalog_is_built_home_says_so_and_reloads(tmp_path):
    app = App(Settings(cache_dir=tmp_path), refresher=Stub(running=True))
    page = app.respond("/", "")
    assert "Getting every open market from both venues" in words(page)
    assert '<meta http-equiv="refresh"' in page


def test_with_no_catalog_and_no_venues_the_app_says_they_cant_be_reached(tmp_path):
    stub = Stub(problem="kalshi: connection refused. The previous catalog is kept.")
    text = words(App(Settings(cache_dir=tmp_path), refresher=stub).respond("/", ""))
    assert "The venues can't be reached right now" in text


def test_the_top_bar_says_when_a_refresh_is_running_or_failed(tmp_path):
    rebuild(tmp_path)
    app = App(Settings(cache_dir=tmp_path), refresher=Stub(running=True))
    running = words(app.respond("/", ""))
    assert "Refreshing now" in running
    stub = Stub(problem="kalshi: connection refused.")
    failed = words(App(Settings(cache_dir=tmp_path), refresher=stub).respond("/", ""))
    assert "The last refresh failed" in failed and "Prices as of the last refresh" in failed


def test_the_refresh_button_asks_for_a_refresh(tmp_path):
    rebuild(tmp_path)
    stub = Stub()
    app = App(Settings(cache_dir=tmp_path), refresher=stub)
    assert '<form class="refresh" method="post" action="/refresh">' in app.respond("/", "")
    with serving(app) as base:
        status, home = post(base, "/refresh")
        _, back = post(base, "/refresh", referer=f"{base}/event?m=alpha%3A00")
        _, away = post(base, "/refresh", referer="https://elsewhere.example/phish")
    assert status == 303 and stub.asked.is_set()
    assert (home, back, away) == ("/", "/event?m=alpha%3A00", "/")  # back to the page, never away


def test_without_a_refresher_there_is_no_button(tmp_path):
    rebuild(tmp_path)
    assert 'action="/refresh"' not in App(Settings(cache_dir=tmp_path)).respond("/", "")
    with serving(App(Settings(cache_dir=tmp_path))) as base:
        assert post(base, "/refresh")[0] == 404 and get(base, "/health")[0] == 200


def post(base, path, referer=None):
    """(status, where it sends the browser) for a POST."""
    import urllib.error
    import urllib.request

    class Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(Stay)
    try:
        headers = {"Referer": referer} if referer else {}
        request = urllib.request.Request(f"{base}{path}", data=b"", method="POST", headers=headers)
        with opener.open(request) as r:
            return r.status, r.headers.get("Location")
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Location")
