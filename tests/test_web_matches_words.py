"""feat-14 follow-up: Matches says what was compared and why, in words (D99).

User, 2026-10-12, of "al gharafa vs esteghlal tehran|full_time_score_0_1|official_match_score|
2026-10-12|eq|1|indicator": "noone knows whats this means ... its very vague unless ya know what
exactly isd being wiritten and why". Each pair says what YES pays for, and under "How it was
decided" shows what Equinox compared (the event, the outcome, who decides it, the date) for each
venue, in words, with the lines that differ marked, and one sentence on why that makes the pair
the same bet or not. The matcher's own key is never shown.
"""

import re
from datetime import date
from decimal import Decimal

from test_reader import MAYOR, READINGS, SPRING
from test_scores import score_catalog
from test_web_app import mixed, words
from test_web_matches import read

from equinox import catalog
from equinox.catalog import readings
from equinox.models import ContractTerms
from equinox.reader import prompt
from equinox.sources import Settings
from equinox.web import App

KEY_BITS = ("fed_upper_bound_change", "full_time_score", "|eq|", "indicator", "springfield_mayor")


def raw_pairs(page):
    return re.findall(r'<div class="pair">(.*?)</div>\s*<!--/pair-->', page, re.S)


def decided(pair):
    """The "How it was decided" part of a pair, as its text."""
    found = re.search(r"<details><summary>How it was decided</summary>(.*?)</details>", pair, re.S)
    return words(found.group(1)) if found else ""


def test_an_exact_fed_match_says_what_was_compared_and_why(tmp_path):
    pair = raw_pairs(mixed(tmp_path).respond("/matches", ""))[0]
    assert "Both venues pay $1 a YES share if the Fed leaves its target rate unchanged." in words(
        pair
    )
    why = decided(pair)
    for line in ("Event FOMC", "the Fed leaves its target rate unchanged", "The FOMC statement"):
        assert line in why, line
    assert "December 9, 2026" in why and "Every line matches" in why
    assert not any(bit in pair for bit in KEY_BITS)


def test_an_exact_score_match_names_the_teams_and_the_score(tmp_path):
    score_catalog(tmp_path)
    page = App(Settings(source="fixtures", cache_dir=tmp_path)).respond(
        "/matches", "q=coventry 2-1"
    )
    home_win = next(p for p in raw_pairs(page) if "Final score Coventry City wins 2-1?" in p)
    assert "score after 90 minutes is Coventry City 2, Newcastle United 1." in words(home_win)
    assert "Score after 90 minutes: Coventry City 2, Newcastle United 1" in decided(home_win)
    assert "Official match score" in decided(home_win)
    assert not any(bit in page for bit in KEY_BITS)


def test_a_model_read_match_says_who_read_it_and_what_they_read(tmp_path):
    pair = raw_pairs(read(tmp_path, READINGS).respond("/matches", "show=model"))[0]
    why = decided(pair)
    assert "Both venues" in why and "Springfield Mayor 2026" in why and "winner smith" in why
    assert "Terms read by claude-haiku-5-5" in why and "Medium at most" in why
    assert not any(bit in pair for bit in KEY_BITS)


def test_a_pair_ruled_different_marks_the_line_that_differs(tmp_path):
    jones = READINGS | {SPRING[1]: MAYOR | {"measure": "winner_jones", "evidence": "Smith wins"}}
    pair = raw_pairs(read(tmp_path, jones).respond("/matches", "show=different"))[0]
    why = decided(pair)
    assert "Alpha" in why and "Beta" in why  # each venue's reading, side by side
    assert re.search(r"Outcome differs winner smith winner jones", why)
    assert "different bets" in why


def test_a_title_only_pair_says_only_the_titles_were_compared(tmp_path):
    pair = raw_pairs(mixed(tmp_path).respond("/matches", "show=alike"))[0]
    why = decided(pair)
    assert re.search(r"only the titles were compared \(they share \d+ of \d+ words\)", why)
    assert "AMBIGUOUS" not in pair


def test_a_market_read_twice_shows_the_readings_that_agree(tmp_path):
    """As pricing does (D75): a later reading may name the market another way."""
    app = read(tmp_path, READINGS)
    later = ContractTerms(
        subject="springfield_race_2026",
        measure="winner_smith",
        measured_by="springfield_election_board",
        observed_on=date(2026, 11, 3),
        comparison="eq",
        threshold=Decimal(1),
        unit="indicator",
    )
    row = readings.ReadingRow("alpha:00", 9, later.model_dump_json(), "", "Smith win")
    found = catalog.load_latest(tmp_path)
    readings.record(found, "claude-haiku-5-5", prompt.PROMPT_VERSION, [row], [])
    why = decided(raw_pairs(app.respond("/matches", "show=model"))[0])
    assert "Both venues" in why and "Springfield Mayor 2026" in why
