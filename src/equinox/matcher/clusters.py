"""Clusters: markets whose normalized contract terms are identical (architecture section 6.2).

A market with terms always lands in exactly one cluster, alone if it has no partner. A market
without terms lands in none; only the text fallback sees it. Only cross-venue pairs are
evaluated. The output is sorted (clusters by `cluster_id`, members and pairs by market ID), so it
does not depend on the input order.
"""

from collections.abc import Iterable
from itertools import combinations, pairwise

from equinox.matcher.terms import evaluate_pair, terms_key
from equinox.models import CanonicalMarket, EquivalenceCluster, EquivalenceStatus


def build_clusters(markets: Iterable[CanonicalMarket]) -> list[EquivalenceCluster]:
    """Group the markets that have terms by their normalized key.

    `pairs` holds the EQUIVALENT results among a cluster's members, `ambiguous` the AMBIGUOUS
    results that involve a member (shown, never routed), and `risk_flags` the members' pair flags
    without repeats, in a stable order.
    """
    with_terms = [market for market in _sorted_by_id(markets) if market.terms is not None]
    groups: dict[str, list[CanonicalMarket]] = {}
    for market in with_terms:
        groups.setdefault(terms_key(market.terms), []).append(market)
    results = [evaluate_pair(a, b) for a, b in combinations(with_terms, 2) if a.venue != b.venue]

    clusters = []
    for key in sorted(groups):
        members = {market.market_id for market in groups[key]}
        pairs = tuple(
            r
            for r in results
            if r.status == EquivalenceStatus.EQUIVALENT and {r.market_a, r.market_b} <= members
        )
        ambiguous = tuple(
            r
            for r in results
            if r.status == EquivalenceStatus.AMBIGUOUS and {r.market_a, r.market_b} & members
        )
        clusters.append(
            EquivalenceCluster(
                cluster_id=key,
                markets=tuple(groups[key]),
                pairs=pairs,
                ambiguous=ambiguous,
                risk_flags=tuple(dict.fromkeys(flag for r in pairs for flag in r.risk_flags)),
            )
        )
    return clusters


def cluster_for(
    market_id: str, clusters: Iterable[EquivalenceCluster]
) -> EquivalenceCluster | None:
    """The cluster that holds this market, or None (no terms, or not loaded)."""
    for cluster in clusters:
        if any(market.market_id == market_id for market in cluster.markets):
            return cluster
    return None


def _sorted_by_id(markets: Iterable[CanonicalMarket]) -> list[CanonicalMarket]:
    """The markets sorted by market ID. A repeated ID is an adapter bug, so it is refused."""
    ordered = sorted(markets, key=lambda market: market.market_id)
    for earlier, later in pairwise(ordered):
        if earlier.market_id == later.market_id:
            raise ValueError(f"market_id appears more than once: {later.market_id}")
    return ordered
