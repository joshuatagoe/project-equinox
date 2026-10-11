"""Equivalence: which markets on different venues pay out under exactly the same conditions."""

from equinox.matcher.clusters import build_clusters, cluster_for
from equinox.matcher.confidence import Confidence, cluster_confidence, confidence
from equinox.matcher.terms import evaluate_pair, terms_key
from equinox.matcher.text import text_match, text_matches

__all__ = [
    "Confidence",
    "build_clusters",
    "cluster_confidence",
    "cluster_for",
    "confidence",
    "evaluate_pair",
    "terms_key",
    "text_match",
    "text_matches",
]
