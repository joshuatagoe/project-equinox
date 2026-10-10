"""Shared test data: the golden canonical markets (feat-01) that matcher and router tests use."""

from pathlib import Path

import pytest
from pydantic import TypeAdapter

from equinox.models import CanonicalMarket

GOLDEN = Path(__file__).parent / "golden" / "canonical_markets.json"


@pytest.fixture(scope="session")
def golden_markets() -> dict[str, CanonicalMarket]:
    """Every golden market, by market_id. Models are frozen, so tests can share them."""
    markets = TypeAdapter(list[CanonicalMarket]).validate_json(GOLDEN.read_bytes())
    return {market.market_id: market for market in markets}
