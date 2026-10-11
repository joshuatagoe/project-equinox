"""feat-07 test 10: a confidence level for every match result, derived from its verdict (D46)."""

import pytest

from equinox.matcher import build_clusters, cluster_confidence, confidence, evaluate_pair

H0 = "kalshi:KXFEDDECISION-26OCT-H0"
PAIRS = {
    "E1 same terms, edge-case rules differ": (H0, "polymarket:2589812", "High"),
    "E3 equal only on the grid": ("kalshi:KXFEDDECISION-26OCT-C26", "polymarket:2589810", "Medium"),
    "E4 equal only on the grid": ("kalshi:KXFEDDECISION-26OCT-H26", "polymarket:2589814", "Medium"),
    "E7 tie rule differs": ("meridian:AAPL-330-2026-10-12", "polymarket:5455686", "Medium"),
    "E10 measured differently": (
        "meridian:AAPL-330-2026-10-12",
        "meridian:AAPL-330-2026-10-12-OC",
        "Low",
    ),
    "E13 title only": ("kalshi:E13", "polymarket:E13", "Low"),
    "E5 different outcome": (H0, "polymarket:2589813", None),
}


@pytest.mark.parametrize("a, b, level", PAIRS.values(), ids=PAIRS.keys())
def test_10_confidence_on_the_labelled_pairs(golden_markets, a, b, level):
    result = evaluate_pair(golden_markets[a], golden_markets[b])
    found = confidence(result)
    assert found.level == level
    assert found.reason.endswith(".")


def test_reasons_say_what_still_differs(golden_markets):
    grid = confidence(
        evaluate_pair(*(golden_markets[m] for m in PAIRS["E3 equal only on the grid"][:2]))
    )
    tie = confidence(evaluate_pair(*(golden_markets[m] for m in PAIRS["E7 tie rule differs"][:2])))
    title = confidence(evaluate_pair(*(golden_markets[m] for m in PAIRS["E13 title only"][:2])))
    assert "25 bps" in grid.reason
    assert "exactly" in tie.reason
    assert "title" in title.reason and "0.56" in title.reason


def test_a_cluster_takes_its_weakest_pair_and_a_lone_market_has_none(golden_markets):
    clusters = {c.cluster_id: c for c in build_clusters(golden_markets.values())}
    hold = next(c for key, c in clusters.items() if key.endswith("|eq|0|bps"))
    below = next(c for key, c in clusters.items() if key.endswith("|below|-50|bps"))
    lone = next(c for c in clusters.values() if len(c.markets) == 1)
    assert cluster_confidence(hold).level == "High"
    assert cluster_confidence(below).level == "Medium"
    assert cluster_confidence(lone).level is None
    assert "one venue" in cluster_confidence(lone).reason


def test_match_command_prints_each_clusters_confidence(capsys):
    from equinox import cli

    assert cli.main(["match", "--source", "fixtures"]) == 0
    out = capsys.readouterr().out
    assert out.count("  Confidence: High.") == 3
    assert out.count("  Confidence: Medium.") == 2
