"""feat-10 test 8: the evals, replayed from the recorded answers, so CI never calls the model.

A live run (`python -m equinox.reader.evals --record`) saves every answer and the scores. Here the
same cases are read from that recording and decided again by today's code: the scores must be the
ones recorded, and no set may have a false same-bet, the bar for routing a model-read pair (D58).
A prompt or model change makes a request the recording doesn't have, so this fails until the evals
are run live again.
"""

import json
from dataclasses import asdict

import pytest

from equinox.reader import evals

SCORES = json.loads(evals.SCORES.read_text(encoding="utf-8"))
SETS = {
    "fed": evals.fed_cases,
    "labelled": evals.labelled_cases,
    "held_out": lambda: evals.labelled_cases(evals.HELD_OUT),
}


@pytest.mark.parametrize("name", SETS)
def test_8_the_recorded_answers_score_as_recorded_with_no_false_same_bet(name):
    score = evals.score(SETS[name](), evals.Recorded(), SCORES["model"])
    assert asdict(score) == SCORES[name]
    assert score.false_same == 0


def test_8_the_recording_is_for_this_prompt():
    from equinox.reader.prompt import PROMPT_VERSION

    assert SCORES["prompt"] == PROMPT_VERSION
