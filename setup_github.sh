#!/usr/bin/env bash
# setup_github.sh — initialize the V2 git repo and push to GitHub.
# Run from C:\Projects\tradingap\Trading Agent 2.0 (Git Bash on Windows).
#
# Usage:
#   bash setup_github.sh angelaroe4u trading-agent-v2 [public|private]
#
# Prereqs:
#   - GitHub CLI (`gh`) installed and authenticated: gh auth login
#   - OR a personal access token in $GITHUB_TOKEN env var
set -euo pipefail

GH_USER="${1:-}"
REPO_NAME="${2:-trading-agent-v2}"
VISIBILITY="${3:-private}"

if [ -z "$GH_USER" ]; then
  echo "usage: bash setup_github.sh <github-username> [repo-name] [public|private]"
  exit 1
fi

if [ ! -d .git ]; then
  echo "[git] init"
  git init -b main
  git add -A
  git -c user.email="$GH_USER@users.noreply.github.com" \
      -c user.name="$GH_USER" \
      commit -m "V2: initial scaffold (Multi-Agent RAG, V1-mirror fitness, side-by-side paper trade)"
fi

if command -v gh >/dev/null 2>&1; then
  echo "[gh] creating $GH_USER/$REPO_NAME ($VISIBILITY)"
  gh repo create "$GH_USER/$REPO_NAME" --"$VISIBILITY" --source=. --remote=origin --push
else
  echo "gh CLI not found. Manual fallback:"
  echo "  1. Create empty repo at https://github.com/new (name: $REPO_NAME)"
  echo "  2. git remote add origin https://github.com/$GH_USER/$REPO_NAME.git"
  echo "  3. git push -u origin main"
fi

echo "[done] CI will run pytest on every push (see .github/workflows/tests.yml)"
