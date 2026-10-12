"""feat-12: a catalog market whose venue names no resolution source can still be priced.

127 of 229 model-read same bets on 2026-10-12 had a Polymarket market with no `resolutionSource`;
some had none on their event either, so the adapter skipped them and the pair couldn't be priced.
A market loaded for a catalog pair (no family) is now built with "an unnamed source", and the trace
flags that its source differs. A tracked family keeps the rule that a market without a source is
bad data and is skipped (feat-02b).
"""

import copy

from equinox.adapters.base import TrackedEvent
from equinox.adapters.fetch import DEFAULT_SNAPSHOT, FixtureFetcher
from equinox.adapters.polymarket import PolymarketAdapter

PAIR = DEFAULT_SNAPSHOT.parent / "snapshot-2026-10-11-pair"
SLUG, MBAPPE = "ballon-dor-winner-2026", "608540"


def no_sources(url):
    """The recorded responses, with every resolution source in the event left empty."""
    found = copy.deepcopy(FixtureFetcher(PAIR)(url))
    if "events?slug=" in url:
        for event in found:
            event["resolutionSource"] = ""
            for market in event["markets"]:
                market["resolutionSource"] = ""
    return found


def listed(family):
    adapter = PolymarketAdapter(
        no_sources,
        [TrackedEvent(SLUG, family)],
        "fixture",
        lambda: FixtureFetcher(PAIR).captured_at,
    )
    return adapter.list_markets()


def test_a_catalog_market_without_a_source_is_built_with_an_unnamed_source():
    result = listed("")
    market = next(m for m in result.markets if m.native_id == MBAPPE)
    assert market.resolution_source.name == "an unnamed source"
    assert market.resolution_source.institution == "an unnamed source"
    assert not any(MBAPPE in w and "skipped" in w for w in result.warnings)


def test_a_tracked_familys_market_without_a_source_is_still_skipped():
    result = listed("ballon_dor")
    assert MBAPPE not in {m.native_id for m in result.markets}
    assert any(w.startswith(f"polymarket: market {MBAPPE} skipped: ") for w in result.warnings)
