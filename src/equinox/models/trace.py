"""The trace: the full record of one simulation, in typed sections (D30)."""

from pydantic import model_validator

from equinox.models.canonical import Frozen, UtcDatetime
from equinox.models.equivalence import EquivalenceCluster
from equinox.models.routing import Decision, OrderRequest, RoutingStatus, VenueQuote


class EquinoxTrace(Frozen):
    trace_id: str
    created_at: UtcDatetime
    status: RoutingStatus
    order: OrderRequest | None
    cluster: EquivalenceCluster | None
    quotes: tuple[VenueQuote, ...] = ()
    decision: Decision | None = None
    rationale: str
    assumptions: tuple[str, ...] = ()  # A1, A2, A3 and A5, worded for the reader
    warnings: tuple[str, ...] = ()  # adapter warnings plus quote warnings, in plain words

    @model_validator(mode="after")
    def _decision_only_when_routed(self) -> "EquinoxTrace":
        if (self.status == RoutingStatus.ROUTED) != (self.decision is not None):
            raise ValueError("a trace has a decision exactly when its status is ROUTED")
        return self
