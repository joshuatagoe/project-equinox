"""Equivalence: which markets on different venues pay out under exactly the same conditions."""

from equinox.matcher.clusters import build_clusters, cluster_for
from equinox.matcher.terms import evaluate_pair, terms_key
from equinox.matcher.text import text_match, text_matches

__all__ = [
    "build_clusters",
    "cluster_for",
    "evaluate_pair",
    "terms_key",
    "text_match",
    "text_matches",
]
