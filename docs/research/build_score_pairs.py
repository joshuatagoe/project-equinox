"""Write `evals/score_pairs.json`: live score groups labelled by the score parsers (feat-12).

    python docs/research/build_score_pairs.py <catalog file> [groups]

The model's reversed-score mistakes happened in groups of up to 20 markets, read together. So the
cases are made the way `catalog read` and `catalog check` make their requests: the parsers' score
pairs, planned with `run.plan`. One group is kept per match, the one with the most same bets, at
most `groups` (16), and each pair of markets from two venues in a group is labelled by the
parsers' terms: the same key is the same bet.
The matches, sorted, alternate between the half the reader is tuned on and the half it is only
judged on, so the two share no match. A gold set is never overwritten.
"""

import json
import sys
from pathlib import Path

from equinox.catalog import Catalog
from equinox.catalog.readings import to_check
from equinox.reader import run

OUT = Path(__file__).resolve().parents[2] / "evals" / "score_pairs.json"
SCORE = "|official_match_score|"


def main(catalog: Path, groups: int = 16) -> None:
    if OUT.exists():
        raise SystemExit(f"{OUT} exists: a gold set is never overwritten")
    found = Catalog(catalog.resolve())
    with found.connect() as db:
        keys = dict(db.execute("SELECT market_id, terms_key FROM entries"))
    pairs, markets, _ = to_check(found)
    scores = [p for p in pairs if SCORE in (keys.get(p.a) or "") and SCORE in (keys.get(p.b) or "")]
    chosen: dict[str, run.Call] = {}
    for call in run.plan(scores, markets, 10**9):
        match = _match(call, keys)
        if match and _same_bets(call, keys) > _same_bets(chosen.get(match), keys):
            chosen[match] = call  # the match's request with the most same bets
    items = [
        _item(match, chosen[match], keys, "tune" if n % 2 == 0 else "judge")
        for n, match in enumerate(sorted(chosen)[:groups])
    ]
    OUT.write_text(json.dumps(items, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    labels = [same for item in items for _, _, same in item["labels"]]
    count = sum(len(item["markets"]) for item in items)
    print(f"{len(items)} groups, {count} markets, {len(labels)} pairs, {sum(labels)} same bets")


def _match(call: run.Call, keys: dict[str, str | None]) -> str:
    """The group's match, "subject|date", or "" when its markets are from more than one match."""
    found = set()
    for market in call.markets:
        subject, _measure, _by, day, *_ = keys[market].split("|")
        found.add(f"{subject}|{day}")
    return found.pop() if len(found) == 1 else ""


def _same_bets(call: run.Call | None, keys: dict[str, str | None]) -> int:
    if call is None:
        return -1
    return sum(keys[p.a] == keys[p.b] for p in call.pairs)


def _item(match: str, call: run.Call, keys: dict[str, str | None], half: str) -> dict:
    listed = list(call.markets.values())  # in the order the request reads them
    labels = [
        [a.market_id, b.market_id, keys[a.market_id] == keys[b.market_id]]
        for a in listed
        for b in listed
        if a.venue < b.venue
    ]
    return {
        "name": f"Score group: {match}",
        "match": match,
        "half": half,
        "markets": [_market(m, keys) for m in listed],
        "labels": labels,
    }


def _market(market, keys: dict[str, str | None]) -> dict:
    return {
        "market_id": market.market_id,
        "venue": market.venue,
        "event_title": market.event_title,
        "title": market.title,
        "outcome_label": market.outcome_label,
        "closes_at": market.closes_at.isoformat() if market.closes_at else None,
        "rules": market.text.rules,
        "strike": market.text.strike,
        "terms_key": keys[market.market_id],
    }


if __name__ == "__main__":
    main(Path(sys.argv[1]), *(int(n) for n in sys.argv[2:3]))
