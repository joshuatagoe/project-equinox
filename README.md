# Project Equinox

Project Equinox compares prediction markets across venues. It reads Kalshi and Polymarket, matches markets that pay out on the same event, and simulates which venue is cheapest for a hypothetical order, explaining each decision. The design is in [docs/architecture.md](docs/architecture.md). The full README, with demo commands, comes with the implementation (feature PRD feat-06).

One codebase, two hosts. `scripts/gate.py` (ruff, then pytest) is the check that has to pass, and it is the same check in CI on both:

| Host | Git remote | CI |
|---|---|---|
| GitLab ([labs.gauntletai.com](https://labs.gauntletai.com/calebtagoe/project-equinox)) | `origin` | [`.gitlab-ci.yml`](.gitlab-ci.yml) |
| GitHub ([joshuatagoe/project-equinox](https://github.com/joshuatagoe/project-equinox)) | `github` | [`.github/workflows/ci.yml`](.github/workflows/ci.yml) |

GitHub Actions is the CI of record: it runs on pull requests and on `main`. GitLab runs the same job only when a project runner is registered and the CI/CD variable `EQUINOX_GITLAB_RUNNER` is set, because labs.gauntletai.com gives this project no shared runners (D40). Every push goes to both remotes, one explicit command each: `git push origin <branch>` and `git push github <branch>`, or `make push-hosts` for the current branch. On a fresh clone, `scripts/link-hosts.sh <github-url> <gitlab-url>` sets up both remotes.

## Run locally

Requires Python 3.12.

**macOS and Linux** (needs the stdlib `venv` module; `python3-venv` on Debian and Ubuntu):

```bash
make install
make gate
make run
```

**Windows** (no `make`; uses [uv](https://docs.astral.sh/uv/) to get Python 3.12):

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv -r requirements.txt
.venv\Scripts\python scripts\gate.py
$env:PYTHONPATH = "src"; .venv\Scripts\python -m equinox.server
```

The status page is at http://127.0.0.1:8741, and the JSON check is at http://127.0.0.1:8741/health. `PORT=9001 make run` (or `--port 9001`) changes the port.
