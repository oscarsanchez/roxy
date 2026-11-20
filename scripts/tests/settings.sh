#!/usr/bin/env bash
# scripts/start-lab and the user's settings: where they are read from, the fail-fast
# start that names what is missing, and where the session is saved. mitmweb is a
# fake on PATH that logs its arguments; no lab, no network, no real settings.
# Usage: scripts/tests/settings.sh   (run by scripts/check)
set -euo pipefail
SCRIPTS="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(dirname "$SCRIPTS")"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export LAB_LOCK_DIR="$TMP/locks" XDG_CONFIG_HOME="$TMP/config" XDG_DATA_HOME="$TMP/data" UV_LOG="$TMP/uv.log"
unset ROXY_CONFIG_DIR LAB_LOCK_TOKEN LAB_LOCK_WAIT LAB_LOCK_OWNER LAB_LAN_SUBNETS LAB_REPLAY \
  MITMWEB_PASSWORD LAB_SECRET ROKU_DEV_USER ROKU_DEV_PASSWORD

fail() { echo "FAIL: $*" >&2; exit 1; }

# The fake uv stands in for `uv run mitmweb ...`: it logs one argument per line.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/uv" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$UV_LOG"
EOF
chmod +x "$TMP/bin/uv"
export PATH="$TMP/bin:$PATH"

# seeded DIR : a settings root seeded from the repo's examples, with a mitmweb password.
seeded() {
  mkdir -p "$1"
  cp -R "$REPO/settings.example/." "$1"
  sed -i.bak 's/^MITMWEB_PASSWORD=.*/MITMWEB_PASSWORD=test-password/' "$1/secrets.env"
}

# refused WHAT : start-lab fails, naming WHAT, before mitmweb starts.
refused() {
  local err
  rm -f "$UV_LOG"
  if err="$("$SCRIPTS/start-lab" 2>&1)"; then fail "start-lab started without $1: $err"; fi
  case "$err" in *"$1"*) ;; *) fail "start-lab's refusal does not name $1: $err" ;; esac
  [ ! -e "$UV_LOG" ] || fail "mitmweb started without $1"
}

# Without ROXY_CONFIG_DIR, the settings root is roxy in the user config directory.
refused "$XDG_CONFIG_HOME/roxy/secrets.env"
echo "ok: the settings root defaults to the user config directory"

export ROXY_CONFIG_DIR="$TMP/settings"
refused "$ROXY_CONFIG_DIR/secrets.env"
echo "ok: ROXY_CONFIG_DIR overrides the settings root"

seeded "$ROXY_CONFIG_DIR"
sed -i.bak 's/^MITMWEB_PASSWORD=.*/MITMWEB_PASSWORD=/' "$ROXY_CONFIG_DIR/secrets.env"
refused MITMWEB_PASSWORD
echo "ok: a missing secret is named"

for file in settings.json devices.json; do
  seeded "$ROXY_CONFIG_DIR"
  rm "$ROXY_CONFIG_DIR/$file"
  refused "$ROXY_CONFIG_DIR/$file"
done
seeded "$ROXY_CONFIG_DIR"
echo '{}' > "$ROXY_CONFIG_DIR/settings.json"
refused lan_subnets
echo "ok: a missing settings file or setting is named"

# With every setting in place, mitmweb starts, and the session is saved under the user
# data directory, in the folder for sessions without an App Profile.
seeded "$ROXY_CONFIG_DIR"
out="$("$SCRIPTS/start-lab" 2>&1)" || fail "start-lab with every setting: $out"
[ -e "$UV_LOG" ] || fail "mitmweb did not start: $out"
session="$(sed -n 's/^save_stream_file=//p' "$UV_LOG")"
case "$session" in "$XDG_DATA_HOME/roxy/captures/no-profile/"*.mitm) ;; *) fail "the session is saved to $session" ;; esac
[ -d "$(dirname "$session")" ] || fail "the saved-session folder $(dirname "$session") does not exist"
grep -qx 'web_password=test-password' "$UV_LOG" || fail "mitmweb did not get the password from secrets.env"
echo "ok: a session is saved in the user data directory"
