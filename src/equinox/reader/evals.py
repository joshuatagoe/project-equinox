"""Scoring the term reader against gold labels (D58): `python -m equinox.reader.evals`.

Three gold sets:

- **Fed.** Every cross-venue pair of the meetings both venues list in `snapshot-2026-10-11`. The
  answer for each pair is what the Fed parsers' terms decide, so these labels cost nothing.
- **Labelled pairs** (`evals/pairs.json`). Catalog pairs a person labelled same or different after
  reading both venues' rules, including the traps titles fall for. The prompt was tuned on them.
- **Held-out pairs** (`evals/heldout.json`). Labelled the same way after the prompt was tuned, from
  series the labelled pairs don't use, and run once: the honest measure.

Each case is one request, read and decided exactly as `catalog read` does it. The score counts
false same-bets (a same bet the label says is different: the number that must be zero before a
model-read pair may be routed), missed same-bets and rejected readings.

Run live, it reads through the cache and, with `--record`, saves every answer to
`evals/recorded.json` and the scores to `evals/scores.json`. The tests replay the recorded answers
offline, so CI never calls the model and a changed prompt fails until it is evaluated again.
"""

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from equinox.adapters.fetch import DEFAULT_SNAPSHOT
from equinox.catalog.readings import PairToRead
from equinox.matcher import evaluate_pair
from equinox.models import CanonicalMarket, EquivalenceStatus
from equinox.models.catalog import SAME_BET, MarketText, ReadableMarket
from equinox.reader import client, prompt, run
from equinox.reader.client import Ask
from equinox.sources import CACHE_DIR, Settings, load_markets

EVALS = Path(__file__).resolve().parents[3] / "evals"
PAIRS, HELD_OUT = EVALS / "pairs.json", EVALS / "heldout.json"
RECORDED, SCORES = EVALS / "recorded.json", EVALS / "scores.json"
FED_SNAPSHOT = DEFAULT_SNAPSHOT.parent / "snapshot-2026-10-11"


@dataclass
class Case:
    """One request: its markets, and the label of each pair among them (True: the same bet)."""

    name: str
    markets: list[ReadableMarket]
    labels: dict[tuple[str, str], bool]


@dataclass
class Score:
    cases: int = 0
    pairs: int = 0
    same_labelled: int = 0
    same_found: int = 0
    false_same: int = 0
    missed_same: int = 0
    readings: int = 0
    rejected: int = 0
    mistakes: list[str] = field(default_factory=list)


def fed_cases() -> list[Case]:
    """One case per meeting both venues list, labelled by the Fed parsers' own terms."""
    loaded = load_markets(Settings(source="fixtures", snapshot=FED_SNAPSHOT), with_books=False)
    meetings: dict[str, list[CanonicalMarket]] = {}
    for market in loaded.markets:
        if market.terms is not None:
            meetings.setdefault(str(market.terms.observed_on), []).append(market)
    cases = []
    for day, markets in sorted(meetings.items()):
        if len({m.venue for m in markets}) < 2:
            continue
        labels = {
            (a.market_id, b.market_id): evaluate_pair(a, b).status == EquivalenceStatus.EQUIVALENT
            for a in markets
            for b in markets
            if a.venue < b.venue
        }
        cases.append(Case(f"Fed {day}", [_readable(m) for m in markets], labels))
    return cases


def labelled_cases(path: Path = PAIRS) -> list[Case]:
    """One case per labelled catalog pair."""
    cases = []
    for item in json.loads(path.read_text(encoding="utf-8")):
        a, b = _from_json(item["a"]), _from_json(item["b"])
        same = item["label"] == "same"
        cases.append(Case(item["name"], [a, b], {(a.market_id, b.market_id): same}))
    return cases


def score(cases: Sequence[Case], ask: Ask, model: str) -> Score:
    """Read and decide every case as `catalog read` would, and count against the labels."""
    total = Score()
    for case in cases:
        call = run.Call({m.market_id: m for m in case.markets})
        call.pairs = [PairToRead(a, b, 0) for a, b in case.labels]
        got = run.check_answer(call, ask(prompt.request(case.markets, model)))
        total.cases += 1
        total.readings += len(got)
        total.rejected += sum(r.terms is None for r in got.values())
        for pair in call.pairs:
            reader = f"{model} (prompt {prompt.PROMPT_VERSION})"
            same = run.decide_pair(pair, got, call, reader).status == SAME_BET
            _count(total, case.name, (pair.a, pair.b), same, case.labels[(pair.a, pair.b)])
    return total


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m equinox.reader.evals")
    parser.add_argument("--model", default=prompt.MODEL)
    parser.add_argument("--record", action="store_true", help="save the answers and scores")
    args = parser.parse_args(argv)
    key = client.load_key(os.environ)
    if key is None:
        print(f"No {client.KEY_NAME}; nothing was read.")
        return 1
    live = Recording(client.Cached(client.Claude(key), CACHE_DIR / "readings.sqlite"))
    scores = {
        "fed": score(fed_cases(), live, args.model),
        "labelled": score(labelled_cases(), live, args.model),
        "held_out": score(labelled_cases(HELD_OUT), live, args.model),
    }
    for name, result in scores.items():
        print(f"{name}: {json.dumps(asdict(result), indent=2)}")
    if args.record:
        RECORDED.write_text(json.dumps(live.answers, indent=1, sort_keys=True), encoding="utf-8")
        report = {"model": args.model, "prompt": prompt.PROMPT_VERSION}
        report |= {name: asdict(result) for name, result in scores.items()}
        SCORES.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


def _count(total: Score, case: str, pair: tuple[str, str], same: bool, labelled: bool) -> None:
    total.pairs += 1
    total.same_labelled += labelled
    total.same_found += same
    if same and not labelled:
        total.false_same += 1
        total.mistakes.append(f"{case}: {pair[0]} ~ {pair[1]} read as the same bet")
    elif labelled and not same:
        total.missed_same += 1
        total.mistakes.append(f"{case}: {pair[0]} ~ {pair[1]} not read as the same bet")


def _readable(market: CanonicalMarket) -> ReadableMarket:
    return ReadableMarket(
        market.market_id,
        market.venue,
        "",
        market.title,
        market.outcome_label,
        market.trading_closes_at,
        MarketText(market.rules_text),
    )


def _from_json(item: dict[str, Any]) -> ReadableMarket:
    closes = item.get("closes_at")
    return ReadableMarket(
        item["market_id"],
        item["venue"],
        item["event_title"],
        item["title"],
        item["outcome_label"],
        datetime.fromisoformat(closes) if closes else None,
        MarketText(item["rules"], item.get("strike", "")),
    )


if __name__ == "__main__":
    sys.exit(main())
