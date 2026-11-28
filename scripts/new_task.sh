#!/usr/bin/env bash
# Start work on one issue in its own worktree and branch.
# Usage: scripts/new_task.sh P4 12
set -euo pipefail

module="${1:?module, e.g. P4}"
issue="${2:?issue number}"
m=$(echo "$module" | tr '[:upper:]' '[:lower:]')
branch="mod/${m}/${issue}"
repo_root=$(git rev-parse --show-toplevel)
dir="$(dirname "$repo_root")/narcopolo-${m}-${issue}"

git -C "$repo_root" fetch origin integration
git -C "$repo_root" worktree add "$dir" --no-track -b "$branch" origin/integration

cat <<EOF

Worktree ready: $dir  (branch $branch)

Start your agent with:
  cd "$dir" && claude      (the branch sets the module; NARCO_MODULE is optional)

When finished and merged:
  git worktree remove "$dir"
EOF
