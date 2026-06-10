#!/usr/bin/env bash
# Pre-push audit: fail if secrets or runtime data would be published.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
FAIL=0

say() { printf '%s\n' "$*"; }
fail() { say "FAIL: $*"; FAIL=1; }
ok() { say "ok: $*"; }

say "==> Sensitive paths must be ignored"
for path in .env .env.local data/telemetry.db data/telemetry.jsonl .grok/config.toml; do
  if [[ -e "$path" ]] && ! git check-ignore -q "$path" 2>/dev/null; then
    fail "$path exists but is NOT gitignored"
  elif [[ -e "$path" ]]; then
    ok "gitignored $path"
  fi
done

say ""
say "==> Must not be tracked by git"
for path in .env data/telemetry.db data/telemetry.jsonl; do
  if git ls-files --error-unmatch "$path" &>/dev/null; then
    fail "tracked in git: $path"
  else
    ok "not tracked: $path"
  fi
done

say ""
say "==> Scan tracked files for credential patterns"
# Placeholders in .env.example/README are fine; real tok_* hex segments are not.
if git grep -E 'tok_[a-zA-Z0-9]{12,}' -- ':!*.example' ':!README.md' ':!docs/' ':!tests/' ':!sanitize.py' 2>/dev/null; then
  fail "possible real AGENT_TOKEN in tracked files (see above)"
else
  ok "no long tok_* literals outside docs/tests"
fi

if git grep -E 'postgresql://[^[]' -- \
    ':!tests/' ':!SECURITY.md' ':!src/sm_telemetry_monitor/sanitize.py' \
    ':!scripts/pre-publish-check.sh' 2>/dev/null; then
  fail "postgresql:// connection string in tracked files"
else
  ok "no postgresql:// connection strings"
fi

say ""
say "==> Tests"
uv run python -m unittest discover -s tests -q

say ""
if [[ $FAIL -eq 0 ]]; then
  say "Pre-publish check passed."
else
  say "Pre-publish check FAILED — fix before pushing to GitHub."
  exit 1
fi