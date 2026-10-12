"""How sure the matcher is about a result, in one level and one sentence (D46).

The level is read from the verdict and its risk flags. It never changes a verdict, and nothing is
routed because of it: routing still takes EQUIVALENT pairs only (D15).

- High: EQUIVALENT, and only the venues' edge-case rules differ, or nothing does.
- Medium: EQUIVALENT, but the payouts can still differ in one stated case.
- Low: AMBIGUOUS. Never routed.
- None: DISTINCT. Not the same bet.
"""

from typing import Literal, NamedTuple

from equinox.models import EquivalenceCluster, EquivalenceStatus, MatchResult

Level = Literal["High", "Medium", "Low"]

# The leading phrases of the flags in terms.py, and what each leaves uncertain.
_CAVEATS = (
    ("Equal only on the ", "the payouts agree only for moves on the measure's grid ({step})"),
    ("Tie rule differs: ", "the payouts differ if the value lands exactly on the threshold"),
    ("Resolution sources differ: ", "the venues name different resolution sources"),
    ("Terms read by a model", "its terms were read by a model and checked, not parsed (D58)"),
)
_EDGE_CASES = "Edge-case rules differ: "
_ORDER: dict[Level | None, int] = {"High": 3, "Medium": 2, "Low": 1, None: 0}


class Confidence(NamedTuple):
    level: Level | None
    reason: str


def confidence(result: MatchResult) -> Confidence:
    """The level for one pair, with the reason in plain words."""
    if result.status == EquivalenceStatus.DISTINCT:
        return Confidence(None, "Not the same bet.")
    if result.status == EquivalenceStatus.AMBIGUOUS:
        if result.method == "text":
            score = f"{result.text_score:.2f}" if result.text_score is not None else "none"
            return Confidence("Low", f"Matched by title only (score {score}), so never routed.")
        return Confidence("Low", f"Not confirmed: {_first(result.reasons)}")

    caveats = [
        text.format(step=_grid_step(flag))
        for flag in result.risk_flags
        for phrase, text in _CAVEATS
        if flag.startswith(phrase)
    ]
    if caveats:
        return Confidence("Medium", f"The same bet, but {'; and '.join(caveats)}.")
    if any(flag.startswith(_EDGE_CASES) for flag in result.risk_flags):
        return Confidence(
            "High", "The terms are identical; only the venues' rules for rare events differ."
        )
    return Confidence("High", "The terms are identical.")


def cluster_confidence(cluster: EquivalenceCluster) -> Confidence:
    """The weakest of the cluster's pairs. A market alone on its venue has no match to rate."""
    if not cluster.pairs:
        return Confidence(None, "Only one venue lists this outcome.")
    return min((confidence(pair) for pair in cluster.pairs), key=lambda c: _ORDER[c.level])


def _grid_step(flag: str) -> str:
    """ "Equal only on the 25 bps grid: ..." -> "25 bps steps"."""
    if not flag.startswith("Equal only on the "):
        return ""
    return flag.removeprefix("Equal only on the ").split(" grid", 1)[0] + " steps"


def _first(reasons: tuple[str, ...]) -> str:
    text = reasons[0] if reasons else "the terms could not be compared."
    return text if text.endswith(".") else f"{text}."
