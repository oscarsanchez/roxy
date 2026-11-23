#!/usr/bin/env bash
# Install roxy: link bin/roxy from this checkout into ~/.local/bin, seed the settings root
# (scripts/lib.sh) with each settings file it lacks, nothing set yet (roxy setup fills them
# in), and switch on the repo's git hooks.
# Safe to run again: it refreshes the link and never overwrites a setting. It refuses,
# changing nothing, when ~/.local/bin/roxy exists and is not a link.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/scripts/lib.sh"

bin="$HOME/.local/bin"
link="$bin/roxy"
[ ! -e "$link" ] || [ -L "$link" ] || die "$link exists and is not a link; move it away first"

mkdir -p "$bin"
ln -sfn "$REPO_ROOT/bin/roxy" "$link"
echo "linked $link -> $REPO_ROOT/bin/roxy"

# seed EXAMPLE : the settings file EXAMPLE (in settings.example/) with nothing set yet:
# secrets.env as it is, every secret empty; no made-up devices or lan_subnets, which would
# only hide what is missing.
seed() {
  case "$(basename "$1")" in
    devices.json) echo '{}' ;;
    settings.json) printf '{\n  "lan_subnets": [],\n  "grid_devices": {}\n}\n' ;;
    *) cat "$1" ;;
  esac
}

mkdir -p "$ROXY_CONFIG_DIR"
for example in "$REPO_ROOT"/settings.example/*; do
  file="$ROXY_CONFIG_DIR/$(basename "$example")"
  if [ -e "$file" ]; then
    echo "kept   $file"
  else
    (umask 077; seed "$example" > "$file")  # personal settings and secrets: the user's eyes only
    echo "seeded $file"
  fi
done
echo "next: roxy setup, then roxy device discover or roxy device add (docs/settings.md)"

git -C "$REPO_ROOT" config core.hooksPath .githooks  # scripts/check on every commit, worktrees included
echo "git hooks on: .githooks"

case ":$PATH:" in
  *":$bin:"*) ;;
  *) echo "note: $bin is not on PATH; add it to use roxy from any terminal" ;;
esac
