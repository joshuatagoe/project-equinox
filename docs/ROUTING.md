# Routing: which venue, and why

Given one hypothetical order and a group of equivalent markets ([EQUIVALENCE.md](EQUIVALENCE.md)), the router works out what the order would cost on every venue, decides which venues can take it, picks the cheapest of those, and writes down why. The design is architecture §7 and §8; the decisions are D5, D6, D7, D13, D16, D17, D24, D25, D27 and D43.

The router is pure: it reads only canonical markets, names no venue in its code, and takes the current time as an argument. `tests/test_layering.py` checks the first two on every run.

## What an order costs on one venue

An order is a market, an outcome (YES or NO), a number of contracts and, optionally, a budget. For each market in the group:

1. **Walk the book.** Take the outcome's asks from the cheapest price up: at each level, fill as much as is left of the order or as much as the level holds. Stop when the order is filled or the levels run out.
2. **Price it.** Base cost is the sum of price × contracts over the fills. The fee is the venue's own fee on those fills. Total cost is base plus fee. Average price is base cost over contracts filled; slippage is the average minus the best ask.

Every venue's quote is kept, including venues that turn out not to be eligible, so the trace can show what each would have cost.

### One fee formula for every venue

Both venues charge takers a fee on the curve p × (1 − p), which is largest at 50¢ and smallest near 0 and 1 (K9, P7). Equinox uses one formula for both (D13):

> fee = round up( Σ over fills of coefficient × contracts × (p × (1 − p))^exponent, to the venue's rounding step )

| Venue | Coefficient | Exponent | Rounding step |
|---|---|---|---|
| Kalshi | 0.07 × the series multiplier (1 for Fed decisions) | 1 | $0.01 (A3) |
| Polymarket | the market's `feeSchedule.rate` (0.05 for the October Fed markets), or 0 when fees are off | the market's `feeSchedule.exponent` | $0.00001 |

Fees are rounded up once per order, after summing the levels. For Kalshi that matches its per-order rebate of the per-fill rounding (K10).

### Why the fee is charged per level

The curve isn't a straight line, so the fee on an average price isn't the average fee (D5). Take 100 contracts at 10¢ and 100 at 90¢ with Kalshi's coefficient. Level by level the fee is $0.63 + $0.63 = **$1.26**. On the average price of 50¢ for 200 contracts it would be **$3.50**, nearly three times as much. `tests/test_models.py` test 4 pins both numbers.

### The running example

"Will the Fed hold rates at its October 27–28, 2026 meeting?" is Kalshi `KXFEDDECISION-26OCT-H0` and Polymarket `2589812` ("No change"), from the 2026-10-10 snapshot:

| Order | Kalshi | Polymarket | Routed to |
|---|---|---|---|
| Buy 100 YES | 100 × $0.85 + $0.90 fee = **$85.90** | 100 × $0.84 + $0.672 fee = **$84.672** | Polymarket, $1.228 less |
| Buy 100 NO | 100 × $0.16 + $0.95 fee = **$16.95** | 100 × $0.17 + $0.7055 fee = **$17.7055** | Kalshi, $0.7555 less |
| Buy 5,000 NO | 534.49 at $0.16 and 4,465.51 at $0.17, plus $49.14 fee = **$893.7951** | 5,000 × $0.17 + $35.275 fee = **$885.275** | Polymarket, $8.5201 less |

The last two rows route the same market's NO to different venues. Kalshi is cheaper at the top of the book, but its 16¢ level holds only 534.49 contracts, so a 5,000-contract order spills onto its 17¢ level. A router that priced the whole order at the best ask would quote Kalshi at $847.04 and send the order to the venue that is actually $8.52 more expensive. `python docs/research/running_example.py` reproduces every number from the raw snapshot, independently of the router.

## Books on demand

Reading every market's order book up front would be wasteful: a board of 11 meetings is 70 markets and about 85 book requests, and the router only ever needs one group at a time. So markets load from their venue's listing, which already carries each outcome's best ask (K12, P11), and the full books are fetched only for the group being priced, or for the groups on the board that more than one venue lists (D49). The router refuses a group whose books were not fetched, so a quote can never be built from a listing price alone.

## Who can take the order

A venue is excluded for any of these reasons, and every reason that applies is recorded:

| Reason | When | Why |
|---|---|---|
| `NOT_TRADABLE` | The venue says the market can't take orders now | An expiry date alone can't answer this: Polymarket markets keep trading after their end date (D25, P3) |
| `TEST_MONEY` | The market settles in money with no value | Meridian-style markets settle in devnet USDC. Comparing that with dollars would be meaningless (D24, M5) |
| `EMPTY_BOOK` | Nobody is selling this outcome | |
| `PARTIAL_FILL` | The book runs out before the order is filled | A 40-contract fill isn't comparable with a 100-contract fill on total cost (D6) |
| `OVER_BUDGET` | The order fills completely but costs more than the budget | (D7) |

Some conditions only add a warning; the venue stays eligible:

| Warning | When |
|---|---|
| `STALE_DATA` | The book is more than 300 seconds old at simulation time (D17) |
| `FIXTURE_DATA` | The book comes from the saved snapshot, not a live request (D17) |
| `DEPTH_INCOMPLETE` | The order ran past the last level of a book that the venue returned only in part |

## The decision

Among the eligible venues, the lowest total cost wins. A tie goes to the lower fee, then to the lower market ID, so the result never depends on input order. Savings are measured against the runner-up, the next eligible venue: savings = runner-up total − winner total, and the percentage is savings over the runner-up total, to 0.01.

Each outcome has a status and an exit code (D27, D43):

| Status | Exit | When |
|---|---|---|
| `ROUTED` | 0 | At least one venue is eligible |
| `MARKET_NOT_FOUND` | 1 | The requested market isn't loaded, or it has no contract terms and so belongs to no group |
| `INSUFFICIENT_LIQUIDITY` | 2 | No venue is eligible, and no open, real-money venue can fill the whole order |
| `BUDGET_EXCEEDED` | 3 | No venue is eligible, and an open, real-money venue would fill it but costs more than the budget |
| `INVALID_INPUT` | 4 | Bad arguments: a quantity of 0, an unknown outcome, a missing value |
| `NO_ELIGIBLE_VENUE` | 5 | Every venue is closed or settles in test money |

A group with one market is still routed when that market qualifies. The order names a market, so a market with no equivalent elsewhere can still be quoted and explained on its own venue.

## The explanation

Every simulation returns a **trace** in typed sections: the order, the group with its match results and risk flags, one quote per venue, the decision, a rationale, the assumptions and the warnings (D30). `--json` prints all of it. The rationale names venues only from each market's own `venue` field.

Here is the trace for buying 5,000 NO on the hold market, abridged from `python -m equinox simulate --market kalshi:KXFEDDECISION-26OCT-H0 --outcome NO --quantity 5000 --source fixtures --json`:

```jsonc
{
  "status": "ROUTED",
  "decision": {
    "winner": "polymarket:2589812",
    "runner_up": "kalshi:KXFEDDECISION-26OCT-H0",
    "savings": "8.520100",                  // 893.7951 - 885.275, kept exact
    "savings_percent": "0.95"               // of the runner-up's total
  },
  "quotes": [
    {
      "market_id": "kalshi:KXFEDDECISION-26OCT-H0",
      "eligible": true,
      "fills": [                            // the walk: the 16-cent level runs out
        {"price": "0.1600", "quantity": "534.49"},
        {"price": "0.1700", "quantity": "4465.51"}
      ],
      "average_price": "0.16893102",        // 0.9 cents of slippage over the best ask
      "fee": "49.14",                       // per level, rounded up once to the cent
      "total_cost": "893.795100",
      "warnings": ["STALE_DATA", "FIXTURE_DATA"]   // snapshot data, shown and allowed
    },
    {
      "market_id": "polymarket:2589812",
      "eligible": true,
      "fills": [{"price": "0.17", "quantity": "5000"}],
      "fee": "35.27500",
      "total_cost": "885.27500",
      "warnings": ["STALE_DATA", "FIXTURE_DATA"]
    }
  ],
  "rationale": "Polymarket is the cheapest venue that can fill all 5,000 NO contracts: $885.28 including $35.28 in fees, versus $893.80 on Kalshi ($8.52 or 0.95% less). Match risks: Edge-case rules differ: Kalshi: If the meeting is cancelled, 'Fed maintains rate' resolves Yes. Polymarket: A change not shown in the brackets is rounded up to the nearest 25 bps. ..."
}
```

Amounts are exact strings in JSON. In the text report they are rounded to the cent, and shown to 5 decimal places when two totals would otherwise round to the same cent (architecture §4.6).

An excluded venue gets its own sentence. From the cut-by-25 market, buying 100 NO:

> Polymarket is the only eligible venue that can fill all 100 NO contracts: $99.62 including $0.02 in fees. Kalshi was not eligible: nobody is selling NO.

The fit-check markets show the same for test money. Meridian-style AAPL-330 is cheaper ($4.75 for 5 YES against Polymarket's $4.80768), but it settles in devnet USDC, so Polymarket wins and the rationale says Meridian "would cost $4.75" (architecture §9.3).

## Pairs a model read

The router doesn't know how a group's terms were read. A same bet a model read (EQUIVALENCE.md, D57) reaches it through the same cluster as a parser-read one, with two differences in what it is given: the pair is priced only when the committed evals show zero false same-bets for the model and prompt that read it (D58), and its cluster carries the risk flag "Terms read by a model", which the trace prints and which keeps the confidence at Medium. On 2026-10-11, 10 YES on Kalshi's `KXBALLONDOR-26-KMBA` (Mbappé wins the 2026 Ballon d'Or), read as the same bet as Polymarket `608540`, routed to Polymarket at $0.22 against $0.33 on Kalshi; the trace also flagged that Kalshi names foxnews.com and Polymarket francefootball.fr as the source.

## Pairs a parser read from the catalog

Exact scores have parsers (D61) but are not a discovered family, so a score pair is priced from the catalog too. The venues' listings are read again, their parsers give the terms, and the group goes to the router with no gate and no model flag (D65). On 2026-10-12, 10 YES on Coventry City 2-1 Newcastle United routed to Polymarket at $0.84 against $0.86 on Kalshi; the trace flagged that Kalshi settles by ESPN and Polymarket by the league's statistics, and that only Polymarket states what a postponement does.

## Assumptions

Every trace carries these, worded for the reader (DECISIONS.md, Assumptions):

- **A1:** One US dollar equals one USDC, with no transfer cost or delay. This holds only for collateral with monetary value.
- **A2:** Order books are frozen at the moment they were captured. There is no latency, queue position or market impact.
- **A3:** Kalshi fees are rounded up to the cent, as for FCM-cleared accounts. A direct-member account could pay up to 1¢ less per order; rounding up never understates the cost.
- **A4** concerns only the paper mapping of a Meridian-like venue (architecture §9.1) and doesn't affect routing.
- **A5:** Costs use list fees. Polymarket's taker rebates and builder fees are ignored, so it can be cheaper in practice than shown.

## Limits

- One order goes to one venue. Splitting an order across venues, selling, and maker orders are out of scope (D6).
- The simulation is only as fresh as its books. Snapshot runs warn on every quote; live runs read the books once, in about 18 requests.
- A venue's per-order costs that don't scale with contracts, such as Solana transaction fees on Meridian, aren't modelled (DECISIONS.md, "Cut").
