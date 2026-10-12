"""Pricing a same bet from the catalog, outside the families Equinox loads (D58, D65).

The catalog says which markets are the same bet. The venues give their listings and order books.

- **Read by the parsers** (D65): the venues' listings carry the terms again, and the group goes
  through the clusters and router as it is. A parser's pair can reach High confidence.
- **Read by a model** (D58): the committed evals (`evals/scores.json`) say whether the pair may be
  routed at all: only when it was read with the model and prompt the evals were recorded with, and
  every gold set shows zero false same-bets. The model's accepted terms are attached, and a risk
  flag says they were read by a model, which keeps the confidence at Medium at most.

A market in both kinds of pair is priced with its parsers' group.
"""

import json
import re
from collections.abc import Sequence

from equinox.adapters.base import FetchError
from equinox.catalog import Catalog
from equinox.matcher import build_clusters, cluster_for
from equinox.models import CanonicalMarket, ContractTerms, EquivalenceCluster
from equinox.models.catalog import SAME_BET
from equinox.reader import evals
from equinox.sources import LiveFetchers, Loaded, Settings, load_by_id

FLAG = "Terms read by a model: {reader}. Both readings passed the checks against the venues' texts."
_READER = re.compile(r"^(?P<model>.+) \(prompt (?P<prompt>[^)]+)\)$")


class PricingError(Exception):
    """A model-read same bet that can't be priced, said in words."""


class NotInCatalog(PricingError):
    """The market is not in a same bet in the catalog."""


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
    """The market's same-bet group, loaded from the venues, ready for books and the router."""
    partners, reader = _same_bets(found, market_id)
    if reader is None:  # the parsers' terms, read again from the venues' listings (D65)
        loaded = _load(settings, [market_id, *partners], live_fetcher)
        return _group(market_id, loaded.markets), loaded
    problem = gate(reader)
    if problem:
        raise PricingError(
            f"{market_id} was read as the same bet as {', '.join(partners)}, but it isn't "
            f"routed: {problem}."
        )
    terms = _terms(found, [market_id, *partners], reader)
    loaded = _load(settings, [market_id, *partners], live_fetcher)
    read = [m.model_copy(update={"terms": terms[m.market_id]}) for m in loaded.markets]
    return _flagged(_group(market_id, read), FLAG.format(reader=reader)), loaded


def _load(settings: Settings, markets: list[str], live_fetcher: LiveFetchers | None) -> Loaded:
    try:
        return load_by_id(settings, markets, live_fetcher)
    except FetchError as error:
        raise PricingError(f"the venues couldn't be read for {markets[0]}: {error}") from error


def _group(market_id: str, markets: list[CanonicalMarket]) -> EquivalenceCluster:
    cluster = cluster_for(market_id, build_clusters(markets))
    if cluster is None or len(cluster.markets) < 2:
        raise PricingError(f"the venues' current listings for {market_id} no longer match")
    return cluster


def _same_bets(found: Catalog, market_id: str) -> tuple[list[str], str | None]:
    """The market's partners, and who read them: None for the parsers, else the model reader.
    The parsers' pairs come first."""
    query = (
        "SELECT market_a, market_b, read_by FROM pairs WHERE status = ? "
        "AND (market_a = ? OR market_b = ?)"
    )
    with found.connect() as db:
        rows = db.execute(query, (SAME_BET, market_id, market_id)).fetchall()
    if not rows:
        raise NotInCatalog(f"{market_id} is not in a same bet in the catalog")
    by_parser = [row for row in rows if row[2] is None]
    chosen = by_parser or rows
    return [b if a == market_id else a for a, b, _ in chosen], chosen[0][2]


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
