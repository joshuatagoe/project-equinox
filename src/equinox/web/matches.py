"""Matches (Morgan): every pair Equinox kept, by how it was decided (feat-14, D94).

Each pair shows both venues' titles, how it was decided and why. A same bet links to its order
ticket's "Is this really the same bet?" panel: both venues' rules side by side, the confidence and
the risks. Pairs that only look alike, or that a model ruled different, are never priced.
"""

from html import escape

from equinox.catalog import review
from equinox.catalog.review import ALIKE, EXACT, KINDS, MODEL, Pair
from equinox.web import home, shell, words
from equinox.web.shell import Context, href

PER_PAGE = 40
LEAD = (
    "Every pair of markets Equinox kept after comparing both venues. Two markets are the same "
    "bet only if YES pays under exactly the same real-world conditions on both; only same bets "
    "are ever priced."
)
NOTES = {
    EXACT: "Both venues' terms were read by Equinox's own reader and match exactly.",
    MODEL: "A model read both venues' terms and Equinox checked the readings: Medium confidence "
    "at most.",
    ALIKE: "Only the titles look alike (title score {score}), so it is never priced.",
    review.RULED: "A model read both venues' terms and they differ, so it is never priced.",
}
BADGES = {
    EXACT: ("Exact match", "high"),
    MODEL: ("Read by a model", "medium"),
    ALIKE: ("Look alike", ""),
    review.RULED: ("Ruled different by a model", ""),
}


def page(ctx: Context, params: dict[str, str]) -> str:
    if ctx.found is None:
        return home.no_catalog(ctx)
    kind = params.get("show", EXACT) if params.get("show") in KINDS else EXACT
    asked = params.get("q", "").strip()[:200]
    found = review.listed(ctx.found, kind, asked)
    number = home.page_number(params.get("page", "1"))
    shown = found[(number - 1) * PER_PAGE : number * PER_PAGE]
    listing = "".join(_pair(p) for p in shown) or shell.empty(
        f"No pairs match “{asked}”." if asked else "No pairs of this kind."
    )
    body = (
        f"<h1>Matches</h1><p class='lead'>{escape(LEAD)}</p>"
        f"{_kinds(review.counts(ctx.found), kind)}{_search(kind, asked)}"
        f'<section class="panel">{listing}</section>'
        f"{_pager(len(found), number, kind, asked)}"
    )
    return shell.layout("Matches", body, ctx, active="/matches")


def _pair(p: Pair) -> str:
    sides = "".join(
        f'<div><span class="small muted">{escape(words.venue(side.venue))}'
        + (f" · {escape(side.event)}" if side.event and side.event != side.title else "")
        + f"</span><div>{escape(side.title)}</div></div>"
        for side in (p.a, p.b)
    )
    badge, style = BADGES[p.kind]
    note = NOTES[p.kind].format(score=p.score)
    reasons = "".join(f"<li>{escape(r)}</li>" for r in p.reasons)
    check = ""
    if p.kind in (EXACT, MODEL):
        target = href("/bet", m=p.a.market_id, side="YES") + "#same-bet"
        check = f'<a class="more" href="{escape(target)}">Check the rules and price it →</a>'
    return (
        f'<div class="pair"><div class="sides">{sides}</div>'
        f'<p class="small"><span class="tag {style}">{badge}</span> {escape(note)}</p>'
        + (f"<ul class='notes small muted'>{reasons}</ul>" if reasons else "")
        + f"{check}</div><!--/pair-->"
    )


def _kinds(counted: dict[str, int], chosen: str) -> str:
    links = "".join(
        f'<a href="{escape(href("/matches", show=kind))}"{" class=on" if kind == chosen else ""}>'
        f"{escape(label)}<span>{counted[kind]:,}</span></a>"
        for kind, label in KINDS.items()
    )
    return f'<nav class="chips" aria-label="Kinds of pair">{links}</nav>'


def _search(kind: str, asked: str) -> str:
    return (
        '<form class="find inline" method="get" action="/matches">'
        f'<input type="hidden" name="show" value="{escape(kind)}">'
        f'<input name="q" value="{escape(asked)}" placeholder="Search these pairs by either title" '
        'aria-label="Search these pairs"></form>'
    )


def _pager(total: int, number: int, kind: str, asked: str) -> str:
    last = max((total + PER_PAGE - 1) // PER_PAGE, 1)
    if last == 1:
        return ""

    def link(to: int, text: str) -> str:
        target = href("/matches", show=kind, q=asked, page=str(to))
        return f'<a href="{escape(target)}">{text}</a>'

    back = link(number - 1, "← Previous") if number > 1 else ""
    ahead = link(number + 1, "Next →") if number < last else ""
    return f'<p class="pager">{back}<span class="muted">Page {number} of {last}</span>{ahead}</p>'
