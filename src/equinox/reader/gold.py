"""The term reader's gold sets: each case's markets and the label of each pair (D58, feat-12).

- **Fed.** Every cross-venue pair of the meetings both venues list in `snapshot-2026-10-11`. The
  answer for each pair is what the Fed parsers' terms decide, so these labels cost nothing.
- **Scores.** Exact scores of two matches in `snapshot-2026-10-11-scores`, labelled by the score
  parsers' terms (D60, D61): the same score, the reversed score, and half time against full time.
  Each market is shown as a catalog read shows it: with its event's title and, on Kalshi, its
  strike fields (feat-12).
- **Labelled pairs** (`evals/pairs.json`). Catalog pairs a person labelled same or different after
  reading both venues' rules, including the traps titles fall for. The prompt was tuned on them.
- **Held-out pairs** (`evals/heldout.json`). Labelled the same way after the prompt was tuned, from
  series the labelled pairs don't use, and run once: the honest measure.
- **Traps** (`evals/traps.json`). The seven exact scores the model read as the same bet in the
  2026-10-11 full read although their scores are reversed; the score parser found them (feat-11).
- **Score pairs** (`evals/score_pairs.json`). Groups of the live catalog's score markets, grouped
  as `catalog read` groups them and labelled by the parsers, split by match into a half the reader
  is tuned on and a half it is only judged on (feat-12).
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from equinox.adapters.base import TrackedEvent
from equinox.adapters.fetch import DEFAULT_SNAPSHOT, FixtureFetcher
from equinox.adapters.kalshi import DEFAULT_BASE_URL, KalshiAdapter
from equinox.adapters.kalshi_terms import strike_text
from equinox.adapters.polymarket import GAMMA_URL, PolymarketAdapter
from equinox.matcher import evaluate_pair
from equinox.models import CanonicalMarket, EquivalenceStatus
from equinox.models.catalog import MarketText, ReadableMarket
from equinox.sources import Settings, load_markets

EVALS = Path(__file__).resolve().parents[3] / "evals"
PAIRS, HELD_OUT, TRAPS = EVALS / "pairs.json", EVALS / "heldout.json", EVALS / "traps.json"
SCORE_PAIRS = EVALS / "score_pairs.json"
FED_SNAPSHOT = DEFAULT_SNAPSHOT.parent / "snapshot-2026-10-11"
SCORES_SNAPSHOT = DEFAULT_SNAPSHOT.parent / "snapshot-2026-10-11-scores"
SCORE_EVENTS = (
    (
        KalshiAdapter,
        ("KXEPLSCORE-26OCT12COVNEW", "KXEPL1HSCORE-26OCT12COVNEW", "KXUCLSCORE-26OCT13RBLPSV"),
    ),
    (
        PolymarketAdapter,
        (
            "epl-cov-new-2026-10-12-exact-score",
            "epl-cov-new-2026-10-12-first-half-exact-score",
            "ucl-rbl-psv-2026-10-13-exact-score",
        ),
    ),
)
FIVE = ((0, 0), (1, 0), (0, 1), (2, 1), (1, 2))  # a draw, both wins, and a score both ways
COVENTRY, LEIPZIG = "coventry city vs newcastle united", "rb leipzig vs psv"
# name, match, the periods read on each venue, the scores
SCORE_CASES = (
    ("Scores: Coventry v Newcastle, full time", COVENTRY, ("full_time",), ("full_time",), FIVE),
    (
        "Scores: Coventry v Newcastle, half time against full time",
        COVENTRY,
        ("first_half",),
        ("first_half", "full_time"),
        FIVE[:3],
    ),
    ("Scores: RB Leipzig v PSV, full time", LEIPZIG, ("full_time",), ("full_time",), FIVE),
)


@dataclass
class Case:
    """One request: its markets, and the label of each pair among them (True: the same bet)."""

    name: str
    markets: list[ReadableMarket]
    labels: dict[tuple[str, str], bool]


def fed_cases() -> list[Case]:
    """One case per meeting both venues list, labelled by the Fed parsers' own terms."""
    loaded = load_markets(Settings(source="fixtures", snapshot=FED_SNAPSHOT), with_books=False)
    meetings: dict[str, list[CanonicalMarket]] = {}
    for market in loaded.markets:
        if market.terms is not None:
            meetings.setdefault(str(market.terms.observed_on), []).append(market)
    cases = []
    for day, markets in sorted(meetings.items()):
        if len({m.venue for m in markets}) < 2:
            continue
        cases.append(Case(f"Fed {day}", [_readable(m) for m in markets], _labels(markets)))
    return cases


def score_cases() -> list[Case]:
    """Each case's markets from the score snapshot, labelled by the score parsers' own terms."""
    fetch = FixtureFetcher(SCORES_SNAPSHOT)
    markets: list[CanonicalMarket] = []
    for adapter_class, events in SCORE_EVENTS:
        tracked = [TrackedEvent(event, "") for event in events]
        adapter = adapter_class(fetch, tracked, "fixture", lambda: fetch.captured_at)
        markets += adapter.list_markets().markets
    shown = _as_listed(fetch)
    cases = []
    for name, match, kalshi, polymarket, scores in SCORE_CASES:
        periods = {"kalshi": kalshi, "polymarket": polymarket}
        chosen = sorted(
            (m for m in markets if _is_score(m, match, periods[m.venue], scores)),
            key=lambda m: m.market_id,
        )
        readable = [_readable(m, *shown.get(m.market_id, ("", ""))) for m in chosen]
        cases.append(Case(name, readable, _labels(chosen)))
    return cases


def _as_listed(fetch: FixtureFetcher) -> dict[str, tuple[str, str]]:
    """Each score market's event title and Kalshi strike fields, as a catalog read sends them."""
    shown = {}
    for event_id in SCORE_EVENTS[0][1]:
        event = fetch(f"{DEFAULT_BASE_URL}/events/{event_id}?with_nested_markets=true")["event"]
        for raw in event["markets"]:
            shown[f"kalshi:{raw['ticker']}"] = (event["title"], strike_text(raw))
    for slug in SCORE_EVENTS[1][1]:
        event = fetch(f"{GAMMA_URL}/events?slug={slug}")[0]
        for raw in event["markets"]:
            shown[f"polymarket:{raw['id']}"] = (event["title"], "")
    return shown


def labelled_cases(path: Path = PAIRS) -> list[Case]:
    """One case per labelled catalog pair (the labelled, held-out and trap sets)."""
    cases = []
    for item in json.loads(path.read_text(encoding="utf-8")):
        a, b = _from_json(item["a"]), _from_json(item["b"])
        same = item["label"] == "same"
        cases.append(Case(item["name"], [a, b], {(a.market_id, b.market_id): same}))
    return cases


def score_pair_cases(half: str, path: Path = SCORE_PAIRS) -> list[Case]:
    """The score set's cases in one half: "tune" or "judge"."""
    cases = []
    for item in json.loads(path.read_text(encoding="utf-8")):
        if item["half"] == half:
            markets = [_from_json(m) for m in item["markets"]]
            labels = {(a, b): same for a, b, same in item["labels"]}
            cases.append(Case(item["name"], markets, labels))
    return cases


def _labels(markets: Sequence[CanonicalMarket]) -> dict[tuple[str, str], bool]:
    """Every cross-venue pair, labelled by the parsers' terms: True when the same bet."""
    return {
        (a.market_id, b.market_id): evaluate_pair(a, b).status == EquivalenceStatus.EQUIVALENT
        for a in markets
        for b in markets
        if a.venue < b.venue
    }


def _is_score(
    market: CanonicalMarket,
    match: str,
    periods: Sequence[str],
    scores: Sequence[tuple[int, int]],
) -> bool:
    terms = market.terms
    wanted = {f"{period}_score_{h}_{a}" for period in periods for h, a in scores}
    return terms is not None and terms.subject == match and terms.measure in wanted


def _readable(market: CanonicalMarket, event_title: str = "", strike: str = "") -> ReadableMarket:
    return ReadableMarket(
        market.market_id,
        market.venue,
        event_title,
        market.title,
        market.outcome_label,
        market.trading_closes_at,
        MarketText(market.rules_text, strike),
    )


def _from_json(item: dict[str, Any]) -> ReadableMarket:
    closes = item.get("closes_at")
    return ReadableMarket(
        item["market_id"],
        item["venue"],
        item["event_title"],
        item["title"],
        item["outcome_label"],
        datetime.fromisoformat(closes) if closes else None,
        MarketText(item["rules"], item.get("strike", "")),
    )
