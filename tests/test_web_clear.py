"""feat-13 commit 1: the order page says what it's showing and lets you find any same bet.

Jordan asks "which venue is cheapest for my order, and why". The page now opens on an outcome both
venues list, says which outcomes only one venue lists, finds any same bet in the catalog by its
words, and says where its prices come from in plain words.
"""

import html
import re

from test_scores import SCORES, score_catalog

from equinox.adapters.fetch import DEFAULT_SNAPSHOT
from equinox.sources import Settings
from equinox.web import App

NEW = DEFAULT_SNAPSHOT.parent / "snapshot-2026-10-11"
DAYS = ("October 28, 2026", "December 9, 2026", "January 27, 2027")


def words(page):
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(page)).split())


def outcome_menu(page):
    return re.search(r'<select name="outcome">(.*?)</select>', page, re.S).group(1)


def test_the_order_page_opens_on_an_outcome_both_venues_list():
    page = App(Settings()).respond("/", f"data={NEW.name}")
    menu = outcome_menu(html.unescape(page))
    group = re.search(r'<optgroup label="([^"]*)">(?:(?!</optgroup>).)*? selected>', menu, re.S)
    assert group and "only on" not in group.group(1)
    assert "nothing to compare" not in words(page) and "That's $" in words(page)


def test_meetings_both_venues_list_come_first_and_the_rest_say_who_lists_them():
    menu = outcome_menu(html.unescape(App(Settings()).respond("/", f"data={NEW.name}")))
    groups = re.findall(r'<optgroup label="([^"]*)">', menu)
    shared = [g for g in groups if "only on" not in g]
    assert groups[: len(shared)] == shared
    assert shared == [f"Fed rate decision, {day}" for day in DAYS]  # in date order
    assert "Fed rate decision, March 17, 2027 (only on Kalshi)" in groups


def test_the_search_finds_each_same_bet_once_and_links_to_its_comparison(tmp_path):
    score_catalog(tmp_path)
    app = App(Settings(cache_dir=tmp_path, snapshot=SCORES))
    page = html.unescape(app.respond("/", "find=coventry 2-1"))
    found = re.findall(r'<li><a href="([^"]+)">([^<]+)</a>', page)
    assert found, words(page)[:400]
    assert all("outcome=catalog%3A" in link for link, _ in found)
    assert len(found) == 4  # 2-1 either way, full time and 1st half: each pair once, not twice
    assert any("2 - 1" in name or "2-1" in name for _, name in found)
    assert "Kalshi and Polymarket" in words(page)


def test_a_search_with_no_same_bet_says_so(tmp_path):
    score_catalog(tmp_path)
    page = App(Settings(cache_dir=tmp_path, snapshot=SCORES)).respond("/", "find=zebra unicorn")
    assert "No same bet on two venues matches" in words(page)


def test_a_search_without_a_catalog_says_how_to_build_one(tmp_path):
    page = App(Settings(cache_dir=tmp_path / "none")).respond("/", "find=coventry")
    assert "python -m equinox catalog refresh" in words(page)


def test_the_banner_says_how_old_a_snapshot_is():
    text = words(App(Settings()).respond("/", f"data={NEW.name}"))
    assert re.search(r"Snapshot taken 2026-10-11 14:06 UTC, \d+ (days|hours) ago", text)


def test_old_prices_are_explained_in_plain_words():
    text = words(App(Settings()).respond("/", f"data={NEW.name}"))
    assert "seconds old (captured" not in text
    assert re.search(r"Kalshi's prices are [\d.]+ (hours|days) old", text)


def test_a_search_result_is_priced_from_where_the_catalog_came_from(tmp_path):
    from test_scores import pages as listing_pages

    from equinox import catalog

    listed = listing_pages()
    with catalog.TextStage(tmp_path) as stage:
        for page in listed:
            stage.add(page.texts)
        found = [e for page in listed for e in page.entries]
        catalog.build(found, 0, tmp_path, 0.0, source="live", texts=stage)
    page = html.unescape(
        App(Settings(cache_dir=tmp_path)).respond("/", f"data={NEW.name}&find=coventry 2-1")
    )
    links = re.findall(r'<li><a href="([^"]+)">', page)
    assert links and all("data=live" in link for link in links)


def test_numbers_in_a_search_match_whole_so_2_1_finds_no_2_0(tmp_path):
    score_catalog(tmp_path)
    page = html.unescape(
        App(Settings(cache_dir=tmp_path, snapshot=SCORES)).respond("/", "find=coventry 2-1")
    )
    names = re.findall(r'<li><a href="[^"]+">([^<]+)</a>', page)
    assert names and all("2-0" not in name and "2 - 0" not in name for name in names)
