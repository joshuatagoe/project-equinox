# feat-05: CLI and end-to-end checks

**Lane:** after feat-02a, 02b, 03 and 04 are merged. **Depends on:** all of them.
**Implements:** architecture §5.1 (failures), §7.4, §8.2, §11; D17, D21, D27, D28.
**Owns only:** `src/equinox/cli.py`, `src/equinox/__main__.py`, `tests/test_cli.py`.

## Goal

Wire the adapters, matcher and router into the three commands, and prove the whole pipeline on the snapshot.

## Build

- `__main__.py` calls `cli.main()`. `python -m equinox.server` keeps serving the status page, so `tests/test_equinox.py` stays green.
- `cli.main(argv) -> int` provides `markets`, `match` and `simulate`, with the flags in §8.2. Settings come from §11: environment variables, overridden by flags.
- **Loading:**
  - Read `tracked_events.json` and build one adapter per venue that has an adapter. The registry is a dict from venue name to adapter class, so a new venue is one line here.
  - With `--source fixtures`, every adapter gets a `FixtureFetcher` on the snapshot, `data_source="fixture"`, and a clock that returns the fetcher's `captured_at` (D37).
  - With `--source live`, every adapter gets an `HttpFetcher` and `datetime.now(UTC)` as its clock. If a venue raises `FetchError`, that venue is re-run with its fixture fetcher, the snapshot's clock and a warning (D17).
- **simulate:**
  - Validate the input into an `OrderRequest`. A failure → `failure_trace(INVALID_INPUT)`, exit 4.
  - Look up the market's cluster. If the market isn't loaded → MARKET_NOT_FOUND, exit 1. If it is loaded but has no terms → MARKET_NOT_FOUND, with the message "no contract terms: this market can only be matched by text".
  - Call `simulate` with `now = datetime.now(UTC)`.
  - Add the adapters' warnings to the trace's `warnings` (`model_copy`): `simulate()` sees only the quotes (D43).
  - Print the report, or the trace with `--json`. Return `EXIT_CODES[status]`.
- **Report layout:**
  - One line each for the status, the order and the cluster (members and risk flags).
  - A quote table: venue, eligible, filled, average price, fee, total, reasons.
  - Then the rationale and the warnings.
  - Money is shown to the cent (§4.6).

## Acceptance tests (write first, see each fail)

| # | Test | Expected |
|---|---|---|
| 1–8 | Every row of architecture §7.4 through `main([...])` with `--source fixtures` | The status, exit code and totals in that row |
| 9 | `simulate … --json` for row 1 | Valid JSON; `status` ROUTED; `decision.winner` `polymarket:2589812`; totals as exact strings "84.672" and "85.90" (or exactly equal `Decimal`s) |
| 10 | `markets --source fixtures` | 10 markets: 5 Kalshi and 5 Polymarket |
| 11 | `match --source fixtures` | Five clusters, each pairing one Kalshi and one Polymarket market (E1–E4, plus "25 bps increase" with H25), with their flags |
| 12 | Live mode with a fetcher that raises for Polymarket (inject the fetcher factory) | Polymarket markets are loaded from the fixtures; FIXTURE_DATA on their quotes; a warning line names Polymarket |

No test touches the network.

## Done when

`make gate` passes; `python -m equinox simulate --market kalshi:KXFEDDECISION-26OCT-H0 --outcome YES --quantity 100 --source fixtures` prints the decision in architecture §1.

## Out of scope

The HTTP API (D21), Meridian or any other new venue (architecture §9 is a design check only), and any new venue logic.
