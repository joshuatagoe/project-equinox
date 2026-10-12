# Agent harness

Read this file completely before changing the repo. Then read the sources below. Explore the code. Docs can be stale; the code and a check you ran are the evidence.

## Sources of truth

- **The brief** is the Project Equinox PDF. It is kept out of the repo (`/PRD.md` is gitignored). The user's copy is at `C:\Users\joshu\Downloads\equinox_project.pdf`.
- **The design** is [docs/architecture.md](docs/architecture.md). It wins over [docs/prd.md](docs/prd.md), whose technical sections it replaces.
- **The lane PRDs** in [docs/features/](docs/features/) say what each lane builds, which files it owns, and its acceptance tests.
- **Users and flows:** [user/users.md](user/users.md).
- **Venue facts,** each with a source and a label: [docs/research/venue_facts.md](docs/research/venue_facts.md).
- **Decisions and assumptions:** [docs/DECISIONS.md](docs/DECISIONS.md).

Do not invent product behavior, a stack, or an architecture. Facts about a venue come from `venue_facts.md` or from new research labelled the same way, never from memory.

The design docs record design. Do not tick their checkboxes as status, and do not restate them in a new document.

Status lives only on the board named in [docs/status-board.md](docs/status-board.md). Do not create `IMPLEMENTATION.md` or any other kanban.

Past project lessons live in `C:\Users\joshu\.agents\workflow-reports`, not in this repo. Read the newest report for each project before architecture and before a new plan. Older reports stay. Do not rewrite them. A new report is a dated file in that folder, and the README index there is updated.

## Submission logs

Required deliverables, from the brief's "Deliverables" section:
- a working prototype;
- setup instructions;
- a brief architecture overview;
- written explanations of the equivalence logic and the routing logic;
- disclosure of AI usage.

Each has a card on the status board.

When work makes a decision with a trade-off, cuts something, or corrects the AI, log it in the same commit as the work: decisions and cuts in `docs/DECISIONS.md`, AI corrections in `docs/AI_USAGE.md`. Do not rebuild these logs at the end.

## Skills

Follow the project skills in `.claude/skills/`:

- `grill` before a card is seeded, and again before every commit. A skipped grill means no commit.
- `tdd-plan-implementer` when implementing a slice of the plan.
- `parallel-delivery` when splitting that work across agents.

## Checks

The one check is `scripts/gate.py`: ruff lint, ruff format, then pytest. GitHub Actions runs it on every push to main and every pull request, and is the CI of record. GitLab runs the same job only when a project runner is registered and `EQUINOX_GITLAB_RUNNER` is set (D40).

- Windows: `.venv\Scripts\python scripts\gate.py`
- macOS, Linux and CI: `make gate`

Set up a venv with `uv venv --python 3.12 .venv` and `uv pip install --python .venv -r requirements.txt`. A new git worktree does not get the main checkout's `.venv`: run those two commands inside the worktree first.

No test touches the network. Tests read fixtures under `src/equinox/fixtures/`, which hold raw venue responses. Never edit a fixture file; capture a new snapshot instead. Tests also replay the model's answers in `evals/recorded.json` and check them against `evals/scores.json`; only `python -m equinox.reader.evals --record`, which calls the model, rewrites those two files.

## Working rules

If a routine technical choice is at least 80% certain, decide and proceed. Stop for scope, a public API, schema or data flow, auth, and spend. Stop again before every commit and run `grill` on the diff. Do not commit in that same message.

Pushes go to both remotes this project uses, with explicit commands, and only after the user approves:
- `git push origin <branch>` (GitLab, labs.gauntletai.com)
- `git push github <branch>` (GitHub)

Parallel agents share no files. The same file means one owner, in sequence. Each lane PRD lists the files its lane owns. A lane that needs a file it doesn't own (a model, `pyproject.toml`, `requirements.txt`, CI, the golden test data) stops and reports. Before a lane is merged, `git diff --name-only main...<branch>` must list only that lane's files, and the grill states it. Each non-UI lane runs in its own git worktree and branch.

Tests marked as golden (`tests/golden/`) and approved acceptance tests are frozen. If one looks wrong, stop and name the requirement it contradicts. Do not edit it to go green.

A new session starts from the plan and the board card, not from chat memory.
