"""The pages' stylesheet: plain, readable, no framework (UI polish is out of scope)."""

CSS = """
:root { --ink: #1d2433; --muted: #5b6475; --line: #d9dee7; --soft: #f4f6f9; --accent: #1f5fbf;
        --good: #1c7c4d; --warn: #9a5b00; --bad: #b3261e; --differs: #fff4d6; }
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
       color: var(--ink); background: #fff; }
header { background: var(--ink); color: #fff; padding: 12px 24px; display: flex; gap: 24px;
         align-items: baseline; flex-wrap: wrap; }
header strong { font-size: 18px; }
header nav a { color: #c9d6ee; margin-right: 16px; text-decoration: none; }
header nav a.active { color: #fff; border-bottom: 2px solid #fff; }
main { max-width: 1100px; margin: 0 auto; padding: 20px 24px 48px; }
.banner { background: var(--soft); border: 1px solid var(--line); border-radius: 6px;
          padding: 8px 12px; margin-bottom: 20px; color: var(--muted); }
.banner ul { margin: 4px 0 0; padding-left: 20px; color: var(--warn); }
.banner form.data { display: inline; margin-right: 8px; }
.banner form.data select { font: inherit; }
h1 { font-size: 22px; margin: 0 0 12px; }
h2 { font-size: 17px; margin: 28px 0 8px; }
form.order { display: flex; flex-wrap: wrap; gap: 12px 16px; align-items: end; padding: 14px;
             border: 1px solid var(--line); border-radius: 6px; background: var(--soft); }
form label { display: flex; flex-direction: column; font-size: 13px; color: var(--muted);
             gap: 4px; }
form select, form input { font: inherit; padding: 6px 8px; border: 1px solid #b9c1ce;
                          border-radius: 4px; min-width: 120px; background: #fff; }
form button { font: inherit; padding: 7px 18px; border: 0; border-radius: 4px;
              background: var(--accent); color: #fff; cursor: pointer; }
.errors { color: var(--bad); margin: 10px 0 0; }
.headline { font-size: 19px; margin: 20px 0 6px; padding: 14px 16px; border-radius: 4px;
            border-left: 5px solid var(--good); background: #eef7f1; }
.headline.no { border-color: var(--bad); background: #fbeeed; }
table { border-collapse: collapse; width: 100%; margin: 6px 0; font-size: 14px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--line);
         vertical-align: top; }
th { background: var(--soft); font-weight: 600; }
td.num, th.num { text-align: right; white-space: nowrap; }
tr.out td { color: var(--muted); }
tr.differs td, tr.differs th { background: var(--differs); }
.tag { font-size: 12px; color: var(--warn); font-weight: 600; }
.muted { color: var(--muted); }
details { margin-top: 8px; }
footer { color: var(--muted); font-size: 13px; margin-top: 36px; }
a { color: var(--accent); }
.bet { padding: 14px 0; border-bottom: 1px solid var(--line); }
table.prices { width: auto; margin: 8px 0; }
table.prices td { padding: 3px 14px 3px 0; border: 0; }
.bet details { margin-top: 6px; }
.bet summary { color: var(--accent); cursor: pointer; }
a.button { display: inline-block; margin-top: 8px; padding: 6px 14px; border-radius: 4px;
           background: var(--accent); color: #fff; text-decoration: none; }
form.find { display: flex; gap: 8px; align-items: end; margin: 0 0 14px; }
form.find label { flex: 1; }
ul.found { margin: 0 0 16px; }
"""
