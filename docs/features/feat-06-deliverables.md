# feat-06: Written deliverables

**Lane:** last. **Depends on:** feat-05 merged.
**Implements:** the brief's "Deliverables" section: setup instructions, a brief architecture overview, written explanations of the equivalence and routing logic, and AI-usage disclosure.
**Owns only:** `README.md`, `docs/EQUIVALENCE.md`, `docs/ROUTING.md`, `tests/test_docs.py`, and a final pass on `docs/AI_USAGE.md`.

## Goal

A grader reads the README, runs the commands, sees the numbers the README promises, and finds the reasoning behind matching and routing written plainly. This lane also guards against the earlier projects' failure of docs drifting from the code (workflow reports, 2026-10-05).

## Build

- **`README.md`:**
  - What Equinox is, in five lines.
  - Setup for Windows, macOS and Linux (Python 3.12, `make install`, `make gate`).
  - A **demo** block with the §7.4 commands and their expected one-line results.
  - The architecture overview: the §3 diagram, the module table, and a link to `docs/architecture.md`.
  - Where the decision log, the venue facts and the AI-usage log are.
  - Known limitations, linked to architecture §13.
- **`docs/EQUIVALENCE.md`:**
  - The definition (D8) and why it is strict.
  - Contract terms, with the §4.4 table.
  - The rules and flags (§6.1).
  - Why the text-similarity approach was rejected, with the AI_USAGE 2–4 numbers.
  - The third-venue fit check (architecture §9): why a Meridian-like venue would fit, shown by the AAPL example and its tie-rule flag. Make clear that Meridian is not integrated.
- **`docs/ROUTING.md`:**
  - The cost formula and the fee formula, with the running example.
  - Why fees are computed per level (feat-01 test 4).
  - Eligibility, statuses and exit codes.
  - The rationale, with an annotated example trace.
  - Assumptions A1–A5.
- **`tests/test_docs.py`:** reads the demo block in `README.md` (between `<!-- demo:start -->` and `<!-- demo:end -->`), runs each command through `cli.main`, and asserts each documented exit code and total. A README number that no longer matches the code fails `make gate`.
- **`docs/AI_USAGE.md`:** add the implementation-phase entries. Check that every correction listed is still accurate.

## Acceptance

| # | Check | Expected |
|---|---|---|
| 1 | `tests/test_docs.py` | Passes. Change one number in the README demo block and it fails, which shows the guard works (red, then revert). |
| 2 | Every command in the README run by hand on a clean clone (Windows, plus CI's Linux) | Works as written |
| 3 | Every D-number, A-number and § reference in the README, EQUIVALENCE.md and ROUTING.md | Exists |

## Done when

`make gate` passes on Windows and in both CIs, and the user has read the README.

## Out of scope

New features. Any behaviour change found while writing is a bug for its owning lane, not something to fix here.
