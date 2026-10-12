"""feat-12: how strong the setup is: raw and guarded scores, bounds, traps and a larger score set.

Raw is what the model alone gets right: every reading that forms valid terms. Guarded is what can
route: the readings the checks accept. The traps are the false same-bets the score parser found in
the full read; the score set is the parsers' labels on live catalog groups, split by match into a
half the reader is tuned on and a half it is only judged on.
"""

import json
from dataclasses import asdict
from datetime import UTC, datetime

from equinox.models.catalog import MarketText, ReadableMarket
from equinox.reader import checks, evals

LENS_HOME = "Final score Racing Club De Lens wins 4-1?"
LENS_AWAY = "Exact Score: Racing Club de Lens 1 - 4 Sporting CP?"
CLOSES = datetime(2026, 10, 16, 1, tzinfo=UTC)
KALSHI_RULES = (
    "If Racing Club De Lens wins 4-1 in the Racing Club De Lens vs Sporting CP professional "
    "Champions League soccer game originally scheduled for Oct 13, 2026 after 90 minutes plus "
    "stoppage time (does not include extra time or penalties), then the market resolves to Yes."
)
STRIKE = json.dumps(
    {"strike_type": "custom", "custom_strike": {"home_score": "4", "away_score": "1"}}
)
KALSHI = ReadableMarket(
    "kalshi:LENS41",
    "kalshi",
    "Racing Club De Lens vs Sporting CP: Correct Score",
    LENS_HOME,
    "Racing Club De Lens wins 4-1",
    CLOSES,
    MarketText(KALSHI_RULES, STRIKE),
)
POLY = ReadableMarket(
    "polymarket:1",
    "polymarket",
    "Racing Club de Lens vs. Sporting CP - Exact Score",
    LENS_AWAY,
    "Racing Club de Lens 1 - 4 Sporting CP",
    CLOSES,
    MarketText(
        "This market will resolve based on the final score of the Racing Club de Lens vs. "
        "Sporting CP match originally scheduled for October 13, 2026 at 12:45 PM ET."
    ),
)
SCORE = {
    "readable": True,
    "subject": "racing_club_de_lens_vs_sporting_cp",
    "measured_by": "official_match_result",
    "observed_on": "2026-10-13",
    "comparison": "eq",
    "threshold": "1",
    "unit": "indicator",
}


def reading(measure, evidence):
    return SCORE | {"measure": measure, "evidence": evidence}


# 5: the score-order check


def test_5_a_polymarket_score_read_in_the_wrong_order_is_rejected():
    wrong = checks.accept(reading("final_score_4_1", "Racing Club de Lens 1 - 4 Sporting CP"), POLY)
    assert wrong.terms is None and "1-4" in wrong.problem
    right = checks.accept(reading("final_score_1_4", "Racing Club de Lens 1 - 4 Sporting CP"), POLY)
    assert right.terms is not None


def test_5_kalshi_score_fields_decide_its_order():
    wrong = checks.accept(reading("final_score_1_4", "Racing Club De Lens wins 4-1"), KALSHI)
    assert wrong.terms is None and "4-1" in wrong.problem
    assert checks.accept(reading("final_score_4_1", "Racing Club De Lens wins 4-1"), KALSHI).terms


def test_5_a_measure_that_is_not_a_score_is_not_checked_for_order():
    record = SCORE | {"measure": "named_top_2_2026", "evidence": "Racing Club de Lens 1 - 4"}
    assert checks.accept(record, POLY).terms is not None


# 1: raw and guarded


class Answers:
    """Answers each request with fixed records, in the markets' order."""

    def __init__(self, *records):
        self.records = records

    def __call__(self, body):
        markets = json.loads(body["messages"][0]["content"])["markets"]
        listed = [{"id": m["id"], **r} for m, r in zip(markets, self.records, strict=True)]
        return {
            "content": [{"type": "tool_use", "name": "record_terms", "input": {"markets": listed}}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }


def test_1_a_misread_the_checks_reject_is_a_raw_false_same_bet_but_not_a_guarded_one():
    case = evals.Case("Lens 4-1", [KALSHI, POLY], {(KALSHI.market_id, POLY.market_id): False})
    misread = Answers(
        reading("final_score_4_1", "Racing Club De Lens wins 4-1"),
        reading("final_score_4_1", "Racing Club de Lens 1 - 4 Sporting CP"),
    )
    score = evals.score([case], misread, "claude-haiku-5-5")
    assert (score.raw_false_same, score.false_same) == (1, 0)
    assert score.rejected == 1 and score.raw_same_found == 1


def test_1_a_correct_reading_is_right_both_ways():
    case = evals.Case("Lens 4-1", [KALSHI, POLY], {(KALSHI.market_id, POLY.market_id): False})
    right = Answers(
        reading("final_score_4_1", "Racing Club De Lens wins 4-1"),
        reading("final_score_1_4", "Racing Club de Lens 1 - 4 Sporting CP"),
    )
    score = evals.score([case], right, "claude-haiku-5-5")
    assert (score.raw_false_same, score.false_same, score.rejected) == (0, 0, 0)


# 2: bounds


def test_2_the_bound_says_how_little_a_small_clean_set_shows():
    assert abs(evals.upper_bound(0, 7) - 0.348) < 0.001
    assert evals.upper_bound(0, 300) < 0.01
    assert evals.upper_bound(0, 0) == 1.0  # no different pairs: nothing is shown
    assert 0.05 < evals.upper_bound(3, 100) < 0.09


def test_2_each_score_carries_its_bounds():
    case = evals.Case("Lens 4-1", [KALSHI, POLY], {(KALSHI.market_id, POLY.market_id): False})
    right = Answers(
        reading("final_score_4_1", "Racing Club De Lens wins 4-1"),
        reading("final_score_1_4", "Racing Club de Lens 1 - 4 Sporting CP"),
    )
    score = asdict(evals.score([case], right, "claude-haiku-5-5"))
    assert score["different_labelled"] == 1
    assert score["false_same_bound"] == score["raw_false_same_bound"] == "95.0%"


# 3: traps


def test_3_the_traps_are_the_seven_reversed_scores():
    cases = evals.labelled_cases(evals.TRAPS)
    assert len(cases) == 7 and all(c.name.startswith("Reversed score") for c in cases)
    assert not any(same for c in cases for same in c.labels.values())


# 4: the larger score set


def test_4_the_score_set_is_split_by_match_and_labelled_by_the_parsers():
    items = json.loads(evals.SCORE_PAIRS.read_text(encoding="utf-8"))
    halves = {half: {i["match"] for i in items if i["half"] == half} for half in ("tune", "judge")}
    assert halves["tune"] and halves["judge"] and not halves["tune"] & halves["judge"]
    for item in items:
        keys = {m["market_id"]: m["terms_key"] for m in item["markets"]}
        assert len(keys) <= 20
        for a, b, same in item["labels"]:
            assert same == (keys[a] == keys[b])
    tune, judge = evals.score_pair_cases("tune"), evals.score_pair_cases("judge")
    assert len(tune) + len(judge) == len(items)
    assert sum(sum(c.labels.values()) for c in judge) > 0


# 7: every set replays as recorded


def test_7_every_new_set_replays_as_recorded():
    scores = json.loads(evals.SCORES.read_text(encoding="utf-8"))
    sets = {
        "traps": evals.labelled_cases(evals.TRAPS),
        "score_tune": evals.score_pair_cases("tune"),
        "score_judge": evals.score_pair_cases("judge"),
    }
    for name, cases in sets.items():
        assert asdict(evals.score(cases, evals.Recorded(), scores["model"])) == scores[name]
        assert scores[name]["false_same"] == 0, f"{name} has a guarded false same-bet"
