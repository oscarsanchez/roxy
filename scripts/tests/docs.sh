#!/usr/bin/env bash
# scripts/check-docs on temp trees: relative links and #anchors resolve, a symlinked doc is
# checked as its target, external URLs and code are skipped; the changelog has the plugin version.
# Usage: scripts/tests/docs.sh   (run by scripts/check)
set -euo pipefail
# A git hook (scripts/check from the pre-commit hook) exports the checkout's GIT_INDEX_FILE,
# absolute in a worktree: git add in a temp tree would overwrite the commit's index.
unset GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE
CHECK_DOCS="$(cd "$(dirname "$0")/.." && pwd)/check-docs"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

# tree NAME: a fresh git checkout at $TMP/NAME holding a valid doc set; prints its path.
tree() {
  local t="$TMP/$1"
  mkdir -p "$t/docs" "$t/skill"
  cat > "$t/README.md" <<'EOF'
# Lab

## How it works

See [the guide](docs/guide.md#step-one), [here](#how-it-works), [the site](https://example.com/x.md),
<a href="docs/guide.md">guide</a>, and `[not a link](nowhere.md)`.

```sh
# a comment, not a heading; [nor](a-link.md)
```
EOF
  cat > "$t/docs/guide.md" <<'EOF'
# Guide

## Step one

## Step one

<a id="custom"></a>
Back to [the README](../README.md#how-it-works), [the second step](#step-one-1), [custom](#custom).
EOF
  ln -s ../docs "$t/skill/docs"
  ln -s ../README.md "$t/skill/README.md"
  printf '[Guide](docs/guide.md#step-one)\n' > "$t/skill/SKILL.md"
  mkdir -p "$t/.claude-plugin"
  printf '{"name": "lab", "version": "1.2.0"}\n' > "$t/.claude-plugin/plugin.json"
  printf '# Changelog\n\n## [Unreleased]\n\n## [1.2.0] - 2026-01-01\n' > "$t/CHANGELOG.md"
  git -C "$t" init -q && git -C "$t" add -A
  echo "$t"
}

# expect_fail TREE TEXT: check-docs fails on TREE and reports TEXT.
expect_fail() {
  local err
  if err="$("$CHECK_DOCS" "$1" 2>&1)"; then fail "check-docs passed $1"; fi
  case "$err" in *"$2"*) ;; *) fail "check-docs on $1 said:
$err
expected: $2" ;; esac
}

t="$(tree valid)"
out="$("$CHECK_DOCS" "$t" 2>&1)" || fail "a valid tree failed: $out"
echo "ok: links, anchors, duplicate headings, html anchors and links through symlinks resolve"

t="$(tree broken-link)"
printf '\nSee [gone](docs/gone.md).\n' >> "$t/README.md"
expect_fail "$t" "README.md:12: broken link 'docs/gone.md'"
echo "ok: a broken link fails, naming file:line"

t="$(tree broken-anchor)"
printf '\nSee [nope](guide.md#step-two).\n' >> "$t/docs/guide.md"
expect_fail "$t" "docs/guide.md:10: broken anchor 'guide.md#step-two'"
echo "ok: a broken anchor fails, naming file:line"

t="$(tree broken-through-symlink)"
printf '[Gone](docs/guide.md#gone)\n' >> "$t/skill/SKILL.md"
expect_fail "$t" "skill/SKILL.md:2: broken anchor 'docs/guide.md#gone'"
echo "ok: a link through a symlinked folder is checked"

t="$(tree version-bump)"
printf '{"name": "lab", "version": "1.3.0"}\n' > "$t/.claude-plugin/plugin.json"
expect_fail "$t" "CHANGELOG.md: no '## [1.3.0]' section"
echo "ok: a plugin version with no changelog section fails, naming the version"

t="$(tree ignored-target)"
mkdir -p "$t/notes" && printf '# Local\n' > "$t/notes/local.md" && printf 'notes/\n' > "$t/.gitignore"
git -C "$t" add .gitignore
printf '\nSee [local](notes/local.md).\n' >> "$t/README.md"
expect_fail "$t" "README.md:12: broken link 'notes/local.md'"
echo "ok: a link to a file git does not track fails"
