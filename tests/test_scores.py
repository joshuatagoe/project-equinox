"""feat-11: an exact-score parser on both venues, and the model as its cross-check (D61-D65).

The raw responses are in `snapshot-2026-10-11-scores`, recorded by
`docs/research/capture_scores.py`: Coventry City v Newcastle United (full time and 1st half) and
RB Leipzig v PSV (full time), each on both venues. A catalog listing page is built here from the
recorded events; the files themselves are never edited.
"""

import html
import json
import re
from dataclasses import asdict
from datetime import date

from equinox import catalog, cli
from equinox.adapters.base import TrackedEvent
from equinox.adapters.fetch import DEFAULT_SNAPSHOT, FixtureFetcher
from equinox.adapters.kalshi import DEFAULT_BASE_URL, KalshiAdapter
from equinox.adapters.polymarket import GAMMA_URL, PolymarketAdapter
from equinox.adapters.teams import team_key
from equinox.matcher import terms_key
from equinox.reader import check, client, evals, prompt
from equinox.sources import Settings
from equinox.web import App

SCORES = DEFAULT_SNAPSHOT.parent / "snapshot-2026-10-11-scores"
KALSHI_EVENTS = (
    "KXEPLSCORE-26OCT12COVNEW",
    "KXEPL1HSCORE-26OCT12COVNEW",
    "KXUCLSCORE-26OCT13RBLPSV",
)
POLY_EVENTS = (
    "epl-cov-new-2026-10-12-exact-score",
    "epl-cov-new-2026-10-12-first-half-exact-score",
    "ucl-rbl-psv-2026-10-13-exact-score",
)
FT, HT = "kalshi:KXEPLSCORE-26OCT12COVNEW-", "kalshi:KXEPL1HSCORE-26OCT12COVNEW-"
LEIPZIG = "kalshi:KXUCLSCORE-26OCT13RBLPSV-"
P_FT = {(0, 0): "5114606", (1, 0): "5114611", (0, 1): "5114609", (2, 1): "5114624"}
P_FT |= {(1, 2): "5114622"}
P_HT = {(0, 0): "5299176", (1, 0): "5299178", (0, 1): "5299177", (2, 1): "5299189"}
P_LEIPZIG = {(2, 1): "5158655", (1, 2): "5158654"}
COVENTRY = "coventry city vs newcastle united"


def recorded():
    return FixtureFetcher(SCORES)


def kalshi_events():
    return [
        recorded()(f"{DEFAULT_BASE_URL}/events/{e}?with_nested_markets=true")["event"]
        for e in KALSHI_EVENTS
    ]


def poly_events():
    return [recorded()(f"{GAMMA_URL}/events?slug={slug}")[0] for slug in POLY_EVENTS]


def one_page(kalshi=None, poly=None):
    """A fetcher that answers each venue's listing with one page of the recorded events."""
    kalshi, poly = kalshi or kalshi_events(), poly or poly_events()

    def fetch(url):
        if url.startswith(f"{DEFAULT_BASE_URL}/events?"):
            return {"events": kalshi, "cursor": ""}
        if url.startswith(f"{GAMMA_URL}/events/keyset?"):
            return {"events": poly}
        return recorded()(url)

    return fetch


def pages(kalshi=None, poly=None):
    fetch = one_page(kalshi, poly)
    found = []
    for cls in (KalshiAdapter, PolymarketAdapter):
        found += list(cls(fetch, [], "fixture", lambda: recorded().captured_at).list_open())
    return found


def entries(kalshi=None, poly=None):
    return {e.market_id: e for page in pages(kalshi, poly) for e in page.entries}


def score_catalog(tmp_path, kalshi=None, poly=None):
    listed = pages(kalshi, poly)
    with catalog.TextStage(tmp_path) as stage:
        for page in listed:
            stage.add(page.texts)
        found = [e for page in listed for e in page.entries]
        catalog.build(found, skipped=0, cache_dir=tmp_path, seconds=0.0, texts=stage)
    return catalog.load_latest(tmp_path)


def k(prefix, home, away, teams=("COV", "NEW")):
    return f"{prefix}{teams[0]}{home}{teams[1]}{away}"


# 1-2: each venue's terms


def test_1_kalshi_reads_each_score_from_its_strike_fields():
    found = entries()
    home_win, away_win, draw = (found[k(FT, *s)].terms for s in ((2, 1), (0, 1), (0, 0)))
    assert (home_win.subject, home_win.measure) == (COVENTRY, "full_time_score_2_1")
    assert (away_win.measure, draw.measure) == ("full_time_score_0_1", "full_time_score_0_0")
    assert home_win.observed_on == date(2026, 10, 12) and home_win.measured_by == (
        "official_match_score"
    )
    assert (home_win.comparison, home_win.threshold, home_win.unit) == ("eq", 1, "indicator")
    assert found[k(HT, 1, 0)].terms.measure == "first_half_score_1_0"
    assert found[k(LEIPZIG, 2, 1, ("RBL", "PSV"))].terms.subject == "rb leipzig vs psv"


def edited_kalshi(ticker, **fields):
    events = kalshi_events()
    for event in events:
        for market in event["markets"]:
            if market["ticker"] == ticker:
                market.update(fields)
    return events


def test_1_kalshi_rules_that_state_another_score_or_period_give_no_terms():
    ticker = k(FT, 2, 1).split(":")[1]
    assert entries()[k(FT, 2, 1)].terms is not None
    other_score = edited_kalshi(
        ticker,
        custom_strike={
            **kalshi_events()[0]["markets"][0]["custom_strike"],
            "home_score": "3",
            "away_score": "1",
        },
    )
    assert entries(kalshi=other_score)[k(FT, 2, 1)].terms is None
    raw = next(m for m in kalshi_events()[0]["markets"] if m["ticker"] == ticker)
    extra_time = raw["rules_primary"].replace("does not include", "includes")
    assert (
        entries(kalshi=edited_kalshi(ticker, rules_primary=extra_time))[k(FT, 2, 1)].terms is None
    )


def key(entry):
    assert entry.terms is not None, f"{entry.market_id} has no terms"
    return terms_key(entry.terms)


def test_2_polymarket_reads_the_same_scores_the_same_way():
    found = entries()
    for score, native in P_FT.items():
        assert key(found[f"polymarket:{native}"]) == key(found[k(FT, *score)])
    for score, native in P_HT.items():
        assert key(found[f"polymarket:{native}"]) == key(found[k(HT, *score)])
    leipzig = found[k(LEIPZIG, 2, 1, ("RBL", "PSV"))]
    assert key(found["polymarket:5158655"]) == key(leipzig)
    assert found["polymarket:5114691"].terms is None  # "Any Other Score"
    assert found["polymarket:5114624"].terms.fallback_rules  # postponement, missing data


def renamed_psv(name):
    """The Leipzig event with PSV's name changed everywhere Polymarket writes it."""
    events = poly_events()
    leipzig = events[2]
    for team in leipzig["teams"]:
        if team["ordering"] == "away":
            team["name"] = name
    for market in leipzig["markets"]:
        market["question"] = market["question"].replace(" PSV?", f" {name}?")
        market["description"] = market["description"].replace(" PSV", f" {name}")
    return events


def test_2_a_question_that_names_other_teams_gives_no_terms():
    assert entries()["polymarket:5114624"].terms is not None
    events = poly_events()
    events[0]["teams"][1]["name"] = "Newcastle Jets"  # the question still says Newcastle United
    assert entries(poly=events)["polymarket:5114624"].terms is None
    events = poly_events()
    for market in events[0]["markets"]:
        market["description"] = market["description"].replace("90 minutes", "120 minutes")
    assert entries(poly=events)["polymarket:5114624"].terms is None


# 3: team keys


def test_3_team_names_agree_once_club_words_accents_and_aliases_are_read():
    assert team_key("Coventry City") == team_key("Coventry City FC")
    assert team_key("Atlético San Luis") == team_key("Atletico San Luis")
    assert team_key("St. Louis City SC") == team_key("Saint Louis City SC")
    assert team_key("CR Flamengo RJ") == team_key("CR Flamengo")
    assert team_key("PSV Eindhoven") == team_key("PSV")  # the alias table
    assert team_key("SC Corinthians SP") == team_key("SC Corinthians Paulista")
    assert team_key("Newcastle United") != team_key("Newcastle United Jets")
    assert team_key("Inter Miami CF") != team_key("Inter")


# 4: pairs


def test_4_the_same_score_is_the_same_bet_and_a_reversed_score_or_period_is_not(tmp_path):
    rows = {r.market_id: r for r in score_catalog(tmp_path).search(per_page=500)}
    assert (rows[k(FT, 2, 1)].status, rows[k(FT, 2, 1)].partner) == (
        "same bet",
        f"polymarket:{P_FT[(2, 1)]}",
    )
    assert rows[k(FT, 1, 2)].partner == f"polymarket:{P_FT[(1, 2)]}"
    assert rows[k(HT, 1, 0)].partner == f"polymarket:{P_HT[(1, 0)]}"  # not full time's 1-0
    leipzig = rows[k(LEIPZIG, 2, 1, ("RBL", "PSV"))]
    assert (leipzig.status, leipzig.partner) == ("same bet", "polymarket:5158655")
    assert leipzig.read_by is None


def test_4_a_team_name_not_in_the_alias_table_makes_no_same_bet(tmp_path):
    poly = renamed_psv("Philips SV")
    assert entries(poly=poly)["polymarket:5158655"].terms is not None  # read, but unmatched
    found = score_catalog(tmp_path, poly=poly)
    rows = {r.market_id: r for r in found.search(per_page=500)}
    assert rows[k(LEIPZIG, 2, 1, ("RBL", "PSV"))].status != "same bet"
    assert rows[k(FT, 2, 1)].status == "same bet"


# 5: the resolution source


def poly_listing(events):
    fetch = one_page(poly=events)

    def by_slug(url):
        slug = re.search(r"slug=([^&]+)", url)
        if slug and url.startswith(f"{GAMMA_URL}/events?"):
            return [e for e in events if e["slug"] == slug.group(1)]
        return fetch(url)

    tracked = [TrackedEvent(slug, "") for slug in POLY_EVENTS]
    adapter = PolymarketAdapter(by_slug, tracked, "fixture", lambda: recorded().captured_at)
    return adapter.list_markets()


def test_5_a_score_market_takes_its_events_resolution_source():
    result = poly_listing(poly_events())
    market = next(m for m in result.markets if m.native_id == "5114624")
    assert market.resolution_source.institution == "premierleague.com"
    assert market.terms.measure == "full_time_score_2_1"
    events = poly_events()
    events[0]["resolutionSource"] = ""
    result = poly_listing(events)
    assert "5114624" not in {m.native_id for m in result.markets}
    assert any(w.startswith("polymarket: market 5114624 skipped: ") for w in result.warnings)


# 6: the catalog keeps what the cross-check reads


def test_6_title_alike_parser_pairs_are_kept_as_different_with_their_texts(tmp_path):
    found = score_catalog(tmp_path)
    counts = found.pair_counts()
    assert counts[("same bet", False)] >= 13 and counts[("different", False)] > 0
    assert not any(read for _, read in counts)  # nothing was read by a model
    kept = found.texts()
    assert {k(FT, 2, 1), f"polymarket:{P_FT[(2, 1)]}"} <= set(kept)


# 7: pricing a parser same bet from the catalog


def simulate(capsys, market, quantity="10"):
    argv = ["simulate", "--market", market, "--outcome", "YES", "--quantity", quantity]
    code = cli.main([*argv, "--source", "fixtures", "--snapshot", SCORES.name, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_7_a_parser_same_bet_in_the_catalog_is_priced_without_the_model_flag(
    tmp_path, capsys, monkeypatch
):
    score_catalog(tmp_path)
    monkeypatch.setenv("EQUINOX_CACHE_DIR", str(tmp_path))
    code, trace = simulate(capsys, k(FT, 2, 1))
    assert (code, trace["status"]) == (0, "ROUTED")
    assert {q["market_id"] for q in trace["quotes"]} == {k(FT, 2, 1), "polymarket:5114624"}
    flags = trace["cluster"]["risk_flags"]
    assert not any(f.startswith("Terms read by a model") for f in flags)
    assert any("premierleague.com" in f for f in flags)  # Kalshi uses ESPN


def test_7_the_all_markets_page_links_a_parser_same_bet_by_its_market(tmp_path):
    score_catalog(tmp_path)
    app = App(Settings(cache_dir=tmp_path, snapshot=SCORES))
    listing = html.unescape(app.respond("/markets", "q=coventry 2-1"))
    assert f"outcome=catalog%3A{k(FT, 2, 1).replace(':', '%3A')}" in listing
    page = app.respond("/", f"outcome=catalog:{k(FT, 2, 1)}&side=YES&quantity=10")
    text = " ".join(re.sub(r"<[^>]+>", " ", html.unescape(page)).split())
    assert "Buy on " in text and "Terms read by a model" not in text


def test_7_a_market_in_a_loaded_family_opens_its_usual_outcome(tmp_path):
    hold = "kalshi:KXFEDDECISION-26OCT-H0"
    page = App(Settings(cache_dir=tmp_path)).respond(
        "/", f"outcome=catalog:{hold}&side=YES&quantity=10"
    )
    text = " ".join(re.sub(r"<[^>]+>", " ", html.unescape(page)).split())
    assert "Buy on " in text and "This pair can't be priced" not in text
    assert 'value="FOMC|fed_upper_bound_change|fomc_statement|2026-10-28|eq|0|bps" selected' in (
        html.unescape(page)
    )


# 8: the cross-check


class ParserModel:
    """Answers each market with the parser's own terms, except where `misread` says otherwise."""

    def __init__(self, found, misread=None):
        self.terms = {(e.event_title, e.title): e.terms for e in found.values() if e.terms}
        self.misread, self.bodies = misread or {}, []

    def __call__(self, body):
        self.bodies.append(body)
        answers = []
        for m in json.loads(body["messages"][0]["content"])["markets"]:
            terms = self.terms.get((m["event"], m["title"]))
            if terms is None:
                answers.append({"id": m["id"], "readable": False, "reason": "no score"})
                continue
            record = json.loads(terms.model_dump_json()) | {"evidence": m["title"]}
            answers.append({"id": m["id"], "readable": True, **record})
            answers[-1] |= self.misread.get(m["title"], {})
        return {
            "content": [
                {"type": "tool_use", "name": "record_terms", "input": {"markets": answers}}
            ],
            "usage": {"input_tokens": 1000, "output_tokens": 200},
        }


COV_2_1 = "Final score Coventry City wins 2-1?"


def test_8_the_cross_check_lists_each_pair_where_the_model_and_parser_disagree(tmp_path):
    found = score_catalog(tmp_path)
    before = (found.pair_counts(), [r.status for r in found.search(per_page=500)])
    model = ParserModel(entries(), {COV_2_1: {"measure": "full_time_score_1_2"}})
    report = check.check_catalog(found, model, prompt.MODEL, limit=1000)
    assert report.agree > 0 and report.markets > 0 and len(model.bodies) == report.calls
    pairs = {frozenset((d.a, d.b)): d for d in report.disagreements}
    wrong = pairs[frozenset((k(FT, 2, 1), "polymarket:5114624"))]
    assert (wrong.parser, wrong.model) == ("same bet", "different")
    assert all(k(FT, 2, 1) in (d.a, d.b) for d in report.disagreements)  # only the misread
    found = catalog.load_latest(tmp_path)
    assert (found.pair_counts(), [r.status for r in found.search(per_page=500)]) == before


def test_8_the_cross_check_finds_a_same_bet_the_alias_table_misses(tmp_path):
    poly = renamed_psv("Philips SV")
    found = score_catalog(tmp_path, poly=poly)
    model = ParserModel(entries(poly=poly))
    model.terms = {
        key: t.model_copy(update={"subject": "rb leipzig vs psv"}) if "Leipzig" in key[0] else t
        for key, t in model.terms.items()
    }
    report = check.check_catalog(found, model, prompt.MODEL, limit=1000)
    missed = [d for d in report.disagreements if d.parser == "different" and d.model == "same bet"]
    assert missed and all("RBLPSV" in d.a or "RBLPSV" in d.b for d in missed)


def test_8_catalog_check_prints_the_disagreements_and_the_tokens(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(client, "DOTENV", tmp_path / ".env")  # never the real key file
    monkeypatch.setenv("EQUINOX_CACHE_DIR", str(tmp_path))
    score_catalog(tmp_path)
    model = ParserModel(entries(), {COV_2_1: {"measure": "full_time_score_1_2"}})
    assert cli.main(["catalog", "check", "--limit", "1000"], ask=model) == 0
    out = capsys.readouterr().out
    assert "parser: same bet, model: different" in out and k(FT, 2, 1) in out
    assert "input tokens" in out


def test_8_catalog_check_without_a_key_reads_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(client, "DOTENV", tmp_path / ".env")
    monkeypatch.setenv("EQUINOX_CACHE_DIR", str(tmp_path))
    score_catalog(tmp_path)
    model = ParserModel(entries())
    assert cli.main(["catalog", "check", "--limit", "10"], ask=model) == 1
    assert model.bodies == []


# 9: the parsers label a fourth gold set


def test_9_the_score_gold_set_is_labelled_by_the_parsers():
    cases = evals.score_cases()
    assert all(len(case.markets) <= 20 for case in cases)
    labels = [same for case in cases for same in case.labels.values()]
    assert (len(labels), sum(labels)) == (68, 13)


def test_9_the_recorded_score_answers_score_as_recorded_with_no_false_same_bet():
    scores = json.loads(evals.SCORES.read_text(encoding="utf-8"))
    score = evals.score(evals.score_cases(), evals.Recorded(), scores["model"])
    assert asdict(score) == scores["scores"]
    assert scores["scores"]["false_same"] == 0 and scores["scores"]["same_found"] > 0
