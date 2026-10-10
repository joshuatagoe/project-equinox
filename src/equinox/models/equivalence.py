"""Match results and clusters (architecture section 8.1)."""

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from equinox.models.canonical import CanonicalMarket, Frozen


class EquivalenceStatus(StrEnum):
    EQUIVALENT = "EQUIVALENT"
    AMBIGUOUS = "AMBIGUOUS"
    DISTINCT = "DISTINCT"


class MatchResult(Frozen):
    market_a: str  # market_id
    market_b: str
    status: EquivalenceStatus
    method: Literal["terms", "text"]
    reasons: tuple[str, ...] = ()
    risk_flags: tuple[str, ...] = ()
    text_score: Decimal | None = None

    @model_validator(mode="after")
    def _text_never_equivalent(self) -> "MatchResult":
        if self.method == "text" and self.status == EquivalenceStatus.EQUIVALENT:
            raise ValueError("a text match can be AMBIGUOUS at most (D15)")
        return self


class EquivalenceCluster(Frozen):
    cluster_id: str  # the normalized terms key as text
    markets: tuple[CanonicalMarket, ...] = Field(min_length=1)
    pairs: tuple[MatchResult, ...] = ()  # the EQUIVALENT pairs among the members
    ambiguous: tuple[MatchResult, ...] = ()  # AMBIGUOUS pairs involving a member; never routed
    risk_flags: tuple[str, ...] = ()
