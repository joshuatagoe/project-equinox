"""feat-10: reading terms with a model, checking them, and deciding with the rules (D56-D58)."""

import html
import json
import re
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from equinox import catalog, cli
from equinox.adapters.fetch import DEFAULT_SNAPSHOT, FixtureFetcher
from equinox.adapters.kalshi import KalshiAdapter
from equinox.adapters.polymarket import PolymarketAdapter
from equinox.matcher import confidence
from equinox.matcher.terms import decide
from equinox.models import ContractTerms, EquivalenceStatus, MatchResult
from equinox.models.catalog import CatalogEntry, MarketText, ReadableMarket
from equinox.reader import checks, client, evals, prompt, run
from equinox.sources import Settings
from equinox.web import App

NEW = DEFAULT_SNAPSHOT.parent / "snapshot-2026-10-11"


def listing_texts(cls):
    fetch = FixtureFetcher(NEW)
    adapter = cls(fetch, [], "fixture", lambda: fetch.captured_at)
    pages = list(adapter.list_open(page_size=20, max_pages=2))
    listed = {e.market_id for p in pages for e in p.entries}
    return listed, {market: text for p in pages for market, text in p.texts.items()}


def test_1_listing_pages_carry_each_markets_rules_and_strike_fields():
    listed, texts = listing_texts(KalshiAdapter)
    assert set(texts) == listed
    assert texts["kalshi:KXELONMARS-99"].rules.startswith("If Elon Musk visits Mars before")
    assert texts["kalshi:KXELONMARS-99"].strike == ""
    mbappe = json.loads(texts["kalshi:KXWCCAREERGOALS-KMBAPPE-30"].strike)
    assert (mbappe["strike_type"], mbappe["floor_strike"]) == ("greater", "29.5")  # at least 30
    listed, texts = listing_texts(PolymarketAdapter)
    assert set(texts) == listed
    assert texts["polymarket:3886788"].rules.startswith(
        'This market will resolve to "Yes" if Kraken'
    )


def entry(native, venue, title, day=3):
    return CatalogEntry(
        market_id=f"{venue}:{native}",
        venue=venue,
        event_title=title,
        title=title,
        outcome_label="",
        closes_at=datetime(2026, 11, day, 20, tzinfo=UTC),
        tradable=True,
        yes_ask=Decimal("0.40"),
        no_ask=Decimal("0.62"),
    )


def test_2_the_catalog_keeps_texts_only_for_markets_in_unclear_pairs(tmp_path):
    entries = [
        entry("may1", "alpha", "Will Smith win the 2026 Springfield mayor race?"),
        entry("may2", "beta", "Springfield mayor race 2026: Smith wins?"),
        entry("lone", "beta", "Will it snow in Miami?"),
    ]
    with catalog.TextStage(tmp_path) as stage:
        stage.add({e.market_id: MarketText(f"Rules of {e.market_id}.") for e in entries})
        catalog.build(entries, skipped=0, cache_dir=tmp_path, seconds=0.0, texts=stage)
    kept = catalog.load_latest(tmp_path).texts()
    assert kept == {m: MarketText(f"Rules of {m}.") for m in ("alpha:may1", "beta:may2")}
    assert [p.suffix for p in tmp_path.iterdir()] == [".sqlite"]


def terms(**changes):
    base = {
        "subject": "core_pce",
        "measure": "monthly_change",
        "measured_by": "bea_release",
        "observed_on": date(2026, 10, 29),
        "comparison": "gt",
        "threshold": Decimal("0.1"),
        "unit": "percent",
    }
    return ContractTerms(**(base | changes))


def test_3_the_pair_rules_run_on_terms_alone():
    same = decide(terms(), terms())
    assert same.status == EquivalenceStatus.EQUIVALENT and same.flags == ()
    exactly = decide(terms(), terms(comparison="eq"))
    assert exactly.status == EquivalenceStatus.DISTINCT
    at_least = decide(terms(), terms(comparison="ge"), ("Alpha", "Beta"))
    assert at_least.status == EquivalenceStatus.EQUIVALENT
    assert at_least.flags == (
        "Tie rule differs: at exactly 0.1 percent, Alpha pays No and Beta pays Yes.",
    )
    other_source = decide(terms(), terms(measured_by="fed_release"))
    assert other_source.status == EquivalenceStatus.AMBIGUOUS


def test_3_yes_no_outcomes_are_indicators_of_the_named_outcome():
    def score(home_away):
        return terms(
            subject="al_wasl_fc_vs_al_ahli_saudi_fc",
            measure=f"final_score_{home_away}",
            measured_by="official_match_result",
            comparison="eq",
            threshold=Decimal(1),
            unit="indicator",
        )

    assert decide(score("0_1"), score("0_1")).status == EquivalenceStatus.EQUIVALENT
    assert decide(score("0_1"), score("1_0")).status == EquivalenceStatus.DISTINCT


# Checks: the model reads, deterministic code accepts or rejects (D57).

PCE = ReadableMarket(
    market_id="alpha:pce",
    venue="alpha",
    event_title="How much will core PCE increase in Sep 2026?",
    title="Will the rate of core PCE inflation be above 0.1% in September 2026?",
    outcome_label="Above 0.1%",
    closes_at=datetime(2026, 10, 29, 14, tzinfo=UTC),
    text=MarketText(
        "If the core PCE change for September 2026 is above 0.1%, as first released by the BEA, "
        "the market resolves to Yes.",
        '{"strike_type": "greater", "floor_strike": "0.1"}',
    ),
)
GOOD = {
    "id": "m1",
    "readable": True,
    "subject": "core_pce",
    "measure": "monthly_change_september_2026",
    "measured_by": "bea_release",
    "observed_on": "2026-10-29",
    "comparison": "gt",
    "threshold": "0.1",
    "unit": "percent",
    "evidence": "above 0.1%",
}


def test_4_a_reading_that_matches_the_text_is_accepted():
    reading = checks.accept(GOOD, PCE)
    assert reading.problem == ""
    assert (reading.terms.comparison, reading.terms.threshold) == ("gt", Decimal("0.1"))


def test_4_a_reading_the_text_does_not_support_is_rejected():
    def problem(**change):
        reading = checks.accept(GOOD | change, PCE)
        assert reading.terms is None
        return reading.problem

    assert "0.2 is not a number in the market's text" in problem(threshold="0.2")
    assert "is not in the market's text" in problem(evidence="at least 0.1%")
    assert "says above, so gt" in problem(comparison="eq")
    assert "after the market closes" in problem(observed_on="2027-03-01")
    unreadable = checks.accept({"id": "m1", "readable": False, "reason": "Two conditions."}, PCE)
    assert unreadable.terms is None and "Two conditions." in unreadable.problem


def test_4_kalshi_strike_fields_must_agree_and_whole_counts_compare_as_whole_numbers():
    inclusive = replace(
        PCE,
        text=replace(PCE.text, strike='{"strike_type": "greater_or_equal", "floor_strike": "0.1"}'),
    )
    assert "strike fields say ge 0.1" in checks.accept(GOOD, inclusive).problem
    goals = ReadableMarket(
        market_id="alpha:goals",
        venue="alpha",
        event_title="Kylian Mbappe World Cup career goals",
        title="Will Kylian Mbappe score at least 30 goals in the World Cup in his career?",
        outcome_label="30+ Goals Scored",
        closes_at=datetime(2030, 7, 20, tzinfo=UTC),
        text=MarketText("", '{"strike_type": "greater", "floor_strike": "29.5"}'),
    )
    reading = GOOD | {
        "subject": "kylian_mbappe",
        "measure": "world_cup_career_goals",
        "measured_by": "fifa",
        "observed_on": "2030-07-19",
        "comparison": "ge",
        "threshold": "30",
        "unit": "count",
        "evidence": "at least 30 goals",
    }
    assert checks.accept(reading, goals).problem == ""


def test_4_a_yes_no_outcome_is_an_indicator_equal_to_one():
    award = replace(
        PCE,
        title="Will Taylor Swift be TIME Person of the Year 2026?",
        outcome_label="Taylor Swift",
        closes_at=datetime(2026, 12, 31, tzinfo=UTC),
        text=MarketText("Resolves Yes if TIME names Taylor Swift its 2026 Person of the Year."),
    )
    reading = {
        "id": "m1",
        "readable": True,
        "subject": "time_person_of_the_year_2026",
        "measure": "named_taylor_swift",
        "measured_by": "time_magazine",
        "observed_on": "2026-12-15",
        "comparison": "eq",
        "threshold": "1",
        "unit": "indicator",
        "evidence": "Taylor Swift be TIME Person of the Year 2026",
    }
    assert checks.accept(reading, award).problem == ""
    assert checks.accept(reading | {"comparison": "gt"}, award).terms is None
    # An indicator's threshold is 1 by definition; the outcome is in its measure.
    score = checks.accept(reading | {"threshold": "5-1"}, award)
    assert score.problem == "" and score.terms.threshold == 1


# Reading the catalog: groups, decisions, the cache and the command (D57, D58).

SPRING = (
    "Will Smith win the 2026 Springfield mayor race?",
    "Springfield mayor race 2026: Smith wins?",
)
SHELBY = (
    "Will Jones win the 2026 Shelbyville mayor race?",
    "Shelbyville mayor race 2026: Jones wins?",
)
MAYOR = {
    "readable": True,
    "subject": "springfield_mayor_2026",
    "measure": "winner_smith",
    "measured_by": "springfield_election_board",
    "observed_on": "2026-11-03",
    "comparison": "eq",
    "threshold": "1",
    "unit": "indicator",
}
READINGS = {
    SPRING[0]: MAYOR | {"evidence": "Smith win the 2026 Springfield mayor race"},
    SPRING[1]: MAYOR | {"evidence": "Smith wins"},
    SHELBY[0]: MAYOR | {"subject": "shelbyville_mayor_2026", "evidence": "Will Jones win"},
    SHELBY[1]: MAYOR | {"subject": "shelbyville_mayor_2026", "evidence": "Jones wins"},
}


class FakeModel:
    """Answers each request with the readings for its markets' titles, as the API would."""

    def __init__(self, readings):
        self.readings, self.bodies = readings, []

    def __call__(self, body):
        self.bodies.append(body)
        markets = json.loads(body["messages"][0]["content"])["markets"]
        answers = [{"id": m["id"], **self.readings[m["title"]]} for m in markets]
        return {
            "content": [
                {"type": "tool_use", "name": "record_terms", "input": {"markets": answers}}
            ],
            "usage": {"input_tokens": 1000, "output_tokens": 200},
        }


def mayors(tmp_path, titles=(SPRING,)):
    entries = [
        entry(f"{n}{side}", venue, title, day=3 + 10 * n)  # events far apart
        for n, pair in enumerate(titles)
        for side, (venue, title) in enumerate(zip(("alpha", "beta"), pair, strict=True))
    ]
    with catalog.TextStage(tmp_path) as stage:
        stage.add({e.market_id: MarketText("Resolves by the official count.") for e in entries})
        catalog.build(entries, skipped=0, cache_dir=tmp_path, seconds=0.0, texts=stage)
    return catalog.load_latest(tmp_path)


def rows(tmp_path):
    return {r.market_id: r for r in catalog.load_latest(tmp_path).search(per_page=50)}


def test_5_two_accepted_readings_decide_their_pair(tmp_path):
    report = run.read_catalog(mayors(tmp_path), FakeModel(READINGS), "claude-haiku-5-5", limit=10)
    assert (report.markets, report.accepted, report.rejected, report.same_bet) == (2, 2, 0, 1)
    assert (report.input_tokens, report.output_tokens) == (1000, 200)
    smith = rows(tmp_path)["alpha:00"]
    assert (smith.status, smith.partner) == ("same bet", "beta:01")
    assert smith.read_by == f"claude-haiku-5-5 (prompt {prompt.PROMPT_VERSION})"


def test_5_a_rejected_reading_leaves_its_pair_unclear(tmp_path):
    bad = READINGS | {SPRING[1]: MAYOR | {"evidence": "Smith takes office"}}
    report = run.read_catalog(mayors(tmp_path), FakeModel(bad), "claude-haiku-5-5", limit=10)
    assert (report.accepted, report.rejected, report.same_bet) == (1, 1, 0)
    assert rows(tmp_path)["alpha:00"].status == "unclear"
    problems = catalog.load_latest(tmp_path).readings()
    assert "is not in the market's text" in problems["beta:01"]


def test_5_readings_of_different_outcomes_make_a_different_bet(tmp_path):
    jones = READINGS | {SPRING[1]: MAYOR | {"measure": "winner_jones", "evidence": "Smith wins"}}
    report = run.read_catalog(mayors(tmp_path), FakeModel(jones), "claude-haiku-5-5", limit=10)
    assert (report.accepted, report.different, report.same_bet) == (2, 1, 0)
    assert {r.status for r in rows(tmp_path).values()} == {"no match"}


def test_6_the_same_request_is_sent_only_once(tmp_path):
    model = FakeModel(READINGS)
    cached = client.Cached(model, tmp_path / "readings.sqlite")
    content = json.dumps({"markets": [{"id": "m1", "title": SPRING[0]}]})
    body = {"model": "claude-haiku-5-5", "messages": [{"role": "user", "content": content}]}
    assert cached(body) == cached(body)
    assert len(model.bodies) == 1 and (cached.sent, cached.reused) == (1, 1)
    assert (cached.input_tokens, cached.output_tokens) == (1000, 200)  # paid once


def test_7_catalog_read_without_a_key_reads_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(client, "DOTENV", tmp_path / ".env")
    monkeypatch.setenv("EQUINOX_CACHE_DIR", str(tmp_path))
    mayors(tmp_path)
    model = FakeModel(READINGS)
    assert cli.main(["catalog", "read", "--limit", "5"], ask=model) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().out and model.bodies == []


def test_7_catalog_read_stops_at_the_limit_and_prints_the_tokens(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(client, "DOTENV", tmp_path / ".env")  # never the real key file
    monkeypatch.setenv("EQUINOX_CACHE_DIR", str(tmp_path))
    mayors(tmp_path, (SPRING, SHELBY))
    model = FakeModel(READINGS)
    assert cli.main(["catalog", "read", "--limit", "3"], ask=model) == 0
    out = capsys.readouterr().out
    assert len(model.bodies) == 1 and "2 markets read" in out and "1,000 input tokens" in out


def test_9_a_model_read_same_bet_says_so_on_the_all_markets_page(tmp_path):
    run.read_catalog(mayors(tmp_path), FakeModel(READINGS), "claude-haiku-5-5", limit=10)
    page = App(Settings(cache_dir=tmp_path)).respond("/markets", "q=springfield")
    text = " ".join(re.sub(r"<[^>]+>", " ", html.unescape(page)).split())
    assert "Same bet, read by a model" in text
    assert f"Terms read by claude-haiku-5-5 (prompt {prompt.PROMPT_VERSION})" in text
    assert "1 outcome is the same bet as read by a model" in text


def test_4_no_change_is_zero_even_when_the_evidence_names_a_year():
    hold = replace(
        PCE,
        title="Will there be no change in Fed interest rates after the December 2026 meeting?",
        outcome_label="No change",
        text=MarketText("The upper bound of the target range."),
    )
    reading = GOOD | {
        "subject": "fomc",
        "measure": "fed_upper_bound_change",
        "measured_by": "fomc_statement",
        "comparison": "eq",
        "threshold": "0",
        "unit": "bps",
        "evidence": hold.title,
    }
    assert checks.accept(reading, hold).problem == ""


def test_3_counts_compare_as_whole_numbers():
    goals = terms(unit="count", comparison="gt", threshold=Decimal("1.5"))
    assert decide(goals, terms(unit="count", comparison="ge", threshold=Decimal(2))).flags == ()
    assert decide(goals, terms(unit="count", comparison="ge", threshold=Decimal(2))).status == (
        EquivalenceStatus.EQUIVALENT
    )
    assert decide(goals, terms(unit="count", comparison="ge", threshold=Decimal(3))).status == (
        EquivalenceStatus.DISTINCT
    )


def test_4_a_number_in_the_strike_fields_is_stated_by_the_venue():
    props = replace(
        PCE,
        title="Davante Adams: 2+ touchdowns",
        outcome_label="Davante Adams: 2+",
        text=MarketText("", '{"strike_type": "greater", "floor_strike": "1.5"}'),
    )
    reading = GOOD | {
        "comparison": "gt",
        "threshold": "1.5",
        "unit": "count",
        "evidence": "2+ touchdowns",
    }
    assert checks.accept(reading, props).problem == ""


def test_5_a_malformed_answer_leaves_its_markets_unread():
    markets = [PCE, replace(PCE, market_id="beta:pce")]
    as_text = {
        "content": [{"type": "tool_use", "name": "record_terms", "input": {"markets": "[]"}}]
    }
    as_strings = {
        "content": [{"type": "tool_use", "name": "record_terms", "input": {"markets": ["m1"]}}]
    }
    for answer in (as_text, as_strings, {"content": []}):
        records = prompt.answers(answer, markets)
        assert all(not r["readable"] for r in records.values()), answer


def test_5_records_sent_as_text_with_trailing_junk_are_still_read():
    text = json.dumps([GOOD]) + "}"  # seen live: the list as text, with a stray brace
    answer = {"content": [{"type": "tool_use", "name": "record_terms", "input": {"markets": text}}]}
    assert prompt.answers(answer, [PCE])["alpha:pce"]["evidence"] == "above 0.1%"


def test_5_pairs_decided_by_an_older_prompt_are_read_again(tmp_path, monkeypatch):
    found = mayors(tmp_path)
    model = FakeModel(READINGS)
    run.read_catalog(found, model, "claude-haiku-5-5", limit=10)
    run.read_catalog(found, model, "claude-haiku-5-5", limit=10)
    assert len(model.bodies) == 1  # nothing left to read with the same prompt and model
    monkeypatch.setattr(prompt, "PROMPT_VERSION", "next")
    report = run.read_catalog(found, model, "claude-haiku-5-5", limit=10)
    assert len(model.bodies) == 2 and report.same_bet == 1
    assert rows(tmp_path)["alpha:00"].read_by == "claude-haiku-5-5 (prompt next)"


# Commit 2: pricing a same bet a model read, only when the evals allow it (D58).

PAIR = NEW.parent / "snapshot-2026-10-11-pair"
MBAPPE_K, MBAPPE_P = "kalshi:KXBALLONDOR-26-KMBA", "polymarket:608540"
YEAR_END = datetime(2026, 12, 31, 23, tzinfo=UTC)
BALLON = {
    "readable": True,
    "subject": "ballon_d_or_2026",
    "measure": "named_kylian_mbappe",
    "measured_by": "france_football",
    "observed_on": "2026-12-31",
    "comparison": "eq",
    "threshold": "1",
    "unit": "indicator",
}
BALLON_TITLES = (
    "Who will win the Ballon d'Or in 2026?",
    "Will Kylian Mbappé win the 2026 Ballon d'Or?",
)
BALLON_READINGS = {
    BALLON_TITLES[0]: BALLON | {"evidence": "If Kylian Mbappe wins the Ballon d'Or in 2026"},
    BALLON_TITLES[1]: BALLON | {"evidence": "Kylian Mbappé win the 2026 Ballon d'Or"},
}


def ballon_catalog(tmp_path, monkeypatch, version=None):
    entries = [
        replace(
            entry("x", "kalshi", BALLON_TITLES[0]),
            market_id=MBAPPE_K,
            outcome_label="Kylian Mbappe",
            closes_at=YEAR_END,
        ),
        replace(
            entry("y", "polymarket", BALLON_TITLES[1]),
            market_id=MBAPPE_P,
            outcome_label="Kylian Mbappé",
            closes_at=YEAR_END,
        ),
    ]
    texts = {
        MBAPPE_K: MarketText(
            "If Kylian Mbappe wins the Ballon d'Or in 2026, then the market resolves to Yes."
        ),
        MBAPPE_P: MarketText(
            "This market will resolve according to the winner of the 2026 Ballon d'Or."
        ),
    }
    with catalog.TextStage(tmp_path) as stage:
        stage.add(texts)
        catalog.build(entries, skipped=0, cache_dir=tmp_path, seconds=0.0, texts=stage)
    if version:
        monkeypatch.setattr(prompt, "PROMPT_VERSION", version)
    run.read_catalog(
        catalog.load_latest(tmp_path), FakeModel(BALLON_READINGS), prompt.MODEL, limit=10
    )
    monkeypatch.setenv("EQUINOX_CACHE_DIR", str(tmp_path))


def simulate_mbappe(capsys):
    argv = ["simulate", "--market", MBAPPE_K, "--outcome", "YES", "--quantity", "10"]
    code = cli.main([*argv, "--source", "fixtures", "--snapshot", PAIR.name, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_10_a_model_read_same_bet_is_priced_when_the_evals_allow(tmp_path, capsys, monkeypatch):
    ballon_catalog(tmp_path, monkeypatch)
    code, trace = simulate_mbappe(capsys)
    assert (code, trace["status"]) == (0, "ROUTED")
    assert {q["market_id"] for q in trace["quotes"]} == {MBAPPE_K, MBAPPE_P}
    assert any(f.startswith("Terms read by a model") for f in trace["cluster"]["risk_flags"])
    # Only warnings about the two markets priced: not their events' other markets or parsers.
    assert not any("no term parser" in w or "608550" in w for w in trace["warnings"])


def test_10_a_pair_read_with_another_prompt_is_not_routed(tmp_path, capsys, monkeypatch):
    ballon_catalog(tmp_path, monkeypatch, version="older")
    monkeypatch.setattr(prompt, "PROMPT_VERSION", "feat-10.7")
    code, trace = simulate_mbappe(capsys)
    assert (code, trace["status"]) == (1, "MARKET_NOT_FOUND")
    assert "prompt older" in trace["rationale"] and "evals" in trace["rationale"]


def test_10_no_model_read_pair_is_routed_when_the_evals_show_a_false_same_bet(
    tmp_path, capsys, monkeypatch
):
    ballon_catalog(tmp_path, monkeypatch)
    scores = json.loads(evals.SCORES.read_text(encoding="utf-8"))
    scores["held_out"]["false_same"] = 1
    (tmp_path / "scores.json").write_text(json.dumps(scores), encoding="utf-8")
    monkeypatch.setattr(evals, "SCORES", tmp_path / "scores.json")
    code, trace = simulate_mbappe(capsys)
    assert (code, trace["status"]) == (1, "MARKET_NOT_FOUND")
    assert "false same-bet" in trace["rationale"]


def test_10_a_model_read_pair_is_medium_confidence_at_most():
    pair = MatchResult(
        market_a="a:1",
        market_b="b:1",
        status=EquivalenceStatus.EQUIVALENT,
        method="terms",
        risk_flags=("Terms read by a model: claude-haiku-5-5 (prompt feat-10.7).",),
    )
    level = confidence(pair)
    assert level.level == "Medium" and "read by a model" in level.reason


def test_10_the_all_markets_page_links_a_model_read_pair_to_its_price(tmp_path, monkeypatch):
    ballon_catalog(tmp_path, monkeypatch)
    app = App(Settings(cache_dir=tmp_path, snapshot=PAIR))
    listing = html.unescape(app.respond("/markets", "q=mbappe"))
    assert f"outcome=catalog%3A{MBAPPE_K.replace(':', '%3A')}" in listing
    page = app.respond("/", f"outcome=catalog:{MBAPPE_K}&side=YES&quantity=10")
    text = " ".join(re.sub(r"<[^>]+>", " ", html.unescape(page)).split())
    assert "Buy on " in text and "Terms read by a model" in text
    assert "Confidence: Medium" in text
