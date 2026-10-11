"""feat-09 tests 3-5 and 10: finding title candidates at catalog scale (D50), and their outcomes."""

import time
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from equinox import catalog
from equinox.matcher.index import candidates, index_titles
from equinox.models import ContractTerms
from equinox.models.catalog import CatalogEntry


def entry(native, venue, title, day, terms=None):
    closes = datetime(2026, 11, day, 20, tzinfo=UTC) if day else None
    return CatalogEntry(
        market_id=f"{venue}:{native}",
        venue=venue,
        event_title=title,
        title=title,
        outcome_label="",
        closes_at=closes,
        tradable=True,
        yes_ask=Decimal("0.40"),
        no_ask=Decimal("0.62"),
        terms=terms,
    )


def paired(entries):
    items = index_titles(entries)
    return {frozenset((entries[i].market_id, entries[j].market_id)) for i, j in candidates(items)}


def test_3_a_candidate_shares_two_informative_words_and_closes_within_three_days():
    game = entry(1, "alpha", "Will the Lakers beat the Celtics in Game 7?", 3)
    near = entry(1, "beta", "Lakers vs Celtics: Game 7 winner?", 4)
    far = entry(2, "beta", "Lakers vs Celtics: Game 7 winner?", 14)
    one_word = entry(3, "beta", "Celtics championship parade?", 3)
    same_venue = entry(2, "alpha", "Lakers beat Celtics in Game 7 again?", 3)
    found = paired([game, near, far, one_word, same_venue])
    assert frozenset((game.market_id, near.market_id)) in found
    assert not any(far.market_id in pair or one_word.market_id in pair for pair in found)
    assert frozenset((game.market_id, same_venue.market_id)) not in found


def test_3_words_too_common_on_a_venue_are_not_informative():
    common = [entry(i, "alpha", f"Election result for district {i}", 5) for i in range(60)]
    mayor = entry(99, "alpha", "Springfield mayor election", 5)
    words = index_titles([*common, mayor])[-1].words
    assert "election" not in words  # in 61 of 61 alpha titles
    assert {"springfield", "mayor"} <= words


def test_4_outcomes_are_never_equivalent_and_the_counts_add_up(tmp_path):
    fed = ContractTerms(
        subject="FOMC",
        measure="fed_upper_bound_change",
        measured_by="fomc_statement",
        observed_on=date(2026, 12, 9),
        comparison="eq",
        threshold=Decimal(0),
        unit="bps",
    )
    entries = [
        entry("btc1", "alpha", "Will Bitcoin hit 100000 by November 20?", 20),
        entry("btc2", "beta", "Bitcoin hits 120000 by November 20?", 20),
        entry("may1", "alpha", "Will Smith win the 2026 Springfield mayor race?", 3),
        entry("may2", "beta", "Springfield mayor race 2026: Smith wins?", 3),
        entry("fed1", "alpha", "Fed holds rates in December", 9, terms=fed),
        entry("fed2", "beta", "No change in December", 9, terms=fed),
        entry("lone", "beta", "Will it snow in Miami?", 3),
    ]
    summary = catalog.build(entries, skipped=0, cache_dir=tmp_path, seconds=1.0)
    assert (summary.candidates, summary.distinct, summary.ambiguous) == (2, 1, 1)
    assert summary.same_bet_groups == 1
    assert summary.vetoes == {"Numbers": 1}
    rows = {r.market_id: r for r in catalog.load_latest(tmp_path).search(per_page=100)}
    assert rows["alpha:may1"].status == "unclear" and rows["alpha:may1"].score == Decimal("0.71")
    assert rows["alpha:fed1"].status == rows["beta:fed2"].status == "same bet"
    assert rows["alpha:btc1"].status == rows["beta:lone"].status == "no match"
    assert all(r.status in {"same bet", "unclear", "no match"} for r in rows.values())


def test_5_fifty_thousand_markets_a_side_are_matched_within_a_minute(tmp_path):
    alpha = [
        entry(i, "alpha", f"Team {i} beats team {i + 1} on match day", 1 + i % 28)
        for i in range(50_000)
    ]
    beta = [
        entry(i, "beta", f"Match day: team {i} versus team {i + 1}", 1 + i % 28)
        for i in range(50_000)
    ]
    started = time.perf_counter()
    summary = catalog.build([*alpha, *beta], skipped=0, cache_dir=tmp_path, seconds=0.0)
    elapsed = time.perf_counter() - started
    assert summary.candidates >= 50_000
    assert elapsed < 60, f"{elapsed:.1f} s"


# Added after a mutation check found these rules untested.

FED_HOLD = ContractTerms(
    subject="FOMC",
    measure="fed_upper_bound_change",
    measured_by="fomc_statement",
    observed_on=date(2026, 12, 9),
    comparison="eq",
    threshold=Decimal(0),
    unit="bps",
)


def rows_of(tmp_path, entries):
    summary = catalog.build(entries, skipped=0, cache_dir=tmp_path, seconds=0.0)
    rows = catalog.load_latest(tmp_path).search(per_page=100)
    return summary, {r.market_id: r for r in rows}


def test_4_the_same_terms_twice_on_one_venue_are_not_a_match(tmp_path):
    twins = [
        entry("fed1", "alpha", "Fed holds rates in December", 9, terms=FED_HOLD),
        entry("fed2", "alpha", "No change in December", 9, terms=FED_HOLD),
    ]
    summary, rows = rows_of(tmp_path, twins)
    assert summary.same_bet_groups == 0
    assert {r.status for r in rows.values()} == {"no match"}


def test_4_two_markets_with_terms_are_left_to_their_terms(tmp_path):
    hike = FED_HOLD.model_copy(update={"threshold": Decimal(25)})
    pair = [
        entry("fed1", "alpha", "Fed rate decision in December", 9, terms=FED_HOLD),
        entry("fed2", "beta", "Fed rate decision in December", 9, terms=hike),
    ]
    summary, rows = rows_of(tmp_path, pair)
    assert (summary.candidates, summary.same_bet_groups) == (0, 0)
    assert {r.status for r in rows.values()} == {"no match"}


def test_4_a_market_shows_its_most_similar_match(tmp_path):
    entries = [
        entry("may1", "alpha", "Springfield mayor race 2026: Smith wins?", 3),
        entry("may2", "beta", "Springfield mayor race 2026: Smith wins?", 3),
        entry("may3", "beta", "Springfield mayor race 2026: will Smith win the runoff?", 3),
    ]
    _, rows = rows_of(tmp_path, entries)
    assert rows["alpha:may1"].partner == "beta:may2"
    assert rows["alpha:may1"].score == Decimal("1.00")


def test_4_an_outcome_label_the_title_lacks_is_compared_too(tmp_path):
    pope = entry("pope1", "alpha", "Who will the next Pope be?", 5)
    pope = replace(pope, outcome_label="Pietro Parolin")
    parolin = entry("pope2", "beta", "Will Pietro Parolin be the next Pope?", 5)
    _, rows = rows_of(tmp_path, [pope, parolin])
    assert rows["alpha:pope1"].score == Decimal("1.00")
    assert rows["beta:pope2"].partner_title == "Who will the next Pope be? (Pietro Parolin)"


def test_7_a_market_listed_twice_is_kept_once(tmp_path):
    lone = entry("lone", "beta", "Will it snow in Miami?", 3)
    summary, rows = rows_of(tmp_path, [lone, lone])
    assert summary.entries == {"beta": 1} and list(rows) == ["beta:lone"]


def test_4_markets_naming_different_outcomes_are_different_bets(tmp_path):
    # From the live refresh: 73% of unclear pairs named two different people or teams.
    keria = replace(
        entry("mvp1", "alpha", "Will Keria win Finals MVP at League of Legends Worlds?", 29),
        outcome_label="Keria",
    )
    eddie = replace(
        entry("mvp2", "beta", "Will Eddie win Worlds 2026 Finals MVP?", 29), outcome_label="Eddie"
    )
    summary, rows = rows_of(tmp_path, [keria, eddie])
    assert (summary.candidates, summary.distinct, summary.vetoes) == (1, 1, {"Outcomes": 1})
    assert {r.status for r in rows.values()} == {"no match"}


def test_4_a_label_the_other_title_mentions_is_not_a_different_outcome(tmp_path):
    # The same bet on both venues, labelled by year on one and by name on the other.
    year = replace(
        entry("ocean1", "alpha", "Will Frank Ocean release a new album in 2026?", 30),
        outcome_label="2026",
    )
    name = replace(
        entry("ocean2", "beta", "Will Frank Ocean release an album in 2026?", 30),
        outcome_label="Frank Ocean",
    )
    _, rows = rows_of(tmp_path, [year, name])
    assert (
        rows["alpha:ocean1"].status == "unclear" and rows["alpha:ocean1"].partner == "beta:ocean2"
    )
