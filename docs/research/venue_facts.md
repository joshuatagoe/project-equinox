# Venue facts

What Kalshi and Polymarket actually do, researched on 2026-10-10 by four research subagents (D12) and checked against live public API responses. Every fact carries a label:

- **CONFIRMED**: a primary source (venue docs, official spec, official client code) or a live API response.
- **SECONDARY**: a reputable non-venue source.
- **UNCONFIRMED**: no source, or sources disagree. Both sides are given.

This file replaces the venue claims in `docs/architectural_review.md`, which cites no sources. The places where that review is wrong are listed at the end. Raw API responses are in `samples/`. They were saved byte-for-byte and are the starting point for test fixtures.

## Kalshi

| # | Fact | Label and source |
|---|---|---|
| K1 | Public market data lives at `https://external-api.kalshi.com/trade-api/v2`. `api.elections.kalshi.com` is still supported. Market, event, series and orderbook GETs need no authentication. | CONFIRMED: docs.kalshi.com OpenAPI 3.34.0 `servers` and `security: []`; changelog 2026-05-07; live 200s without headers. |
| K2 | Prices are fixed-point dollar strings with 4 decimals (`yes_bid_dollars: "0.1700"`). The integer-cent fields (`yes_bid`, `last_price`, …) were **removed**, not just deprecated: from markets on 2026-01-15 and from all payloads on 2026-03-12. | CONFIRMED: changelog entries 2026-01-06 and 2026-03-08; absent from the spec and from live responses. |
| K3 | Contract counts are fractional strings with 2 decimals (`"8.12"`, fields ending `_fp`). | CONFIRMED: spec and live. |
| K4 | `GET /markets/{ticker}/orderbook` returns `{"orderbook_fp": {"yes_dollars": [[price, count], …], "no_dollars": […]}}`. Both lists are **bids only**, sorted **ascending**, so the best bid is the **last** element. An empty side is `[]`. An unknown ticker returns 200 with two empty lists, not 404. `depth` accepts 0–100, where 0 means all levels. | CONFIRMED: docs `getting_started/orderbook_responses`; live. The API reference prose ("best to worst", "order counts") contradicts the live data; the live data wins. |
| K5 | To buy YES you pay 1.00 − (highest NO bid); to buy NO you pay 1.00 − (highest YES bid). To walk depth, go through the opposite side's bids from best to worst at 1 − p. | CONFIRMED for the best price: docs `orderbook_responses`. The depth walk is inferred from that rule. |
| K6 | Time fields: `close_time` is when trading stops; `expected_expiration_time` is when the outcome is expected to be known; `latest_expiration_time` is the latest possible. `expiration_time`, `title` and `subtitle` are deprecated but still returned. `yes_sub_title` and `no_sub_title` are required. | CONFIRMED: docs market lifecycle; spec. |
| K7 | The settlement source is listed on the **series** and the **event** (`settlement_sources: [{name, url}]`), not on the market. KXFEDDECISION lists `{"name": "Federal Reserve", "url": "https://www.federalreserve.gov"}`. | CONFIRMED: spec; live. |
| K8 | Fed markets: `KXFEDDECISION-<meeting>` has 5 mutually exclusive markets with `strike_type: "custom"`: `{"Cut": ">25"}`, `{"Cut": "25"}`, `{"Hike": "0"}` ("Fed maintains rate"), `{"Hike": "25"}`, `{"Hike": ">25"}`. `KXFED-<meeting>` has thresholds on the rate **level** ("above 4.00%"), strictly greater. | CONFIRMED: live events KXFEDDECISION-26OCT and KXFED-26OCT, and the settled September 2026 events. |
| K9 | Taker fee = round up(M × 0.07 × C × P × (1 − P)), where C is contracts, P is the price in dollars, and M is a per-series multiplier (`fee_multiplier` on `GET /series`, which an event can override). KXFEDDECISION: `fee_type: quadratic_with_maker_fees`, M = 1. | CONFIRMED: Kalshi Fee Schedule PDF, effective 2026-07-07; live `/series/KXFEDDECISION`. |
| K10 | Fees are rounded up per fill. A per-order accumulator then rebates the overpayment, so an order's total converges to the fee on one equivalent fill. Precision is $0.0001 for direct members and $0.01 for FCM-cleared accounts. Which applies to a kalshi.com retail account is **UNCONFIRMED**. | CONFIRMED: docs `getting_started/fee_rounding`; PDF ("rounded to a centicent"). |
| K11 | Maker fees exist on some series (0.0175 coefficient). They don't affect a taker simulation. | CONFIRMED: Fee Schedule PDF. |

## Polymarket

| # | Fact | Label and source |
|---|---|---|
| P1 | On Gamma `/markets` and `/events`, the fields `outcomes`, `outcomePrices` and `clobTokenIds` are **strings containing JSON** (`"[\"Yes\", \"No\"]"`). For binary markets, index 0 is YES. For markets with `version: "v2"`, `clobTokenIds` may be null, and `positionIds` (a real array) holds the IDs instead. | CONFIRMED: docs `market-details`; live (every one of about 300 sampled markets was v1). |
| P2 | Outcome labels are not always Yes/No (live examples: `["Over","Under"]`, `["Up","Down"]`, team names). | CONFIRMED: live. |
| P3 | `endDate` means "eligible for resolution". It is neither when trading stops nor when the market actually resolved: markets past `endDate` were still accepting orders. Dates come in several formats: ISO with fractional seconds, `"2026-09-16 20:02:43+00"`, and date-only `endDateIso`. A market is tradable when `active && !closed && acceptingOrders`. | CONFIRMED: docs `concepts/resolution`; live. |
| P4 | CLOB `GET /book?token_id=` returns `bids` sorted **ascending** and `asks` sorted **descending**, so the best price is the **last** element of each. Sizes are fractional strings. Prices are not zero-padded (`"0.1"`, `"0.029"`). `min_order_size` is `"5"`. `tick_size` is `"0.01"` or `"0.001"` and varies within one event. | CONFIRMED: docs `prices-order-books`; official client `py-clob-client-v2` walks `reversed(...)`; live. The CLOB OpenAPI spec says the opposite order and is wrong. |
| P5 | The YES-token book and the NO-token book mirror each other: a YES bid at p is a NO ask at 1 − p, with the same size. They are the same liquidity shown twice. To buy NO, walk the NO token's asks; never add the mirrored YES bids on top. | CONFIRMED: docs `market-making` ("buying NO at 0.48 is economically equivalent to selling YES at 0.52"); live, rechecked on the October 2026 "No change" market at 20:21Z. |
| P6 | Fed markets: one neg-risk event per FOMC meeting, with one binary market per bracket. `groupItemTitle` holds the bracket: "50+ bps decrease", "25 bps decrease", "No change", "25 bps increase", "50+ bps increase". The set of brackets varies by meeting. There is a second, non-neg-risk event with the same title, so never select an event by title alone. Off-grid moves are "rounded up to the nearest 25". Resolution source: `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm`. | CONFIRMED: live event 606422 ("Fed Decision in October?") and the September 2026 events. |
| P7 | Taker fee = C × `feeSchedule.rate` × (p × (1 − p))^`feeSchedule.exponent`, charged to takers only. Rate and exponent are set **per market**. `feesEnabled: false` means no fee. Geopolitics markets are the only fee-free category. The October 2026 Fed markets have rate 0.05 and exponent 1. `takerBaseFee: 1000` is a legacy field, **not** a 10% rate. | CONFIRMED: docs `trading/fees`; official client `fees.py`; live Gamma `feeSchedule`. |
| P8 | Fees are rounded to 5 decimal places. The rounding mode, and whether rounding happens per fill or per order, are **UNCONFIRMED**. | CONFIRMED (5 dp): docs `trading/fees`. |
| P9 | Gamma list endpoints return at most 100 items. `/events` returns closed events unless you pass `closed=false`. The keyset endpoints (`/markets/keyset`, `/events/keyset`) are the recommended ones. | CONFIRMED: spec, changelog 2026-04-10, live. |
| P10 | Polymarket US (QCX LLC, CFTC-regulated) is a separate venue with its own API and fee Θ = 0.0695. We don't integrate it. | CONFIRMED: docs.polymarket.us/fees; CFTC filings. |

## Stock and index markets

Researched for the Meridian fit check. Samples are in `samples/stocks/`.

| # | Fact | Label and source |
|---|---|---|
| S1 | Kalshi lists **no** markets on individual stock prices. It has index series: S&P 500 (`KXINX` daily ranges, `KXINXU` hourly above/below, `KXINXDUD` daily up/down), Nasdaq-100 (`KXNASDAQ100`, `KXNASDAQ100U`) and the Dow (`KXDJI`, settled from Pyth). | CONFIRMED: live `/series` (14,942 series) and every open event (15,092). |
| S2 | Kalshi index strikes are structured fields (`strike_type`, `floor_strike`, `cap_strike`), but they need normalizing. Example: `KXINXU-26OCT12H1600-T7629.9999` has `greater_or_equal` and floor 7630, while its title says "above 7629.9999". The observation time and the definition of the price appear only in the title and rules text. | CONFIRMED: live markets. |
| S3 | Polymarket lists daily markets on single stocks. One kind is "Apple (AAPL) closes above ___ on October 12?": one binary market per strike, with strikes $325, $330, $335, $340 and $345 for AAPL. YES requires the Pyth `Equity.US.AAPL/USD` close of the 1-minute candle for the last minute of regular trading to be **strictly above** the strike, so an exact tie resolves No. The official close is used only as a fallback. Fee rate 0.04, finance category. There are also "Up or Down" markets that compare against the prior close and resolve 50-50 on a tie. | CONFIRMED: live event 1158886 and its market descriptions. |
| S4 | Polymarket stock strikes appear only in text (`question`, `groupItemTitle: "$325"`). `groupItemThreshold` is a position index, not the strike. The underlying can be read from the Pyth URL in `resolutionSource`. | CONFIRMED: live. |
| S5 | No Kalshi–Polymarket stock or index pair is strictly equivalent. They differ on the comparison (above vs at-or-above), the tie rule (No vs 50-50), the measured price (Kalshi's own value vs a Pyth candle vs the official close per WSJ) and the underlying (the S&P index vs the SPY ETF). | CONFIRMED from the market rules above. |

## Meridian (the user's binary-stock-outcome project, planned and not deployed)

Read from `binary-stock-outcome/docs` (working tree, 2026-10-10). Labels are Meridian's own: DECIDED means an accepted decision or an approved architecture section. Nothing is deployed, so no fact here can be CONFIRMED against a live system yet.

| # | Fact | Source in Meridian |
|---|---|---|
| M1 | One binary contract per stock, strike and day, for 7 tickers (AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA). YES pays 1 USDC if the close is **at or above** the strike, so an exact tie resolves Yes. Strikes are the previous close ±3/6/9% plus the rounded close, rounded to the nearest $10. | DECIDED: D1, D6, D48, D52 |
| M2 | The settlement price is Pyth's regular-session `Equity.US.<T>/USD` price, published at or before the 4:00 PM ET close and no more than 5 s earlier. If its confidence band straddles the strike, the market goes Under review, and an admin can settle it with the official close. | DECIDED: D57, D59, D103, D112 |
| M3 | One on-chain book per market trades YES against USDC. Buying NO mints a pair and sells the YES into the bids, at a cost of 100¢ − the YES bid. Prices are whole cents from 1 to 99; quantities are whole contracts. The market-making bot quotes 5 contracts per side. | DECIDED: D5, D41, D45, ARCHITECTURE §5 |
| M4 | No protocol, maker or taker fees. Solana network costs exist: 5,000 lamports per signature plus about 0.002 SOL per new token account. | DECIDED: A1, PROBLEM_SPACE money model |
| M5 | Runs on Solana devnet with Circle devnet USDC, which has no value. | DECIDED: D3, D32, D33 |
| M6 | An outside reader would use Solana RPC (program accounts, decoded with the program's IDL) or the backend's server-sent-events stream. There is no REST endpoint for listing markets. No program ID or IDL exists yet. | DECIDED: D16, D22, ARCHITECTURE §6; build status |

## Running example: "Fed holds rates at the October 2026 meeting"

From the snapshot `samples/snapshot-2026-10-10/` (captured 2026-10-10T20:44:29Z by `capture_snapshot.py`): Kalshi `KXFEDDECISION-26OCT-H0` and Polymarket market 2589812 ("No change"). Fees are summed per level and rounded up once per order: $0.01 for Kalshi, $0.00001 for Polymarket. Reproduce with `python docs/research/running_example.py`, which also prints the other demo scenarios in architecture §7.4.

| Order | Kalshi | Polymarket | Cheaper |
|---|---|---|---|
| Buy 100 YES | 100 × $0.85 + $0.90 fee = **$85.90** | 100 × $0.84 + $0.672 fee = **$84.672** | Polymarket |
| Buy 100 NO | 100 × $0.16 + $0.95 fee = **$16.95** | 100 × $0.17 + $0.7055 fee = **$17.7055** | Kalshi |
| Buy 5,000 NO | 2 price levels, average $0.1689, $49.14 fee = **$893.7951** | 5,000 × $0.17 + $35.275 fee = **$885.275** | Polymarket |

The 100 NO and 5,000 NO rows have different winners: Kalshi's 16¢ level is too small for 5,000 contracts. Charging the fee on the average price instead of level by level, or ignoring depth, would pick the wrong venue.

## Where `docs/architectural_review.md` is wrong

1. **"Kalshi rounds to the nearest cent per order."** Out of date since the 2026-07-07 fee schedule: Kalshi rounds per fill with a per-order rebate, at $0.0001 or $0.01 depending on the account (K10). The formula also has a per-series multiplier M (K9).
2. **"Polymarket Θ ≈ 0.04–0.10 by category; macro is fee-free."** The rate is set per market, and live rates range from 0.03 to 0.07. Economics markets, including the Fed markets, pay 0.05. Only geopolitics is fee-free. The 0.10 figure comes from Polymarket US (P7, P10).
3. **"Kalshi Fed markets are cumulative thresholds (≥25, ≥50 bps)."** KXFED thresholds are on the rate level and strictly greater. KXFEDDECISION is a set of mutually exclusive buckets (K8).
4. **"Polymarket Fed markets close at month-end."** Their `endDate` falls on the FOMC decision day (P3, P6).
5. **"Kalshi deprecated cent fields."** They were removed (K2).
6. **"Kalshi orderbook: `yes_dollars` / `no_dollars` arrays."** This is correct, but they are nested under `orderbook_fp`, sorted ascending with the best price last (K4).
7. **"min_order_size e.g. '5.0'."** It is `"5"` (P4).

## Notes for implementers

- On Windows, Python's default file encoding is cp1252, and opening `samples/*.json` without `encoding="utf-8"` fails. That happened during this research.
- Sort every book explicitly. Kalshi and Polymarket each put the best price last, and Polymarket's own spec gets the order wrong.
- The October 2026 Fed event resolves on 2026-10-28. Fixtures from it are fine after that date. A live demo after it must select the next open meeting (December 2026) and must not hard-code `26OCT`.
