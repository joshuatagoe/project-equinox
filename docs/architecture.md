# Project Equinox: Architecture

**Revised 2026-10-10.** This replaces the first version written in the Antigravity session. The decisions behind it are D1–D30 and D37–D52 in [DECISIONS.md](DECISIONS.md). The venue facts it relies on, each with a source and a label, are in [research/venue_facts.md](research/venue_facts.md). Each feature PRD in `docs/features/` names the sections it implements. When a PRD and this document disagree, this document wins, and the disagreement is a bug in the PRD.

---

## 1. Summary

Equinox is a prototype with a command line and a local web UI. It looks at everything open on two venues, matches only what it can prove is the same bet, and explains what it can't. It does five things:

1. **Reads** prediction markets from two venues, Kalshi and Polymarket, through their live public APIs or a saved snapshot: every open market into a **catalog**, and in full the events of each **family** whose terms it can read, found automatically (D47–D49).
2. **Normalizes** each venue's response into one venue-neutral shape, the **canonical market**.
3. **Groups** markets that pay out under exactly the same conditions. It decides this by comparing their **contract terms**, not by how similar their titles are.
4. **Simulates** a buy order on every market in the group. For each one it walks the order book and adds that venue's fees, then picks the cheapest venue that can fill the whole order.
5. **Explains** the decision in a **trace**: which markets were matched and why, what each venue would cost, which venues were excluded and why, and what could still go wrong.

### Running example

"Will the Fed hold rates at its October 27–28, 2026 meeting?" This is Kalshi `KXFEDDECISION-26OCT-H0` and Polymarket market `2589812` ("No change"). All numbers below come from the snapshot taken at 2026-10-10T20:44:29Z, and `docs/research/running_example.py` reproduces them.

| Order | Kalshi | Polymarket | Decision |
|---|---|---|---|
| Buy 100 YES | 100 × $0.85 + $0.90 fee = **$85.90** | 100 × $0.84 + $0.672 fee = **$84.672** | Polymarket, $1.228 less |
| Buy 100 NO | 100 × $0.16 + $0.95 fee = **$16.95** | 100 × $0.17 + $0.7055 fee = **$17.7055** | Kalshi, $0.7555 less |
| Buy 5,000 NO | walks 2 price levels: average $0.1689, $49.14 fee = **$893.7951** | 5,000 × $0.17 + $35.275 fee = **$885.275** | Polymarket, $8.5201 less |

The last two rows give different answers for the same market. Kalshi's 16¢ price level holds fewer contracts than the order needs, so at 5,000 contracts the order spills onto its 17¢ level. Ignoring depth would pick the wrong venue: priced at Kalshi's best level alone, 5,000 NO would cost $847.04 and beat Polymarket's $885.275. Charging the fee on the average price happens to give the same $49.14 here; it changes the result when an order spans prices far apart (D5).

### Third-venue check

Meridian, the user's binary-stock-outcome project, is **not integrated**. Section 9 checks that a venue like it would fit without changes to the matcher or the router. The check has two parts: a mapping on paper, and hand-built Meridian-like markets in the test data that go through the real matcher and router. Its example is "Will Apple (AAPL) close above $330 on October 12, 2026?", using the values of Polymarket market `5455686` and a Meridian-style `AAPL-330-2026-10-12`.

### Words used here

| Word | Meaning |
|---|---|
| Outcome | YES or NO. Each pays $1 per contract if it happens, otherwise $0. |
| Ask / bid | An ask is an offer to sell a contract at a price; a bid is an offer to buy one. |
| Level | One price in the order book and how many contracts are available at it. |
| Depth | The levels beyond the best price. Walking the book means filling the order from the cheapest ask upward. |
| Fill | The part of the order taken at one level: (price, quantity). |
| Average price | Total price paid divided by contracts filled, before fees. Often called VWAP. |
| Slippage | Average price minus the best ask. |
| Contract terms | What a market pays on: subject, measure, how it is measured, when, the comparison and the threshold (§4.4). |
| Cluster | A group of markets on different venues with the same terms. |
| Trace | The full record of one simulation (§8). |
| Fixture | A saved, unedited API response used instead of a live request. |

---

## 2. Scale and availability

One person runs one command or one local web page on one machine. Markets load in three tiers, because reading everything in full is not practical (D49):

| Tier | What | Requests | When |
|---|---|---|---|
| Catalog | Every open market on both venues as a lean entry: title, dates, best YES and NO ask, terms where a parser exists. Kalshi from `/events?status=open&with_nested_markets=true` (no combo markets, K12); Polymarket from `/events/keyset?closed=false` paged with `after_cursor` (P11). | 286 in the recorded refresh: 151 MiB with gzip (1.9 GB without), 94 s to read and 158 s in all, at 383 MiB of memory (2026-10-11, D55) | `python -m equinox catalog refresh`, cached in `.cache/equinox/` (D48) |
| Families | The discovered events of each family Equinox can read (Fed decisions: K13, P12), loaded from their listings without books | A few: one discovery request and one listing per venue | Every live command and page load |
| Books | Order books for the markets being priced: on the web, the one pair on the order ticket | 1 per Kalshi market, 2 per Polymarket market | On demand |

Equinox makes its requests one at a time, each with a 10-second timeout, and asks for gzip (D55). The research crawls paced theirs 150 ms apart and made about 700 requests without a rate-limit error; Equinox does not pace, and the recorded refresh made its 286 requests back to back without one. The catalog refresh retries a timeout, a dropped connection, a 429 or a 5xx twice; the command line and the web UI fall back to the snapshot instead (D17). A refresh streams page by page, so it holds one page of raw JSON at a time, but it keeps every lean entry in memory to compare them. The research snapshot also captured Polymarket's AAPL event for the §9 test data.

**Availability.** If a venue fails, its markets come from the snapshot and the trace says so (D17). We run no load test, because there is no concurrency to test.

---

## 3. System overview

```mermaid
flowchart LR
    subgraph IN["Interfaces"]
        CLI["cli.py, cli_catalog.py<br/>markets, match, simulate, catalog"]
        UI["server.py and web/<br/>markets, event and order-ticket pages"]
    end
    SRC["sources.py and catalog/<br/>data sources, discovery, books on demand,<br/>catalog refresh and its SQLite file"]
    subgraph AD["Adapters: the only venue-aware code"]
        K["kalshi.py"]
        P["polymarket.py"]
        F["fetch.py<br/>HTTP fetcher or fixture fetcher"]
    end
    subgraph EN["Engines: pure functions, no venue names"]
        MA["matcher/<br/>terms rules, text fallback,<br/>catalog index and comparison"]
        RO["router/<br/>depth walk, fees, decision"]
    end
    subgraph MO["Models: schemas and validation only"]
        CM["canonical.py, equivalence.py, routing.py, trace.py"]
    end
    CLI & UI --> SRC
    SRC -->|discover, list, fetch books| K & P
    K & P --> F
    K & P -->|canonical markets and catalog entries| SRC
    SRC -->|markets| MA
    MA -->|clusters and candidates| SRC
    SRC -->|order and booked cluster| RO
    RO -->|EquinoxTrace| SRC
    AD -.-> MO
    EN -.-> MO
```

| Module | Owns | Rule it keeps |
|---|---|---|
| `models/` | Every shape that crosses a module boundary, plus its validation | No I/O and no venue names. Imports only the standard library and `pydantic`. |
| `adapters/` | Venue URLs, field names, units, sort orders, paging, and the discovery rules and term parsers for each family | Returns canonical markets and catalog entries that are fully normalized: prices in dollars between 0 and 1, books (when fetched) sorted best-first, terms filled in where the family is supported. Nothing downstream ever sees a venue field. |
| `matcher/` | Equivalence rules, clusters, confidence, and for the catalog the title index (`index.py`, D50) and the comparison of every market (`compare.py`, D54) | Pure. Imports only `models/`. Contains no venue names. |
| `router/` | Depth walking, fees, eligibility, decision, rationale and trace | Pure. Imports only `models/`. Contains no venue names. The time comes in as an argument. |
| `sources.py` | Settings, data sources (snapshots and live), discovery with its pinned fallback, loading families, fetching books on demand | Wires adapters, matcher and router together for both interfaces; neither interface imports the other (D52). |
| `catalog/` | `catalog refresh` (`__init__.py`): pages every open market through the adapters and compares them with `matcher/compare.py`; the catalog file (`store.py`): one SQLite database per refresh, searchable by title words (D53); the model's decisions kept across a refresh (`carry.py`, D91); the server's hourly refresh (`background.py`, D90) | A failed refresh keeps the previous catalog (D48). |
| `reader/` | The term reader (§6.5): the prompt, the model client and its cache, the checks, reading the catalog, and the evals | The model only fills in terms; deterministic checks and the matcher's rules decide (D57). |
| `cli.py`, `cli_catalog.py` | Arguments, output and exit codes for `markets`, `match`, `simulate` and `catalog` | Calls `sources.py` and `catalog/`; no loading logic of its own. |
| `server.py`, `web/` | The web UI's pages (§8.3), one module per page, and `/health` | Renders what the matcher and router decide, through `sources.py` and `catalog/`. Adds no matching or routing logic and names no venue. No JSON API (D21, D45). |

**Quality gate (D52).** Ruff's C901 rule caps function complexity at 10, and `tests/test_quality.py` caps modules at 300 lines and functions at 40, checks that the interfaces don't import each other, and checks the README's map of the code.

**Guard.** `tests/test_layering.py` parses the source of `matcher/` and `router/`. It fails if either imports anything outside `equinox.models`, the standard library or `pydantic`, or if the words "kalshi", "polymarket" or "meridian" appear in their code. This is how the brief's rule "routing logic should not contain venue-specific assumptions" is checked on every run.

**Stubs and seams.**
- **Fetching.** Adapters never call HTTP themselves. They get a `Fetcher`, and there are two: a live one (`urllib`) and a fixture one that looks the URL up in a snapshot's `index.json`. An adapter can't tell which one it has.
- **A new venue** plugs in as one adapter (discovery, listing, books), a fixture, and one line in the adapter registry. Section 9 checks this against Meridian.
- **Time** is passed in (`now` for the router, a `clock` for adapters) so that the staleness check and trace timestamps are deterministic in tests.

---

## 4. Canonical model

All of these live in `src/equinox/models/`. Every model is frozen (`ConfigDict(frozen=True, extra="forbid")`). Money and quantities are `Decimal`. Every datetime must carry a time zone and is stored in UTC.

### 4.1 Books and fees (`models/canonical.py`)

```python
Outcome = Literal["YES", "NO"]

class OrderBookLevel(Frozen):
    price: Decimal      # dollars per contract, 0 < price < 1
    quantity: Decimal   # contracts, > 0, fractional allowed

class OutcomeBook(Frozen):
    asks: tuple[OrderBookLevel, ...] = ()   # what it costs to BUY this outcome: cheapest first
    bids: tuple[OrderBookLevel, ...] = ()   # what you'd get to SELL it: highest first
    depth_complete: bool = True             # False if the venue returned only part of the book

class Fill(Frozen):
    price: Decimal
    quantity: Decimal

class FeeSchedule(Frozen):
    coefficient: Decimal        # >= 0. Kalshi 0.07 x series multiplier; Polymarket feeSchedule.rate; 0 = no fee
    exponent: int = 1           # >= 1
    rounding_step: Decimal      # > 0. Kalshi 0.01 (A3); Polymarket 0.00001

    def fee(self, fills: Sequence[Fill]) -> Decimal:
        """Round up, once, the sum over fills of coefficient x quantity x (price x (1 - price)) ** exponent."""
```

### 4.2 Supporting types

```python
class Collateral(Frozen):
    asset: str          # "USD", "USDC", "devnet USDC"
    has_value: bool     # False for test money (D24)

class ResolutionSource(Frozen):
    name: str
    url: str | None = None
    # institution: the URL's host without "www." (e.g. "federalreserve.gov"), else name.lower() (D18)
```

### 4.3 The market

```python
class CanonicalMarket(Frozen):
    market_id: str                   # "<venue>:<native_id>", e.g. "kalshi:KXFEDDECISION-26OCT-H0"
    venue: str                       # "kalshi" | "polymarket"; used for display only
    native_id: str
    event_id: str
    title: str                       # the venue's question, for display
    outcome_label: str               # e.g. "Fed maintains rate", "No change", "$330"
    rules_text: str = ""
    terms: ContractTerms | None      # None when the adapter has no parser for this family
    resolution_source: ResolutionSource
    collateral: Collateral
    tradable: bool                   # can an order be placed right now (D25)
    trading_closes_at: datetime | None
    resolves_at: datetime | None     # when the venue expects the outcome to be known
    captured_at: datetime            # when the book was read
    data_source: Literal["live", "fixture"]
    fees: FeeSchedule
    books: dict[Outcome, OutcomeBook]   # must contain "YES" and "NO" (D14)
    venue_metadata: dict[str, Any] = {}
```

### 4.4 Contract terms (D22)

```python
Comparison = Literal["gt", "ge", "lt", "le", "eq", "between"]

class ContractTerms(Frozen):
    subject: str                 # "FOMC", "AAPL"
    measure: str                 # "fed_upper_bound_change" | "close_price"
    measured_by: str             # "fomc_statement" | "pyth_regular_close" | "official_close"
    observed_on: date            # the date in New York (America/New_York)
    observed_at: datetime | None = None   # the exact instant, when the venue states one
    comparison: Comparison
    threshold: Decimal
    upper: Decimal | None = None # required for "between", forbidden otherwise
    unit: Literal["bps", "usd"]
    fallback_rules: tuple[str, ...] = ()  # the venue's edge-case rules in plain words
```

How markets map onto terms. The Fed rows are produced by the adapters from the snapshot. The two AAPL rows are hand-built test data for the §9 check; no adapter produces them.

| Market | subject | measure | measured_by | observed_on | comparison | threshold | unit |
|---|---|---|---|---|---|---|---|
| Kalshi `…-C26` "Cut >25bps" | FOMC | fed_upper_bound_change | fomc_statement | 2026-10-28 | lt | −25 | bps |
| Kalshi `…-C25` "Cut 25bps" | FOMC | fed_upper_bound_change | fomc_statement | 2026-10-28 | eq | −25 | bps |
| Kalshi `…-H0` "Fed maintains rate" | FOMC | fed_upper_bound_change | fomc_statement | 2026-10-28 | eq | 0 | bps |
| Kalshi `…-H25` / `…-H26` | FOMC | … | … | 2026-10-28 | eq / gt | 25 / 25 | bps |
| Polymarket "50+ bps decrease" | FOMC | fed_upper_bound_change | fomc_statement | 2026-10-28 | le | −50 | bps |
| Polymarket "25 bps decrease" / "No change" / "25 bps increase" | FOMC | … | … | 2026-10-28 | eq | −25 / 0 / 25 | bps |
| Polymarket "50+ bps increase" | FOMC | … | … | 2026-10-28 | ge | 50 | bps |
| §9 test data: Polymarket `5455686` "$330" | AAPL | close_price | pyth_regular_close | 2026-10-12, at 20:00Z | gt | 330 | usd |
| §9 test data: Meridian-style `AAPL-330-2026-10-12` | AAPL | close_price | pyth_regular_close | 2026-10-12, at 20:00Z | ge | 330 | usd |

### 4.5 Validation rules

These hold even if an adapter has a bug:

| Rule | Where | What it stops |
|---|---|---|
| 0 < price < 1, and quantity > 0 | `OrderBookLevel` | Cents not divided by 100; a zero-size level |
| Ask prices strictly rising and bid prices strictly falling | `OutcomeBook` | A book left in the venue's own order (both Kalshi and Polymarket list the best price last) |
| `books` has both YES and NO | `CanonicalMarket` | An adapter that forgot the NO side (D11) |
| `market_id == f"{venue}:{native_id}"` | `CanonicalMarket` | ID collisions across venues |
| Datetimes carry a time zone | all models | A naive time read as local time |
| `upper` is present exactly when the comparison is `between`, and is greater than `threshold` | `ContractTerms` | Malformed ranges |
| `coefficient >= 0`, `exponent >= 1`, `rounding_step > 0` | `FeeSchedule` | Negative or zero-step fees |
| JSON numbers are parsed as `Decimal` (`parse_float=Decimal`) | `Fetcher` | Polymarket's `feeSchedule.rate: 0.05` becoming the float 0.05000000000000000277 |
| A float is refused where an exact number is expected (D3) | every `Decimal` field except `text_score` | A float slipping past the fetcher into money or a threshold |
| A text match is never EQUIVALENT (D15) | `MatchResult` | The fallback routing a pair that has no terms |
| `eligible` is true exactly when `reasons` is empty | `VenueQuote` | A venue excluded without a reason, or a reason that doesn't exclude |
| `decision` is present exactly when the status is ROUTED | `EquinoxTrace` | A failure trace that still names a winner |
| A cluster holds at least one market | `EquivalenceCluster` | An empty cluster reaching the router |

### 4.6 Money rules

- **Cost of an order on one venue:** total cost = Σ(fill price × fill quantity) + `fees.fee(fills)`. Every comparison uses full precision.
- **Fee:** one formula for every venue (D13). It is summed per level and rounded up once per order. The worked examples are the table in §1, and `running_example.py` reproduces them.
- **Display:** amounts in the text output are rounded to the cent, half up. If two totals round to the same cent, both are shown to 5 decimal places. `--json` prints the exact `Decimal` values as strings.

---

## 5. Adapters

### 5.1 Contract (`adapters/base.py`)

```python
Fetcher = Callable[[str], Any]      # URL -> parsed JSON (parse_float=Decimal); raises FetchError
Clock = Callable[[], datetime]      # the time a response was read, time-zone aware

@dataclass(frozen=True)
class AdapterResult:
    markets: list[CanonicalMarket]
    warnings: list[str]             # e.g. "kalshi: market X has no terms: no parser for custom_strike {...}"

class VenueAdapter(ABC):
    venue: ClassVar[str]
    def __init__(self, fetch: Fetcher, tracked: list[TrackedEvent],
                 data_source: Literal["live", "fixture"], clock: Clock): ...
    @abstractmethod
    def discover(self, family: str) -> list[TrackedEvent]: ...    # D47; raises FetchError
    @abstractmethod
    def list_markets(self) -> AdapterResult: ...                   # the tracked events, no books (D49)
    @abstractmethod
    def fetch_books(self, market: CanonicalMarket) -> CanonicalMarket: ...   # the same market, with books
    @abstractmethod
    def list_open(self, page_size, max_pages) -> Iterator[CatalogPage]: ...  # every open market
    def fetch_markets(self) -> AdapterResult: ...                  # list_markets, then fetch_books for each
```

`CanonicalMarket.books` is optional (D49): a market from a listing carries `best_asks` (the best price to buy YES and NO, from the listing fields in K12 and P11) and no books until `fetch_books` adds them. The router refuses a market without books. `CatalogEntry` (`models/catalog.py`) is the catalog's lean record: market ID, venue, event title, title, outcome label, close time, tradable, best asks, and terms where a parser exists. `list_open` yields one `CatalogPage` per listing page: its entries, and how many markets were left out because they aren't Yes/No or couldn't be read. Markets already closed inside an event that is still open are not listed.

**Read time (D37).** An adapter whose venue puts no timestamp on a response (Kalshi) sets `captured_at` from `clock()`. Live runs pass `datetime.now(UTC)`. Fixture runs pass the snapshot's own capture time, which `FixtureFetcher.captured_at` reads from the snapshot's `index.json`, so fixture data never looks fresh. Tests pass a fixed clock.

`TrackedEvent` holds a venue's event ID (a Kalshi event ticker or a Polymarket slug) and its family. The only family that is discovered and tracked is `fed_decision`. Exact scores also have a parser on each venue (D61), but they are read from the catalog, not discovered: an event loaded without a family is parsed by what it is, and a tracked family keeps its own parser or none (D65). Adding a tracked family means adding a discovery rule and a parser to each adapter that lists it. Events are discovered (D47): Kalshi by series (K13), Polymarket by tag, open, neg-risk and title (P12). `tracked_events.json` is the pinned fallback when discovery can't run: a snapshot captured before discovery, or a failed live discovery request, in which case the events and books still come from the live API.

**Failures.** One market that fails validation is skipped, and a warning names it. A request that fails makes the CLI retry that whole venue with the fixture fetcher, and say so (D17). If the fixture is missing too, that venue contributes no markets and a warning.

### 5.2 Kalshi (`adapters/kalshi.py`)

**Requests:**
- `GET {base}/series/{series_ticker}`
- `GET {base}/events/{event_ticker}?with_nested_markets=true`
- `GET {base}/markets/{ticker}/orderbook`, once per market

The base URL is `https://external-api.kalshi.com/trade-api/v2` (K1).

| Canonical | From |
|---|---|
| native_id, event_id | `ticker`, `event_ticker` |
| title, outcome_label, rules_text | `title` (deprecated but returned; if missing, the event title plus `yes_sub_title`), `yes_sub_title`, `rules_primary` + `rules_secondary` |
| terms (`fed_decision`) | `custom_strike`: `{"Cut": "25"}` → eq −25; `{"Cut": ">25"}` → lt −25; `{"Hike": "0"}` → eq 0; `{"Hike": "25"}` → eq 25; `{"Hike": ">25"}` → gt 25. observed_on is the event's `strike_date` converted to the New York date. Fallback rule: "If the meeting is cancelled, 'Fed maintains rate' resolves Yes." Anything else → terms None, with a warning. |
| resolution_source | `series.settlement_sources[0]` (K7) |
| collateral | USD, has value |
| tradable | `status == "active"` |
| trading_closes_at, resolves_at | `close_time`, `expected_expiration_time` |
| fees | coefficient 0.07 × (event `fee_multiplier_override` if set, else series `fee_multiplier`), exponent 1, step 0.01 (K9, A3) |
| books (K4, K5) | YES asks = `no_dollars` at 1 − p, cheapest first. YES bids = `yes_dollars`, highest first. NO asks = `yes_dollars` at 1 − p. NO bids = `no_dollars`. An empty side is an empty book. |
| captured_at | `clock()` when the orderbook response was read; the API gives no timestamp (D37) |

### 5.3 Polymarket (`adapters/polymarket.py`)

**Requests:**
- `GET {gamma}/events?slug={slug}`
- `GET {clob}/book?token_id={token}`, for both tokens of every market

| Canonical | From |
|---|---|
| native_id, event_id | market `id`, event `id` |
| title, outcome_label, rules_text | `question`, `groupItemTitle`, `description` |
| outcome tokens | `json.loads(outcomes)` must be `["Yes", "No"]`, or the market is skipped with a warning. The token IDs come from `json.loads(clobTokenIds)`, index 0 YES. For `version: "v2"` with null `clobTokenIds`, use `positionIds` (P1). |
| terms (`fed_decision`) | `groupItemTitle`: "N bps decrease" → eq −N; "N+ bps decrease" → le −N; "No change" → eq 0; "N bps increase" → eq N; "N+ bps increase" → ge N. observed_on is the last day of "scheduled for Month D1-D2, YYYY" in `description`; if that text is absent, `endDate` converted to the New York date, with a warning. Fallback rules: "A change not shown in the brackets is rounded up to the nearest 25 bps." and "If no statement is released by the end date of the next scheduled meeting, 'No change' resolves Yes." |
| resolution_source | `resolutionSource` (the name is the URL's host) |
| collateral | USDC, has value |
| tradable | `active and not closed and acceptingOrders` (P3) |
| trading_closes_at, resolves_at | None (Polymarket has no such field), `endDate` |
| fees | `feesEnabled` false → coefficient 0. Otherwise `feeSchedule.rate` and `feeSchedule.exponent`. Step 0.00001 (P7, P8). |
| books (P4, P5) | YES book from the YES token's `asks` and `bids`; NO book from the NO token's. Both are re-sorted best-first. The mirrored levels are never merged. |
| captured_at | The earlier of the two books' `timestamp` values (epoch milliseconds) |

---

## 6. Equivalence (`matcher/`)

**Definition (D8).** Two markets are equivalent if and only if holding YES on one pays out under exactly the same real-world conditions as holding YES on the other.

### 6.1 Rules (D23, applied in order to each cross-venue pair)

```mermaid
flowchart TD
    A["Pair of markets on different venues"] --> B{"Both have terms?"}
    B -->|no| T["Text fallback<br/>at most AMBIGUOUS"]
    B -->|yes| C{"Same subject, measure, unit<br/>and observed_on, and the same<br/>observed_at if both state one?"}
    C -->|no| D1["DISTINCT<br/>different event"]
    C -->|yes| G["Normalize on the measure's grid<br/>Fed change grid is 25 bps<br/>lt t becomes le t-25, gt t becomes ge t+25"]
    G --> E{"Same direction and threshold?"}
    E -->|no| D2["DISTINCT<br/>different outcome"]
    E -->|yes| H{"Same measured_by?"}
    H -->|no| AM["AMBIGUOUS<br/>measured differently, never routed"]
    H -->|yes| O{"observed_at stated<br/>by only one market?"}
    O -->|yes| AM2["AMBIGUOUS<br/>observation time unknown, never routed"]
    O -->|no| EQ["EQUIVALENT<br/>plus risk flags"]
```

- **Direction** groups `gt` with `ge` as "above", and `lt` with `le` as "below". `eq` and `between` are their own groups. After grid normalization, a pair that differs only between `gt` and `ge` is "same direction and threshold".
- **Risk flags** are attached to an EQUIVALENT pair and copied into the trace:
  - **The strictness differs** (`gt` vs `ge`): "At exactly 330 USD, Polymarket pays No and Meridian pays Yes."
  - **Equal only on the grid:** "Equal only for moves in 25 bps steps."
  - **The fallback rules differ:** both venues' rules are listed.
  - **The resolution-source institutions differ** (D18).

### 6.2 Clusters

A cluster is every market whose normalized terms key is identical:

> (subject, measure, measured_by, observed_on, observed_at when stated, direction, normalized threshold, upper, unit)

A stated `observed_at` is compared as an instant in UTC (D23, D42), so two markets that observe the same day at different times never share a cluster.

A cluster may hold one market. By construction every pair inside a cluster is EQUIVALENT, and a test checks that. A cluster's `ambiguous` list holds the AMBIGUOUS pairs that involve its members. The trace shows them, but they are never routed.

### 6.3 Text fallback

Only markets without terms reach it, and the result can never be EQUIVALENT:
- Candidates are cross-venue pairs whose token Jaccard (shared words over all words, stop words removed) is at least 0.3.
- **Veto → DISTINCT:**
  - numbers differ, ignoring four-digit years from 1900–2099;
  - a known entity differs: US state names, month names, or a "cut" vs "hike" style pair from a small list.
- Every other candidate → AMBIGUOUS, with its score.

**At catalog scale (D50).** The catalog compares 133,002 Kalshi markets with 207,646 Polymarket Yes/No markets (K12, P11), which is about 28 billion pairs, so candidates come from `matcher/index.py` first:
- Each title (with the outcome label) is reduced to its informative words: stop words removed, and a word dropped when it appears in more than 2% of one venue's titles (and in more than 50 of them, so a small sample keeps its words).
- An inverted index maps each informative word and closing day to the markets with both.
- A cross-venue pair becomes a candidate only if its close dates are within 3 days of each other and it shares at least two informative words.
- Each candidate then goes through the rules above, comparing the title plus the outcome label where the label adds words (some titles leave the outcome out: "Who will the next Pope be?" with the label "Pietro Parolin"). A pair where both markets have terms is left to the terms.

`matcher/compare.py` gives every catalog market one status (D54): **same bet** when its terms key equals that of a market on another venue (§6.2), **unclear** when a title candidate is AMBIGUOUS (the most similar one is kept, with its score and reasons), and **no match** otherwise. The catalog records, per refresh, how many pairs were candidates, how many each veto turned DISTINCT, and how many stayed AMBIGUOUS. `docs/EQUIVALENCE.md` reports those counts from a real refresh.

### 6.5 Term reader (`reader/`, D56–D58)

For markets in the catalog's unclear pairs, a model fills in the terms that a parser would:

1. **Group.** The unclear pairs, most similar first, grouped by the event of their first market; each group (up to 20 markets) is one request, so the model names both sides alike.
2. **Read.** A Messages API request (`claude-haiku-5-5`) forced through one tool whose input is one terms record per market, with the evidence phrase it read them from (`prompt.py`). An exact score is read in parts: the model works out which team is at home and how the market writes its score, then gives the teams and goals, and code writes the score's terms from them as the parsers do (D71). A text answer that doesn't parse is read record by record (D72).
3. **Check.** `checks.py` rejects a record whose evidence isn't in the market's text, whose threshold isn't a number the venue wrote (text or strike fields), whose comparison disagrees with the evidence's words, whose date falls after the market closes, which Kalshi's strike fields contradict, or whose score's goals aren't in the order the venue states them (D67). On a count, only the side must agree (2+ is greater 1.5).
4. **Decide.** `matcher.terms.decide` applies rules 2–6 of §6.1 to the two accepted readings. EQUIVALENT is the same bet, DISTINCT a different bet, AMBIGUOUS stays unclear.
5. **Record.** Readings and decisions go into the catalog file. Every request is cached by its content; a pair decided by another prompt version or model is read again.
6. **Route** (`pricing.py`). `simulate` on a market that isn't in a loaded family, and the order page for a `catalog:` outcome, look the market up among the catalog's model-read same bets. The gate allows it only when the pair was read with the model and prompt the committed evals were recorded with, and every gold set shows zero false same-bets. Each market's event is looked up from the venue at pricing time (D59), the listings and books are loaded, the model's terms are attached, and the group goes through the same clusters and router as a parser-read one, with the risk flag "Terms read by a model", so its confidence is Medium at most.

A parser's same bet outside the loaded families (exact scores) is priced the same way, but its terms come from the venues' listings, with no gate and no model flag (D65).

`catalog check --limit N` (`check.py`, D64) reads the parsers' pairs with the model: the same bets and the pairs a refresh keeps as "different" because their titles alone would have left them unclear. It decides them with the same rules and lists every disagreement, changing nothing.

`catalog check --drift --limit N` (D69) reads only the markets a parser family is meant to read (the catalog's `family` column) but gave no terms, and says which still look like the family.

Only `catalog read` and `catalog check` call the model, and both print the tokens they spent. The evals (`reader/evals.py`, sets in `reader/gold.py`) score seven gold sets twice, raw and guarded, with upper bounds (D66); the tests replay their recorded answers.

### 6.4 Labelled pairs (acceptance tests for feat-03)

| # | Pair | Expected |
|---|---|---|
| E1 | Kalshi H0 ↔ Polymarket "No change" | EQUIVALENT. Flag: fallback rules differ. |
| E2 | Kalshi C25 ↔ Polymarket "25 bps decrease" | EQUIVALENT. Flag: fallback rules differ. |
| E3 | Kalshi C26 (lt −25) ↔ Polymarket "50+ bps decrease" (le −50) | EQUIVALENT. Flags: equal only on the 25 bps grid; fallback rules differ. |
| E4 | Kalshi H26 (gt 25) ↔ Polymarket "50+ bps increase" (ge 50) | EQUIVALENT. Same flags as E3. |
| E5 | Kalshi H0 ↔ Polymarket "25 bps increase" | DISTINCT (different outcome) |
| E6 | Kalshi C25 ↔ Polymarket "50+ bps decrease" | DISTINCT (different outcome) |
| E7 | Meridian AAPL-330 ↔ Polymarket "$330" | EQUIVALENT. Flags: strictness (tie at 330 USD); fallback rules differ. |
| E8 | Meridian AAPL-330 ↔ Polymarket "$335" | DISTINCT |
| E9 | Meridian AAPL-330 on 2026-10-12 ↔ AAPL-330 on 2026-10-13 | DISTINCT (different event) |
| E10 | Same terms, `pyth_regular_close` vs `official_close` | AMBIGUOUS |
| E11 | Text: "Will the Fed cut rates by 25 bps in December 2025?" ↔ the same with 50 bps | DISTINCT (number veto, with "2025" ignored) |
| E12 | Text: "Will Trump win Pennsylvania in 2024?" ↔ "…Michigan in 2024?" | DISTINCT (entity veto) |
| E13 | Text: "Will the Fed cut rates at the December 2025 FOMC meeting?" ↔ "Fed decreases interest rates after December 2025 meeting?" | AMBIGUOUS, never EQUIVALENT |

E11–E13 are the three cases the first version's matching code got wrong (AI_USAGE items 2–4).

---

## 7. Routing (`router/`), the core flow

```python
def simulate(order: OrderRequest, cluster: EquivalenceCluster, now: datetime,
             stale_after: timedelta = timedelta(seconds=300), trace_id: str | None = None) -> EquinoxTrace
```

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant C as cli.py
    participant A as Adapters
    participant M as Matcher
    participant R as Router
    U->>C: simulate --market kalshi:KXFEDDECISION-26OCT-H0 --outcome YES --quantity 100
    C->>A: fetch_markets() for each venue
    A-->>C: canonical markets and warnings
    C->>M: clusters(markets)
    M-->>C: the cluster holding the requested market
    C->>R: simulate(order, cluster, now)
    loop each market in the cluster
        R->>R: walk books[outcome].asks, fees.fee(fills), checks
    end
    R->>R: pick the cheapest eligible venue, write the rationale
    R-->>C: EquinoxTrace with status
    C-->>U: report or JSON, and the exit code
```

### 7.1 Each venue's quote

Every market in the cluster is simulated, including ones that will be excluded, so the trace can show what each venue would have cost.

1. **Walk** `books[outcome].asks` from the cheapest level: take min(remaining, level quantity) until the order is filled or the levels run out.
2. **Cost:** base = Σ price × quantity. fee = `fees.fee(fills)`. total = base + fee. Average price = base / filled. Slippage = average − best ask.
3. **Reasons the venue is excluded** (all that apply are recorded):
   - `NOT_TRADABLE`: `tradable` is false.
   - `TEST_MONEY`: `collateral.has_value` is false.
   - `EMPTY_BOOK`: there are no asks.
   - `PARTIAL_FILL`: filled < quantity.
   - `OVER_BUDGET`: the order is fully filled but total > `max_budget`.
4. **Warnings** (shown, but the venue stays eligible):
   - `STALE_DATA`: now − captured_at > `stale_after`.
   - `FIXTURE_DATA`: `data_source` is fixture.
   - `DEPTH_INCOMPLETE`: the walk ran out of levels on a book with `depth_complete` false.

### 7.2 Decision and status

| Situation | Status | Exit code |
|---|---|---|
| At least one venue is eligible. The winner has the lowest total, then the lower fee, then the lower `market_id`. | `ROUTED` | 0 |
| The requested `market_id` is not in the loaded markets (set by the CLI) | `MARKET_NOT_FOUND` | 1 |
| No venue is eligible, the cluster has a tradable real-money venue, and none of those can fill the whole order | `INSUFFICIENT_LIQUIDITY` | 2 |
| No venue is eligible, and at least one tradable real-money venue fills the whole order but is over budget | `BUDGET_EXCEEDED` | 3 |
| Bad arguments, such as a quantity of 0 or an unknown outcome (set by the CLI) | `INVALID_INPUT` | 4 |
| Every venue is excluded for `NOT_TRADABLE` or `TEST_MONEY` | `NO_ELIGIBLE_VENUE` | 5 |

**Savings.** The runner-up is the next eligible venue. Savings = runner-up total − winner total. Savings percent = savings / runner-up total × 100, rounded to 0.01.

**Rationale.** It names venues from the market's `venue` field and nothing else. For the running example (100 YES):

> Polymarket is the cheapest venue that can fill all 100 YES contracts: $84.67 including $0.67 in fees, versus $85.90 on Kalshi ($1.23 or 1.43% less). Match risks: Edge-case rules differ: Kalshi: if the meeting is cancelled, "Fed maintains rate" resolves Yes. Polymarket: a change not shown in the brackets is rounded up to the nearest 25 bps; if no statement is released by the end date of the next scheduled meeting, "No change" resolves Yes.

Each excluded venue adds one sentence, for example: "Meridian was not eligible: it settles in devnet USDC, which has no monetary value (it would cost $4.75)."

### 7.3 Every place it can break

| Breaks at | What happens | What the user sees | How it's settled |
|---|---|---|---|
| A venue request fails or times out | The CLI uses that venue's fixture (D17) | `FIXTURE_DATA` on that venue's quotes, plus a warning line | Rerun later with `--source live` |
| A response has an unexpected shape | That market fails validation and is skipped | "polymarket: market 2589812 skipped: …" | Fix the adapter; the golden tests catch it |
| A book arrives in the venue's order | The adapter re-sorts it; if it didn't, the model would reject it (§4.5) | Nothing, or the skip warning | — |
| Terms can't be parsed | terms None; the market reaches the text fallback only | It appears in `match` as AMBIGUOUS at best | Add a parser for that family |
| The book is empty | `EMPTY_BOOK` | "Kalshi was not eligible: nobody is selling NO" | — |
| The book is too thin | `PARTIAL_FILL`, status 2 if nothing else qualifies | "only 5 of 10 contracts are available" | — |
| Old data | `STALE_DATA` warning | The book's age, in the warning | — |
| Test money or a closed market | `TEST_MONEY` or `NOT_TRADABLE`, status 5 if nothing else qualifies | The reason sentence | — |

Nothing is written anywhere, so there is no double-submit, no locking and no partial state to guard against.

### 7.4 Demo inputs (snapshot fixtures, `--source fixtures`)

| Command arguments | Result |
|---|---|
| `--market kalshi:KXFEDDECISION-26OCT-H0 --outcome YES --quantity 100` | ROUTED to Polymarket, $84.672 vs $85.90 |
| `… -H0 --outcome NO --quantity 100` | ROUTED to Kalshi, $16.95 vs $17.7055 |
| `… -H0 --outcome NO --quantity 5000` | ROUTED to Polymarket, $885.275 vs $893.7951 (Kalshi used 2 levels) |
| `… -H0 --outcome YES --quantity 100 --budget 80` | BUDGET_EXCEEDED (exit 3) |
| `… -H0 --outcome YES --quantity 5000000` | INSUFFICIENT_LIQUIDITY (exit 2). Total YES ask depth is 4,649,443.27 on Kalshi and 3,453,123.38 on Polymarket. |
| `--market kalshi:KXFEDDECISION-26OCT-C25 --outcome NO --quantity 100` | ROUTED to Polymarket at $99.61992; Kalshi EMPTY_BOOK |
| `--market kalshi:NOPE --outcome YES --quantity 1` | MARKET_NOT_FOUND (exit 1) |
| `--market kalshi:KXFEDDECISION-26OCT-H0 --outcome YES --quantity 0` | INVALID_INPUT (exit 4) |

---

## 8. Trace and CLI contract

### 8.1 Trace (`models/routing.py`, `models/trace.py`)

```python
class OrderRequest(Frozen):
    market_id: str
    outcome: Outcome
    quantity: Decimal              # > 0
    max_budget: Decimal | None     # > 0 if set

class VenueQuote(Frozen):
    market_id: str
    venue: str
    eligible: bool
    reasons: tuple[QuoteReason, ...]      # NOT_TRADABLE, TEST_MONEY, EMPTY_BOOK, PARTIAL_FILL, OVER_BUDGET
    warnings: tuple[QuoteWarning, ...]    # STALE_DATA, FIXTURE_DATA, DEPTH_INCOMPLETE
    fills: tuple[Fill, ...]
    filled_quantity: Decimal
    best_ask: Decimal | None
    average_price: Decimal | None
    slippage: Decimal | None
    base_cost: Decimal
    fee: Decimal
    total_cost: Decimal

class Decision(Frozen):
    winner: str                    # market_id
    runner_up: str | None
    savings: Decimal | None
    savings_percent: Decimal | None

class EquinoxTrace(Frozen):
    trace_id: str
    created_at: datetime
    status: RoutingStatus
    order: OrderRequest | None
    cluster: EquivalenceCluster | None
    quotes: tuple[VenueQuote, ...]
    decision: Decision | None
    rationale: str
    assumptions: tuple[str, ...]   # A1, A2, A3, A5, worded for the reader
    warnings: tuple[str, ...]      # quote warnings from simulate(), plus adapter warnings the CLI adds
```

The trace uses typed sections instead of the first version's generic "spans" (D30). Each section is a field that tests can assert on directly.

`models/equivalence.py` holds:
- `EquivalenceStatus` (EQUIVALENT, AMBIGUOUS, DISTINCT)
- `MatchResult(market_a, market_b, status, method: "terms" | "text", reasons, risk_flags, text_score)`
- `EquivalenceCluster(cluster_id, markets, pairs, ambiguous, risk_flags)`

### 8.2 CLI (`python -m equinox …`)

| Command | Prints |
|---|---|
| `markets [--source live\|fixtures] [--snapshot NAME] [--json]` | One line per canonical market of every discovered family: market_id, terms in words, tradable, best asks |
| `match [--source …] [--snapshot NAME] [--catalog] [--json]` | Clusters with their risk flags and confidence, then AMBIGUOUS pairs with their reasons. `--catalog` adds the saved catalog's summary and its 20 most similar unclear pairs. |
| `catalog read --limit N [--model M] [--workers W]` | Reads the terms of at most N markets in unclear pairs with a model, checks and decides them (§6.5), and prints the readings accepted and rejected, the pairs decided and the tokens spent. Exit 1 without a key. |
| `catalog check --limit N [--model M] [--workers W]` | Reads at most N markets of the parsers' pairs with the model and lists every pair the two decide differently (D64), with the tokens spent. Changes nothing. Exit 1 without a key. |
| `catalog refresh [--source …] [--snapshot NAME]` / `catalog status` | `refresh` pages every open market on both venues (§2), compares them and saves the catalog, printing progress every 10 pages and a summary; from a snapshot it reads the snapshot's small sample. `status` prints the catalog's age and counts. Exit 0, or 1 when there is no catalog or the refresh failed (the previous catalog is kept), or 4 for bad arguments. |
| `simulate --market ID --outcome YES\|NO --quantity N [--budget B] [--source …] [--json]` | A report: status, the quote table, the decision, the rationale and warnings. `--json` prints the whole trace instead. The exit code is from §7.2. |

The default source is `live`. `--snapshot` picks a snapshot folder under `src/equinox/fixtures/`; the default is `snapshot-2026-10-10`, the frozen baseline (D51). The demo commands in the README use `--source fixtures` so that their numbers match this document. `match` also prints each cluster's confidence (D46). `simulate` fetches books only for the requested market's group (D49).

### 8.3 Web app (`python -m equinox.server`, feat-07, feat-14)

Server-rendered pages for the two people in `user/users.md`, built from the catalog of every open market (D86). AutoTrader, a program, uses `--json`.

| Page | For | Shows |
|---|---|---|
| `/`, Markets | Jordan | The events both venues list (`catalog/events.py`), soonest to close first (D88), as cards: topic (D87), closing date, the three likeliest outcomes with what YES costs on each venue, the cheaper marked, and how many outcomes both venues list. Topic chips filter them; `?q=` searches either market's title words. With no catalog it says how to build one. |
| `/event?m=`, an event | Jordan | Every outcome of the event both venues list, likeliest first: what YES pays in words, how it matched (Equinox's own reader, or a model, Medium at most), YES and NO on each venue, Buy YES and Buy NO. |
| `/bet?m=&side=&quantity=&budget=`, the order ticket | Jordan and Morgan | A line saying what comparing does and that nothing is bought, and fields that say what they mean (D92). The recommendation as the headline, then what the contracts pay: which venue, the total including fees, the saving over the runner-up. Then each venue's fills, average price, fee and total or why it can't take the order, the router's rationale, data notes in plain words and the assumptions. Beside it, "Is this really the same bet?": how it matched, the verdict and confidence, one column per venue and one row per rule (question, pays YES if, measured by, observed, settlement source, closing and resolution times, edge-case rules) with differing rows marked, and the risk flags. |
| `/matches?show=&q=`, Matches | Morgan | Every pair Equinox kept (`catalog/review.py`), by kind with counts: exact matches, same bets a model read, pairs that only look alike (title score, never priced), pairs a model ruled different. Both venues' titles, how it was decided in words, and under "How it was decided" what was compared (event, outcome, who decides, date) for each venue with differences marked, and why (D99); a same bet links to its ticket's "Is this really the same bet?" panel (D94). |

Rules the pages keep:
- Every order goes through `simulate`, and every match through the matcher and the catalog; the ticket prices a pair through `reader/pricing.py` from where the catalog was read (D78). A test checks that the ticket and `cli.main --json` show the same totals.
- Only the pair being priced is read from the venues, with its order books (D49). If they can't be reached, the ticket says so and doesn't price.
- The top bar says how old the catalog's prices are, whether a refresh is running or the last one failed, and has a Refresh button; the ticket's notes say how old each order book is.
- With live data the server refreshes the catalog on start when it has none or it is 6 hours old, then every 6 hours, and on Refresh (D90, D98); Refresh is a link under an hour, a button from an hour, and from 3 hours a note at the top too. Before the first catalog the home page says it is being built; with no catalog and no venues, that they can't be reached. A refresh keeps the model's decisions where both markets' rules are unchanged (D91); the server never calls the model.
- Every string that came from a venue is HTML-escaped. Venue names come only from each market's `venue` field.
- One stylesheet, light and dark, from phone width up; one script prices the ticket again as you type by fetching the ticket page itself, and hides Compare venues, which only a browser without it needs (D89, D96).
- While a refresh runs, every page keeps the markets it has and says they are updating; Markets reloads itself until the new ones are in (D95).
- The server listens on 127.0.0.1 unless `--host` says otherwise.

---

## 9. Third-venue fit check: Meridian (D26)

Meridian is the user's binary-stock-outcome project: daily contracts on whether a stock closes at or above a strike, traded on Solana devnet. It is planned, not deployed, and **we are not integrating it**. The check asks a narrower question: if we did integrate a venue like it, would the matcher, the router and the shared model work unchanged? Meridian's facts are M1–M6 in `venue_facts.md`.

### 9.1 How an adapter would map it (on paper, not built)

The table assumes Meridian exposes HTTP endpoints like the other venues (A4): `GET /api/markets?day=` and `GET /api/markets/{key}/book`, with prices in whole cents and quantities in whole contracts. Only a Meridian adapter would depend on that shape.

| Canonical | Meridian source |
|---|---|
| native_id, event_id | `key` (`AAPL-330-2026-10-12`), `{ticker}-{day}` |
| terms | subject `ticker`, measure close_price, measured_by pyth_regular_close, observed_on `day`, observed_at the 4:00 PM ET close, comparison ge (M1: at or above), threshold `strike_cents` / 100, unit usd. Fallback rule: "If Pyth's confidence band straddles the strike, the market is held and an admin settles it on the official close." (M2) |
| collateral | devnet USDC, `has_value` false (M5) |
| tradable | the market is open and the program isn't paused |
| fees | coefficient 0 (M4) |
| books | YES asks = asks / 100. YES bids = bids / 100. NO asks = 1 − YES bids. NO bids = 1 − YES asks (M3: buying NO costs 100¢ − the YES bid). |

### 9.2 Result

| Part | Fits? | How |
|---|---|---|
| Adapter boundary | Yes | One adapter file, one fixture and one `tracked_events.json` entry. Nothing else changes. |
| Prices and quantities | Yes | Whole cents / 100 → `Decimal` between 0 and 1. Whole contracts. |
| YES and NO books (D14) | Yes | NO asks = 1 − YES bids, the same derivation the Kalshi adapter uses |
| Fees (D13) | Yes | coefficient 0. Solana transaction costs aren't modelled (DECISIONS, "Cut"). |
| Contract terms (D22) | Yes, because of D22 | "at or above $330 at the 4:00 PM ET close, per Pyth". Terms shaped around the Fed alone could not express it. |
| Equivalence (D23) | Yes | E7: EQUIVALENT to Polymarket's "$330", with the tie-rule and fallback flags |
| Money (D24) | Yes, because of D24 | devnet USDC has no value → TEST_MONEY. Without D24, A1 would treat play money as dollars. |
| Tradability (D25) | Yes, because of D25 | Meridian works out open and closed from the clock. Polymarket keeps trading past `endDate`. |
| Router | Unchanged | It reads only canonical fields |

### 9.3 Evidence that runs

The check counts only if it runs, so it is part of the test suite. No Meridian adapter is involved.

- `tests/golden/canonical_markets.json` (feat-01) includes hand-built **fit-check markets**:
  - Meridian-style AAPL-330 and AAPL-320 for 2026-10-12, mapped as in §9.1.
  - Polymarket's "$330" and "$335" AAPL markets, with values copied from the research snapshot.
  - The E9 and E10 variants.
- The **matcher** tests run E7–E10 on them (feat-03).
- The **router** tests run three cases on them (feat-04 tests 7–9):
  - 5 YES → Polymarket wins at $4.80768; Meridian TEST_MONEY, would cost $4.75.
  - 10 YES → Meridian also PARTIAL_FILL.
  - Meridian alone → NO_ELIGIBLE_VENUE.
- `test_layering.py` proves the matcher and router contain no venue names, so none of this needed engine changes.

---

## 10. Stack, testing and delivery

**Stack (D1).** Python 3.12, `pydantic` 2, and `tzdata`. `tzdata` is needed because Python on Windows has no time-zone database: `ZoneInfo("America/New_York")` raised `ZoneInfoNotFoundError` on this machine. The HTTP client and the server are the standard library's. The exact versions are pinned in `requirements.txt` by feat-01.

**Test layers.**

| Layer | What | Owner |
|---|---|---|
| Model rules | Every row of §4.5, plus the fee formula against the §1 numbers | feat-01 |
| Layering guard | `test_layering.py` (§3) | feat-01 |
| Adapter facts | Each adapter on the snapshot: counts, terms per market, best asks, total depth, fee coefficient, tradable, skip warnings | feat-02a/b |
| Matcher pairs | E1–E13 on the golden canonical markets, including the §9 fit-check markets | feat-03 |
| Router scenarios | §7.1–7.2 on the golden canonical markets: every reason, every status, the tie-break, the rationale text, and the §9 cases | feat-04 |
| End to end | Every row of §7.4 through `python -m equinox … --source fixtures`, checking the exit codes and numbers | feat-05 |

**Golden canonical markets.** `tests/golden/canonical_markets.json` holds hand-written canonical markets: the Fed pairs (E1–E6), the §9 fit-check markets (E7–E10), and the router cases. The books are trimmed to the top levels from the snapshot. The matcher and router lanes test against this file, so they don't wait for the adapters (D19).

**Gate.** `scripts/gate.py` runs `ruff check`, `ruff format --check` and `pytest`; `make gate` calls it. It must pass on Windows and in GitHub Actions, the CI of record (D31, D40). No test touches the network beyond the local web server the UI tests start.

---

## 11. Configuration

| Setting | Default | Notes |
|---|---|---|
| `--source` / `EQUINOX_SOURCE` | `live` | `fixtures` reads `src/equinox/fixtures/` |
| `KALSHI_BASE_URL` | `https://external-api.kalshi.com/trade-api/v2` | K1 |
| `POLYMARKET_GAMMA_URL`, `POLYMARKET_CLOB_URL` | `https://gamma-api.polymarket.com`, `https://clob.polymarket.com` | |
| `EQUINOX_STALE_AFTER_SECONDS` | 300 | §7.1 |
| `EQUINOX_HTTP_TIMEOUT_SECONDS` | 10 | |
| `--snapshot` / `EQUINOX_SNAPSHOT` | `snapshot-2026-10-10` | A folder under `src/equinox/fixtures/` (D51) |
| `EQUINOX_CACHE_DIR` | `.cache/equinox` | Where `catalog refresh` writes the catalog (D48), and `catalog read` caches the model's answers; gitignored |
| `ANTHROPIC_API_KEY` | none | The term reader's key (D57), from the environment or from `.env` at the repository root (gitignored). Only `catalog read` and the live evals use it. |
| Pinned events | `src/equinox/tracked_events.json` | Used only when discovery can't run (D47): a snapshot captured before discovery, or a failed live discovery request |

---

## 12. Repository layout and build order

```
src/equinox/
  __main__.py            # python -m equinox -> cli.main
  cli.py                 # arguments and output only
  cli_catalog.py         # the catalog commands' output
  sources.py             # settings, data sources, discovery, books on demand (D49, D51)
  catalog/  __init__.py  store.py  events.py  review.py  carry.py  background.py
            # refresh, its SQLite file, the events both venues list, the pairs for review,
            # decisions kept across a refresh, the background refresh
  server.py              # the web app's routes and /health (§8.3)
  web/      app.py  shell.py  home.py  event.py  ticket.py  same_bet.py  matches.py  explain.py  order.py  words.py  style.py  script.py
  tracked_events.json
  fixtures/
    snapshot-2026-10-10/ # raw Kalshi and Polymarket responses + index.json; the frozen baseline
    snapshot-2026-10-11/ # adds discovery responses, every discovered Fed meeting, a small catalog sample
  models/   canonical.py  catalog.py  equivalence.py  routing.py  trace.py
  adapters/ base.py  fetch.py  kalshi.py  polymarket.py  scores.py  teams.py  team_aliases.json
  matcher/  terms.py  text.py  clusters.py  confidence.py  index.py  compare.py
  reader/   prompt.py  client.py  checks.py  run.py  evals.py  gold.py  pricing.py  check.py
  router/   depth.py  engine.py  rationale.py
tests/
  golden/canonical_markets.json   # includes the §9 fit-check markets
  conftest.py            # loads the golden markets for every test file
  test_models.py  test_layering.py
  test_kalshi.py  test_polymarket.py
  test_matcher.py  test_router.py  test_cli.py
  test_confidence.py  test_web.py  test_docs.py  test_quality.py
  test_discovery.py  test_catalog.py  test_index.py  test_web_catalog.py  test_fetch.py
  test_reader.py  test_reader_evals.py  test_scores.py  test_strength.py  test_upkeep.py
evals/      pairs.json  heldout.json  traps.json  score_pairs.json  recorded.json  scores.json
  test_equinox.py        # existing status-server tests
```

**Build order (D19).** Each lane owns only its own files.

| Step | Feature | Owns | Done when |
|---|---|---|---|
| 1 | feat-01 models and fixtures | `models/`, `adapters/base.py`, `adapters/fetch.py`, `fixtures/`, `tracked_events.json`, `tests/golden/`, `tests/conftest.py`, `test_models.py`, `test_layering.py`, `requirements.txt` | `make gate` passes; the golden file validates against the models |
| 2 (parallel) | feat-02a Kalshi | `adapters/kalshi.py`, `test_kalshi.py` | Snapshot facts asserted |
| 2 | feat-02b Polymarket | `adapters/polymarket.py`, `test_polymarket.py` | Snapshot facts asserted |
| 2 | feat-03 matcher | `matcher/`, `test_matcher.py` | E1–E13 pass |
| 2 | feat-04 router | `router/`, `test_router.py` | Every reason, status and rationale case passes, including §9's |
| 3 | feat-05 CLI | `cli.py`, `__main__.py`, `test_cli.py` | Every row of §7.4 |
| 4 | feat-06 written deliverables | `README.md`, `docs/EQUIVALENCE.md`, `docs/ROUTING.md`, a final pass on `docs/AI_USAGE.md` | Every README command runs as written; the numbers match a fresh run |
| 5 | feat-07 web UI | `server.py`, `web/`, `matcher/confidence.py`, `test_web.py`, `test_confidence.py` | The page and the CLI agree on every demo order; browser check recorded |
| 6 | chore-01 modularity | `sources.py`, `cli.py`, `web/`, `router/engine.py`, `pyproject.toml`, `test_quality.py`, the README's "Reading the code" | Every existing test passes unchanged; the quality checks pass (D52) |
| 7 | feat-08 discovery and plain bps | `adapters/`, `models/canonical.py`, `sources.py`, `snapshot-2026-10-11/`, `capture_snapshot.py`, `web/`, `test_discovery.py` | Every discovered Fed meeting is matched and priceable; frozen tests unchanged |
| 9 | feat-10 term reader | `reader/`, `models/canonical.py` (units), `models/catalog.py`, `adapters/` (texts), `catalog/` (texts and readings), `matcher/terms.py` (`decide`), `cli.py`, `cli_catalog.py`, `web/markets.py`, `test_reader.py`, `test_reader_evals.py`, `evals/` | The evals show zero false same-bets; a 100-market sample is read and recorded |
| 8 | feat-09 catalog | `models/catalog.py`, `adapters/`, `matcher/index.py`, `matcher/compare.py`, `catalog/`, `cli.py`, `cli_catalog.py`, `sources.py` (the cache folder), `web/markets.py`, `web/markets_html.py`, `test_catalog.py`, `test_index.py`, `test_web_catalog.py`, `test_fetch.py` | A live refresh is recorded; the All markets page searches it |

**If time runs short, cut from the bottom:**
1. feat-09, the catalog: Equinox then reads only the families it can discover, and `EQUIVALENCE.md` describes the catalog as the next step.
2. The text fallback (§6.3): pairs without terms are simply unmatched.
3. Live mode (fixtures only). The brief asks for API integration, so this is the last cut.

---

## 13. Known limitations

- **Two families have term parsers:** Fed rate decisions, found automatically on both venues (D47), and exact scores, read from the catalog (D61). Other catalog markets are read by a model (§6.5); those pairs are Medium confidence at most and routed only while the evals allow it. The full read held 7 reversed-score false same-bets among 456 the evals didn't catch; feat-12 adds them as traps. §9 shows that a second family, stock close-above, fits the same terms shape.
- **The catalog is as fresh as its last refresh** (D48), and title candidates are limited by the index's blocking rules (D50): a true pair worded with no shared informative words, or dated days apart, is missed.
- **Discovery rules are per venue** (D47). A venue that renames its series or tag needs a code change; until then, live runs fall back to the pinned events.
- **Fees are list fees.** Polymarket's taker rebates (up to 50%) and builder fees are ignored (A5).
- **Kalshi fees are rounded to the cent (A3).** Polymarket's rounding mode and per-fill granularity are unconfirmed (P8). In both cases the effect is under 1¢ per order.
- **Books are frozen at capture (A2).** There is no latency, no queue position and no market impact.
- **One order goes to one venue.** There is no split routing.
- **Meridian is not integrated.** §9 checks that it would fit.
- **"Up or Down" markets and Solana transaction costs are cut** (DECISIONS, "Cut").
