"""feat-12: a model-read pair is priced with readings that agree, not each market's latest.

A market in several pairs is read in several requests, and the model names it differently from one
request to the next ("taylor_swift" / "time_person_of_the_year_2026" in one, the other way round in
another). Pricing used each market's latest reading, so 71 of 229 live same bets "no longer
matched". It now uses the most recent readings of the group that agree, which is what made the
pair the same bet.
"""

from test_reader import MBAPPE_K, ballon_catalog, simulate_mbappe

from equinox import catalog
from equinox.catalog import readings
from equinox.catalog.readings import ReadingRow
from equinox.models import ContractTerms
from equinox.reader import prompt


def read_again_with_other_names(tmp_path):
    """A later request reads the Kalshi market alone, naming it another way."""
    other = ContractTerms(
        subject="kylian_mbappe",
        measure="wins_ballon_d_or_2026",
        measured_by="france_football",
        observed_on="2026-12-31",
        comparison="eq",
        threshold=1,
        unit="indicator",
    )
    row = ReadingRow(MBAPPE_K, 99, other.model_dump_json(), "", "If Kylian Mbappe wins")
    readings.record(catalog.load_latest(tmp_path), prompt.MODEL, prompt.PROMPT_VERSION, [row], [])


def test_a_later_reading_with_other_names_doesnt_stop_the_pair_pricing(
    tmp_path, capsys, monkeypatch
):
    ballon_catalog(tmp_path, monkeypatch)
    read_again_with_other_names(tmp_path)
    code, trace = simulate_mbappe(capsys)
    assert (code, trace["status"]) == (0, "ROUTED")


def test_a_pair_with_no_readings_that_agree_is_not_priced(tmp_path, capsys, monkeypatch):
    ballon_catalog(tmp_path, monkeypatch)
    found = catalog.load_latest(tmp_path)
    with found.connect(write=True) as db:  # Kalshi keeps only a reading that disagrees
        db.execute("DELETE FROM readings WHERE market_id = ?", (MBAPPE_K,))
        db.commit()
    read_again_with_other_names(tmp_path)
    code, trace = simulate_mbappe(capsys)
    assert code == 1 and "agree" in trace["rationale"]
