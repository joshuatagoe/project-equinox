"""Team names the cross-check found the parsers spelling two ways (D62, D64)."""

from equinox.adapters.teams import team_key


def test_chapecoense_as_each_venue_writes_it_is_one_team():
    # catalog check, 2026-10-12: 13 Chapecoense v CA Paranaense scores the model matched
    assert team_key("Associação Chapecoense de Futebol") == team_key("Chapecoense SC")
