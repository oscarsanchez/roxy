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

# The fake uv stands in for `uv run mitmweb ...`: it logs one argument per line. Its empty
# answer to start-lab's App Profile resolve (proxy/cli.py) means none, as these settings have none.
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

# refused WHAT... : start-lab fails, naming every WHAT in one run, before mitmweb starts.
refused() {
  local err what
  rm -f "$UV_LOG"
  if err="$("$SCRIPTS/start-lab" ${START_ARGS[@]+"${START_ARGS[@]}"} 2>&1)"; then fail "start-lab started without $*: $err"; fi
  for what in "$@"; do
    case "$err" in *"$what"*) ;; *) fail "start-lab's refusal does not name $what: $err" ;; esac
  done
  [ ! -e "$UV_LOG" ] || fail "mitmweb started without $*"
}
START_ARGS=()

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

# As install.sh seeds them: no devices and no lan_subnets are named, with the commands that
# fill them in, and so is the empty mitmweb password.
seeded "$ROXY_CONFIG_DIR"
sed -i.bak 's/^MITMWEB_PASSWORD=.*/MITMWEB_PASSWORD=/' "$ROXY_CONFIG_DIR/secrets.env"
echo '{}' > "$ROXY_CONFIG_DIR/devices.json"
printf '{"lan_subnets": [], "grid_devices": {}}\n' > "$ROXY_CONFIG_DIR/settings.json"
refused "no Target Devices in $ROXY_CONFIG_DIR/devices.json" "roxy device add" lan_subnets MITMWEB_PASSWORD "roxy setup"
echo "ok: no devices and no lan_subnets are named, pointing at roxy setup and roxy device add"

# Everything missing is named in one run, not one problem per try.
rm -r "$ROXY_CONFIG_DIR"
refused "$ROXY_CONFIG_DIR/secrets.env" "$ROXY_CONFIG_DIR/devices.json" "$ROXY_CONFIG_DIR/settings.json"
seeded "$ROXY_CONFIG_DIR"
sed -i.bak 's/^MITMWEB_PASSWORD=.*/MITMWEB_PASSWORD=/' "$ROXY_CONFIG_DIR/secrets.env"
sed -i.bak 's/^LAB_SECRET=.*/LAB_SECRET=/' "$ROXY_CONFIG_DIR/secrets.env"
rm "$ROXY_CONFIG_DIR/devices.json"
echo '{}' > "$ROXY_CONFIG_DIR/settings.json"
START_ARGS=(--tunnel)
refused MITMWEB_PASSWORD LAB_SECRET "$ROXY_CONFIG_DIR/devices.json" lan_subnets
START_ARGS=()
echo "ok: every missing settings file, setting and secret is named in one run"

# With every setting in place, mitmweb starts, and the session is saved under the user
# data directory, in the folder for sessions without an App Profile.
seeded "$ROXY_CONFIG_DIR"
out="$("$SCRIPTS/start-lab" 2>&1)" || fail "start-lab with every setting: $out"
[ -e "$UV_LOG" ] || fail "mitmweb did not start: $out"
session="$(sed -n 's/^save_stream_file=//p' "$UV_LOG")"
case "$session" in "$XDG_DATA_HOME/roxy/captures/no-profile/"*.mitm) ;; *) fail "the session is saved to $session" ;; esac
[ -d "$(dirname "$session")" ] || fail "the Recordings folder $(dirname "$session") does not exist"
grep -qx 'web_password=test-password' "$UV_LOG" || fail "mitmweb did not get the password from secrets.env"
echo "ok: a session is saved in the user data directory"

# Both LAN listeners start (8888 is Charles's port, which client hooks hardcode), and the
# start prints the Proxy IP to type into an app's debug proxy setting and both LAN Proxy Bases.
grep -qx 'reverse:http://127.0.0.1:9@8080' "$UV_LOG" || fail "mitmweb has no LAN listener on 8080"
grep -qx 'reverse:http://127.0.0.1:9@8888' "$UV_LOG" || fail "mitmweb has no LAN listener on 8888"
ip="$(printf '%s\n' "$out" | sed -n 's/^Proxy IP: *\([^ ]*\).*/\1/p')"
[ -n "$ip" ] || fail "the start does not print the Proxy IP: $out"
case "$out" in *"http://$ip:8080"*"http://$ip:8888"*) ;; *) fail "the start does not print both LAN Proxy Bases: $out" ;; esac
echo "ok: both LAN listeners start, and the start prints the Proxy IP and both LAN Proxy Bases"

# The Proxy Routing listener starts too, an HTTP proxy on the LAN that the lab tells apart
# by its port, and the start prints the address to set as a Proxied Device's HTTP proxy.
grep -qx 'regular@8090' "$UV_LOG" || fail "mitmweb has no Proxy Routing listener on 8090"
grep -qx 'lab_proxy_routing_port=8090' "$UV_LOG" || fail "the lab does not know the Proxy Routing listener's port"
case "$out" in *"Proxy Routing:     $ip:8090"*) ;; *) fail "the start does not print the Proxy Routing address: $out" ;; esac
echo "ok: the Proxy Routing listener starts, and the start prints its address"
