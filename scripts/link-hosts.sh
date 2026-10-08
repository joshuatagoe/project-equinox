#!/usr/bin/env bash
# Point this checkout at a GitHub repo and a GitLab repo, both named project-equinox.
# Usage:
#   scripts/link-hosts.sh <github-url> <gitlab-url>
# Example (GitLab is labs.gauntletai.com):
#   scripts/link-hosts.sh \
#     https://github.com/joshuatagoe/project-equinox.git \
#     https://labs.gauntletai.com/calebtagoe/project-equinox.git
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: scripts/link-hosts.sh <github-url> <gitlab-url>" >&2
  exit 1
fi

github_url="$1"
gitlab_url="$2"

upsert_remote() {
  local name="$1"
  local url="$2"
  if git remote get-url "$name" >/dev/null 2>&1; then
    git remote set-url "$name" "$url"
  else
    git remote add "$name" "$url"
  fi
}

upsert_remote github "$github_url"
upsert_remote gitlab "$gitlab_url"

echo "github $(git remote get-url github)"
echo "gitlab $(git remote get-url gitlab)"
echo "Next: make push-hosts"
