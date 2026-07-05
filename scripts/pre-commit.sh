#!/usr/bin/env bash
# Canonical source copy of the pre-commit hook — kept under version control.
# .git/hooks/pre-commit should be a copy of (or symlink to) this file.
# Run scripts/install-hooks.sh to install.
#
# Burma Bites — Semgrep pre-commit security hook
# Blocks commits containing hardcoded API keys or secrets (p/secrets ruleset).
#
# Bypass:  git commit --no-verify  (requires explicit project owner approval)

set -euo pipefail

SEMGREP_CONFIG="p/secrets"
SEMGREP_BIN="$(command -v semgrep 2>/dev/null || echo "")"

# ── Check Semgrep is available ────────────────────────────────────────────────
if [[ -z "$SEMGREP_BIN" ]]; then
  echo ""
  echo "╔══════════════════════════════════════════════════════════════════╗"
  echo "║  ⚠️  Semgrep not found — skipping security scan.                ║"
  echo "║  Install: pip install semgrep  or  brew install semgrep         ║"
  echo "╚══════════════════════════════════════════════════════════════════╝"
  echo ""
  exit 0
fi

# ── Get list of staged Python/config files ────────────────────────────────────
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM \
  | grep -E '\.(py|json|yaml|yml|env\.example|toml)$' || true)

if [[ -z "$STAGED_FILES" ]]; then
  exit 0
fi

echo ""
echo "🔒 Burma Bites Security Scan (Semgrep $SEMGREP_CONFIG)"
echo "──────────────────────────────────────────────────────"

TMPDIR_SCAN=$(mktemp -d)
trap 'rm -rf "$TMPDIR_SCAN"' EXIT

while IFS= read -r file; do
  if [[ -f "$file" ]]; then
    dir="$TMPDIR_SCAN/$(dirname "$file")"
    mkdir -p "$dir"
    git show ":$file" > "$TMPDIR_SCAN/$file" 2>/dev/null || true
  fi
done <<< "$STAGED_FILES"

SEMGREP_OUTPUT=$(semgrep \
  --config "$SEMGREP_CONFIG" \
  --error \
  --quiet \
  --text \
  "$TMPDIR_SCAN" 2>&1) || SEMGREP_EXIT=$?

SEMGREP_EXIT=${SEMGREP_EXIT:-0}

if [[ $SEMGREP_EXIT -eq 0 ]]; then
  echo "✅ No secrets or hardcoded credentials detected."
  echo ""
  exit 0
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  🚨 COMMIT BLOCKED — Hardcoded secret or credential detected!   ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "$SEMGREP_OUTPUT"
echo ""
echo "──────────────────────────────────────────────────────"
echo "📋 HOW TO FIX:"
echo "  1. Replace hardcoded values with environment variable references:"
echo "       api_key = os.environ[\"YOUR_KEY_NAME\"]"
echo "  2. Add the variable to .env (which is in .gitignore)"
echo "  3. Stage the fix:  git add <file>"
echo "  4. Retry:          git commit"
echo ""
echo "  See .agents/CONTEXT.md Rule 1 for the full policy."
echo "──────────────────────────────────────────────────────"
echo ""
echo "⛔ To bypass (requires project owner approval): git commit --no-verify"
echo ""
exit 1
