"""Is this really the same bet? (Morgan): the panel beside every order ticket (feat-14, D86).

It says how the two markets were matched, the confidence and its reason, each venue's rules side
by side with the rows that differ marked, and the risks. Without the venues' listings it says what
the catalog knows and that the rules couldn't be read just now.
"""

from html import escape

from equinox.models import CanonicalMarket, EquivalenceCluster
from equinox.models.catalog import CatalogRow
from equinox.web import order, words

TITLE = "Is this really the same bet?"
INTRO = (
    "Two markets are the same bet only if YES pays under exactly the same real-world conditions "
    "on both. Here are each venue's rules side by side; rows that differ are marked."
)


def panel(row: CatalogRow, cluster: EquivalenceCluster | None) -> str:
    how = f"<p>{escape(words.matched(row))}</p>"
    if cluster is None:
        other = f"{row.partner_title} on {words.venue(row.partner.split(':', 1)[0])}"
        body = f"<p>Matched with {escape(other)}.</p>{how}" + (
            "<p class='muted'>Each venue's rules are shown once the venues can be read.</p>"
        )
        return _framed(body)
    members = sorted(cluster.markets, key=lambda m: (m.venue, m.market_id))
    level = order.verdict(cluster)
    risks = "".join(f"<li>{escape(flag)}</li>" for flag in cluster.risk_flags)
    body = (
        f"<p><strong>{escape(level)}</strong></p>{how}"
        f"<p class='muted small'>{escape(INTRO)}</p>{_rules(members)}"
        + (f"<h2>Things to know</h2><ul class='notes'>{risks}</ul>" if risks else "")
    )
    return _framed(body)


def _framed(body: str) -> str:
    return f'<section class="panel" id="same-bet"><h2>{TITLE}</h2>{body}</section>'


def _rules(members: list[CanonicalMarket]) -> str:
    """One column per venue, one row per rule; rows where the venues differ are marked."""
    rows = [
        ("Question", [m.title for m in members], False),
        ("Pays YES if", [words.pays_if(m.terms) for m in members], True),
        ("Measured by", [words.measured_by(m.terms) for m in members], True),
        ("Observed", [words.observed(m.terms) for m in members], True),
        ("Settlement source", [m.resolution_source.institution for m in members], True),
        ("Trading closes", [words.moment(m.trading_closes_at) for m in members], True),
        ("Expected to resolve", [words.moment(m.resolves_at) for m in members], True),
        ("Edge-case rules", [words.edge_cases(m.terms) for m in members], True),
    ]
    head = "".join(f"<th>{escape(words.venue(m.venue))}</th>" for m in members)
    body = "".join(
        f"<tr{' class=differs' if compare and len(set(texts)) > 1 else ''}><th>{escape(label)}"
        f"{' <span class=tag>differs</span>' if compare and len(set(texts)) > 1 else ''}</th>"
        + "".join(f"<td>{escape(text)}</td>" for text in texts)
        + "</tr>"
        for label, texts, compare in rows
    )
    table = f"<table><thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table>"
    return f'<div class="wrap">{table}</div>'
