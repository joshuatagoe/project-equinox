"""The web UI: three server-rendered pages built on the CLI's own functions (feat-07, D45).

The pages only present what the adapters, matcher and router decide. The UI adds no matching or
routing logic, and names venues only from each market's `venue` field.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs

from equinox.adapters.base import FetchError
from equinox.adapters.fetch import FixtureFetcher
from equinox.cli import LiveFetchers, Loaded, Settings, load_markets
from equinox.matcher import build_clusters, cluster_confidence, confidence, text_matches
from equinox.models import (
    CanonicalMarket,
    ContractTerms,
    EquinoxTrace,
    EquivalenceCluster,
    EquivalenceStatus,
    MatchResult,
    OrderRequest,
    QuoteReason,
    RoutingStatus,
)
from equinox.router import simulate
from equinox.router.rationale import CENT, contracts, dollars, money_step
from equinox.web import pages, words

SOURCES = ("snapshot", "live")
BOARD_ORDER = Decimal(100)
NOT_REAL = {QuoteReason.NOT_TRADABLE, QuoteReason.TEST_MONEY}
INCLUSIVE = ("eq", "le", "ge", "between")


@dataclass(frozen=True)
class Outcome:
    """One cluster, named for people."""

    cluster: EquivalenceCluster
    event: str
    name: str

    @property
    def key(self) -> str:
        return self.cluster.cluster_id


@dataclass
class View:
    """Everything one data source gives the pages, loaded once and shared."""

    source: str
    loaded: Loaded
    clusters: list[EquivalenceCluster]
    outcomes: list[Outcome]
    read_at: datetime

    @property
    def markets(self) -> dict[str, CanonicalMarket]:
        return {m.market_id: m for m in self.loaded.markets}


class App:
    def __init__(
        self,
        settings: Settings,
        *,
        live_fetcher: LiveFetchers | None = None,
        load: Callable[[str], Loaded] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        live_for: timedelta = timedelta(seconds=60),
    ) -> None:
        self.settings = settings
        self.live_fetcher = live_fetcher
        self._load = load or self._load_markets
        self._clock = clock
        self._live_for = live_for
        self._views: dict[str, View] = {}
        self._lock = threading.Lock()

    def respond(self, path: str, query: str) -> str | None:
        """The page for a GET request, or None for a path the UI doesn't serve."""
        routes = {"/": self._order, "/index.html": self._order, "/board": self._board}
        routes["/match"] = self._match
        route = routes.get(path)
        if route is None:
            return None
        params = {k: v[-1] for k, v in parse_qs(query, keep_blank_values=True).items()}
        source = params.get("data") if params.get("data") in SOURCES else "snapshot"
        return route(self._view(source), params)

    # Data.

    def _load_markets(self, source: str) -> Loaded:
        settings = replace(self.settings, source="fixtures" if source == "snapshot" else "live")
        return load_markets(settings, self.live_fetcher)

    def _view(self, source: str) -> View:
        with self._lock:
            now = self._clock()
            view = self._views.get(source)
            if view and (source == "snapshot" or now - view.read_at < self._live_for):
                return view
            loaded = self._load(source)
            clusters = build_clusters(loaded.markets)
            view = View(source, loaded, clusters, _outcomes(clusters), now)
            self._views[source] = view
            return view

    def _banner(self, view: View, path: str, params: dict[str, str]) -> pages.Banner:
        other = "live" if view.source == "snapshot" else "snapshot"
        switch = pages.href(path, **{**params, "data": other if other == "live" else ""})
        if view.source == "snapshot":
            try:
                taken = FixtureFetcher(self.settings.snapshot).captured_at
                summary = f"Snapshot taken {taken:%Y-%m-%d %H:%M} UTC."
            except FetchError:
                summary = "Snapshot data."
            label = "Use live prices instead"
        else:
            age = int((self._clock() - view.read_at).total_seconds())
            summary = f"Live prices, read at {view.read_at:%H:%M:%S} UTC ({age} s ago)."
            label = "Use the snapshot instead"
        return pages.Banner(summary, label, switch, view.loaded.warnings)

    # Pages.

    def _order(self, view: View, params: dict[str, str]) -> str:
        form = pages.OrderForm(
            choices=_choices(view),
            outcome=params.get("outcome") or _favorite(view),
            side=params.get("side", "YES").strip().upper(),
            quantity=params.get("quantity", "100").strip(),
            budget=params.get("budget", "").strip(),
            data=view.source,
        )
        outcome = next((o for o in view.outcomes if o.key == form.outcome), None)
        quantity, budget = _amount(form.quantity), _amount(form.budget) if form.budget else None
        form.errors = [
            message
            for failed, message in (
                (outcome is None, "That outcome isn't among the loaded markets."),
                (form.side not in ("YES", "NO"), "Choose Buy YES or Buy NO."),
                (quantity is None, "Contracts must be a number greater than 0."),
                (
                    bool(form.budget) and budget is None,
                    "The budget must be a dollar amount greater than 0.",
                ),
            )
            if failed
        ]
        result = None
        if not form.errors and outcome is not None:
            order = OrderRequest(
                market_id=outcome.cluster.markets[0].market_id,
                outcome=form.side,
                quantity=quantity,
                max_budget=budget,
            )
            trace = simulate(order, outcome.cluster, self._clock(), self.settings.stale_after)
            result = self._result(view, outcome, trace)
        body = pages.order_body(form, result, empty=not view.outcomes)
        return pages.layout(
            "Price an order", "/", view.source, self._banner(view, "/", params), body
        )

    def _result(self, view: View, outcome: Outcome, trace: EquinoxTrace) -> pages.Result:
        order, markets = trace.order, view.markets
        budget = dollars(order.max_budget, CENT) if order.max_budget else ""
        quotes = sorted(trace.quotes, key=lambda q: (not q.eligible, q.total_cost, q.market_id))
        step = money_step([q.total_cost for q in quotes if q.filled_quantity])
        rows = [
            [
                words.venue(q.venue),
                "Yes" if q.eligible else "No",
                words.fills(q),
                words.cents(q.average_price) if q.average_price is not None else "–",
                dollars(q.fee, step) if q.filled_quantity else "–",
                dollars(q.total_cost, step) if q.filled_quantity else "–",
                words.why_not(q, markets[q.market_id], order, budget) or "–",
            ]
            for q in quotes
        ]
        level = cluster_confidence(outcome.cluster)
        if outcome.cluster.pairs:
            verdict = f"Same bet. Confidence: {level.level}. {level.reason}"
        else:
            only = words.venue(outcome.cluster.markets[0].venue)
            verdict = f"Only {only} lists this outcome, so there is nothing to compare it with."
        return pages.Result(
            headline=_headline(trace),
            routed=trace.status == RoutingStatus.ROUTED,
            rationale=trace.rationale,
            columns=[
                "Venue",
                "Can take it",
                "Would buy",
                "Average price",
                "Fee",
                "Total",
                "Why not",
            ],
            rows=rows,
            excluded=[not q.eligible for q in quotes],
            verdict=verdict,
            match_href=pages.href("/match", outcome=outcome.key, data=_data(view)),
            risks=outcome.cluster.risk_flags,
            warnings=list(dict.fromkeys(trace.warnings)),
            assumptions=trace.assumptions,
        )

    def _board(self, view: View, params: dict[str, str]) -> str:
        tables: dict[str, pages.Table] = {}
        now = self._clock()
        for outcome in view.outcomes:
            venues = _event_venues(view, outcome.event)
            if outcome.event not in tables:
                columns = ["Outcome"]
                for v in venues:
                    columns += [f"{words.venue(v)} YES", f"{words.venue(v)} NO"]
                columns += ["Same bet?", "Best for 100 YES", "Best for 100 NO"]
                tables[outcome.event] = pages.Table(outcome.event, columns, [], [])
            members = {m.venue: m for m in outcome.cluster.markets}
            cells = [outcome.name]
            for v in venues:
                market = members.get(v)
                cells += [_ask(market, "YES"), _ask(market, "NO")] if market else ["Not listed"] * 2
            level = cluster_confidence(outcome.cluster)
            if outcome.cluster.pairs:
                cells.append(f"Yes ({level.level} confidence)")
            else:
                cells.append(f"Only on {words.venue(outcome.cluster.markets[0].venue)}")
            for side in ("YES", "NO"):
                order = OrderRequest(
                    market_id=outcome.cluster.markets[0].market_id,
                    outcome=side,
                    quantity=BOARD_ORDER,
                )
                trace = simulate(order, outcome.cluster, now, self.settings.stale_after)
                cells.append(_best(trace))
            tables[outcome.event].rows.append(cells)
            tables[outcome.event].links.append(
                pages.href("/", outcome=outcome.key, data=_data(view))
            )
        termless = [
            f"{words.venue(m.venue)}: {m.title}" for m in view.loaded.markets if m.terms is None
        ]
        body = pages.board_body(list(tables.values()), termless, view.source)
        banner = self._banner(view, "/board", params)
        return pages.layout("Market board", "/board", view.source, banner, body)

    def _match(self, view: View, params: dict[str, str]) -> str:
        key = params.get("outcome") or _favorite(view)
        outcome = next((o for o in view.outcomes if o.key == key), None)
        comparison = _comparison(view, outcome) if outcome else None
        body = pages.match_body(_choices(view), key, view.source, comparison)
        banner = self._banner(view, "/match", params)
        return pages.layout("Why these match", "/match", view.source, banner, body)


# Naming and ordering.


def _outcomes(clusters: list[EquivalenceCluster]) -> list[Outcome]:
    named = []
    for cluster in clusters:
        terms = _representative(cluster)
        sort = (terms.observed_on, terms.subject, terms.measure, terms.threshold, terms.comparison)
        named.append((sort, Outcome(cluster, words.event_name(terms), words.outcome_name(terms))))
    return [outcome for _, outcome in sorted(named, key=lambda pair: pair[0])]


def _representative(cluster: EquivalenceCluster) -> ContractTerms:
    """The member whose terms read most simply: "50 bps or more" rather than "more than 25"."""
    members = sorted(
        cluster.markets, key=lambda m: (m.terms.comparison not in INCLUSIVE, m.market_id)
    )
    return members[0].terms


def _choices(view: View) -> list[pages.Choice]:
    return [pages.Choice(o.key, o.name, o.event) for o in view.outcomes]


def _favorite(view: View) -> str:
    """The outcome the markets think most likely: the highest price to buy YES."""

    def best_yes(outcome: Outcome) -> Decimal:
        asks = [
            m.books["YES"].asks[0].price for m in outcome.cluster.markets if m.books["YES"].asks
        ]
        return max(asks, default=Decimal(0))

    return max(view.outcomes, key=best_yes).key if view.outcomes else ""


def _event_venues(view: View, event: str) -> list[str]:
    return sorted({m.venue for o in view.outcomes if o.event == event for m in o.cluster.markets})


def _data(view: View) -> str:
    return "" if view.source == "snapshot" else view.source


# Wording the results.


def _headline(trace: EquinoxTrace) -> str:
    order, status = trace.order, trace.status
    side, size = order.outcome, contracts(order.quantity)
    by_id = {q.market_id: q for q in trace.quotes}
    real = [q for q in trace.quotes if not NOT_REAL.intersection(q.reasons)]
    if status == RoutingStatus.ROUTED:
        decision = trace.decision
        winner, runner_up = by_id[decision.winner], by_id.get(decision.runner_up or "")
        step = money_step([q.total_cost for q in (winner, runner_up) if q])
        text = (
            f"Buy on {words.venue(winner.venue)}: {dollars(winner.total_cost, step)} for {size} "
            f"{side} contracts, including {dollars(winner.fee, step)} in fees."
        )
        if runner_up:
            other = f"{words.venue(runner_up.venue)} at {dollars(runner_up.total_cost, step)}"
            saved = f"{dollars(decision.savings, step)} ({decision.savings_percent}%)"
            return f"{text} That's {saved} less than {other}."
        return f"{text} {words.venue(winner.venue)} is the only venue that can take this order."
    if status == RoutingStatus.BUDGET_EXCEEDED:
        cheapest = min(
            (q for q in real if QuoteReason.OVER_BUDGET in q.reasons), key=lambda q: q.total_cost
        )
        return (
            f"No venue can fill {size} {side} contracts within {dollars(order.max_budget, CENT)}. "
            f"The cheapest full fill is {words.venue(cheapest.venue)} at "
            f"{dollars(cheapest.total_cost, CENT)}."
        )
    if status == RoutingStatus.INSUFFICIENT_LIQUIDITY:
        most = max(real, key=lambda q: q.filled_quantity)
        on_offer = (
            f"The most on offer is {contracts(most.filled_quantity)} on {words.venue(most.venue)}."
            if most.filled_quantity
            else f"Nobody is selling {side} on any open venue."
        )
        return f"No venue has {size} {side} contracts for sale. {on_offer}"
    return "No venue can take this order."


def _best(trace: EquinoxTrace) -> str:
    if trace.status != RoutingStatus.ROUTED:
        return "No venue can fill it"
    winner = next(q for q in trace.quotes if q.market_id == trace.decision.winner)
    return f"{words.venue(winner.venue)} {dollars(winner.total_cost, CENT)}"


def _ask(market: CanonicalMarket, side: str) -> str:
    asks = market.books[side].asks
    return words.cents(asks[0].price) if asks else "–"


def _amount(text: str) -> Decimal | None:
    """A positive, finite number typed by a person ("1,000" allowed), else None."""
    try:
        value = Decimal(text.replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() and value > 0 else None


# Why these match.


def _comparison(view: View, outcome: Outcome) -> pages.Comparison:
    members = sorted(outcome.cluster.markets, key=lambda m: m.venue)
    rules = [
        ("Question", [m.title for m in members], None, False),
        ("Pays YES if", [words.pays_if(m.terms) for m in members], None, True),
        ("Measured by", [words.measured_by(m.terms) for m in members], None, True),
        ("Observed", [words.observed(m.terms) for m in members], None, True),
        (
            "Settlement source",
            [m.resolution_source.institution for m in members],
            [m.resolution_source.url for m in members],
            True,
        ),
        ("Trading closes", [words.moment(m.trading_closes_at) for m in members], None, True),
        ("Expected to resolve", [words.moment(m.resolves_at) for m in members], None, True),
        ("Edge-case rules", [words.edge_cases(m.terms) for m in members], None, True),
    ]
    rows = [
        (label, texts, hrefs or [None] * len(texts), compare and len(set(texts)) > 1)
        for label, texts, hrefs, compare in rules
    ]
    verdicts = [(_pair_line(view, pair), list(pair.risk_flags)) for pair in outcome.cluster.pairs]
    if not verdicts:
        only = words.venue(members[0].venue)
        verdicts = [
            (f"Only {only} lists this outcome, so there is nothing to compare it with.", [])
        ]
    return pages.Comparison(
        columns=[f"{words.venue(m.venue)} ({m.native_id})" for m in members],
        rows=rows,
        verdicts=verdicts,
        set_aside=[_pair_line(view, pair, titles=True) for pair in _set_aside(view)],
    )


def _set_aside(view: View) -> list[MatchResult]:
    found: dict[frozenset[str], MatchResult] = {}
    for result in [r for c in view.clusters for r in c.ambiguous] + text_matches(
        view.loaded.markets
    ):
        if result.status == EquivalenceStatus.AMBIGUOUS:
            found.setdefault(frozenset((result.market_a, result.market_b)), result)
    return list(found.values())


def _pair_line(view: View, pair: MatchResult, titles: bool = False) -> str:
    a, b = view.markets[pair.market_a], view.markets[pair.market_b]
    level = confidence(pair)
    names = (
        f"{words.venue(a.venue)} “{a.title}” and {words.venue(b.venue)} “{b.title}”"
        if titles
        else f"{words.venue(a.venue)} and {words.venue(b.venue)}"
    )
    rated = f"Confidence: {level.level}. " if level.level else ""
    reasons = f" {' '.join(pair.reasons)}" if titles else ""
    return f"{names}: {words.VERDICTS[pair.status]}. {rated}{level.reason}{reasons}"
