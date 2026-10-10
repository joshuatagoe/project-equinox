"""feat-05 acceptance tests: the CLI end to end on the snapshot. No test touches the network."""

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from equinox import cli
from equinox.adapters.base import FetchError
from equinox.adapters.fetch import DEFAULT_SNAPSHOT, FixtureFetcher

H0 = "kalshi:KXFEDDECISION-26OCT-H0"
C25 = "kalshi:KXFEDDECISION-26OCT-C25"
PM_NO_CHANGE = "polymarket:2589812"
PM_25_DOWN = "polymarket:2589811"
REPO = Path(__file__).resolve().parents[1]


def run(capsys, *args, **kwargs):
    code = cli.main(list(args), **kwargs)
    return code, capsys.readouterr().out


def simulate_json(capsys, *args, **kwargs):
    code, out = run(capsys, "simulate", *args, "--json", **kwargs)
    return code, json.loads(out)


def totals(trace):
    return {q["market_id"]: Decimal(q["total_cost"]) for q in trace["quotes"]}


def quote(trace, market_id):
    [found] = [q for q in trace["quotes"] if q["market_id"] == market_id]
    return found


# Tests 1-8: every row of architecture section 7.4, with --source fixtures.

ROWS = {
    "hold 100 YES": (
        [H0, "YES", "100"],
        ("ROUTED", 0, PM_NO_CHANGE),
        {PM_NO_CHANGE: "84.672", H0: "85.90"},
    ),
    "hold 100 NO": ([H0, "NO", "100"], ("ROUTED", 0, H0), {H0: "16.95", PM_NO_CHANGE: "17.7055"}),
    "hold 5000 NO": (
        [H0, "NO", "5000"],
        ("ROUTED", 0, PM_NO_CHANGE),
        {PM_NO_CHANGE: "885.275", H0: "893.7951"},
    ),
    "over budget": (
        [H0, "YES", "100", "80"],
        ("BUDGET_EXCEEDED", 3, None),
        {PM_NO_CHANGE: "84.672", H0: "85.90"},
    ),
    "too deep": ([H0, "YES", "5000000"], ("INSUFFICIENT_LIQUIDITY", 2, None), {}),
    "cut 25 NO": ([C25, "NO", "100"], ("ROUTED", 0, PM_25_DOWN), {PM_25_DOWN: "99.61992"}),
    "unknown market": (["kalshi:NOPE", "YES", "1"], ("MARKET_NOT_FOUND", 1, None), {}),
    "zero quantity": ([H0, "YES", "0"], ("INVALID_INPUT", 4, None), {}),
}


def order_args(market, outcome, quantity, budget=None):
    args = ["--market", market, "--outcome", outcome, "--quantity", quantity]
    return args + (["--budget", budget] if budget else []) + ["--source", "fixtures"]


@pytest.mark.parametrize("order, expected, expected_totals", ROWS.values(), ids=ROWS.keys())
def test_1_to_8_demo_rows(capsys, order, expected, expected_totals):
    status, exit_code, winner = expected
    code, trace = simulate_json(capsys, *order_args(*order))
    assert (trace["status"], code) == (status, exit_code)
    assert (trace["decision"] or {}).get("winner") == winner
    for market_id, total in expected_totals.items():
        assert totals(trace)[market_id] == Decimal(total)


def test_3_kalshi_walks_two_levels_for_5000_no(capsys):
    _, trace = simulate_json(capsys, *order_args(H0, "NO", "5000"))
    kalshi = quote(trace, H0)
    assert [(Decimal(f["price"]), Decimal(f["quantity"])) for f in kalshi["fills"]] == [
        (Decimal("0.16"), Decimal("534.49")),
        (Decimal("0.17"), Decimal("4465.51")),
    ]


def test_5_the_full_books_run_out_at_the_documented_depth(capsys):
    _, trace = simulate_json(capsys, *order_args(H0, "YES", "5000000"))
    assert Decimal(quote(trace, H0)["filled_quantity"]) == Decimal("4649443.27")
    assert Decimal(quote(trace, PM_NO_CHANGE)["filled_quantity"]) == Decimal("3453123.38")
    assert all("PARTIAL_FILL" in q["reasons"] for q in trace["quotes"])


def test_6_an_empty_book_is_shown_but_cannot_win(capsys):
    _, trace = simulate_json(capsys, *order_args(C25, "NO", "100"))
    assert "EMPTY_BOOK" in quote(trace, C25)["reasons"]


def test_text_report_states_the_decision_and_every_quote(capsys):
    code, out = run(capsys, "simulate", *order_args(H0, "YES", "100"))
    assert code == 0
    assert out.splitlines()[0].startswith("ROUTED")
    assert "Polymarket is the cheapest venue that can fill all 100 YES contracts" in out
    for text in ("$84.67", "$85.90", "1.43%", PM_NO_CHANGE, H0, "Edge-case rules differ"):
        assert text in out


@pytest.mark.parametrize(
    "args",
    [
        ["--market", H0, "--outcome", "MAYBE", "--quantity", "1"],
        ["--market", H0, "--outcome", "YES", "--quantity", "lots"],
        ["--market", H0, "--outcome", "YES"],
        ["--market", H0, "--outcome", "YES", "--quantity", "5", "--budget", "-1"],
    ],
    ids=["unknown outcome", "quantity not a number", "quantity missing", "negative budget"],
)
def test_bad_arguments_are_invalid_input_not_a_usage_crash(capsys, args):
    code, trace = simulate_json(capsys, *args, "--source", "fixtures")
    assert (trace["status"], code) == ("INVALID_INPUT", 4)
    assert trace["rationale"]


def test_a_market_without_terms_is_not_found_for_routing(capsys, tmp_path, monkeypatch):
    tracked = {"polymarket": [{"event_id": "aapl-close-above-on-october-12-2026", "family": "x"}]}
    path = tmp_path / "tracked_events.json"
    path.write_text(json.dumps(tracked), encoding="utf-8")
    monkeypatch.setattr(cli, "TRACKED_EVENTS", path)
    code, trace = simulate_json(capsys, *order_args("polymarket:5455686", "YES", "5"))
    assert (trace["status"], code) == ("MARKET_NOT_FOUND", 1)
    assert "no contract terms: this market can only be matched by text" in trace["rationale"]


# Test 9: --json prints the whole trace.


def test_9_json_trace_for_the_running_example(capsys):
    code, trace = simulate_json(capsys, *order_args(H0, "YES", "100"))
    assert code == 0 and trace["status"] == "ROUTED"
    assert trace["decision"]["winner"] == PM_NO_CHANGE
    assert isinstance(quote(trace, PM_NO_CHANGE)["total_cost"], str)  # exact, not a float
    assert totals(trace) == {PM_NO_CHANGE: Decimal("84.672"), H0: Decimal("85.90")}
    assert {m["market_id"] for m in trace["cluster"]["markets"]} == {H0, PM_NO_CHANGE}
    assert any("FIXTURE_DATA" in q["warnings"] for q in trace["quotes"])
    assert len(trace["assumptions"]) == 4


# Tests 10 and 11: markets and match.


def test_10_markets_lists_ten_snapshot_markets(capsys):
    code, out = run(capsys, "markets", "--source", "fixtures", "--json")
    listing = json.loads(out)
    assert code == 0
    venues = [m["venue"] for m in listing["markets"]]
    assert (venues.count("kalshi"), venues.count("polymarket"), len(venues)) == (5, 5, 10)

    code, text = run(capsys, "markets", "--source", "fixtures")
    assert code == 0
    assert all(m["market_id"] in text for m in listing["markets"])


FED_PAIRS = {
    frozenset(("kalshi:KXFEDDECISION-26OCT-C26", "polymarket:2589810")): {"Equal only", "Edge"},
    frozenset((C25, PM_25_DOWN)): {"Edge"},
    frozenset((H0, PM_NO_CHANGE)): {"Edge"},
    frozenset(("kalshi:KXFEDDECISION-26OCT-H25", "polymarket:2589813")): {"Edge"},
    frozenset(("kalshi:KXFEDDECISION-26OCT-H26", "polymarket:2589814")): {"Equal only", "Edge"},
}


def test_11_match_pairs_each_kalshi_market_with_one_polymarket_market(capsys):
    code, out = run(capsys, "match", "--source", "fixtures", "--json")
    clusters = json.loads(out)["clusters"]
    assert code == 0 and len(clusters) == 5
    found = {}
    for cluster in clusters:
        members = frozenset(m["market_id"] for m in cluster["markets"])
        flags = cluster["risk_flags"]
        found[members] = {"Edge" for f in flags if f.startswith("Edge-case rules differ: ")} | {
            "Equal only" for f in flags if f.startswith("Equal only on the 25 bps grid: ")
        }
    assert found == FED_PAIRS

    code, text = run(capsys, "match", "--source", "fixtures")
    assert code == 0 and "Edge-case rules differ" in text


# Test 12: a live venue that fails falls back to the snapshot (D17).


def live_fetcher_failing_for(failing_venue):
    def factory(venue):
        if venue == failing_venue:

            def fail(url):
                raise FetchError(f"{url}: connection refused")

            return fail
        return FixtureFetcher(DEFAULT_SNAPSHOT)  # stands in for a working live venue

    return factory


def test_12_a_failing_live_venue_is_loaded_from_the_snapshot(capsys):
    code, trace = simulate_json(
        capsys,
        *["--market", H0, "--outcome", "YES", "--quantity", "100", "--source", "live"],
        live_fetcher=live_fetcher_failing_for("polymarket"),
    )
    assert (trace["status"], code) == ("ROUTED", 0)
    assert "FIXTURE_DATA" in quote(trace, PM_NO_CHANGE)["warnings"]
    assert "FIXTURE_DATA" not in quote(trace, H0)["warnings"]
    # The fallback notice itself, not the router's FIXTURE_DATA line, which also names the snapshot.
    fallback = [w for w in trace["warnings"] if "live data unavailable" in w]
    assert len(fallback) == 1 and fallback[0].startswith("Polymarket:")
    assert "snapshot captured 2026-10-10" in fallback[0]


def test_12_the_fallback_is_announced_in_the_text_report(capsys):
    code, out = run(
        capsys,
        "markets",
        "--source",
        "live",
        live_fetcher=live_fetcher_failing_for("kalshi"),
    )
    assert code == 0
    assert "Kalshi: live data unavailable" in out and "snapshot captured" in out


# Done when: the section 1 command prints the decision, through python -m equinox.


def test_python_dash_m_equinox_prints_the_running_example_decision():
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    command = [sys.executable, "-m", "equinox", "simulate", *order_args(H0, "YES", "100")]
    result = subprocess.run(command, capture_output=True, text=True, env=env, cwd=REPO)
    assert result.returncode == 0, result.stderr
    assert "Polymarket is the cheapest venue that can fill all 100 YES contracts" in result.stdout
