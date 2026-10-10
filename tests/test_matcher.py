"""Equivalence matcher (feat-03, architecture section 6) on the golden canonical markets."""

import random
from decimal import Decimal
from itertools import combinations

import pytest

from equinox.matcher import (
    build_clusters,
    cluster_for,
    evaluate_pair,
    terms_key,
    text_match,
    text_matches,
)
from equinox.models import CanonicalMarket, EquivalenceStatus, ResolutionSource

EQUIVALENT = EquivalenceStatus.EQUIVALENT
AMBIGUOUS = EquivalenceStatus.AMBIGUOUS
DISTINCT = EquivalenceStatus.DISTINCT

TIE = "Tie rule differs: "
GRID = "Equal only on the 25 bps grid: "
EDGE = "Edge-case rules differ: "
SOURCE = "Resolution sources differ: "
LEADING_PHRASES = (TIE, GRID, EDGE, SOURCE)

H0 = "kalshi:KXFEDDECISION-26OCT-H0"
C25 = "kalshi:KXFEDDECISION-26OCT-C25"
C26 = "kalshi:KXFEDDECISION-26OCT-C26"
H26 = "kalshi:KXFEDDECISION-26OCT-H26"
PM_50_DOWN = "polymarket:2589810"
PM_25_DOWN = "polymarket:2589811"
PM_NO_CHANGE = "polymarket:2589812"
PM_25_UP = "polymarket:2589813"
PM_50_UP = "polymarket:2589814"
PM_AAPL_330 = "polymarket:5455686"
PM_AAPL_335 = "polymarket:5455687"
MD_AAPL_330 = "meridian:AAPL-330-2026-10-12"
MD_AAPL_320 = "meridian:AAPL-320-2026-10-12"
MD_AAPL_330_NEXT_DAY = "meridian:AAPL-330-2026-10-13"
MD_AAPL_330_OFFICIAL = "meridian:AAPL-330-2026-10-12-OC"
TERMLESS = tuple(f"{venue}:E{n}" for n in (11, 12, 13) for venue in ("kalshi", "polymarket"))

# Architecture section 6.4: (label, market a, market b, status, method, leading phrases of flags).
LABELLED_PAIRS = [
    ("E1", H0, PM_NO_CHANGE, EQUIVALENT, "terms", {EDGE}),
    ("E2", C25, PM_25_DOWN, EQUIVALENT, "terms", {EDGE}),
    ("E3", C26, PM_50_DOWN, EQUIVALENT, "terms", {GRID, EDGE}),
    ("E4", H26, PM_50_UP, EQUIVALENT, "terms", {GRID, EDGE}),
    ("E5", H0, PM_25_UP, DISTINCT, "terms", set()),
    ("E6", C25, PM_50_DOWN, DISTINCT, "terms", set()),
    ("E7", MD_AAPL_330, PM_AAPL_330, EQUIVALENT, "terms", {TIE, EDGE}),
    ("E8", MD_AAPL_330, PM_AAPL_335, DISTINCT, "terms", set()),
    ("E9", MD_AAPL_330, MD_AAPL_330_NEXT_DAY, DISTINCT, "terms", set()),
    ("E10", MD_AAPL_330, MD_AAPL_330_OFFICIAL, AMBIGUOUS, "terms", set()),
    ("E11", "kalshi:E11", "polymarket:E11", DISTINCT, "text", set()),
    ("E12", "kalshi:E12", "polymarket:E12", DISTINCT, "text", set()),
    ("E13", "kalshi:E13", "polymarket:E13", AMBIGUOUS, "text", set()),
]


def leading_phrases(flags):
    phrases = {p for flag in flags for p in LEADING_PHRASES if flag.startswith(p)}
    assert len(phrases) == len(flags), f"a flag has no known leading phrase: {flags}"
    return phrases


def with_terms(market: CanonicalMarket, **changes) -> CanonicalMarket:
    """A validated copy of a golden market with some of its contract terms changed."""
    terms = {**market.terms.model_dump(), **changes}
    return CanonicalMarket.model_validate({**market.model_dump(), "terms": terms})


def ids(markets):
    return sorted(m.market_id for m in markets)


def pair_ids(result):
    return frozenset((result.market_a, result.market_b))


# Tests 1-13: the labelled pairs.


@pytest.mark.parametrize(
    ("a", "b", "status", "method", "phrases"),
    [row[1:] for row in LABELLED_PAIRS],
    ids=[row[0] for row in LABELLED_PAIRS],
)
def test_1_to_13_labelled_pairs(golden_markets, a, b, status, method, phrases):
    result = evaluate_pair(golden_markets[a], golden_markets[b])
    assert (result.market_a, result.market_b) == (a, b)
    assert result.status == status
    assert result.method == method
    assert result.reasons, "every decision is explained"
    assert leading_phrases(result.risk_flags) == phrases


@pytest.mark.parametrize(
    ("a", "b"), [(H0, PM_NO_CHANGE), (C26, PM_50_DOWN), (PM_AAPL_330, MD_AAPL_330)]
)
def test_risk_flags_do_not_depend_on_argument_order(golden_markets, a, b):
    forward = evaluate_pair(golden_markets[a], golden_markets[b])
    backward = evaluate_pair(golden_markets[b], golden_markets[a])
    assert (backward.market_a, backward.market_b) == (b, a)
    assert backward.status == forward.status
    assert backward.risk_flags == forward.risk_flags


def test_7_tie_flag_names_the_threshold_and_who_pays_what(golden_markets):
    for a, b in ((MD_AAPL_330, PM_AAPL_330), (PM_AAPL_330, MD_AAPL_330)):
        flags = evaluate_pair(golden_markets[a], golden_markets[b]).risk_flags
        tie = [f for f in flags if f.startswith(TIE)]
        assert tie == [
            "Tie rule differs: at exactly 330 USD, Polymarket pays No and Meridian pays Yes."
        ]


def test_tie_flag_reads_venue_names_from_the_market(golden_markets):
    strict = golden_markets[PM_AAPL_330].model_dump()
    renamed = CanonicalMarket.model_validate(
        {**strict, "venue": "alpha", "market_id": f"alpha:{strict['native_id']}"}
    )
    flags = evaluate_pair(renamed, golden_markets[MD_AAPL_330]).risk_flags
    assert "Tie rule differs: at exactly 330 USD, Alpha pays No and Meridian pays Yes." in flags


@pytest.mark.parametrize(("a", "b"), [(H0, PM_NO_CHANGE), (MD_AAPL_330, PM_AAPL_330)])
def test_edge_case_flag_lists_each_venues_fallback_rules(golden_markets, a, b):
    market_a, market_b = golden_markets[a], golden_markets[b]
    [edge] = [f for f in evaluate_pair(market_a, market_b).risk_flags if f.startswith(EDGE)]
    for market in (market_a, market_b):
        assert market.venue.capitalize() in edge
        for rule in market.terms.fallback_rules:
            assert rule in edge


def test_same_fallback_rules_raise_no_edge_case_flag(golden_markets):
    kalshi, polymarket = golden_markets[H0], golden_markets[PM_NO_CHANGE]
    same_rules = with_terms(polymarket, fallback_rules=kalshi.terms.fallback_rules)
    assert evaluate_pair(kalshi, same_rules).risk_flags == ()


def test_resolution_sources_are_compared_by_institution_not_url(golden_markets):
    # E1's sources are different URLs on the same host, so section 6.4 lists no source flag (D18).
    kalshi, polymarket = golden_markets[H0], golden_markets[PM_NO_CHANGE]
    assert kalshi.resolution_source.url != polymarket.resolution_source.url
    other = polymarket.model_copy(
        update={"resolution_source": ResolutionSource(name="Other", url="https://example.org/fomc")}
    )
    result = evaluate_pair(kalshi, other)
    assert result.status == EQUIVALENT
    [source] = [f for f in result.risk_flags if f.startswith(SOURCE)]
    assert "federalreserve.gov" in source and "example.org" in source


def test_strictness_on_the_grid_is_a_different_outcome(golden_markets):
    # On the 25 bps grid "above 25" means 50 or more, so it is not "at or above 25" (section 6.1).
    at_or_above_25 = with_terms(golden_markets[PM_50_UP], threshold=Decimal(25))
    assert evaluate_pair(golden_markets[H26], at_or_above_25).status == DISTINCT


def test_a_measure_without_a_grid_is_not_normalized(golden_markets):
    # Without a grid, "above 330" does not become "at or above 331" or similar.
    at_or_above_331 = with_terms(golden_markets[MD_AAPL_330], threshold=Decimal(331))
    assert evaluate_pair(at_or_above_331, golden_markets[PM_AAPL_330]).status == DISTINCT


def test_a_pair_with_one_term_less_market_uses_the_text_fallback(golden_markets):
    result = evaluate_pair(golden_markets[H0], golden_markets["polymarket:E11"])
    assert result.method == "text"
    assert result.status != EQUIVALENT


# Observation time (D23): a stated instant is part of the event.


def test_a_different_stated_observation_time_is_a_different_event(golden_markets):
    earlier_close = with_terms(golden_markets[MD_AAPL_330], observed_at="2026-10-12T19:00:00Z")
    result = evaluate_pair(earlier_close, golden_markets[PM_AAPL_330])
    assert result.status == DISTINCT
    assert "observed_at" in result.reasons[0]
    assert terms_key(earlier_close.terms) != terms_key(golden_markets[PM_AAPL_330].terms)


def test_an_observation_time_stated_by_one_market_only_is_ambiguous(golden_markets):
    unstated = with_terms(golden_markets[MD_AAPL_330], observed_at=None)
    result = evaluate_pair(unstated, golden_markets[PM_AAPL_330])
    assert result.status == AMBIGUOUS
    assert "observation time" in result.reasons[0]
    assert terms_key(unstated.terms) != terms_key(golden_markets[PM_AAPL_330].terms)


def test_the_same_observation_time_in_another_zone_is_the_same_event(golden_markets):
    eastern = with_terms(golden_markets[MD_AAPL_330], observed_at="2026-10-12T16:00:00-04:00")
    assert evaluate_pair(eastern, golden_markets[PM_AAPL_330]).status == EQUIVALENT
    assert terms_key(eastern.terms) == terms_key(golden_markets[PM_AAPL_330].terms)


# Cluster keys.


def test_cluster_key_is_the_normalized_terms_as_text(golden_markets):
    assert terms_key(golden_markets[H0].terms) == (
        "FOMC|fed_upper_bound_change|fomc_statement|2026-10-28|eq|0|bps"
    )
    assert terms_key(golden_markets[C26].terms) == (
        "FOMC|fed_upper_bound_change|fomc_statement|2026-10-28|below|-50|bps"
    )
    aapl = "AAPL|close_price|pyth_regular_close|2026-10-12|2026-10-12T20:00:00Z|above|330|usd"
    assert terms_key(golden_markets[PM_AAPL_330].terms) == aapl
    assert terms_key(golden_markets[MD_AAPL_330].terms) == aapl


def test_cluster_key_writes_the_same_number_one_way(golden_markets):
    padded = with_terms(golden_markets[MD_AAPL_330], threshold=Decimal("330.00"))
    assert terms_key(padded.terms) == terms_key(golden_markets[MD_AAPL_330].terms)


def test_cluster_key_carries_upper_only_for_a_range(golden_markets):
    market = with_terms(golden_markets[MD_AAPL_330], comparison="between", upper=Decimal(340))
    assert terms_key(market.terms) == (
        "AAPL|close_price|pyth_regular_close|2026-10-12|2026-10-12T20:00:00Z|between|330|340|usd"
    )


def test_equivalent_exactly_when_the_keys_match(golden_markets):
    with_contract_terms = [m for m in golden_markets.values() if m.terms is not None]
    for a, b in combinations(with_contract_terms, 2):
        same_key = terms_key(a.terms) == terms_key(b.terms)
        assert (evaluate_pair(a, b).status == EQUIVALENT) == same_key, (a.market_id, b.market_id)


# Tests 14-16: clusters.


def test_14_clusters_on_the_golden_markets(golden_markets):
    clusters = build_clusters(golden_markets.values())
    by_id = {c.cluster_id: c for c in clusters}
    assert len(by_id) == len(clusters), "cluster IDs are unique"

    hold = by_id["FOMC|fed_upper_bound_change|fomc_statement|2026-10-28|eq|0|bps"]
    assert ids(hold.markets) == [H0, PM_NO_CHANGE]
    assert [pair_ids(p) for p in hold.pairs] == [frozenset((H0, PM_NO_CHANGE))]
    assert leading_phrases(hold.risk_flags) == {EDGE}

    aapl = by_id[
        "AAPL|close_price|pyth_regular_close|2026-10-12|2026-10-12T20:00:00Z|above|330|usd"
    ]
    assert ids(aapl.markets) == [MD_AAPL_330, PM_AAPL_330]
    assert leading_phrases(aapl.risk_flags) == {TIE, EDGE}
    # The official-close variant is shown as AMBIGUOUS, never as a member. Only cross-venue pairs
    # are evaluated, so the same-venue pair (E10 itself) is not listed here.
    assert MD_AAPL_330_OFFICIAL not in ids(aapl.markets)
    assert [pair_ids(p) for p in aapl.ambiguous] == [frozenset((PM_AAPL_330, MD_AAPL_330_OFFICIAL))]
    assert all(p.status == AMBIGUOUS for p in aapl.ambiguous)

    lone = cluster_for(MD_AAPL_320, clusters)
    assert lone is not None
    assert ids(lone.markets) == [MD_AAPL_320]
    assert lone.pairs == () and lone.risk_flags == ()


@pytest.mark.parametrize("label", ["E1", "E2", "E3", "E4", "E5", "E6", "E8"])
def test_14_labelled_pairs_share_a_cluster_exactly_when_equivalent(golden_markets, label):
    [(_, a, b, status, _, _)] = [row for row in LABELLED_PAIRS if row[0] == label]
    clusters = build_clusters(golden_markets.values())
    assert (cluster_for(a, clusters) == cluster_for(b, clusters)) == (status == EQUIVALENT)


def test_15_every_pair_inside_a_cluster_is_equivalent(golden_markets):
    for cluster in build_clusters(golden_markets.values()):
        member_ids = {m.market_id for m in cluster.markets}
        for a, b in combinations(cluster.markets, 2):
            assert evaluate_pair(a, b).status == EQUIVALENT, (a.market_id, b.market_id)
        assert all(p.status == EQUIVALENT and pair_ids(p) <= member_ids for p in cluster.pairs)
        assert all(p.status == AMBIGUOUS and pair_ids(p) & member_ids for p in cluster.ambiguous)


def test_16_clusters_do_not_depend_on_input_order(golden_markets):
    forward = build_clusters(list(golden_markets.values()))
    backward = build_clusters(list(reversed(golden_markets.values())))
    shuffled = list(golden_markets.values())
    random.Random(16).shuffle(shuffled)
    summary = [(c.cluster_id, ids(c.markets)) for c in forward]
    assert [(c.cluster_id, ids(c.markets)) for c in backward] == summary
    assert backward == forward
    assert build_clusters(shuffled) == forward


def test_cluster_risk_flags_are_the_pair_flags_without_repeats(golden_markets):
    for cluster in build_clusters(golden_markets.values()):
        pair_flags = [f for p in cluster.pairs for f in p.risk_flags]
        assert list(cluster.risk_flags) == list(dict.fromkeys(pair_flags))


def test_cluster_for_a_market_without_a_cluster_is_none(golden_markets):
    clusters = build_clusters(golden_markets.values())
    assert cluster_for("kalshi:E11", clusters) is None
    assert cluster_for("nowhere:missing", clusters) is None


def test_build_clusters_refuses_a_repeated_market_id(golden_markets):
    market = golden_markets[H0]
    with pytest.raises(ValueError, match="kalshi:KXFEDDECISION-26OCT-H0"):
        build_clusters([market, market])


# Test 17 and the text fallback.


def test_17_term_less_markets_join_no_cluster_and_match_by_text(golden_markets):
    clusters = build_clusters(golden_markets.values())
    clustered = {m.market_id for c in clusters for m in c.markets}
    assert clustered.isdisjoint(TERMLESS)
    assert clustered == {mid for mid, m in golden_markets.items() if m.terms is not None}

    results = text_matches(golden_markets.values())
    assert all(r.method == "text" and r.status != EQUIVALENT for r in results)
    assert all(pair_ids(r) <= set(TERMLESS) for r in results), "only term-less markets reach it"
    by_pair = {pair_ids(r): r for r in results}
    assert by_pair[frozenset(("kalshi:E11", "polymarket:E11"))].status == DISTINCT
    assert by_pair[frozenset(("kalshi:E12", "polymarket:E12"))].status == DISTINCT
    assert by_pair[frozenset(("kalshi:E13", "polymarket:E13"))].status == AMBIGUOUS


def test_text_matches_skip_same_venue_pairs_and_do_not_depend_on_order(golden_markets):
    markets = list(golden_markets.values())
    results = text_matches(markets)
    assert all(r.market_a.split(":")[0] != r.market_b.split(":")[0] for r in results)
    assert text_matches(list(reversed(markets))) == results


def test_text_scores_are_exact_decimals_at_or_above_the_candidate_bar(golden_markets):
    for result in text_matches(golden_markets.values()):
        assert isinstance(result.text_score, Decimal)
        assert result.text_score >= Decimal("0.3")


def test_11_number_veto_ignores_years(golden_markets):
    result = text_match(golden_markets["kalshi:E11"], golden_markets["polymarket:E11"])
    assert result.status == DISTINCT
    joined = " ".join(result.reasons)
    assert "25" in joined and "50" in joined
    assert "2025" not in joined, "a year is not a differing number"


def test_12_entity_veto_names_the_states(golden_markets):
    result = text_match(golden_markets["kalshi:E12"], golden_markets["polymarket:E12"])
    assert result.status == DISTINCT
    joined = " ".join(result.reasons).lower()
    assert "pennsylvania" in joined and "michigan" in joined


def test_13_similar_titles_are_ambiguous_at_most(golden_markets):
    result = text_match(golden_markets["kalshi:E13"], golden_markets["polymarket:E13"])
    assert result.status == AMBIGUOUS
    assert result.text_score >= Decimal("0.3")


def test_cut_and_hike_titles_are_distinct(golden_markets):
    hike = golden_markets["polymarket:E13"].model_copy(
        update={"title": "Fed increases interest rates after December 2025 meeting?"}
    )
    assert text_match(golden_markets["kalshi:E13"], hike).status == DISTINCT


def test_titles_that_share_too_few_words_are_distinct(golden_markets):
    result = text_match(golden_markets["kalshi:E12"], golden_markets["polymarket:E11"])
    assert result.status == DISTINCT
    assert result.text_score < Decimal("0.3")
