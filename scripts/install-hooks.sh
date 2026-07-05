#!/usr/bin/env bash
# Install Burma Bites git hooks into .git/hooks/
# Usage: bash scripts/install-hooks.sh

set -euo pipefail

HOOKS_DIR="$(git rev-parse --git-dir)/hooks"
SCRIPTS_DIR="$(dirname "$0")"
REPO_ROOT="$(git rev-parse --show-toplevel)"

echo "🔧 Installing Burma Bites git hooks..."

# Install pre-commit hook
cp "$REPO_ROOT/scripts/pre-commit.sh" "$HOOKS_DIR/pre-commit"
chmod +x "$HOOKS_DIR/pre-commit"
echo "  ✅ pre-commit hook installed"

# Install Semgrep if not present
if ! command -v semgrep &>/dev/null; then
  echo ""
  echo "  ⚠️  Semgrep not found. Install it with:"
  echo "       pip install semgrep"
  echo "       # or"
  echo "       brew install semgrep"
fi

echo ""
echo "✅ Done. Hooks are active for this repository."
