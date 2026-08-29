#!/usr/bin/env bash
# Dependency audit — checks the versions a FRESH INSTALL could resolve to, not
# just the ones happening to sit in this checkout's lockfile.
#
# The distinction is the whole point: pyproject declares floors ("httpx>=0.27"),
# and a downstream installer is entitled to any version at or above them. A
# lockfile that is clean today says nothing about the floor a new user gets.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAIL=0

say() { printf '%s\n' "$*"; }

say "==> Declared dependencies"
sed -n '/^dependencies = \[/,/^]/p' pyproject.toml | sed 's/^/    /'

say ""
say "==> A. Resolved set (this checkout's lockfile)"
uv pip freeze 2>/dev/null | grep -viE '^-e |^sm-telemetry-monitor' > "$TMP/resolved.txt" || true
if uv run --with pip-audit python -m pip_audit -r "$TMP/resolved.txt" --progress-spinner off; then
  say "ok: resolved set clean"
else
  say "FAIL: vulnerability in the resolved set — upgrade and re-lock"; FAIL=1
fi

say ""
say "==> B. Floor set (lowest versions the declared minimums permit)"
if uv pip compile pyproject.toml --resolution lowest-direct -o "$TMP/floor.txt" --quiet 2>/dev/null; then
  grep -vE '^#|^$|^ ' "$TMP/floor.txt" | sed 's/^/    /'
  if uv run --with pip-audit python -m pip_audit -r "$TMP/floor.txt" --progress-spinner off; then
    say "ok: a fresh install at the declared floors is clean"
  else
    say "FAIL: the declared minimums permit a vulnerable version."
    say "      Raise the floor in pyproject.toml to the first fixed release."
    FAIL=1
  fi
else
  say "FAIL: could not resolve the floor set"; FAIL=1
fi

say ""
say "==> C. Declared but unimported"
# A dependency nothing imports is surface with no function — remove it rather
# than carry its advisories.
for pkg in $(sed -n '/^dependencies = \[/,/^]/p' pyproject.toml \
             | grep -oE '"[a-zA-Z0-9._-]+' | tr -d '"'); do
  mod="${pkg//-/_}"
  case "$pkg" in
    python-dotenv) mod="dotenv" ;;
  esac
  if grep -rqE "^\s*(import|from)\s+${mod}\b" src/ --include=*.py; then
    say "    ok: $pkg is imported"
  else
    say "    FAIL: $pkg is declared but never imported"; FAIL=1
  fi
done

say ""
if [[ $FAIL -eq 0 ]]; then
  say "Dependency audit passed."
else
  say "Dependency audit FAILED — see above."
  exit 1
fi
