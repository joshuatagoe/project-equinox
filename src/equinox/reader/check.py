"""The model as a cross-check of the parsers (D60, D64): `catalog check --limit N`.

The catalog keeps the parsers' pairs: the same bets their terms found, and the pairs their terms
make different although the titles alone would have left them unclear. The check reads those
pairs' markets with the model exactly as `catalog read` reads unclear pairs (`run.py`), decides
them with the same rules, and lists every pair the model and the parsers decide differently. It
compares the model's own readings, before the checks (feat-12), so a misread the checks would
refuse still shows as a disagreement: the check measures the model, not what routes.

It changes nothing in the catalog. A disagreement is a lead for a person: usually a venue that
reworded its markets, a team name the alias table lacks (D62), or a model misread. A pair the model
leaves unclear, or whose reading doesn't form valid terms, is counted as undecided.

`drift` (`catalog check --drift`) is upkeep detection (feat-12): it reads only the markets a parser
family is meant to read but gave no terms, and says which the model still reads as that family (a
rewording the parser misses) and which it doesn't. Those markets stay unclear or unmatched.
"""

import re
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

from equinox.catalog import Catalog, readings
from equinox.catalog.readings import DIFFERENT
from equinox.models.catalog import SAME_BET, MarketText, ReadableMarket
from equinox.reader import prompt, run
from equinox.reader.checks import Reading
from equinox.reader.client import Ask


@dataclass(frozen=True)
class Disagreement:
    a: str
    b: str
    parser: str  # SAME_BET or DIFFERENT
    model: str  # the other one
    reasons: tuple[str, ...]  # the model's


# What a family's measure looks like when the model reads one of its markets.
FAMILY_MEASURES = {
    "exact_score": re.compile(r"score.*_\d+_\d+$"),
    "fed_decision": re.compile("fed"),
}
_FAMILY_MARKETS = (
    "SELECT e.market_id, e.venue, e.event_title, e.title, e.outcome_label, e.closes_at, t.rules, "
    "t.strike, e.family FROM entries e JOIN texts t ON t.market_id = e.market_id "
    "WHERE e.family != '' AND e.terms_key IS NULL ORDER BY e.rowid"
)


@dataclass(frozen=True)
class Candidate:
    market_id: str
    title: str
    family: str
    verdict: (
        str  # "looks like exact_score: the parser missed it", "not exact_score: ..." or "unread"
    )


@dataclass
class DriftReport:
    candidates: list[Candidate] = field(default_factory=list)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    problem: str = ""  # why nothing was read, such as a catalog that records no families


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
            got = run.unchecked_answer(call, answer)
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


def drift(
    found: Catalog,
    ask: Ask,
    model: str,
    limit: int,
    progress: Callable[[str], None] = lambda line: None,
    workers: int = 1,
) -> DriftReport:
    """Read at most `limit` markets a parser family gave no terms, and say what each looks like."""
    try:
        with found.connect() as db:
            rows = db.execute(_FAMILY_MARKETS).fetchall()
    except sqlite3.OperationalError:
        return DriftReport(problem="this catalog records no families: refresh it")
    families = {row[0]: row[8] for row in rows}
    calls = _groups([_readable(row) for row in rows], limit)
    report = DriftReport()
    requests = (prompt.request(list(call.markets.values()), model) for call in calls)
    with ThreadPoolExecutor(max(workers, 1)) as pool:
        for number, (call, answer) in enumerate(
            zip(calls, pool.map(ask, requests), strict=True), start=1
        ):
            got = run.unchecked_answer(call, answer)
            for market_id, market in call.markets.items():
                family = families[market_id]
                verdict = _verdict(family, got[market_id])
                report.candidates.append(Candidate(market_id, market.title, family, verdict))
            used_in, used_out = prompt.usage(answer)
            report.calls += 1
            report.input_tokens += used_in
            report.output_tokens += used_out
            progress(f"{number} of {len(calls)} requests")
    return report


def _groups(markets: list[ReadableMarket], limit: int) -> list[run.Call]:
    """The markets by event, at most `run.GROUP_SIZE` a request and `limit` in all."""
    calls: list[run.Call] = []
    current, event, total = run.Call(), None, 0
    for market in markets:
        if total == limit:
            break
        key = (market.venue, market.event_title)
        if current.markets and (key != event or len(current.markets) == run.GROUP_SIZE):
            calls.append(current)
            current = run.Call()
        current.markets[market.market_id] = market
        event, total = key, total + 1
    return calls + ([current] if current.markets else [])


def _verdict(family: str, reading: Reading) -> str:
    if reading.terms is None:
        return f"unread: {reading.problem}"
    pattern = FAMILY_MEASURES.get(family)
    if pattern and pattern.search(reading.terms.measure):
        return f"looks like {family}: the parser missed it"
    return f"not {family}: the model read {reading.terms.measure}"


def _readable(row: tuple) -> ReadableMarket:
    market_id, venue, event, title, label, closes, rules, strike, _family = row
    closes_at = datetime.fromisoformat(closes) if closes else None
    text = MarketText(rules, strike)
    return ReadableMarket(market_id, venue, event, title, label, closes_at, text)


def _compare(report: CheckReport, parser: str, decided: readings.PairDecision) -> None:
    report.pairs += 1
    if decided.status not in (SAME_BET, DIFFERENT):
        report.undecided += 1
    elif decided.status == parser:
        report.agree += 1
    else:
        found = Disagreement(decided.a, decided.b, parser, decided.status, decided.reasons)
        report.disagreements.append(found)
