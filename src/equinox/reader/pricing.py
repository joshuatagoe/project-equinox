"""Pricing a same bet whose terms a model read (D58).

The catalog says which markets a model read as the same bet, and each one's accepted terms. The
venues give their listings and order books. The committed evals (`evals/scores.json`) say whether
a model-read pair may be routed at all: only when it was read with the model and prompt the evals
were recorded with, and every gold set shows zero false same-bets. Then the pair goes through the
same clusters and router as a parser-read one, with a risk flag saying its terms were read by a
model, which keeps its confidence at Medium at most.
"""

import json
import re
from collections.abc import Sequence

from equinox.adapters.base import FetchError
from equinox.catalog import Catalog
from equinox.matcher import build_clusters, cluster_for
from equinox.models import ContractTerms, EquivalenceCluster
from equinox.models.catalog import SAME_BET
from equinox.reader import evals
from equinox.sources import LiveFetchers, Loaded, Settings, load_by_id

FLAG = "Terms read by a model: {reader}. Both readings passed the checks against the venues' texts."
_READER = re.compile(r"^(?P<model>.+) \(prompt (?P<prompt>[^)]+)\)$")


class PricingError(Exception):
    """A model-read same bet that can't be priced, said in words."""


class NotModelRead(PricingError):
    """The market is not in a same bet a model read."""


def gate(reader: str) -> str:
    """Why a pair read by `reader` may not be routed, or "" when it may."""
    scores = json.loads(evals.SCORES.read_text(encoding="utf-8"))
    recorded = f"{scores['model']} (prompt {scores['prompt']})"
    if reader != recorded:
        return (
            f"it was read by {reader}, but the evals were recorded with {recorded}; "
            "read the catalog again with that prompt"
        )
    false = [f"{name} {s['false_same']}" for name, s in scores.items() if _false(s)]
    if false:
        return f"the evals for {recorded} show a false same-bet ({', '.join(false)})"
    return ""


def priced_group(
    found: Catalog, market_id: str, settings: Settings, live_fetcher: LiveFetchers | None = None
) -> tuple[EquivalenceCluster, Loaded]:
    """The market's model-read group, loaded from the venues, ready for books and the router."""
    partners, reader = _same_bets(found, market_id)
    problem = gate(reader)
    if problem:
        raise PricingError(
            f"{market_id} was read as the same bet as {', '.join(partners)}, but it isn't "
            f"routed: {problem}."
        )
    terms = _terms(found, [market_id, *partners], reader)
    try:
        loaded = load_by_id(settings, [market_id, *partners], live_fetcher)
    except FetchError as error:
        raise PricingError(f"the venues couldn't be read for {market_id}: {error}") from error
    read = [m.model_copy(update={"terms": terms[m.market_id]}) for m in loaded.markets]
    cluster = cluster_for(market_id, build_clusters(read))
    if cluster is None or len(cluster.markets) < 2:
        raise PricingError(f"the venues' current listings for {market_id} no longer match")
    return _flagged(cluster, FLAG.format(reader=reader)), loaded


def _same_bets(found: Catalog, market_id: str) -> tuple[list[str], str]:
    query = (
        "SELECT market_a, market_b, read_by FROM pairs WHERE status = ? AND read_by IS NOT NULL "
        "AND (market_a = ? OR market_b = ?)"
    )
    with found.connect() as db:
        rows = db.execute(query, (SAME_BET, market_id, market_id)).fetchall()
    if not rows:
        raise NotModelRead(f"{market_id} is not in a same bet read by a model")
    partners = [b if a == market_id else a for a, b, _ in rows]
    return partners, rows[0][2]


def _terms(found: Catalog, markets: Sequence[str], reader: str) -> dict[str, ContractTerms]:
    """Each market's latest accepted reading by `reader`."""
    named = _READER.match(reader)
    if named is None:
        raise PricingError(f"no readings are recorded for {reader}")
    query = (
        "SELECT terms FROM readings WHERE market_id = ? AND terms IS NOT NULL AND model = ? "
        "AND prompt = ? ORDER BY rowid DESC LIMIT 1"
    )
    found_terms = {}
    with found.connect() as db:
        for market in markets:
            row = db.execute(query, (market, named["model"], named["prompt"])).fetchone()
            if row is None:
                raise PricingError(f"no accepted reading of {market} by {reader} is recorded")
            found_terms[market] = ContractTerms.model_validate_json(row[0])
    return found_terms


def _flagged(cluster: EquivalenceCluster, flag: str) -> EquivalenceCluster:
    pairs = tuple(p.model_copy(update={"risk_flags": (*p.risk_flags, flag)}) for p in cluster.pairs)
    return cluster.model_copy(update={"pairs": pairs, "risk_flags": (*cluster.risk_flags, flag)})


def _false(score: object) -> bool:
    return isinstance(score, dict) and bool(score.get("false_same"))
