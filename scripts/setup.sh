#!/usr/bin/env bash
# One-time setup for every team member. Run from the repo root: scripts/setup.sh
set -uo pipefail

ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
miss() { printf "  \033[31m✗\033[0m %s — %s\n" "$1" "$2"; }

echo "Checking tools"
command -v git    >/dev/null && ok git    || miss git    "install git"
command -v gh     >/dev/null && ok gh     || miss gh     "https://cli.github.com, then: gh auth login"
command -v python3 >/dev/null && ok python3 || miss python3 "install Python 3.12"
if ! command -v uv >/dev/null; then
  echo "  installing uv"; curl -LsSf https://astral.sh/uv/install.sh | sh
fi
command -v uv     >/dev/null && ok uv     || miss uv     "restart your shell so uv is on PATH"
command -v claude >/dev/null && ok "Claude Code" || miss "Claude Code" "see https://code.claude.com/docs"

if [ -f pyproject.toml ]; then
  echo "Installing locked Python dependencies"
  uv sync --frozen && ok "uv sync" || miss "uv sync" "ask P1"
else
  echo "  (pyproject.toml not committed yet — P1 adds it; rerun this script after)"
fi

echo "Installing graphify CLI (code graph for agents, pinned to match .claude/skills/graphify)"
uv tool install "graphifyy==0.9.121" >/dev/null 2>&1 && ok "graphify" || miss "graphify" "uv tool install graphifyy==0.9.121"

git config core.hooksPath .githooks && ok "git hooks (strip AI attribution from commit messages)"
if [ -z "$(git config user.email)" ]; then
  miss "git identity" "git config user.name \"<your GitHub name>\" && git config user.email \"<your GitHub email>\""
else
  ok "git identity: $(git config user.name) <$(git config user.email)>"
fi

if [ ! -f .env ]; then cp .env.example .env && ok ".env created from .env.example (only P2 fills in tokens)"; fi

echo
echo "Optional token saver — Serena (symbol-level code lookups for Claude Code):"
echo "  claude mcp add serena -- uvx --from git+https://github.com/oraios/serena serena start-mcp-server --context ide-assistant --project \"\$(pwd)\""
echo "  (if the flags have changed, follow the Serena README)"
echo
echo "Every session: cd into a worktree from scripts/new_task.sh, then run claude (the branch sets the module)"
