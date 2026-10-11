"""The command line: markets, match and simulate (architecture section 8.2).

Arguments, output and exit codes only. Markets are loaded by `equinox.sources`, which the web UI
uses too. Exit codes follow the routing status (D27).
"""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from equinox import cli_catalog, sources
from equinox.adapters.base import TRACKED_EVENTS, FetchError
from equinox.matcher import build_clusters, cluster_confidence, cluster_for, text_matches
from equinox.models import (
    EXIT_CODES,
    CanonicalMarket,
    ContractTerms,
    EquinoxTrace,
    EquivalenceStatus,
    MatchResult,
    OrderRequest,
    RoutingStatus,
)
from equinox.reader.client import Ask
from equinox.reader.prompt import MODEL
from equinox.router import failure_trace, simulate
from equinox.router.rationale import contracts, dollars, money_step
from equinox.sources import ADAPTERS, LiveFetchers, Loaded, Settings, SettingsError

__all__ = ["ADAPTERS", "Loaded", "LiveFetchers", "Settings", "load_markets", "main"]

_WORDS = {"gt": "above", "ge": "at or above", "lt": "below", "le": "at or below", "eq": "exactly"}


class _UsageError(Exception):
    """Bad arguments or settings: INVALID_INPUT, exit 4, never argparse's own exit 2."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # argparse would exit 2, which means INSUFFICIENT_LIQUIDITY
        raise _UsageError(message)


def main(
    argv: Sequence[str] | None = None,
    *,
    live_fetcher: LiveFetchers | None = None,
    ask: Ask | None = None,
) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    try:
        args = _parser().parse_args(argv)
        settings = Settings.from_env(os.environ)
        if args.source:
            settings = replace(settings, source=args.source)
        if args.snapshot:
            settings = replace(settings, snapshot=sources.snapshot_path(args.snapshot))
        if settings.source not in ("live", "fixtures"):
            raise _UsageError(f"--source must be live or fixtures, not {settings.source!r}")
    except (_UsageError, SettingsError) as error:
        trace = failure_trace(RoutingStatus.INVALID_INPUT, str(error), now=datetime.now(UTC))
        return _print_trace(trace, as_json)
    if args.command == "catalog":
        return cli_catalog.command(args, settings, live_fetcher, ask)
    # Books are fetched later, only for the group being priced (D49).
    loaded = sources.load_markets(settings, live_fetcher, tracked=TRACKED_EVENTS, with_books=False)
    if args.command == "markets":
        return _markets(loaded, args.json)
    if args.command == "match":
        return _match(loaded, args.json, settings if args.catalog else None)
    return _simulate(args, settings, loaded)


def load_markets(settings: Settings, live_fetcher: LiveFetchers | None = None) -> Loaded:
    """`sources.load_markets`, reading this module's TRACKED_EVENTS so tests can repoint it."""
    return sources.load_markets(settings, live_fetcher, tracked=TRACKED_EVENTS)


# Commands.


def _markets(loaded: Loaded, as_json: bool) -> int:
    if as_json:
        markets = [m.model_dump(mode="json") for m in loaded.markets]
        print(json.dumps({"markets": markets, "warnings": loaded.warnings}, indent=2))
        return 0
    width = max((len(m.market_id) for m in loaded.markets), default=0)
    for m in loaded.markets:
        tradable = "tradable" if m.tradable else "not tradable"
        print(f"{m.market_id:<{width}}  {_terms(m.terms)}  {tradable}  {_best_asks(m)}")
    _print_warnings(loaded.warnings)
    return 0


def _match(loaded: Loaded, as_json: bool, catalog: Settings | None) -> int:
    """The groups of equivalent markets; with `catalog`, also the catalog's unclear pairs."""
    clusters = build_clusters(loaded.markets)
    ambiguous = _unique([r for c in clusters for r in c.ambiguous])
    ambiguous += [
        r for r in text_matches(loaded.markets) if r.status == EquivalenceStatus.AMBIGUOUS
    ]
    if as_json:
        report = {
            "clusters": [c.model_dump(mode="json") for c in clusters],
            "ambiguous": [r.model_dump(mode="json") for r in ambiguous],
            "warnings": loaded.warnings,
        }
        if catalog:
            report["catalog"] = cli_catalog.as_json(catalog)
        print(json.dumps(report, indent=2))
        return 0
    for cluster in clusters:
        print(f"{cluster.cluster_id}: {', '.join(m.market_id for m in cluster.markets)}")
        level = cluster_confidence(cluster)
        print(f"  Confidence: {level.level or 'none'}. {level.reason}")
        for flag in cluster.risk_flags:
            print(f"  Risk: {flag}")
    if ambiguous:
        print("\nAmbiguous pairs (shown, never routed):")
        for result in ambiguous:
            print(f"  {result.market_a} ~ {result.market_b}: {' '.join(result.reasons)}")
    _print_warnings(loaded.warnings)
    if catalog:
        print()
        return cli_catalog.unclear_pairs(catalog)
    return 0


def _simulate(args: argparse.Namespace, settings: Settings, loaded: Loaded) -> int:
    now = datetime.now(UTC)
    try:
        order = OrderRequest(
            market_id=args.market,
            outcome=args.outcome.upper(),
            quantity=Decimal(args.quantity),
            max_budget=None if args.budget is None else Decimal(args.budget),
        )
    except (ValidationError, InvalidOperation) as error:
        trace = failure_trace(RoutingStatus.INVALID_INPUT, _one_line(error), now=now)
        return _print_trace(trace, args.json)

    market = next((m for m in loaded.markets if m.market_id == order.market_id), None)
    cluster = cluster_for(order.market_id, build_clusters(loaded.markets))
    if market is None or cluster is None:
        message = (
            f"{order.market_id} is not among the loaded markets."
            if market is None
            else f"{order.market_id} has no contract terms: this market can only be matched by "
            "text, so it is never routed."
        )
        trace = failure_trace(RoutingStatus.MARKET_NOT_FOUND, message, order, now=now)
    else:
        trace = _route(order, cluster, loaded, settings, now)
    trace = trace.model_copy(update={"warnings": (*loaded.warnings, *trace.warnings)})
    return _print_trace(trace, args.json)


def _route(order: OrderRequest, cluster, loaded: Loaded, settings: Settings, now) -> EquinoxTrace:
    """Fetch the group's books, then simulate; a venue whose books can't be read is reported."""
    try:
        booked = sources.ensure_books(cluster, loaded)
    except FetchError as error:
        message = f"the order books for {order.market_id}'s group couldn't be read ({error})."
        return failure_trace(RoutingStatus.MARKET_NOT_FOUND, message, order, now=now)
    return simulate(order, booked, now, settings.stale_after)


# Output.


def _print_trace(trace: EquinoxTrace, as_json: bool) -> int:
    print(trace.model_dump_json(indent=2) if as_json else _report(trace))
    return EXIT_CODES[trace.status]


def _report(trace: EquinoxTrace) -> str:
    lines = [f"{trace.status} (exit {EXIT_CODES[trace.status]})"]
    if trace.order:
        order = trace.order
        budget = f", budget ${order.max_budget}" if order.max_budget is not None else ""
        lines.append(
            f"Order: buy {contracts(order.quantity)} {order.outcome} on {order.market_id}{budget}"
        )
    if trace.cluster:
        lines.append(f"Cluster: {', '.join(m.market_id for m in trace.cluster.markets)}")
        lines += [f"  Risk: {flag}" for flag in trace.cluster.risk_flags]
    if trace.quotes:
        lines += ["", *_quote_table(trace)]
    lines += ["", trace.rationale]
    if trace.warnings:
        lines += ["", "Warnings:", *(f"  - {warning}" for warning in trace.warnings)]
    return "\n".join(lines)


def _quote_table(trace: EquinoxTrace) -> list[str]:
    quotes = sorted(trace.quotes, key=lambda q: (not q.eligible, q.total_cost, q.market_id))
    step = money_step([q.total_cost for q in quotes if q.filled_quantity])
    rows = [("Venue", "Market", "Eligible", "Filled", "Avg price", "Fee", "Total", "Reasons")]
    for q in quotes:
        average = "-" if q.average_price is None else f"{q.average_price:.4f}"
        rows.append(
            (
                q.venue.capitalize(),
                q.market_id,
                "yes" if q.eligible else "no",
                contracts(q.filled_quantity),
                average,
                dollars(q.fee, step),
                dollars(q.total_cost, step),
                ", ".join(q.reasons) or "-",
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return [
        "  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip()
        for row in rows
    ]


def _terms(terms: ContractTerms | None) -> str:
    if terms is None:
        return "no terms (text match only)"
    bound = f"{_WORDS.get(terms.comparison, terms.comparison)} {terms.threshold}"
    if terms.upper is not None:
        bound = f"between {terms.threshold} and {terms.upper}"
    return f"{terms.subject} {terms.measure} {bound} {terms.unit} on {terms.observed_on}"


def _best_asks(market: CanonicalMarket) -> str:
    asks = [f"{side} ask {market.best_asks.get(side) or 'none'}" for side in ("YES", "NO")]
    return ", ".join(asks)


def _print_warnings(warnings: list[str]) -> None:
    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"  - {warning}")


def _unique(results: list[MatchResult]) -> list[MatchResult]:
    seen: dict[frozenset[str], MatchResult] = {}
    for result in results:
        seen.setdefault(frozenset((result.market_a, result.market_b)), result)
    return list(seen.values())


def _one_line(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors())
    return f"not a number: {error}"


def _parser() -> _Parser:
    parser = _Parser(prog="python -m equinox", description="Compare prediction-market venues.")
    common = _Parser(add_help=False)
    common.add_argument(
        "--source", choices=("live", "fixtures"), help="default: EQUINOX_SOURCE or live"
    )
    common.add_argument("--snapshot", help="a folder in src/equinox/fixtures (D51)")
    common.add_argument("--json", action="store_true", help="print JSON instead of a report")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("markets", parents=[common], help="list canonical markets")
    match = commands.add_parser("match", parents=[common], help="group equivalent markets")
    match.add_argument("--catalog", action="store_true", help="add the catalog's unclear pairs")
    every = commands.add_parser("catalog", help="every open market on both venues (D48)")
    actions = every.add_subparsers(dest="action", required=True)
    actions.add_parser("refresh", parents=[common], help="read and compare every open market")
    actions.add_parser("status", parents=[common], help="the saved catalog's age and counts")
    read = actions.add_parser("read", parents=[common], help="read unclear pairs' terms (D57)")
    read.add_argument("--limit", type=int, required=True, help="the most markets to read")
    read.add_argument("--model", default=MODEL, help=f"default: {MODEL}")
    read.add_argument("--workers", type=int, default=4, help="requests at once (default: 4)")
    order = commands.add_parser("simulate", parents=[common], help="route a hypothetical order")
    order.add_argument("--market", required=True, help="e.g. kalshi:KXFEDDECISION-26OCT-H0")
    order.add_argument("--outcome", required=True, help="YES or NO")
    order.add_argument("--quantity", required=True, help="contracts, > 0")
    order.add_argument("--budget", help="the most the order may cost, in dollars")
    return parser
