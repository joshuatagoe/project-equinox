"""feat-14 commit 1: Equinox as an app. Jordan finds a bet, sees both prices and prices an order.

The web app is built from the catalog of every open market: the home page lists the events both
venues list, an event page shows each outcome's prices on both venues, and the order ticket prices
an order from the venues' order books for that one pair. Morgan's question, "is it really the same
bet?", is answered on the ticket. A pair whose titles only look alike never appears here.
"""

import html
import re
import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from test_reader import MBAPPE_K, PAIR, ballon_catalog
from test_scores import FT, SCORES, k, pages, score_catalog, simulate

from equinox import catalog
from equinox.adapters.base import FetchError
from equinox.models import ContractTerms
from equinox.models.catalog import CatalogEntry
from equinox.reader import prompt
from equinox.sources import Settings
from equinox.web import App

COV_2_1 = k(FT, 2, 1)
NOW = datetime(2026, 10, 12, 9, tzinfo=UTC)


def words(page):
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(page)).split())


def cards(page):
    """Each event card on a list page, as its text."""
    return [words(c) for c in re.findall(r'<a class="card"[^>]*>(.*?)</a>', page, re.S)]


def scores_app(tmp_path, **options):
    score_catalog(tmp_path)
    settings = Settings(source="fixtures", snapshot=SCORES, cache_dir=tmp_path)
    return App(settings, clock=lambda: NOW, **options)


def entry(native, venue, title, terms=None, topic="", day=9):
    return CatalogEntry(
        market_id=f"{venue}:{native}",
        venue=venue,
        event_title=title,
        title=title,
        outcome_label="",
        closes_at=datetime(2026, 12, day, 20, tzinfo=UTC),
        tradable=True,
        yes_ask=Decimal("0.40"),
        no_ask=Decimal("0.62"),
        terms=terms,
        topic=topic,
    )


FED = ContractTerms(
    subject="FOMC",
    measure="fed_upper_bound_change",
    measured_by="fomc_statement",
    observed_on=date(2026, 12, 9),
    comparison="eq",
    threshold=Decimal(0),
    unit="bps",
)


def mixed(tmp_path, fed_title="Fed holds rates in December"):
    """A same bet, a pair whose titles only look alike, and a market no other venue matches."""
    entries = [
        entry("fed1", "alpha", fed_title, FED),
        entry("fed2", "beta", "No change in December", FED),
        entry("may1", "alpha", "Will Smith win the 2026 Springfield mayor race?"),
        entry("may2", "beta", "Springfield mayor race 2026: Smith wins?"),
        entry("lone", "beta", "Will it snow in Miami?"),
    ]
    catalog.build(entries, skipped=0, cache_dir=tmp_path, seconds=1.0)
    return App(Settings(source="fixtures", cache_dir=tmp_path), clock=lambda: NOW)


# The home page: every event both venues list, by topic, and a search.


def test_home_shows_one_card_per_event_both_venues_list_with_both_prices(tmp_path):
    found = cards(scores_app(tmp_path).respond("/", ""))
    full_time = [c for c in found if "Coventry City vs Newcastle United: Correct Score" in c]
    assert len(found) == 3 and len(full_time) == 1
    assert re.search(r"Kalshi [\d.]+¢ Polymarket [\d.]+¢", full_time[0])
    assert "Sports" in full_time[0] and "32 outcomes" in full_time[0]


def test_a_pair_that_only_looks_alike_never_appears(tmp_path):
    app = mixed(tmp_path)
    home = words(app.respond("/", ""))
    assert "Fed holds rates in December" in home
    assert "Springfield" not in home and "snow" not in home
    found = words(app.respond("/", "q=springfield"))
    assert "Springfield" not in found.replace("springfield", "")
    assert "No bet on both venues matches" in found


def chips(page):
    """The topic chips' labels, or [] when the page shows none."""
    bar = re.search(r'<nav class="chips"[^>]*>(.*?)</nav>', page, re.S)
    return re.findall(r"<a [^>]*>([^<]+)<span>", bar.group(1)) if bar else []


def test_topics_narrow_the_events(tmp_path):
    """Changed with the user's OK (G5, 2026-10-12): one topic shows no chips; the filter stays."""
    app = scores_app(tmp_path)
    assert chips(app.respond("/", "")) == []  # every event is Sports: nothing to pick
    assert len(cards(app.respond("/", "topic=Sports"))) == 3
    none = app.respond("/", "topic=Politics")
    assert cards(none) == [] and "No events in Politics" in words(none)


def test_two_topics_show_their_chips(tmp_path):
    later = FED.model_copy(update={"observed_on": date(2026, 12, 20)})
    entries = [
        entry("f1", "alpha", "Fed holds rates in December", FED, topic="Economics"),
        entry("f2", "beta", "No change in December", FED),
        entry("g1", "alpha", "Final whistle bet", later, topic="Sports", day=20),
        entry("g2", "beta", "Final whistle wager", later, day=20),
    ]
    catalog.build(entries, skipped=0, cache_dir=tmp_path, seconds=1.0)
    page = App(Settings(source="fixtures", cache_dir=tmp_path)).respond("/", "")
    assert chips(page) == ["All", "Economics", "Sports"]
    assert re.search(r'<a [^>]*href="/\?topic=Sports"[^>]*>Sports', page)


def test_an_event_with_no_topic_is_under_other(tmp_path):
    """Changed with the user's OK (G5): the card says Other; with one topic there are no chips."""
    app = mixed(tmp_path)
    page = app.respond("/", "")
    assert cards(page)[0].startswith("Other") and chips(page) == []
    assert len(cards(app.respond("/", "topic=Other"))) == 1


def test_an_older_catalog_without_topics_still_opens(tmp_path):
    """Changed with the user's OK (G5): every card says Other, and there are no chips."""
    score_catalog(tmp_path)
    with sqlite3.connect(catalog.store.latest(tmp_path)) as db:
        db.execute("ALTER TABLE entries DROP COLUMN topic")
    app = App(Settings(source="fixtures", snapshot=SCORES, cache_dir=tmp_path))
    page = app.respond("/", "")
    assert len(cards(page)) == 3 and all(c.startswith("Other") for c in cards(page))
    assert chips(page) == []


def test_search_finds_the_outcome_within_its_event(tmp_path):
    found = cards(scores_app(tmp_path).respond("/", "q=coventry 2-1"))
    assert any("Coventry City wins 2-1" in c for c in found)
    assert not any("wins 2-0" in c for c in found)


def test_search_finds_a_bet_by_the_other_venues_words(tmp_path):
    found = cards(scores_app(tmp_path).respond("/", "q=exact score coventry city fc 2 - 1"))
    assert any("Coventry City wins 2-1" in c for c in found)


def test_events_closing_soonest_come_first(tmp_path):
    later = FED.model_copy(update={"observed_on": date(2026, 12, 20)})
    entries = [
        entry("a1", "alpha", "Alpha meeting holds", later, day=20),
        entry("a2", "beta", "Alpha meeting: no change", later, day=20),
        entry("z1", "alpha", "Zulu meeting holds", FED, day=9),
        entry("z2", "beta", "Zulu meeting: no change", FED, day=9),
    ]
    catalog.build(entries, skipped=0, cache_dir=tmp_path, seconds=1.0)
    found = cards(App(Settings(source="fixtures", cache_dir=tmp_path)).respond("/", ""))
    assert "Zulu" in found[0] and "Alpha" in found[1]


def test_home_says_how_old_its_prices_are(tmp_path):
    text = words(scores_app(tmp_path).respond("/", ""))
    assert re.search(r"Prices as of the last refresh, [\w ]+ ago", text)


def test_without_a_catalog_home_says_how_to_get_one(tmp_path):
    text = words(App(Settings(cache_dir=tmp_path / "none")).respond("/", ""))
    assert "python -m equinox catalog refresh" in text


# The event page: each outcome on both venues.


def test_the_event_page_shows_each_outcome_on_both_venues_with_buy_buttons(tmp_path):
    page = scores_app(tmp_path).respond("/event", f"m={COV_2_1}")
    text = words(page)
    assert "Coventry City vs Newcastle United: Correct Score" in text
    row = re.search(r"Coventry City wins 2-1.{0,400}", text).group(0)
    assert re.search(r"Kalshi .*Polymarket", row)
    assert "YES pays $1 if the score after 90 minutes is Coventry City 2, Newcastle United 1" in (
        text
    )
    links = html.unescape(page)
    assert f"/bet?m={COV_2_1.replace(':', '%3A')}&side=YES" in links
    assert f"/bet?m={COV_2_1.replace(':', '%3A')}&side=NO" in links
    assert text.count("Buy YES") == 32


def test_an_event_lists_its_likeliest_outcome_first(tmp_path):
    """Likeliest by the cheapest YES offer: a thin book's 46¢ ask doesn't put a 1¢ outcome first."""
    cut = FED.model_copy(update={"threshold": Decimal(-25)})

    def outcome(native, venue, terms, yes, label):
        listed = entry(native, venue, "Fed decision in December", terms)
        return replace(listed, outcome_label=label, yes_ask=Decimal(yes))

    entries = [
        outcome("h1", "alpha", FED, "0.46", "Hold"),
        outcome("h2", "beta", FED, "0.01", "Hold"),
        outcome("c1", "alpha", cut, "0.30", "Cut"),
        outcome("c2", "beta", cut, "0.32", "Cut"),
    ]
    catalog.build(entries, skipped=0, cache_dir=tmp_path, seconds=1.0)
    page = App(Settings(source="fixtures", cache_dir=tmp_path)).respond("/event", "m=alpha:h1")
    names = [name.strip() for name in re.findall(r'<div class="what">([^<]+)', page)]
    assert names == ["Cut", "Hold"]


def test_an_unknown_event_says_so(tmp_path):
    text = words(scores_app(tmp_path).respond("/event", "m=kalshi:NOPE"))
    assert "isn't a bet both venues list" in text


# The order ticket: the answer, the cost on each venue, why, and whether it's the same bet.


def test_the_ticket_answers_first_then_the_costs_then_whether_it_is_the_same_bet(tmp_path):
    text = words(scores_app(tmp_path).respond("/bet", f"m={COV_2_1}&side=YES&quantity=10"))
    answer = text.index("Buy on ")
    assert answer < text.index("Cost on each venue") < text.index("Is this really the same bet?")
    panel = text[text.index("Is this really the same bet?") :]
    assert panel.count("Pays YES if") == 1 and "Confidence:" in panel
    assert "Equinox's own reader" in panel and "read by a model" not in panel
    assert "Settlement source differs" in panel  # each venue names its own source


def test_the_ticket_and_the_command_line_agree(tmp_path, capsys, monkeypatch):
    text = words(scores_app(tmp_path).respond("/bet", f"m={COV_2_1}&side=YES&quantity=10"))
    monkeypatch.setenv("EQUINOX_CACHE_DIR", str(tmp_path))
    _, trace = simulate(capsys, COV_2_1)
    for quote in trace["quotes"]:
        cents = Decimal(quote["total_cost"]).quantize(Decimal("0.01"), ROUND_HALF_UP)
        assert f"${cents:,}" in text, quote["market_id"]


def test_a_model_read_pair_says_so_on_the_ticket(tmp_path, monkeypatch):
    ballon_catalog(tmp_path, monkeypatch)
    app = App(Settings(source="fixtures", snapshot=PAIR, cache_dir=tmp_path))
    text = words(app.respond("/bet", f"m={MBAPPE_K}&side=YES&quantity=10"))
    assert "Buy on " in text and "read by a model" in text and "Confidence: Medium" in text
    assert not re.search(r"\(D\d+\)", text)  # decision numbers are for the docs


def test_a_pair_that_cant_be_priced_says_why(tmp_path, monkeypatch):
    ballon_catalog(tmp_path, monkeypatch, version="older")
    monkeypatch.setattr(prompt, "PROMPT_VERSION", "feat-10.7")
    app = App(Settings(source="fixtures", snapshot=PAIR, cache_dir=tmp_path))
    text = words(app.respond("/bet", f"m={MBAPPE_K}&side=YES&quantity=10"))
    assert "This bet can't be priced" in text and "Buy on " not in text


def test_when_the_venues_cant_be_reached_the_ticket_says_so(tmp_path):
    score_catalog(tmp_path)

    def down(venue):
        def fail(url):
            raise FetchError(f"{url}: connection refused")

        return fail

    app = App(Settings(source="live", cache_dir=tmp_path), live_fetcher=down)
    text = words(app.respond("/bet", f"m={COV_2_1}&side=YES&quantity=10"))
    assert "The venues can't be reached right now" in text and "Buy on " not in text


def test_a_catalog_read_from_a_snapshot_is_priced_from_that_snapshot(tmp_path):
    listed = pages()
    found = [e for page in listed for e in page.entries]
    catalog.build(found, skipped=0, cache_dir=tmp_path, seconds=0.0, source=SCORES.name)

    def down(venue):
        def fail(url):
            raise FetchError(f"{url}: connection refused")

        return fail

    app = App(Settings(source="live", cache_dir=tmp_path), live_fetcher=down)
    text = words(app.respond("/bet", f"m={COV_2_1}&side=YES&quantity=10"))
    assert "Buy on " in text


def test_bad_input_is_explained_next_to_the_form(tmp_path):
    app = scores_app(tmp_path)
    zero = words(app.respond("/bet", f"m={COV_2_1}&side=YES&quantity=0"))
    assert "Contracts must be a number greater than 0." in zero and "Buy on " not in zero
    side = words(app.respond("/bet", f"m={COV_2_1}&side=MAYBE&quantity=10"))
    assert "Choose Buy YES or Buy NO." in side
    budget = words(app.respond("/bet", f"m={COV_2_1}&side=YES&quantity=10&budget=lots"))
    assert "The budget must be a dollar amount greater than 0." in budget


# The whole app.


def test_no_page_offers_a_data_source_and_the_old_pages_are_gone(tmp_path):
    app = scores_app(tmp_path)
    pages = [app.respond("/", ""), app.respond("/event", f"m={COV_2_1}")]
    pages.append(app.respond("/bet", f"m={COV_2_1}&side=YES&quantity=10"))
    assert all('name="data"' not in page for page in pages)
    assert all(app.respond(path, "") is None for path in ("/board", "/match", "/markets"))


def test_text_from_the_venues_is_escaped(tmp_path):
    app = mixed(tmp_path, fed_title="<script>alert(1)</script>")
    pages = [app.respond("/", ""), app.respond("/event", "m=alpha:fed1")]
    assert all("<script>alert(1)</script>" not in page for page in pages)
    assert all("&lt;script&gt;alert(1)&lt;/script&gt;" in page for page in pages)
