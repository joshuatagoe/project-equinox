"""feat-09 test 9: the All markets page; and the board's order of strict and exact outcomes."""

import html
import re
from datetime import UTC, date, datetime
from decimal import Decimal

from equinox import catalog
from equinox.adapters.fetch import DEFAULT_SNAPSHOT
from equinox.models import ContractTerms
from equinox.models.catalog import CatalogEntry
from equinox.sources import Settings
from equinox.web import App

NEW = DEFAULT_SNAPSHOT.parent / "snapshot-2026-10-11"


def words(page):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def entry(native, venue, title, day, terms=None):
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
        terms=terms,
    )


def built(tmp_path):
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
        entry("may1", "alpha", "Will Smith win the 2026 Springfield mayor race?", 3),
        entry("may2", "beta", "Springfield mayor race 2026: Smith wins?", 3),
        entry("fed1", "alpha", "Fed holds rates in December", 9, terms=fed),
        entry("fed2", "beta", "No change in December", 9, terms=fed),
        entry("lone", "beta", "Will it snow in Miami?", 3),
    ]
    catalog.build(entries, skipped=0, cache_dir=tmp_path, seconds=1.0)
    return App(Settings(cache_dir=tmp_path))


def test_9_search_finds_entries_and_shows_why_a_pair_is_unclear(tmp_path):
    text = words(built(tmp_path).respond("/markets", "q=springfield"))
    assert "Will Smith win the 2026 Springfield mayor race?" in text
    assert "Springfield mayor race 2026: Smith wins?" in text
    assert "Unclear" in text and "0.71" in text and "never routed" in text
    assert "Will it snow in Miami?" not in text


def test_9_filters_narrow_the_results(tmp_path):
    app = built(tmp_path)
    same = words(app.respond("/markets", "status=same+bet"))
    assert "Fed holds rates in December" in same and "Springfield" not in same
    beta = words(app.respond("/markets", "venue=beta"))
    # alpha:fed1 is still named as beta:fed2's match, but it is not a row of its own.
    assert "beta:fed2" in beta and "alpha:fed1" not in beta


def test_9_without_a_catalog_the_page_says_how_to_build_one(tmp_path):
    text = words(App(Settings(cache_dir=tmp_path / "none")).respond("/markets", ""))
    assert "python -m equinox catalog refresh" in text


def test_board_lists_a_deeper_cut_before_a_smaller_one():
    text = words(App(Settings()).respond("/board", f"data={NEW.name}"))
    march = text[text.index("Fed rate decision, March 17, 2027") :]
    assert march.index("Cut more than 25 bps") < march.index("Cut 25 bps")
    assert march.index("Hike 25 bps") < march.index("Hike more than 25 bps")
