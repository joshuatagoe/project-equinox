"""Scoring the term reader against gold labels (D58): `python -m equinox.reader.evals`.

The gold sets are in `gold.py`. Each case is one request, read and decided exactly as `catalog
read` does it, and scored twice (feat-12):

- **Guarded**: from the readings the checks accept, which is what can route. A false same-bet here
  (a same bet the label says is different) must be zero on every set before a model-read pair may
  be routed.
- **Raw**: from every reading that forms valid terms, before the checks. It says how often the model
  alone is right, apart from what the checks catch.

Each false same-bet rate also gets a one-sided 95% upper bound (Clopper-Pearson) over the pairs
labelled different, so a small clean set reads as what it shows: 0 of 7 is "under 34.8%".

Run live, it reads through the cache and, with `--record`, saves every answer to
`evals/recorded.json` and the scores to `evals/scores.json`. The tests replay the recorded answers
offline, so CI never calls the model and a changed prompt fails until it is evaluated again.
"""

import argparse
import hashlib
import json
import math
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from equinox.catalog.readings import PairToRead
from equinox.models.catalog import SAME_BET
from equinox.reader import client, prompt, run
from equinox.reader.client import Ask
from equinox.reader.gold import (  # re-exported: the sets are named from here too
    EVALS,
    HELD_OUT,
    PAIRS,
    SCORE_PAIRS,
    TRAPS,
    Case,
    fed_cases,
    labelled_cases,
    score_cases,
    score_pair_cases,
)
from equinox.sources import CACHE_DIR

__all__ = ["EVALS", "HELD_OUT", "PAIRS", "SCORE_PAIRS", "TRAPS", "Case", "Score", "score"]
__all__ += ["fed_cases", "labelled_cases", "score_cases", "score_pair_cases", "upper_bound"]

RECORDED, SCORES = EVALS / "recorded.json", EVALS / "scores.json"
CONFIDENCE = 0.95


@dataclass
class Score:
    cases: int = 0
    pairs: int = 0
    same_labelled: int = 0
    different_labelled: int = 0
    same_found: int = 0  # guarded: from the readings the checks accept
    false_same: int = 0
    missed_same: int = 0
    readings: int = 0
    rejected: int = 0
    false_same_bound: str = ""  # 95% upper bound on false same-bets over pairs labelled different
    raw_same_found: int = 0  # raw: from every reading that forms valid terms
    raw_false_same: int = 0
    raw_missed_same: int = 0
    raw_false_same_bound: str = ""
    mistakes: list[str] = field(default_factory=list)  # guarded; raw ones say "before the checks"


def score(cases: Sequence[Case], ask: Ask, model: str) -> Score:
    """Read and decide every case as `catalog read` would, and count against the labels."""
    total = Score()
    reader = f"{model} (prompt {prompt.PROMPT_VERSION})"
    for case in cases:
        call = run.Call({m.market_id: m for m in case.markets})
        call.pairs = [PairToRead(a, b, 0) for a, b in case.labels]
        answer = ask(prompt.request(case.markets, model))
        guarded, raw = run.check_answer(call, answer), run.unchecked_answer(call, answer)
        total.cases += 1
        total.readings += len(guarded)
        total.rejected += sum(r.terms is None for r in guarded.values())
        for pair in call.pairs:
            labelled = case.labels[(pair.a, pair.b)]
            same = run.decide_pair(pair, guarded, call, reader).status == SAME_BET
            raw_same = run.decide_pair(pair, raw, call, reader).status == SAME_BET
            _count(total, f"{case.name}: {pair.a} ~ {pair.b}", same, raw_same, labelled)
    total.false_same_bound = _percent(upper_bound(total.false_same, total.different_labelled))
    total.raw_false_same_bound = _percent(
        upper_bound(total.raw_false_same, total.different_labelled)
    )
    return total


def upper_bound(found: int, trials: int, confidence: float = CONFIDENCE) -> float:
    """The one-sided upper bound on a rate seen `found` times in `trials` (Clopper-Pearson): the
    largest rate under which so few would be seen at least 5% of the time. 1.0 with no trials."""
    if trials == 0 or found >= trials:
        return 1.0
    low, high = found / trials, 1.0
    for _ in range(60):
        middle = (low + high) / 2
        if _at_most(found, trials, middle) > 1 - confidence:
            low = middle
        else:
            high = middle
    return high


class Recorded:
    """Answers recorded by a live run, looked up by request; a request never recorded fails."""

    def __init__(self, path: Path = RECORDED) -> None:
        self.answers = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        key = request_key(body)
        if key not in self.answers:
            raise KeyError("this request was never recorded: run the evals live with --record")
        return self.answers[key]


class Recording:
    """A live model whose answers are kept, to save as the recording."""

    def __init__(self, ask: Ask) -> None:
        self.ask, self.answers = ask, {}

    def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        answer = self.ask(body)
        self.answers[request_key(body)] = answer
        return answer


def request_key(body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()


def every_set() -> dict[str, list[Case]]:
    return {
        "fed": fed_cases(),
        "labelled": labelled_cases(),
        "held_out": labelled_cases(HELD_OUT),
        "scores": score_cases(),
        "traps": labelled_cases(TRAPS),
        "score_tune": score_pair_cases("tune"),
        "score_judge": score_pair_cases("judge"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m equinox.reader.evals")
    parser.add_argument("--model", default=prompt.MODEL)
    parser.add_argument("--record", action="store_true", help="save the answers and scores")
    args = parser.parse_args(argv)
    key = client.load_key(os.environ)
    if key is None:
        print(f"No {client.KEY_NAME}; nothing was read.")
        return 1
    cached = client.Cached(client.Claude(key), CACHE_DIR / "readings.sqlite")
    live = Recording(cached)
    scores = {name: score(cases, live, args.model) for name, cases in every_set().items()}
    for name, s in scores.items():
        print(
            f"{name}: guarded {s.false_same} false of {s.different_labelled} (under "
            f"{s.false_same_bound}), {s.same_found}/{s.same_labelled} same found; raw "
            f"{s.raw_false_same} false (under {s.raw_false_same_bound}), "
            f"{s.raw_same_found}/{s.same_labelled} found; {s.rejected} readings rejected"
        )
    print(f"Spent {cached.input_tokens:,} input and {cached.output_tokens:,} output tokens.")
    if args.record:
        RECORDED.write_text(json.dumps(live.answers, indent=1, sort_keys=True), encoding="utf-8")
        report = {"model": args.model, "prompt": prompt.PROMPT_VERSION}
        report |= {name: asdict(result) for name, result in scores.items()}
        SCORES.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


def _count(total: Score, pair: str, same: bool, raw_same: bool, labelled: bool) -> None:
    total.pairs += 1
    total.same_labelled += labelled
    total.different_labelled += not labelled
    total.same_found += same
    total.raw_same_found += raw_same
    if same and not labelled:
        total.false_same += 1
        total.mistakes.append(f"{pair} read as the same bet")
    elif labelled and not same:
        total.missed_same += 1
        total.mistakes.append(f"{pair} not read as the same bet")
    if raw_same and not labelled:
        total.raw_false_same += 1
        total.mistakes.append(f"{pair} read as the same bet before the checks")
    elif labelled and not raw_same:
        total.raw_missed_same += 1


def _at_most(found: int, trials: int, rate: float) -> float:
    """P(X <= found) for X ~ Binomial(trials, rate)."""
    return sum(
        math.comb(trials, k) * rate**k * (1 - rate) ** (trials - k) for k in range(found + 1)
    )


def _percent(rate: float) -> str:
    return f"{rate * 100:.1f}%"


if __name__ == "__main__":
    sys.exit(main())
