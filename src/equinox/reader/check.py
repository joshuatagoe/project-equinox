"""The model as a cross-check of the parsers (D60, D64): `catalog check --limit N`.

The catalog keeps the parsers' pairs: the same bets their terms found, and the pairs their terms
make different although the titles alone would have left them unclear. The check reads those
pairs' markets with the model exactly as `catalog read` reads unclear pairs (`run.py`), decides
them with the same rules, and lists every pair the model and the parsers decide differently.

It changes nothing in the catalog. A disagreement is a lead for a person: usually a venue that
reworded its markets, or a team name the alias table lacks (D62). A pair the model leaves unclear,
or whose reading the checks reject, is counted as undecided, not as a disagreement.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from equinox.catalog import Catalog, readings
from equinox.catalog.readings import DIFFERENT
from equinox.models.catalog import SAME_BET
from equinox.reader import prompt, run
from equinox.reader.client import Ask


@dataclass(frozen=True)
class Disagreement:
    a: str
    b: str
    parser: str  # SAME_BET or DIFFERENT
    model: str  # the other one
    reasons: tuple[str, ...]  # the model's


@dataclass
class CheckReport:
    calls: int = 0
    markets: int = 0
    pairs: int = 0
    agree: int = 0
    undecided: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    disagreements: list[Disagreement] = field(default_factory=list)


def check_catalog(
    found: Catalog,
    ask: Ask,
    model: str,
    limit: int,
    progress: Callable[[str], None] = lambda line: None,
    workers: int = 1,
) -> CheckReport:
    """Read at most `limit` markets of the parsers' pairs, and compare the decisions."""
    reader = f"{model} (prompt {prompt.PROMPT_VERSION})"
    pairs, markets, by_parser = readings.to_check(found)
    calls = run.plan(pairs, markets, limit)
    report = CheckReport()
    requests = (prompt.request(list(call.markets.values()), model) for call in calls)
    with ThreadPoolExecutor(max(workers, 1)) as pool:
        answers = zip(calls, pool.map(ask, requests), strict=True)
        for number, (call, answer) in enumerate(answers, start=1):
            got = run.check_answer(call, answer)
            for pair in call.pairs:
                decided = run.decide_pair(pair, got, call, reader)
                _compare(report, by_parser[(pair.a, pair.b)], decided)
            used_in, used_out = prompt.usage(answer)
            report.calls, report.markets = report.calls + 1, report.markets + len(call.markets)
            report.input_tokens += used_in
            report.output_tokens += used_out
            if number % 10 == 0 or number == len(calls):
                progress(f"{number} of {len(calls)} requests, {report.markets:,} markets read")
    return report


def _compare(report: CheckReport, parser: str, decided: readings.PairDecision) -> None:
    report.pairs += 1
    if decided.status not in (SAME_BET, DIFFERENT):
        report.undecided += 1
    elif decided.status == parser:
        report.agree += 1
    else:
        found = Disagreement(decided.a, decided.b, parser, decided.status, decided.reasons)
        report.disagreements.append(found)
