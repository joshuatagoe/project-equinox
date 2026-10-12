"""feat-14 commit 3: match review for Morgan, the auditor.

Morgan asks why two markets were called the same bet, how sure Equinox is, and which pairs it set
aside. Matches lists every pair Equinox kept, by how it was decided: exact matches, same bets a
model read, pairs that only look alike (never priced), and pairs a model ruled different. Each same
bet opens its ticket's "Is this really the same bet?" panel.
"""

import re

from test_reader import MAYOR, READINGS, SPRING, FakeModel, mayors
from test_web_app import mixed, scores_app, words

from equinox.reader import run
from equinox.sources import Settings
from equinox.web import App


def pairs(page):
    """Each pair on the page, as its text."""
    return [
        words(p) for p in re.findall(r'<div class="pair">(.*?)</div>\s*<!--/pair-->', page, re.S)
    ]


def read(tmp_path, readings):
    run.read_catalog(mayors(tmp_path), FakeModel(readings), "claude-haiku-5-5", limit=10)
    return App(Settings(source="fixtures", cache_dir=tmp_path))


def test_matches_opens_on_exact_matches_each_linked_to_its_rules(tmp_path):
    page = mixed(tmp_path).respond("/matches", "")
    found = pairs(page)
    assert len(found) == 1 and "Fed holds rates in December" in found[0]
    assert "No change in December" in found[0] and "Exact match" in found[0]
    assert 'href="/bet?m=alpha%3Afed1&amp;side=YES#same-bet"' in page


def test_pairs_that_only_look_alike_show_their_score_and_are_never_priced(tmp_path):
    page = mixed(tmp_path).respond("/matches", "show=alike")
    found = pairs(page)
    assert len(found) == 1 and "Springfield" in found[0]
    assert "title score 0.71" in found[0] and "never priced" in found[0]
    assert "/bet?" not in page.split('<div class="pair">', 1)[1]


def test_same_bets_a_model_read_say_so(tmp_path):
    app = read(tmp_path, READINGS)
    assert pairs(app.respond("/matches", "")) == []  # not among the exact matches
    page = app.respond("/matches", "show=model")
    found = pairs(page)
    assert len(found) == 1 and "Read by a model" in found[0]
    assert "Terms read by claude-haiku-5-5" in found[0]
    assert "/bet?m=alpha%3A00" in page


def test_pairs_a_model_ruled_different_show_why(tmp_path):
    jones = READINGS | {SPRING[1]: MAYOR | {"measure": "winner_jones", "evidence": "Smith wins"}}
    found = pairs(read(tmp_path, jones).respond("/matches", "show=different"))
    assert len(found) == 1 and "Ruled different by a model" in found[0]
    assert "winner_jones" in found[0] or "winner jones" in found[0]


def test_only_a_models_rulings_are_listed_as_different(tmp_path):
    """Two scores of one match are different bets by their terms; that needs no review."""
    app = scores_app(tmp_path)
    assert pairs(app.respond("/matches", "show=different")) == []
    assert "Ruled different by a model 0" in words(app.respond("/matches", ""))


def test_each_kind_says_how_many_pairs_it_has(tmp_path):
    text = words(mixed(tmp_path).respond("/matches", ""))
    assert "Exact matches 1" in text and "Look alike, never priced 1" in text
    assert "Read by a model 0" in text and "Ruled different by a model 0" in text


def test_a_search_covers_both_titles(tmp_path):
    app = mixed(tmp_path)
    assert len(pairs(app.respond("/matches", "q=no change"))) == 1  # the second venue's words
    assert pairs(app.respond("/matches", "show=alike&q=fed")) == []
    assert len(pairs(app.respond("/matches", "show=alike&q=springfield"))) == 1


def test_the_top_bar_links_to_matches(tmp_path):
    assert '<a href="/matches"' in mixed(tmp_path).respond("/", "")


def test_titles_are_escaped(tmp_path):
    page = mixed(tmp_path, fed_title="<script>alert(1)</script>").respond("/matches", "")
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


def test_without_a_catalog_matches_says_how_to_get_one(tmp_path):
    text = words(App(Settings(cache_dir=tmp_path / "none")).respond("/matches", ""))
    assert "python -m equinox catalog refresh" in text
