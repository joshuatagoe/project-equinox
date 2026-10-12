"""feat-14 follow-up: the older the prices, the louder Refresh (user, 2026-10-12).

"maybe we should make the backgruond refresh 3-6 hrs and the refresh button more prominent the
longer the data is stale": the server refreshes every 6 hours by itself; Refresh is a small
outlined button under an hour, a filled one from an hour, and from 3 hours a note at the top says
how old the prices are with Refresh beside it. The order ticket always prices from live order books.
"""

import re
from datetime import timedelta

from test_web_refresh import Stub, rebuild, words

from equinox import catalog
from equinox.catalog import background
from equinox.sources import Settings
from equinox.web import App


def page_at(tmp_path, hours, **status):
    rebuild(tmp_path)
    made = catalog.load_latest(tmp_path).summary.refreshed_at
    later = made + timedelta(hours=hours)
    app = App(Settings(cache_dir=tmp_path), refresher=Stub(**status), clock=lambda: later)
    return app.respond("/", "")


def refresh_button(page):
    found = re.search(r'<form class="refresh"[^>]*>\s*<button class="([^"]+)"[^>]*>([^<]+)<', page)
    return found.groups() if found else None


def test_fresh_prices_have_a_small_outlined_refresh_button(tmp_path):
    """A text link was easy to miss (user, 2026-10-12: "i dont see the refresh button")."""
    page = page_at(tmp_path, 0.5)
    assert refresh_button(page) == ("btn small ghost", "Refresh")
    assert "These prices are" not in words(page)


def test_from_an_hour_refresh_is_a_button(tmp_path):
    page = page_at(tmp_path, 2)
    assert refresh_button(page) == ("btn small", "Refresh prices")
    assert "These prices are" not in words(page)


def test_from_three_hours_a_note_says_how_old_with_refresh_beside_it(tmp_path):
    page = page_at(tmp_path, 4)
    assert "These prices are 4 hours old. Refresh to update them." in words(page)
    note = re.search(r'<p class="notice stale">(.*?)</p>', page, re.S)
    assert note and 'action="/refresh"' in note.group(1)


def test_while_updating_the_note_says_updating_not_old(tmp_path):
    text = words(page_at(tmp_path, 4, running=True))
    assert "Updating markets from both venues." in text and "These prices are" not in text


def test_the_server_refreshes_every_six_hours(tmp_path):
    assert background.EVERY == timedelta(hours=6)
