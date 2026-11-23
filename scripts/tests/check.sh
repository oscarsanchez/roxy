#!/usr/bin/env bash
# scripts/check runs only the steps it is given, and every step without one.
# Usage: scripts/tests/check.sh   (run by scripts/check)
set -euo pipefail
CHECK="$(cd "$(dirname "$0")/.." && pwd)/check"

fail() { echo "FAIL: $*" >&2; exit 1; }

# A named step runs alone: its header is the only one.
out="$("$CHECK" syntax 2>&1)" || fail "scripts/check syntax: $out"
[ "$(grep -c '^== ' <<< "$out")" = 1 ] || fail "scripts/check syntax ran other steps:
$out"
case "$out" in "== syntax: "*"all checks passed") ;; *) fail "scripts/check syntax said:
$out" ;; esac
echo "ok: scripts/check runs only the named step"

# An unknown step stops it before any step runs, listing the steps.
if err="$("$CHECK" syntax no-such-step 2>&1)"; then fail "scripts/check took an unknown step: $err"; fi
case "$err" in "error: unknown step 'no-such-step' (steps: "*"syntax"*"glossary"*"docs"*) ;; *) fail "an unknown step said: $err" ;; esac
echo "ok: an unknown step is refused, naming the steps"

# A hook's git variables never reach a step: with them, git in a step would use the hook's
# repo and index (here, none) instead of the one its folder is in.
out="$(GIT_DIR=/nonexistent/git GIT_INDEX_FILE=/nonexistent/index GIT_WORK_TREE=/nonexistent "$CHECK" glossary 2>&1)" \
  || fail "scripts/check glossary with a hook's git variables: $out"
echo "ok: a hook's git variables never reach the steps"
