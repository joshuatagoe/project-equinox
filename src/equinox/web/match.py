"""Why these match (Morgan): each venue's rules side by side, the verdict, and what's set aside."""

from equinox.matcher import confidence, text_matches
from equinox.models import EquivalenceStatus, MatchResult
from equinox.web import pages, words
from equinox.web.view import Outcome, PageContext, View, choices, favorite, find


def page(view: View, params: dict[str, str], ctx: PageContext) -> str:
    key = params.get("outcome") or favorite(view)
    outcome = find(view, key)
    comparison = _comparison(view, outcome) if outcome else None
    body = pages.match_body(choices(view), key, view.source, comparison)
    return pages.layout("Why these match", "/match", view.source, ctx.banner, body)


def _comparison(view: View, outcome: Outcome) -> pages.Comparison:
    members = sorted(outcome.cluster.markets, key=lambda m: m.venue)
    verdicts = [(_pair_line(view, pair), list(pair.risk_flags)) for pair in outcome.cluster.pairs]
    if not verdicts:
        only = words.venue(members[0].venue)
        verdicts = [
            (f"Only {only} lists this outcome, so there is nothing to compare it with.", [])
        ]
    return pages.Comparison(
        columns=[f"{words.venue(m.venue)} ({m.native_id})" for m in members],
        rows=_rule_rows(members),
        verdicts=verdicts,
        set_aside=[_pair_line(view, pair, titles=True) for pair in _set_aside(view)],
    )


def _rule_rows(members) -> list[tuple]:
    """One row per rule: (label, each venue's wording, links, whether the venues differ)."""
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
    return [
        (label, texts, hrefs or [None] * len(texts), compare and len(set(texts)) > 1)
        for label, texts, hrefs, compare in rules
    ]


def _set_aside(view: View) -> list[MatchResult]:
    """Every AMBIGUOUS pair, from the terms rules and from the title fallback, once each."""
    found: dict[frozenset[str], MatchResult] = {}
    candidates = [r for c in view.clusters for r in c.ambiguous]
    for result in candidates + text_matches(view.loaded.markets):
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
