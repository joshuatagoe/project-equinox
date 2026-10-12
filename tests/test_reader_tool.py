"""feat-12 commit 2: the reader's tool asks for a score in parts, and code assembles the terms.

The model reversed scores when it wrote a whole score as one string ("final_score_4_1"). Now it
first works out which side is at home and how the market states the score, then fills each part,
and code writes the subject and measure from the parts, with the team keys the parsers use.
"""

from dataclasses import replace

from equinox.models.catalog import MarketText, ReadableMarket
from equinox.reader import checks, prompt

POLY = ReadableMarket(
    "polymarket:1",
    "polymarket",
    "Racing Club de Lens vs. Sporting CP - Exact Score",
    "Exact Score: Racing Club de Lens 1 - 4 Sporting CP?",
    "Racing Club de Lens 1 - 4 Sporting CP",
    None,
    MarketText("Resolves on the final score of the match originally scheduled for Oct 13, 2026."),
)
PARTS = {
    "readable": True,
    "score_order": "Lens is first in 'Lens vs. Sporting', so at home; the score is home first.",
    "home_team": "Racing Club de Lens",
    "away_team": "Sporting CP",
    "home_goals": 1,
    "away_goals": 4,
    "period": "full_time",
    "measured_by": "official_match_result",
    "observed_on": "2026-10-13",
    "comparison": "eq",
    "threshold": "1",
    "unit": "indicator",
    "evidence": "Racing Club de Lens 1 - 4 Sporting CP",
}


def test_code_writes_a_scores_subject_and_measure_from_its_parts():
    terms = checks.accept(PARTS | {"subject": "x", "measure": "final_score_4_1"}, POLY).terms
    assert terms is not None
    assert (terms.subject, terms.measure) == ("racing_lens_vs_sporting_cp", "full_time_score_1_4")


def test_both_venues_spellings_of_a_team_give_one_subject():
    kalshi_spelling = PARTS | {"home_team": "Racing Club De Lens", "away_team": "Sporting CP"}
    a = checks.unchecked(PARTS, POLY).terms
    b = checks.unchecked(kalshi_spelling, POLY).terms
    assert a.subject == b.subject


def test_a_first_half_score_is_a_different_measure():
    terms = checks.unchecked(PARTS | {"period": "first_half"}, POLY).terms
    assert terms.measure == "first_half_score_1_4"


def test_parts_in_the_wrong_order_are_still_refused():
    swapped = PARTS | {"home_goals": 4, "away_goals": 1}
    refused = checks.accept(swapped, POLY)
    assert refused.terms is None and "1-4" in refused.problem


def test_a_market_without_score_parts_is_read_as_before():
    record = {k: v for k, v in PARTS.items() if k not in checks.SCORE_PARTS}
    record |= {"subject": "racing_lens_vs_sporting_cp", "measure": "final_score_1_4"}
    assert checks.accept(record, POLY).terms.measure == "final_score_1_4"


def test_the_tool_asks_for_the_order_before_the_goals_and_describes_every_field():
    fields = prompt.TOOL["input_schema"]["properties"]["markets"]["items"]["properties"]
    names = list(fields)
    assert names.index("score_order") < names.index("home_goals") < names.index("measure")
    assert fields["home_goals"]["type"] == fields["away_goals"]["type"] == "integer"
    assert fields["period"]["enum"] == ["full_time", "first_half"]
    assert all(field.get("description") for name, field in fields.items() if name != "id")
    assert prompt.PROMPT_VERSION != "feat-10.7"


def test_code_writes_a_scores_measuring_body_so_both_venues_agree():
    a = checks.unchecked(PARTS | {"measured_by": "official_match_result"}, POLY).terms
    b = checks.unchecked(PARTS | {"measured_by": "official_statistics"}, POLY).terms
    assert a.measured_by == b.measured_by == "official_match_score"  # as the parsers write it


def test_the_score_gold_set_shows_kalshis_strike_fields_and_event_titles():
    from equinox.reader import gold

    kalshi = [m for case in gold.score_cases() for m in case.markets if m.venue == "kalshi"]
    assert kalshi and all('"home_score"' in m.text.strike for m in kalshi)
    assert all(m.event_title.endswith("Correct Score") for m in kalshi)


def answer_text(text):
    block = {"type": "tool_use", "name": "record_terms", "input": {"markets": text}}
    return {"content": [block]}


def test_one_broken_record_in_a_text_answer_loses_only_itself():
    markets = [POLY, replace(POLY, market_id="polymarket:2")]
    good = '{"id":"m2","readable":true,"evidence":"x"}'
    slipped = '{"id":"m1","readable":true,"evidence":"Lens 1 - 4 Sporting","}'  # seen live
    records = prompt.answers(answer_text(f"[{slipped},{good}]"), markets)
    assert records["polymarket:2"]["evidence"] == "x"
    assert records["polymarket:1"]["evidence"] == "Lens 1 - 4 Sporting"  # repaired
    garbage = '{"id":"m1","readable":tru'
    records = prompt.answers(answer_text(f"[{garbage},{good}]"), markets)
    assert records["polymarket:2"]["readable"] is True
    assert records["polymarket:1"]["readable"] is False  # no record: rejected as unread


def test_code_writes_every_term_of_a_score_so_stray_fields_cant_spoil_it():
    seen_live = PARTS | {"unit": "count", "threshold": "0-0", "comparison": "ge"}
    terms = checks.accept(seen_live, POLY).terms
    assert terms is not None
    assert (terms.comparison, terms.threshold, terms.unit) == ("eq", 1, "indicator")


def test_a_reading_that_doesnt_validate_is_unread_not_another_family():
    from equinox.reader import check

    unread = checks.Reading("polymarket:1", None, "The terms don't validate: bad threshold.")
    assert check._verdict("exact_score", unread) == (
        "unread: The terms don't validate: bad threshold."
    )
