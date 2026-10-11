"""HTML for the pages. Every string passed in is escaped here or, for the All markets page, in
`markets_html.py`; nothing else writes HTML."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from html import escape
from urllib.parse import urlencode

from equinox.web.style import CSS


@dataclass
class Banner:
    summary: str
    path: str  # the page the data selector reloads
    current: str  # the selected data source
    sources: Sequence[tuple[str, str]]  # (value, label) for every snapshot and live data
    warnings: Sequence[str] = ()


@dataclass
class Choice:
    value: str
    label: str
    group: str


@dataclass
class OrderForm:
    choices: Sequence[Choice]
    outcome: str
    side: str
    quantity: str
    budget: str
    data: str
    errors: Sequence[str] = ()


@dataclass
class Result:
    headline: str
    routed: bool
    rationale: str
    columns: Sequence[str]
    rows: Sequence[Sequence[str]]
    excluded: Sequence[bool]
    verdict: str
    match_href: str
    risks: Sequence[str] = ()
    warnings: Sequence[str] = ()
    assumptions: Sequence[str] = ()


@dataclass
class Table:
    title: str
    columns: Sequence[str]
    rows: Sequence[Sequence[str]]
    links: Sequence[str] = ()  # one href per row, shown as "Price my order"


@dataclass
class Comparison:
    columns: Sequence[str]
    rows: Sequence[
        tuple[str, Sequence[str], Sequence[str | None], bool]
    ]  # label, texts, hrefs, differs
    verdicts: Sequence[tuple[str, Sequence[str]]]  # (verdict line, flags)
    set_aside: Sequence[str] = field(default_factory=list)


def href(path: str, **params: str) -> str:
    query = urlencode({k: v for k, v in params.items() if v})
    return f"{path}?{query}" if query else path


BPS_NOTE = (
    "bps means basis points: 1 bp is 0.01 percentage point, so 25 bps is a quarter of a point."
)


def layout(title: str, active: str, data: str, banner: Banner, body: str) -> str:
    """The page frame. `data` is the query value that keeps links on the same data source."""
    nav = "".join(
        f'<a href="{escape(href(path, data=data))}"'
        f"{' class=active' if path == active else ''}>{escape(label)}</a>"
        for path, label in (
            ("/", "Price an order"),
            ("/board", "Market board"),
            ("/match", "Why these match"),
            ("/markets", "All markets"),
        )
    )
    warnings = "".join(f"<li>{escape(w)}</li>" for w in banner.warnings)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · Project Equinox</title>
<style>{CSS}</style>
</head>
<body>
<header><strong>Project Equinox</strong><nav>{nav}</nav></header>
<main>
<div class="banner">{_data_selector(banner) if banner.sources else ""} {escape(banner.summary)}
 {f"<ul>{warnings}</ul>" if warnings else ""}</div>
{body}
<footer>{escape(BPS_NOTE)}<br>Equinox simulates orders. It doesn't place them. Prices, fees and
depth come from each venue's public order book; see the README for how decisions are made.</footer>
</main>
</body>
</html>
"""


def _data_selector(banner: Banner) -> str:
    options = "".join(
        f'<option value="{escape(value)}"{" selected" if value == banner.current else ""}>'
        f"{escape(label)}</option>"
        for value, label in banner.sources
    )
    return (
        f'<form class="data" method="get" action="{escape(banner.path)}">Data '
        f'<select name="data">{options}</select> <button type="submit">Show</button></form>'
    )


def order_body(form: OrderForm, result: Result | None, empty: bool) -> str:
    if empty:
        return "<h1>Price an order</h1><p>No markets are loaded. Check the warnings above.</p>"
    return f"""<h1>Price an order</h1>
<p class="muted">Pick an outcome and an order. Equinox checks every venue that lists the same bet
and recommends the cheapest one that can fill the whole order.</p>
{_order_form(form)}
{_result(result) if result else ""}"""


def board_body(tables: Sequence[Table], termless: Sequence[str], data: str) -> str:
    parts = [
        "<h1>Market board</h1>",
        '<p class="muted">Every outcome, with each venue\'s price to buy YES and to buy NO, and '
        "the best venue for an order of 100 contracts. Prices are per contract; each pays $1 if "
        "it wins. A dash means nobody is selling.</p>",
    ]
    for table in tables:
        parts.append(f"<h2>{escape(table.title)}</h2>")
        rows = [
            [*cells, f'<a href="{escape(link)}">Price my order</a>']
            for cells, link in zip(
                [[escape(c) for c in row] for row in table.rows], table.links, strict=True
            )
        ]
        parts.append(html_table([*table.columns, ""], rows, raw=True))
    parts.append("<h2>Can't be compared yet</h2>")
    if termless:
        items = "".join(f"<li>{escape(t)}</li>" for t in termless)
        parts.append(
            "<p class='muted'>Equinox has no rules for reading these markets' terms, so it can "
            f"only compare their titles, and never routes them.</p><ul>{items}</ul>"
        )
    else:
        parts.append("<p class='muted'>None. Every loaded market has contract terms.</p>")
    return "".join(parts)


def match_body(
    form_choices: Sequence[Choice], outcome: str, data: str, cmp: Comparison | None
) -> str:
    options = _options(form_choices, outcome)
    picker = f"""<form class="order" method="get" action="/match">
<label>Outcome<select name="outcome">{options}</select></label>
<input type="hidden" name="data" value="{escape(data)}">
<button type="submit">Compare</button></form>"""
    intro = (
        "<h1>Why these match</h1><p class='muted'>Two markets are the same bet only if YES pays "
        "under exactly the same real-world conditions on both. Here are each venue's rules side by "
        "side, with the rows that differ marked.</p>"
    )
    if cmp is None:
        return intro + picker + "<p>That outcome isn't among the loaded markets.</p>"
    verdicts = "".join(
        f"<p><strong>{escape(line)}</strong></p>"
        + ("<ul>" + "".join(f"<li>{escape(f)}</li>" for f in flags) + "</ul>" if flags else "")
        for line, flags in cmp.verdicts
    )
    aside = (
        "<ul>" + "".join(f"<li>{escape(s)}</li>" for s in cmp.set_aside) + "</ul>"
        if cmp.set_aside
        else "<p class='muted'>None. Every pair Equinox compared was either the same bet or "
        "clearly different.</p>"
    )
    return f"""{intro}{picker}
{_comparison_table(cmp)}
<h2>Verdict</h2>{verdicts}
<h2>Considered and set aside</h2>{aside}"""


def _comparison_table(cmp: Comparison) -> str:
    """One column per venue, one row per rule; rows where the venues differ are marked."""
    head = "".join(f"<th>{escape(c)}</th>" for c in ["", *cmp.columns])
    rows = []
    for label, texts, hrefs, differs in cmp.rows:
        cells = "".join(
            f'<td><a href="{escape(link)}">{escape(text)}</a></td>'
            if link
            else f"<td>{escape(text)}</td>"
            for text, link in zip(texts, hrefs, strict=True)
        )
        mark = ' <span class="tag">differs</span>' if differs else ""
        row_class = ' class="differs"' if differs else ""
        rows.append(f"<tr{row_class}><th>{escape(label)}{mark}</th>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _order_form(form: OrderForm) -> str:
    sides = "".join(
        f'<option value="{s}"{" selected" if form.side == s else ""}>Buy {s}</option>'
        for s in ("YES", "NO")
    )
    errors = "".join(f"<p class='errors'>{escape(e)}</p>" for e in form.errors)
    return f"""<form class="order" method="get" action="/">
<label>Outcome<select name="outcome">{_options(form.choices, form.outcome)}</select></label>
<label>Order<select name="side">{sides}</select></label>
<label>Contracts<input name="quantity" value="{escape(form.quantity)}" inputmode="decimal"></label>
<label>Budget, optional ($)
<input name="budget" value="{escape(form.budget)}" inputmode="decimal"></label>
<input type="hidden" name="data" value="{escape(form.data)}">
<button type="submit">Find the best venue</button>
</form>{errors}"""


def _options(choices: Sequence[Choice], selected: str) -> str:
    groups: dict[str, list[str]] = {}
    for c in choices:
        mark = " selected" if c.value == selected else ""
        groups.setdefault(c.group, []).append(
            f'<option value="{escape(c.value)}"{mark}>{escape(c.label)}</option>'
        )
    return "".join(
        f'<optgroup label="{escape(group)}">{"".join(items)}</optgroup>'
        for group, items in groups.items()
    )


def _result(r: Result) -> str:
    rows = [[escape(c) for c in row] for row in r.rows]
    table = html_table(r.columns, rows, raw=True, out=r.excluded, numeric={3, 4, 5})
    risks = "".join(f"<li>{escape(x)}</li>" for x in r.risks)
    warnings = "".join(f"<li>{escape(x)}</li>" for x in r.warnings)
    assumptions = "".join(f"<li>{escape(x)}</li>" for x in r.assumptions)
    return f"""<p class="headline{"" if r.routed else " no"}">{escape(r.headline)}</p>
<h2>Why</h2><p>{escape(r.rationale)}</p>
<h2>Cost on each venue</h2>{table}
<h2>Same bet?</h2><p>{escape(r.verdict)} <a href="{escape(r.match_href)}">Why these match</a></p>
<h2>Things to know</h2>
{f"<p>Match risks:</p><ul>{risks}</ul>" if risks else "<p class='muted'>No match risks.</p>"}
{f"<p>Data:</p><ul>{warnings}</ul>" if warnings else ""}
<details><summary>Assumptions behind every price</summary><ul>{assumptions}</ul></details>"""


def html_table(
    columns: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    raw: bool = False,
    out: Sequence[bool] = (),
    numeric: Collection[int] = (),
) -> str:
    head = "".join(
        f"<th{' class=num' if j in numeric else ''}>{escape(c)}</th>" for j, c in enumerate(columns)
    )
    body = []
    for i, row in enumerate(rows):
        cells = "".join(
            f"<td{' class=num' if j in numeric else ''}>{cell if raw else escape(cell)}</td>"
            for j, cell in enumerate(row)
        )
        body.append(f"<tr{' class=out' if i < len(out) and out[i] else ''}>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
