"""The app's look (feat-14, D89): one stylesheet, light and dark, from phone width up."""

CSS = """
:root {
  --bg: #f5f6f8; --surface: #ffffff; --raised: #fbfcfd; --ink: #0f172a; --muted: #5b6475;
  --line: #e3e7ee; --accent: #2457d6; --accent-ink: #ffffff; --accent-soft: #eaf0fd;
  --yes: #0f7a4f; --yes-soft: #e7f6ef; --no: #b4233a; --no-soft: #fcebee;
  --warn: #9a5b00; --warn-soft: #fff4e0; --radius: 12px;
  --shadow: 0 1px 2px rgba(15, 23, 42, .05), 0 2px 8px rgba(15, 23, 42, .05);
  --lift: 0 4px 16px rgba(15, 23, 42, .10);
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0b1017; --surface: #121923; --raised: #17202c; --ink: #e6eaf0; --muted: #96a0b0;
    --line: #243042; --accent: #6b93ff; --accent-ink: #0b1017; --accent-soft: #1b2740;
    --yes: #4cc38a; --yes-soft: #13281f; --no: #f07386; --no-soft: #2e161b;
    --warn: #f0b45a; --warn-soft: #2b2112;
    --shadow: none; --lift: 0 4px 16px rgba(0, 0, 0, .4);
    color-scheme: dark;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
       font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { font-size: 28px; line-height: 1.2; margin: 0 0 6px; letter-spacing: -.01em; }
h2 { font-size: 17px; margin: 0 0 12px; }
.num, .pill, .answer, table { font-variant-numeric: tabular-nums; }
.muted { color: var(--muted); }
.small { font-size: 13px; }

.top { position: sticky; top: 0; z-index: 5; background: var(--surface);
       border-bottom: 1px solid var(--line); }
.top .in { max-width: 1120px; margin: 0 auto; padding: 10px 16px; display: flex;
           align-items: center; gap: 18px; flex-wrap: wrap; }
.brand { display: flex; align-items: center; gap: 8px; color: var(--ink); font-weight: 700;
         font-size: 17px; }
.brand:hover { text-decoration: none; }
.mark { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--ink);
        background: linear-gradient(90deg, var(--ink) 50%, transparent 50%); }
.top nav a { color: var(--muted); font-weight: 600; margin-right: 14px; }
.top nav a.on { color: var(--ink); }
.find { flex: 1; min-width: 200px; display: flex; }
.find input { width: 100%; padding: 8px 14px; border: 1px solid var(--line); border-radius: 999px;
              background: var(--bg); color: var(--ink); font: inherit; }
.find input:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
.fresh { font-size: 13px; color: var(--muted); white-space: nowrap; }
form.refresh { display: inline; margin: 0; }
.btn.small { padding: 4px 10px; font-size: 13px; }
.btn.ghost { background: transparent; color: var(--accent); border-color: var(--accent); }
.notice.stale { background: var(--warn-soft); border-left-color: var(--warn); }
.notice form.refresh { margin-left: 8px; }
button.link { background: none; border: 0; padding: 0; font: inherit; font-size: 13px;
              font-weight: 600; color: var(--accent); cursor: pointer; }
.fresh::before { content: ""; display: inline-block; width: 8px; height: 8px; margin-right: 6px;
                 border-radius: 50%; background: var(--yes); vertical-align: 1px; }

main { max-width: 1120px; margin: 0 auto; padding: 24px 16px 40px; }
.lead { margin: 0 0 18px; color: var(--muted); max-width: 70ch; }
.notice { margin: 0 0 18px; padding: 10px 14px; border-radius: 10px; font-size: 14px;
          background: var(--accent-soft); color: var(--ink); border-left: 4px solid var(--accent); }
.crumbs { font-size: 13px; color: var(--muted); margin-bottom: 8px; }

.chips { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; margin: 0 0 20px; }
.chips a { white-space: nowrap; padding: 6px 12px; border-radius: 999px; font-size: 14px;
           border: 1px solid var(--line); background: var(--surface); color: var(--ink); }
.chips a:hover { text-decoration: none; border-color: var(--accent); }
.chips a.on { background: var(--ink); color: var(--bg); border-color: var(--ink); }
.chips span { color: var(--muted); margin-left: 4px; }
.chips a.on span { color: inherit; opacity: .7; }

.grid { display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }
.card { display: flex; flex-direction: column; gap: 10px; padding: 16px; color: var(--ink);
        background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
        box-shadow: var(--shadow); transition: box-shadow .15s, transform .15s; }
.card:hover { text-decoration: none; box-shadow: var(--lift); transform: translateY(-1px); }
.card h3 { font-size: 16px; line-height: 1.3; margin: 0; }
.meta { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; font-size: 13px;
        color: var(--muted); }
.tag { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px;
       font-weight: 600; background: var(--accent-soft); color: var(--accent); }
.tag.high { background: var(--yes-soft); color: var(--yes); }
.tag.medium { background: var(--warn-soft); color: var(--warn); }
.line { display: flex; justify-content: space-between; gap: 10px; align-items: baseline;
        font-size: 14px; border-top: 1px solid var(--line); padding-top: 8px; }
.line .name { min-width: 0; overflow-wrap: anywhere; }
.prices { display: flex; gap: 6px; flex-shrink: 0; flex-wrap: wrap; }
.pill { padding: 2px 8px; border-radius: 6px; background: var(--raised); font-size: 13px;
        border: 1px solid var(--line); white-space: nowrap; }
.pill b { font-weight: 600; }
.pill.best { background: var(--yes-soft); border-color: transparent; color: var(--yes); }
.more { font-size: 13px; color: var(--accent); font-weight: 600; }
.empty { padding: 32px; text-align: center; color: var(--muted); background: var(--surface);
         border: 1px dashed var(--line); border-radius: var(--radius); }
.pager { display: flex; gap: 12px; justify-content: center; margin-top: 20px; }
.pair { padding: 16px 0; border-top: 1px solid var(--line); }
.pair:first-child { border-top: 0; padding-top: 0; }
.sides { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
         font-weight: 600; }
.pair p { margin: 10px 0 4px; }
.find.inline { margin: 0 0 16px; max-width: 520px; }

.panel { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
         box-shadow: var(--shadow); padding: 20px; margin-bottom: 16px; }
.row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px 20px;
       align-items: center; padding: 14px 0; border-top: 1px solid var(--line); }
.row:first-child { border-top: 0; padding-top: 0; }
.row .what { font-weight: 600; }
.row .side { display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
             justify-content: flex-end; }
.btn { display: inline-block; padding: 8px 14px; border-radius: 8px; font: inherit;
       font-weight: 600; border: 1px solid transparent; cursor: pointer;
       background: var(--accent); color: var(--accent-ink); }
.btn:hover { text-decoration: none; filter: brightness(1.05); }
.btn.yes { background: var(--yes-soft); color: var(--yes); }
.btn.no { background: var(--no-soft); color: var(--no); }
.buys { display: flex; gap: 8px; }

.ticket { display: grid; gap: 16px; grid-template-columns: minmax(0, 1fr); }
@media (min-width: 920px) {
  .ticket { grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); align-items: start; }
  .ticket aside { position: sticky; top: 76px; }
}
form.order { display: grid; gap: 14px; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
             align-items: start; }
form.order .btn { grid-column: 1 / -1; justify-self: start; }
form.order label { display: grid; gap: 6px; font-size: 13px; color: var(--muted); }
form.order small { font-size: 12px; }
.intro { margin: 0 0 16px; color: var(--muted); font-size: 14px; }
#result:empty { display: none; }
#result[aria-busy="true"] { opacity: .5; transition: opacity .15s; }
[hidden] { display: none !important; }
form.order [data-live-note] { grid-column: 1 / -1; margin: 0; }
form.order input[inputmode] { padding: 9px 12px; font: inherit; border: 1px solid var(--line);
                              border-radius: 8px; background: var(--bg); color: var(--ink);
                              width: 100%; min-width: 0; }
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden;
       width: max-content; }
.seg input { position: absolute; opacity: 0; pointer-events: none; }
.seg span { display: inline-block; padding: 8px 16px; cursor: pointer; font-weight: 600;
            color: var(--muted); }
.seg input:checked + span.y { background: var(--yes-soft); color: var(--yes); }
.seg input:checked + span.n { background: var(--no-soft); color: var(--no); }
.seg input:focus-visible + span { outline: 2px solid var(--accent); }
.errors { color: var(--no); margin: 12px 0 0; }
.answer { font-size: 19px; font-weight: 650; line-height: 1.35; padding: 14px 16px;
          border-radius: 10px; background: var(--yes-soft); color: var(--ink);
          border-left: 4px solid var(--yes); margin: 0 0 16px; }
.answer.no { background: var(--warn-soft); border-left-color: var(--warn); }
.answer.down { background: var(--no-soft); border-left-color: var(--no); }
.wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line);
         vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: 13px; }
td.num, th.num { text-align: right; }
tr.out td { color: var(--muted); }
tr.differs th:first-child { color: var(--warn); }
details summary { cursor: pointer; color: var(--accent); font-weight: 600; margin-top: 8px; }
ul.notes { margin: 8px 0 0; padding-left: 20px; }
footer { color: var(--muted); font-size: 13px; margin-top: 40px; padding-top: 16px;
         border-top: 1px solid var(--line); }
@media (max-width: 560px) {
  h1 { font-size: 23px; }
  .fresh { order: 4; width: 100%; }
  .row { grid-template-columns: minmax(0, 1fr); }
  .row .side { justify-content: flex-start; }
}
"""
