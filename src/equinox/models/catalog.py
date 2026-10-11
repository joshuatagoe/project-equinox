"""The catalog: every open market on both venues (D48, D49, D50; architecture section 5.1).

A catalog holds about 340,000 Yes/No markets (K12, P11). So an entry is a small frozen dataclass
with what the catalog needs to search and match, not a full canonical market: it has no order
books and no rules text. Terms are filled in only for markets of a family Equinox can read. The
summary records what one refresh read and found; a row is one market as the catalog shows it.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from equinox.models.canonical import ContractTerms


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    market_id: str  # "<venue>:<native_id>", the same form as a canonical market
    venue: str
    event_title: str
    title: str
    outcome_label: str
    closes_at: datetime | None  # when the market stops trading or resolves; used to block pairs
    tradable: bool
    yes_ask: Decimal | None  # the best price to buy YES, from the listing; None if nobody sells
    no_ask: Decimal | None
    terms: ContractTerms | None = None


@dataclass(frozen=True, slots=True)
class MarketText:
    """What the term reader reads besides the title (D57): the rules, and any strike fields."""

    rules: str
    strike: str = ""  # the venue's structured strike fields as JSON, "" when it has none


@dataclass(frozen=True, slots=True)
class ReadableMarket:
    """A catalog market with everything the term reader reads (D57)."""

    market_id: str
    venue: str
    event_title: str
    title: str
    outcome_label: str
    closes_at: datetime | None
    text: MarketText

    @property
    def full_text(self) -> str:
        """Everything the venue says about the market, which a reading's evidence must quote."""
        return "\n".join((self.event_title, self.title, self.outcome_label, self.text.rules))


@dataclass(frozen=True)
class CatalogPage:
    """One page of a venue's listing, as an adapter reads it."""

    entries: list[CatalogEntry]
    skipped: int  # markets left out because they aren't Yes/No
    texts: dict[str, MarketText] = field(default_factory=dict)  # by market ID


SAME_BET, UNCLEAR, NO_MATCH = "same bet", "unclear", "no match"
STATUSES = (SAME_BET, UNCLEAR, NO_MATCH)
"""A catalog market's status, best first. Only "same bet" can be priced; "unclear" never is."""


@dataclass(frozen=True)
class CatalogSummary:
    """What one refresh read and found. Saved with the catalog and printed by the CLI."""

    refreshed_at: datetime  # when the markets were read: now, or the snapshot's capture time
    source: str  # "live", or the snapshot folder's name
    read_seconds: float  # how long reading the venues took
    compare_seconds: float  # how long comparing the markets took
    entries: dict[str, int]  # markets listed per venue
    skipped: int  # markets left out because they aren't Yes/No or couldn't be read
    same_bet_groups: int  # outcomes listed on two or more venues with the same terms
    candidates: int  # cross-venue pairs whose titles were compared
    distinct: int  # candidates found to be different bets
    ambiguous: int  # candidates that may be the same bet: shown as unclear, never routed
    vetoes: dict[str, int]  # why candidates were distinct: "Numbers", "Months", "Low score", ...

    @property
    def total(self) -> int:
        return sum(self.entries.values())

    def describe(self, now: datetime) -> str:
        """ "840 markets (Kalshi 371, Polymarket 469), read live 2026-10-11 14:06 UTC (2 hours
        ago)": the line both interfaces show."""
        venues = ", ".join(f"{name.capitalize()} {n:,}" for name, n in self.entries.items())
        read = "read live" if self.source == "live" else f"from {self.source}, captured"
        return (
            f"{self.total:,} markets ({venues}), {read} {self.refreshed_at:%Y-%m-%d %H:%M} UTC "
            f"({_age((now - self.refreshed_at).total_seconds())} ago)"
        )


@dataclass(frozen=True, slots=True)
class CatalogRow:
    """One market as the catalog shows it, with its best match on another venue, if any."""

    market_id: str
    venue: str
    event_title: str
    title: str
    outcome_label: str
    yes_ask: Decimal | None
    no_ask: Decimal | None
    terms_key: str | None  # its outcome's key, for a market whose terms Equinox can read
    status: str  # one of STATUSES
    partner: str | None  # the matching market on another venue
    partner_title: str | None
    score: Decimal | None  # the title score, for a pair compared by title
    reasons: tuple[str, ...]  # why the pair matches or may match
    read_by: str | None = None  # the model that read both markets' terms, when one did (D57)


def _age(seconds: float) -> str:
    for size, unit in ((86_400, "day"), (3_600, "hour"), (60, "minute")):
        if seconds >= size:
            count = int(seconds // size)
            return f"{count} {unit}{'s' if count != 1 else ''}"
    return "under a minute"
