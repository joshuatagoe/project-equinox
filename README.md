# Project Equinox

Project Equinox is one codebase with two remotes: **GitHub** and **GitLab**. The working agreement matches the ecommerce supplement store and the binary stock outcome repos: `make gate` is the check that has to pass, and that same check runs in CI on both hosts.

| Host | Git remote | CI |
|---|---|---|
| GitHub | `github` | [`.github/workflows/ci.yml`](.github/workflows/ci.yml) |
| GitLab | `gitlab` | [`.gitlab-ci.yml`](.gitlab-ci.yml) |

Both pipelines install the pinned dependencies and run `make gate` (ruff, then pytest).

## Create the two repositories

GitLab for this project is [labs.gauntletai.com](https://labs.gauntletai.com). This environment is not signed in there or on GitHub, so the remotes are not created from here. Create two empty repositories named `project-equinox` (no README, no license, so the first push is clean), then link them:

```bash
scripts/link-hosts.sh \
  https://github.com/joshuatagoe/project-equinox.git \
  https://labs.gauntletai.com/calebtagoe/project-equinox.git
make push-hosts
```

`scripts/link-hosts.sh` adds or updates the `github` and `gitlab` remotes. `make push-hosts` pushes the current `HEAD` to `main` on both. The existing `origin` remote is left as it is.

## Run locally

Requires Python 3.12, including the stdlib `venv` module (`python3-venv` on Debian and Ubuntu).

```bash
make install
make gate
make run
```

The status page is at http://127.0.0.1:8741 and the JSON check is at http://127.0.0.1:8741/health.

`PORT=9001 make run` changes the port.
