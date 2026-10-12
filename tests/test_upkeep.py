"""feat-12: the model as a detector of parser upkeep.

Each catalog market records the parser family meant to read it, even when the parser gave it no
terms: an exact score whose wording a venue changed keeps its family. `catalog check --drift` reads
only those markets with the model and says which still look like the family (a rewording the
parser misses) and which don't. It changes nothing: they stay unclear or unmatched, never routed.
"""

import json

from test_scores import P_FT, entries, poly_events, score_catalog

from equinox import catalog, cli
from equinox.models.catalog import CatalogEntry, MarketText
from equinox.reader import check, client, prompt

RENAMED = "polymarket:5114624"  # Coventry City FC 2 - 1 Newcastle United FC


def reworded():
    """Polymarket rewrites one score question; its event's teams still name the old spelling."""
    events = poly_events()
    for market in events[0]["markets"]:
        if str(market["id"]) == RENAMED.split(":")[1]:
            market["question"] = "Exact Score: Coventry 2 - 1 Newcastle?"
    return events


def test_6_a_market_keeps_its_family_when_its_terms_fail():
    found = entries(poly=reworded())
    assert found[RENAMED].terms is None and found[RENAMED].family == "exact_score"
    assert found[f"polymarket:{P_FT[(1, 0)]}"].family == "exact_score"
    assert found["polymarket:5114691"].family == ""  # "Any Other Score": no parser reads it
    assert found["kalshi:KXEPLSCORE-26OCT12COVNEW-COV2NEW1"].family == "exact_score"


class Reader:
    """Reads every market as an exact score, except the titles in `other`: a match winner."""

    def __init__(self, other=()):
        self.other, self.bodies = other, []

    def __call__(self, body):
        self.bodies.append(body)
        answers = []
        for m in json.loads(body["messages"][0]["content"])["markets"]:
            measure = "winner_coventry" if m["title"] in self.other else "full_time_score_2_1"
            record = {
                "readable": True,
                "subject": "coventry_vs_newcastle",
                "measure": measure,
                "measured_by": "official_match_result",
                "observed_on": "2026-10-12",
                "comparison": "eq",
                "threshold": "1",
                "unit": "indicator",
                "evidence": m["title"],
            }
            answers.append({"id": m["id"], **record})
        return {
            "content": [
                {"type": "tool_use", "name": "record_terms", "input": {"markets": answers}}
            ],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }


def test_6_the_drift_check_reads_only_family_markets_without_terms(tmp_path):
    found = score_catalog(tmp_path, poly=reworded())
    before = [r.status for r in found.search(per_page=500)]
    reader = Reader()
    report = check.drift(found, reader, prompt.MODEL, limit=100)
    assert [d.market_id for d in report.candidates] == [RENAMED]
    assert report.candidates[0].verdict == "looks like exact_score: the parser missed it"
    assert len(reader.bodies) == 1
    found = catalog.load_latest(tmp_path)
    assert [r.status for r in found.search(per_page=500)] == before


def test_6_a_market_the_model_reads_as_something_else_is_not_a_rewording(tmp_path):
    found = score_catalog(tmp_path, poly=reworded())
    report = check.drift(
        found, Reader(other={"Exact Score: Coventry 2 - 1 Newcastle?"}), prompt.MODEL, limit=100
    )
    assert report.candidates[0].verdict == "not exact_score: the model read winner_coventry"


def test_6_a_refresh_keeps_the_text_of_a_family_market_in_no_pair(tmp_path):
    def lone(native, title, family):
        return CatalogEntry(
            f"beta:{native}", "beta", title, title, "", None, True, None, None, family=family
        )

    listed = [lone("a", "Exact Score: CFC 2 - 1 NUFC?", "exact_score"), lone("b", "Rain?", "")]
    with catalog.TextStage(tmp_path) as stage:
        stage.add({e.market_id: MarketText(f"Rules of {e.market_id}.") for e in listed})
        catalog.build(listed, skipped=0, cache_dir=tmp_path, seconds=0.0, texts=stage)
    assert set(catalog.load_latest(tmp_path).texts()) == {"beta:a"}


def test_6_catalog_check_drift_prints_the_candidates(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(client, "DOTENV", tmp_path / ".env")  # never the real key file
    monkeypatch.setenv("EQUINOX_CACHE_DIR", str(tmp_path))
    score_catalog(tmp_path, poly=reworded())
    assert cli.main(["catalog", "check", "--drift", "--limit", "50"], ask=Reader()) == 0
    out = capsys.readouterr().out
    assert RENAMED in out and "the parser missed it" in out and "input tokens" in out


def test_6_an_old_catalog_without_families_says_to_refresh(tmp_path):
    found = score_catalog(tmp_path)
    with found.connect(write=True) as db:
        db.execute("ALTER TABLE entries DROP COLUMN family")
        db.commit()
    report = check.drift(catalog.load_latest(tmp_path), Reader(), prompt.MODEL, limit=10)
    assert report.candidates == [] and "refresh" in report.problem
