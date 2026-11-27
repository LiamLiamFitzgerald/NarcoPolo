#!/usr/bin/env bash
# One-time GitHub setup (P1, needs repo admin): labels, integration branch, branch protection.
# Usage: scripts/github_setup.sh
set -euo pipefail

repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
echo "Setting up $repo"

label() { gh label create "$1" --color "$2" --description "$3" --force >/dev/null && echo "  label $1"; }
for n in 1 2 3 4 5 6 7; do label "module:P$n" "1d76db" "Owned by P$n"; done
label task        "0e8a16" "One unit of work in one module"
label question    "d876e3" "Spec gap: never guess, ask"
label contract    "b60205" "Schema / stage-file / shared config change"
label blocked     "000000" "Three failed CI attempts; needs a human"
label overnight-ok "fbca04" "Safe for unattended overnight agents"
label stub        "c5def5" "Stub returning schema-valid simulator output"

# integration branch from main
if ! gh api "repos/$repo/branches/integration" >/dev/null 2>&1; then
  sha=$(gh api "repos/$repo/git/ref/heads/main" -q .object.sha)
  gh api "repos/$repo/git/refs" -f ref=refs/heads/integration -f sha="$sha" >/dev/null
  echo "  created branch integration"
fi

protect() {
  gh api -X PUT "repos/$repo/branches/$1/protection" --input - >/dev/null <<JSON && echo "  protected $1" \
    || echo "  could not protect $1 (private repos on GitHub Free can't use branch protection; make the repo public or rely on CI + convention)"
{
  "required_status_checks": {"strict": false, "contexts": ["Path ownership", "Identity scan"]},
  "enforce_admins": false,
  "required_pull_request_reviews": {"required_approving_review_count": 0, "require_code_owner_reviews": true},
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
}
protect main
protect integration

gh repo edit "$repo" --delete-branch-on-merge --enable-auto-merge >/dev/null && echo "  auto-merge on, branches deleted after merge"

echo
echo "Still to do by hand:"
echo "  1. Install the Claude GitHub App: https://github.com/apps/claude  (or run /install-github-app in Claude Code)"
echo "  2. Add secret ANTHROPIC_API_KEY:   gh secret set ANTHROPIC_API_KEY"
echo "  3. Fill github_users in .github/owners.json, then: python3 scripts/make_codeowners.py"
echo "  4. Seed issues:                    python3 scripts/seed_issues.py --apply"
