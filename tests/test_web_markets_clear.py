"""feat-13 commit 2: All markets shows each same bet once, in plain words, and says how it matched.

Jordan wants to see a bet once, with both venues' prices; Morgan wants to know how the match was
made and how sure it is. The page opens on the same bets that can be priced; a search covers every
market, and markets that only look alike, or are on one venue, are behind the status filter.
"""

import html
import re
from dataclasses import replace
from datetime import date
from decimal import Decimal

from test_reader import READINGS, SPRING, FakeModel, entry, mayors
from test_scores import SCORES, score_catalog
from test_web_catalog import built

from equinox import catalog
from equinox.models import ContractTerms
from equinox.models.catalog import MarketText
from equinox.reader import run
from equinox.sources import Settings
from equinox.web import App

COV_2_1 = "kalshi:KXEPLSCORE-26OCT12COVNEW-COV2NEW1"


def words(page):
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(page)).split())


def bets(page):
    """Each row of the listing as its text."""
    return [
        words(b) for b in re.findall(r'<div class="bet">(.*?)</div>', html.unescape(page), re.S)
    ]


def scores_page(tmp_path, query):
    score_catalog(tmp_path)
    return App(Settings(cache_dir=tmp_path, snapshot=SCORES)).respond("/markets", query)


def test_the_page_opens_on_same_bets_you_can_price(tmp_path):
    page = scores_page(tmp_path, "")
    rows = bets(page)
    assert rows and all("Compare the cost on both venues" in row for row in rows)
    assert "Showing the same bets you can price" in words(page)


def test_a_same_bet_is_one_row_with_both_venues_prices_and_what_yes_pays(tmp_path):
    rows = [
        r
        for r in bets(scores_page(tmp_path, "q=coventry 2-1"))
        if "Final score Coventry City wins 2-1" in r
    ]
    assert len(rows) == 1  # one row for the pair, not one per venue
    row = rows[0]
    assert "YES pays $1 if the score after 90 minutes is Coventry City 2, Newcastle United 1" in row
    assert re.search(r"Kalshi YES [\d.]+¢ NO [\d.]+¢ Polymarket YES [\d.]+¢ NO [\d.]+¢", row)
    assert "matched exactly by Equinox's reader for this kind of market" in row


def test_the_compare_button_opens_the_pairs_comparison(tmp_path):
    page = html.unescape(scores_page(tmp_path, "q=coventry 2-1"))
    assert f"outcome=catalog%3A{COV_2_1.replace(':', '%3A')}" in page


def test_a_fed_same_bet_says_what_yes_pays(tmp_path):
    rows = bets(built(tmp_path).respond("/markets", ""))
    fed = next(r for r in rows if "Fed holds rates in December" in r)
    assert "YES pays $1 if the Fed leaves its target rate unchanged" in fed


def test_a_market_with_no_match_says_why_not_that_no_other_venue_lists_it(tmp_path):
    """A venue can date the same question a year later (seen live), so "only on" would overclaim."""
    rows = bets(built(tmp_path).respond("/markets", "q=snow"))
    assert rows and "No match found" in rows[0] and "Only on" not in rows[0]
    assert "or a similar title closing within 3 days of this one" in rows[0]


def test_markets_that_only_look_alike_say_they_are_never_priced(tmp_path):
    rows = bets(built(tmp_path).respond("/markets", "q=springfield"))
    assert rows and all("Looks alike, not checked" in r and "never priced" in r for r in rows)


def test_the_page_says_what_each_label_means(tmp_path):
    text = words(built(tmp_path).respond("/markets", ""))
    for meaning in ("High confidence:", "Medium confidence:", "Looks alike, not checked:"):
        assert meaning in text


def test_exact_matches_come_before_model_read_ones(tmp_path):
    """The surest matches first: the venues list the model-read pair first, but it is shown last."""
    fed = ContractTerms(
        subject="FOMC",
        measure="fed_upper_bound_change",
        measured_by="fomc_statement",
        observed_on=date(2026, 12, 9),
        comparison="eq",
        threshold=Decimal(0),
        unit="bps",
    )
    entries = [
        entry("00", "alpha", SPRING[0]),
        entry("01", "beta", SPRING[1]),
        replace(entry("fed1", "alpha", "Fed holds rates in December", day=9), terms=fed),
        replace(entry("fed2", "beta", "No change in December", day=9), terms=fed),
    ]
    with catalog.TextStage(tmp_path) as stage:
        stage.add({e.market_id: MarketText("Resolves by the official count.") for e in entries})
        catalog.build(entries, skipped=0, cache_dir=tmp_path, seconds=0.0, texts=stage)
    found = catalog.load_latest(tmp_path)
    run.read_catalog(found, FakeModel(READINGS), "claude-haiku-5-5", limit=10)
    rows = bets(App(Settings(cache_dir=tmp_path)).respond("/markets", ""))
    assert len(rows) == 2
    assert "Fed holds rates in December" in rows[0] and "read by a model" in rows[1]


def test_the_page_says_what_a_price_is(tmp_path):
    text = words(built(tmp_path).respond("/markets", ""))
    assert "Cost to buy one share now; – means no one is selling." in text


def test_a_model_read_match_keeps_its_reasons_under_how_it_matched(tmp_path):
    run.read_catalog(mayors(tmp_path), FakeModel(READINGS), "claude-haiku-5-5", limit=10)
    page = App(Settings(cache_dir=tmp_path)).respond("/markets", "")
    folded = re.search(r"<details><summary>How it matched</summary>(.*?)</details>", page, re.S)
    assert folded and "Terms read by claude-haiku-5-5" in html.unescape(folded.group(1))
