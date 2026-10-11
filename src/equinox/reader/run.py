"""Reading the catalog's unclear pairs with a model, and deciding them with the rules (D57).

1. **Plan.** The unclear pairs, most similar first, grouped by the event of their first market. A
   group's markets, at most 20, go in one request, so the model names both sides alike. Groups
   are taken until the next would pass the market limit.
2. **Read.** Each request goes to the model, through the cache; `workers` requests run at once.
3. **Check.** Every record goes through `checks.accept`, which can only reject.
4. **Decide.** A pair whose two markets were accepted in the same request goes through the terms
   rules: EQUIVALENT is the same bet, DISTINCT a different bet, AMBIGUOUS stays unclear. A pair
   with a rejected market stays unclear, with the reason.
5. **Record.** The readings and decisions go into the catalog file.
"""

from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from equinox.catalog import Catalog, readings
from equinox.catalog.readings import DIFFERENT, PairDecision, PairToRead, ReadingRow
from equinox.matcher.terms import decide
from equinox.models import EquivalenceStatus
from equinox.models.catalog import SAME_BET, UNCLEAR, ReadableMarket
from equinox.reader import checks, prompt
from equinox.reader.checks import Reading
from equinox.reader.client import Ask

GROUP_SIZE = 20
_STATUSES = {
    EquivalenceStatus.EQUIVALENT: SAME_BET,
    EquivalenceStatus.DISTINCT: DIFFERENT,
    EquivalenceStatus.AMBIGUOUS: UNCLEAR,
}


@dataclass
class ReadReport:
    calls: int = 0
    markets: int = 0
    accepted: int = 0
    rejected: int = 0
    same_bet: int = 0
    different: int = 0
    unclear: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Call:
    """One request: the markets it reads, and the pairs among them it decides."""

    markets: dict[str, ReadableMarket] = field(default_factory=dict)
    pairs: list[PairToRead] = field(default_factory=list)


def read_catalog(
    found: Catalog,
    ask: Ask,
    model: str,
    limit: int,
    progress: Callable[[str], None] = lambda line: None,
    workers: int = 1,
) -> ReadReport:
    """Read at most `limit` markets of the catalog's unclear pairs and record what they decide."""
    reader = f"{model} (prompt {prompt.PROMPT_VERSION})"
    pairs, markets = readings.to_read(found, reader)
    calls = plan(pairs, markets, limit)
    report, rows, decisions = ReadReport(), [], []
    requests = (prompt.request(list(call.markets.values()), model) for call in calls)
    with ThreadPoolExecutor(max(workers, 1)) as pool:
        answers = zip(calls, pool.map(ask, requests), strict=True)
        for number, (call, answer) in enumerate(answers, start=1):
            got = check_answer(call, answer)
            rows += [_row(reading, number) for reading in got.values()]
            decisions += [decide_pair(pair, got, call, reader) for pair in call.pairs]
            _count(report, call, got, answer)
            if number % 10 == 0 or number == len(calls):
                progress(f"{number} of {len(calls)} requests, {report.markets:,} markets read")
    for decision in decisions:
        report.same_bet += decision.status == SAME_BET
        report.different += decision.status == DIFFERENT
        report.unclear += decision.status == UNCLEAR
    readings.record(found, model, prompt.PROMPT_VERSION, rows, decisions)
    return report


def plan(pairs: Sequence[PairToRead], markets: dict[str, ReadableMarket], limit: int) -> list[Call]:
    """The requests that read the best pairs first, up to `limit` markets in all."""
    by_event: dict[tuple[str, str], list[PairToRead]] = {}
    for pair in pairs:
        if pair.a in markets and pair.b in markets:
            first = markets[pair.a]
            by_event.setdefault((first.venue, first.event_title), []).append(pair)
    calls, total = [], 0
    for event_pairs in by_event.values():
        for call in _chunks(event_pairs, markets):
            if total + len(call.markets) > limit:
                return calls
            calls.append(call)
            total += len(call.markets)
    return calls


def _chunks(pairs: list[PairToRead], markets: dict[str, ReadableMarket]) -> Iterator[Call]:
    call = Call()
    for pair in pairs:
        new = [m for m in (pair.a, pair.b) if m not in call.markets]
        if call.pairs and len(call.markets) + len(new) > GROUP_SIZE:
            yield call
            call, new = Call(), [pair.a, pair.b]
        call.markets.update({m: markets[m] for m in new})
        call.pairs.append(pair)
    if call.pairs:
        yield call


def check_answer(call: Call, answer: dict) -> dict[str, Reading]:
    records = prompt.answers(answer, list(call.markets.values()))
    return {m: checks.accept(records[m], market) for m, market in call.markets.items()}


def decide_pair(pair: PairToRead, got: dict[str, Reading], call: Call, reader: str) -> PairDecision:
    """`reader` names the model and prompt that read the pair, as recorded with the decision."""
    first, second = got[pair.a], got[pair.b]
    if first.terms is None or second.terms is None:
        problems = " ".join(r.problem for r in (first, second) if r.problem)
        return PairDecision(pair.a, pair.b, UNCLEAR, (f"Not decided: {problems}",), reader)
    names = (call.markets[pair.a].venue.capitalize(), call.markets[pair.b].venue.capitalize())
    decision = decide(first.terms, second.terms, names)
    note = f"Terms read by {reader} from both venues' texts; both readings passed the checks."
    reasons = (decision.reason, *decision.flags, note)
    return PairDecision(pair.a, pair.b, _STATUSES[decision.status], reasons, reader)


def _row(reading: Reading, call: int) -> ReadingRow:
    terms = reading.terms.model_dump_json() if reading.terms else None
    return ReadingRow(reading.market_id, call, terms, reading.problem, reading.evidence)


def _count(report: ReadReport, call: Call, got: dict[str, Reading], answer: dict) -> None:
    used_in, used_out = prompt.usage(answer)
    report.calls += 1
    report.markets += len(call.markets)
    report.accepted += sum(r.terms is not None for r in got.values())
    report.rejected += sum(r.terms is None for r in got.values())
    report.input_tokens += used_in
    report.output_tokens += used_out
