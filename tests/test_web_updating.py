"""feat-14 follow-up: while the catalog updates, the old markets stay, and the page says so.

User, 2026-10-12: "isnt the besy way to fix to show the old items before the refresh while noting
things are updating?" During a refresh every page keeps the previous catalog's markets and says,
at the top, that they are being updated and how old they are. Markets reloads itself until the new
ones are in; the ticket never reloads, so nothing typed is lost.
"""

from test_web_app import COV_2_1, cards, chips, scores_app, words
from test_web_refresh import Stub

NOTE = "Updating markets from both venues."


def test_while_updating_markets_keep_the_old_cards_say_so_and_reload(tmp_path):
    page = scores_app(tmp_path, refresher=Stub(running=True)).respond("/", "")
    assert len(cards(page)) == 3  # the previous catalog's markets, still shown
    text = words(page)
    assert NOTE in text and "the new ones appear when the update finishes" in text
    assert '<meta http-equiv="refresh"' in page


def test_the_event_page_says_so_too_and_the_ticket_never_reloads(tmp_path):
    app = scores_app(tmp_path, refresher=Stub(running=True))
    event = app.respond("/event", f"m={COV_2_1}")
    ticket = app.respond("/bet", f"m={COV_2_1}&side=YES&quantity=10")
    assert NOTE in words(event) and NOTE in words(ticket)
    assert '<meta http-equiv="refresh"' not in ticket


def test_no_note_when_nothing_is_updating(tmp_path):
    page = scores_app(tmp_path, refresher=Stub()).respond("/", "")
    assert NOTE not in words(page) and '<meta http-equiv="refresh"' not in page


def test_a_refresh_keeps_the_previous_markets_topics_on_screen(tmp_path):
    """User, 2026-10-12: "a refresh should not erase everything that was and have just items with
    the other tag"."""
    page = scores_app(tmp_path, refresher=Stub(running=True)).respond("/", "")
    assert chips(page) == ["All", "Sports"]
    assert all(card.startswith("Sports") for card in cards(page))
