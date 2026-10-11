# chore-01: Modularity and the quality gate

**Lane:** after feat-07, before feat-08. **Depends on:** feat-01 to feat-07 merged.
**Implements:** D52; architecture §3 and §12. No behaviour changes.
**Owns only these files:**
- `src/equinox/sources.py` (new): what moves out of `cli.py`
- `src/equinox/cli.py`
- `src/equinox/web/*`: `app.py` split into `order.py`, `board.py`, `match.py`
- `src/equinox/router/engine.py`: `quote` broken into named helpers
- `pyproject.toml`: ruff `C901`, max complexity 10
- `tests/test_quality.py` (new)
- `README.md`: the "Reading the code" section

## Goal

A grader can open any module and see one job, done in short functions with plain names. The web UI and the command line don't depend on each other. The gate fails if that stops being true.

## Build

1. **Move loading out of the CLI.** `Settings`, `Loaded`, `LiveFetchers`, `ADAPTERS`, `load_markets` and the snapshot fallback move to `src/equinox/sources.py`. `cli.py` keeps only argument parsing, the three commands, report formatting and exit codes. `web/` imports from `sources.py`, never from `cli.py`. For compatibility, `cli.py` re-exports the names that tests import from it (`equinox.cli.Settings`, `Loaded` and `load_markets` are used by `tests/test_web.py`).
2. **Split `web/app.py` by page.**
   - `app.py` keeps routing, the data cache and the banner.
   - `order.py`, `board.py` and `match.py` each build one page's content.
   - `pages.py` keeps the HTML, and `words.py` keeps the wording.
3. **Shorten the three functions over 40 lines:**
   - `router/engine.py: quote` takes its reasons and its warnings from two named helpers;
   - `web/app.py: _result`, rewritten as part of `order.py`;
   - `web/pages.py: match_body`, whose comparison table becomes its own function.
4. **Turn on ruff `C901`** with `max-complexity = 10` in `pyproject.toml`.
5. **Add `tests/test_quality.py`:**
   - no module under `src/equinox/` has more than 300 lines;
   - no function has more than 40 lines;
   - nothing under `web/` imports `equinox.cli`, and `cli.py` imports nothing from `equinox.web`;
   - every path in the README's "Reading the code" table exists.
6. **Add "Reading the code" to the README:** a table from each question a grader asks to the file that answers it. For example:
   - where venues are read → `adapters/kalshi.py`, `adapters/polymarket.py`;
   - where equivalence is decided → `matcher/terms.py`;
   - where a venue is chosen → `router/engine.py`;
   - where the explanation is written → `router/rationale.py`;
   - where the rules are tested → `tests/test_matcher.py`, `tests/test_router.py`.

## Acceptance tests

| # | Test | Expected |
|---|---|---|
| 1 | `tests/test_quality.py`, written first | Fails on today's code (`web/app.py` 429 lines, `cli.py` 343; `quote` 47, `_result` 44, `match_body` 42 lines; `web/app.py` imports `equinox.cli`), then passes |
| 2 | `ruff check` with `C901` on | Passes |
| 3 | Every existing test | Passes, with no existing test file changed: `git diff --name-only` lists no file under `tests/` other than `test_quality.py` |
| 4 | `tests/test_docs.py` | Passes: README numbers and references unchanged |
| 5 | Browser check | The order, board and match pages render as before on the default snapshot |

## Done when

`make gate` passes and tests 1–5 hold.

## Out of scope

Any change in behaviour, wording or numbers. Discovery and the catalog are feat-08 and feat-09.
