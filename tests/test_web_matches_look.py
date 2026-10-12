"""feat-14 follow-up: the toggle and the link on a pair are one row of actions (D100).

User, 2026-10-12: "the UX for the how it was decided dropdown looks kinda ugly and clashes with the
link right below, different text size for example". The toggle and Check the rules sit side by
side in one row and look alike; opened, the explanation sits in its own box.
"""

import re

from test_web_app import mixed

from equinox.web.style import CSS


def test_the_toggle_and_the_link_are_one_row_of_actions(tmp_path):
    page = mixed(tmp_path).respond("/matches", "")
    row = re.search(r'<div class="foot">(.*?)</div>\s*</div><!--/pair-->', page, re.S)
    assert row and "<summary>How it was decided</summary>" in row.group(1)
    assert "Check the rules and price it" in row.group(1)
    assert '<div class="explain">' in row.group(1)  # the opened part, in its own box


def test_every_toggle_looks_like_the_links_beside_it():
    summary = re.search(r"details > summary \{([^}]*)\}", CSS)
    link = re.search(r"\.more \{([^}]*)\}", CSS)
    assert summary and link
    for rule in ("font-size: 13px", "font-weight: 600", "color: var(--accent)"):
        assert rule in summary.group(1) and rule in link.group(1), rule
    assert "::-webkit-details-marker" in CSS  # no browser triangle beside our own chevron


def test_the_chevron_is_a_real_character():
    """A CSS escape inside a Python string lost its backslash once and drew "BE" instead."""
    assert 'details > summary::after { content: "▾";' in CSS
