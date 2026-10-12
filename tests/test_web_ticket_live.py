"""feat-14 follow-up: Compare venues is only for a browser without the script.

User, 2026-10-12: "i dont see the popoint of the compare venues button as it is". The ticket prices
again as you change the order, so the script hides the button and shows a line saying the
comparison updates by itself; a browser without the script keeps the button and never sees the
line.
"""

import re

from test_web_app import COV_2_1, scores_app

from equinox.web.script import SCRIPT


def ticket(tmp_path):
    return scores_app(tmp_path).respond("/bet", f"m={COV_2_1}&side=YES&quantity=10")


def test_the_button_is_marked_as_the_fallback_and_the_script_hides_it(tmp_path):
    page = ticket(tmp_path)
    assert re.search(r"<button [^>]*data-fallback[^>]*>Compare venues</button>", page)
    assert "[data-fallback]" in SCRIPT and ".hidden = true" in SCRIPT


def test_the_page_says_the_comparison_updates_itself_only_when_the_script_runs(tmp_path):
    page = ticket(tmp_path)
    note = re.search(r"<p [^>]*data-live-note[^>]*>([^<]+)</p>", page)
    assert note and "hidden" in note.group(0)  # without the script it would be untrue
    assert "updates as you change the order" in note.group(1)
    assert "[data-live-note]" in SCRIPT and ".hidden = false" in SCRIPT
