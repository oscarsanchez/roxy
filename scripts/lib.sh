# Shared helpers for the lab scripts. Source it; do not run it.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The settings root: the user's secrets, devices and LAN subnets, never in a repo.
# ROXY_CONFIG_DIR overrides it (tests, experiments). Exported: the proxy reads it too.
export ROXY_CONFIG_DIR="${ROXY_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/roxy}"
SECRETS_FILE="$ROXY_CONFIG_DIR/secrets.env"
DEVICES_FILE="$ROXY_CONFIG_DIR/devices.json"
SETTINGS_FILE="$ROXY_CONFIG_DIR/settings.json"
# Recordings: the Recordings root (RECORDINGS_ROOT) in the user data directory, in the loaded
# App Profile's folder (LAB_APP, which scripts/start-lab exports), or the one for Lab
# Sessions without a profile.
RECORDINGS_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/roxy/captures"
RECORDINGS_DIR="$RECORDINGS_ROOT/${LAB_APP:-no-profile}"

LAB_PORT=8080      # LAN listener (Prefix Routing)
LAB_CHARLES_PORT=8888  # second LAN listener, the same chain: Charles's port, which client hooks hardcode
LAB_WEB_PORT="${LAB_WEB_PORT:-8081}"  # mitmweb UI, localhost only; LAB_WEB_PORT overrides it (tests)
LAB_PROXY_ROUTING_PORT=8090  # Proxy Routing listener: the HTTP proxy a Proxied Device sets, LAN only
LAB_TUNNEL_PORT=8082  # tunnel listener: only cloudflared dials it, never reachable from the LAN
LAB_CA_ROUTING_PORTS="443 80"  # CA Routing listeners: Origin URLs that DNS sends to the lab
LAB_CA_CERT="$HOME/.mitmproxy/mitmproxy-ca-cert.pem"  # the lab's CA, created by mitmweb's first start
TUNNEL_METRICS="127.0.0.1:20241"  # cloudflared's local metrics server: readiness and the quick tunnel hostname
# Build output and logs: packages, the tunnel's log, console and grid evidence, in the
# checkout's gitignored out/. ROXY_OUT_DIR overrides it (tests). Exported: grid/ reads it too.
export ROXY_OUT_DIR="${ROXY_OUT_DIR:-$REPO_ROOT/out}"
CLOUDFLARED_LOG="$ROXY_OUT_DIR/cloudflared.log"  # the tunnel's log

LAB_LOCK_DIR="${LAB_LOCK_DIR:-$HOME/.cache/roxy/locks}"  # per user, shared by every checkout

die() { echo "error: $*" >&2; exit 1; }

# on_exit COMMAND : run COMMAND when the script exits, after those registered later.
_on_exit=""
on_exit() {
  _on_exit="$1; $_on_exit"
  trap "$_on_exit" EXIT
}

# lab_lock NAME : hold the per-user lock NAME until the script exits.
#   Held by a live process: fail naming it, or wait for it with LAB_LOCK_WAIT=1.
#   Held by a dead process: reclaimed. Re-entrant: the holder's child processes inherit
#   LAB_LOCK_TOKEN and pass straight through (scripts/grid running deploy and launch).
#   LAB_LOCK_OWNER (optional) names the holder in the lock, e.g. an agent's name.
# The lock is a file hard-linked into place already written: taking it is atomic, and
# a lock always names its holder's pid, so a dead holder's lock can always be reclaimed.
lab_lock() {
  local lock="$LAB_LOCK_DIR/$1" draft="$LAB_LOCK_DIR/.$1.$$" pid waited=false
  export LAB_LOCK_TOKEN="${LAB_LOCK_TOKEN:-$$.$RANDOM.$(date +%s)}"
  mkdir -p "$LAB_LOCK_DIR"
  printf 'pid=%s\nowner=%s\ncommand=%s\nsince=%s\ntoken=%s\n' "$$" "${LAB_LOCK_OWNER:-}" \
    "$(ps -o args= -p $$)" "$(date '+%Y-%m-%d %H:%M:%S')" "$LAB_LOCK_TOKEN" > "$draft"
  on_exit "rm -f $(printf %q "$draft")"
  until ln "$draft" "$lock" 2>/dev/null; do
    [ -e "$lock" ] || continue  # released just now
    [ "$(lock_field "$lock" token)" != "$LAB_LOCK_TOKEN" ] || return 0
    pid="$(lock_field "$lock" pid)"
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
      echo "reclaiming the $1 lock: its holder (pid $pid) is gone" >&2
      rm -f "$lock"
      continue
    fi
    [ "${LAB_LOCK_WAIT:-}" = 1 ] || die "the $1 lock is held by $(lock_holder "$lock"). Retry later, or wait with LAB_LOCK_WAIT=1"
    $waited || echo "waiting for the $1 lock, held by $(lock_holder "$lock")" >&2
    waited=true
    sleep 1
  done
  on_exit "rm -f $(printf %q "$lock")"
  trap 'exit 130' INT
  trap 'exit 143' TERM
}

# lock_field LOCK FIELD : one field of a lock, empty once the lock is gone.
lock_field() { sed -n "s/^$2=//p" "$1" 2>/dev/null || true; }

lock_holder() {
  local owner
  owner="$(lock_field "$1" owner)"
  echo "${owner:+$owner, }pid $(lock_field "$1" pid) since $(lock_field "$1" since): $(lock_field "$1" command)"
}

require_jq() { command -v jq >/dev/null || die "jq is required (brew install jq)"; }

# setting_file_problem FILE : names FILE and its example when FILE is missing; nothing otherwise.
setting_file_problem() {
  [ -f "$1" ] || echo "missing setting file $1 (copy settings.example/$(basename "$1") there, then fill it in)"
}

# require_setting_file FILE : fail when FILE is missing, naming it and its example.
require_setting_file() {
  local problem
  problem="$(setting_file_problem "$1")"
  [ -z "$problem" ] || die "$problem"
}

load_env() {
  require_setting_file "$SECRETS_FILE"
  set -a
  # shellcheck disable=SC1090
  . "$SECRETS_FILE"
  set +a
}

# secrets_problem NAME... : names every secret NAME that is not set (after load_env); nothing
# when all are.
secrets_problem() {
  local missing="" name
  for name in "$@"; do
    [ -n "${!name:-}" ] || missing="$missing $name"
  done
  [ -z "$missing" ] || echo "missing secrets in $SECRETS_FILE:$missing"
}

# require_env NAME... : fail fast, naming every missing secret.
require_env() {
  local problem
  problem="$(secrets_problem "$@")"
  [ -z "$problem" ] || die "$problem"
}

# require_lab_settings SECRET... : what the lab needs to start, loading secrets.env. Fails
# naming everything missing at once (settings files, lan_subnets, the secrets SECRET...),
# so one run shows all there is to fill in.
require_lab_settings() {
  local problems=() problem file
  require_jq
  for file in "$SECRETS_FILE" "$DEVICES_FILE" "$SETTINGS_FILE"; do
    problem="$(setting_file_problem "$file")"
    [ -z "$problem" ] || problems+=("$problem")
  done
  if [ -f "$SECRETS_FILE" ]; then
    load_env
    problem="$(secrets_problem "$@")"
    [ -z "$problem" ] || problems+=("$problem")
  fi
  if [ -f "$SETTINGS_FILE" ] && ! jq -e '.lan_subnets | length > 0' "$SETTINGS_FILE" >/dev/null 2>&1; then
    problems+=("missing setting lan_subnets (your LAN's subnets, CIDR) in $SETTINGS_FILE")
  fi
  [ ${#problems[@]} -eq 0 ] || { printf 'error: %s\n' "${problems[@]}" >&2; exit 1; }
}

# proxy_cli ARG... : App Profiles, their Scenarios, the running Lab Session and Recordings
# (proxy/cli.py describes the commands), run in the caller's folder, which resolving, app new
# and export read. It loads secrets.env first, when there is one, for MITMWEB_PASSWORD and
# LAB_SECRET, and passes LAB_WEB_PORT and RECORDINGS_ROOT.
# Refusals print error: ... and exit 1.
proxy_cli() {
  [ ! -f "$SECRETS_FILE" ] || load_env
  LAB_WEB_PORT="$LAB_WEB_PORT" RECORDINGS_ROOT="$RECORDINGS_ROOT" uv run --quiet --project "$REPO_ROOT/proxy" python "$REPO_ROOT/proxy/cli.py" "$@"
}

# The Mac's address on the default-route interface.
lan_ip() {
  local iface ip
  iface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')"
  ip="$(ipconfig getifaddr "$iface" 2>/dev/null)" || true
  [ -n "$ip" ] || die "could not find the Mac's LAN IP"
  echo "$ip"
}

# lan_proxy_base [IP [PORT]] : the LAN Proxy Base on IP (default: the Mac's LAN IP) and PORT
# (default: the LAN listener's).
lan_proxy_base() {
  local ip="${1-$(lan_ip)}"
  echo "http://$ip:${2:-$LAB_PORT}"
}

# print_lan_addresses IP : the Proxy IP, LAN Proxy Bases and Proxy Routing lines, as
# start-lab and roxy status print them.
print_lan_addresses() {
  echo "Proxy IP:          $1  (for an app's debug proxy setting)"
  echo "LAN Proxy Bases:   $(lan_proxy_base "$1")  $(lan_proxy_base "$1" "$LAB_CHARLES_PORT")  (each takes the / and /; forms)"
  echo "Proxy Routing:     $1:$LAB_PROXY_ROUTING_PORT  (a Mobile Device's HTTP proxy)"
}

# tunnel_host : the running quick tunnel's hostname; fails when no tunnel is up.
tunnel_host() {
  curl -fsS --noproxy '*' "http://$TUNNEL_METRICS/quicktunnel" 2>/dev/null | jq -er '.hostname | select(. != "")'
}

# public_proxy_base : the running tunnel's public Proxy Base, without a device slug;
# fails when no tunnel is up. Needs load_env.
public_proxy_base() {
  local host
  host="$(tunnel_host)" || return 1
  require_env LAB_SECRET
  echo "https://$host/$LAB_SECRET"
}

# redact_secret TEXT : TEXT with LAB_SECRET shown as <secret>, for what roxy prints: the
# secret reaches Cloud Devices, never a terminal (roxy status --show-secret aside). Needs load_env.
redact_secret() {
  if [ -n "${LAB_SECRET:-}" ]; then echo "${1//"$LAB_SECRET"/<secret>}"; else echo "$1"; fi
}

# require_public_proxy_base : public_proxy_base, loading secrets.env; fails saying how to
# start the tunnel when none is up.
require_public_proxy_base() {
  load_env
  public_proxy_base \
    || die "a Cloud Device needs the public Proxy Base: start the lab with its tunnel (roxy start --tunnel), or pass --proxy-base"
}

# device_field DEVICE-NAME FIELD : a field of a named Roku (a Physical or Cloud Device),
# empty if unset. Every script that drives a device looks it up here, so a Proxied Device
# ("kind": "proxied", or "mobile" as 0.2.0 wrote it) is refused before any device or rce call.
device_field() {
  require_jq
  require_setting_file "$DEVICES_FILE"
  jq -e --arg n "$1" 'has($n)' "$DEVICES_FILE" >/dev/null \
    || die "unknown device '$1'. Known: $(jq -r 'keys | join(", ")' "$DEVICES_FILE")"
  jq -e --arg n "$1" '.[$n].kind | IN("proxied", "mobile") | not' "$DEVICES_FILE" >/dev/null \
    || die "'$1' is a Proxied Device, not a Roku"
  jq -r --arg n "$1" --arg f "$2" '.[$n][$f] // empty' "$DEVICES_FILE"
}

# grid_device SETUP : the Target Device that scripts/grid fills SETUP cells on (physical,
# cloud or ca-routing: grid/verdict.py setup), named in settings.json grid_devices.
grid_device() {
  require_jq
  require_setting_file "$SETTINGS_FILE"
  jq -er --arg s "$1" '.grid_devices[$s] // empty' "$SETTINGS_FILE" \
    || die "missing setting grid_devices.$1 (a device name from devices.json) in $SETTINGS_FILE"
}

# Percent-encode one value completely, for ECP query parameters.
uri_encode() { jq -rn --arg v "$1" '$v | @uri'; }

# ecp_post IP PATH : POST to the ECP of the Physical Device at IP (PATH with its query).
ecp_post() { curl -sS --fail -o /dev/null -X POST -d '' "http://$1:8060/$2"; }

# rce_device_name DEVICE-NAME : the rce Device Name of a Cloud Device in devices.json, empty
# for a Physical Device. The rce CLI does everything RCE for the lab;
# `rce device resolve` checks the name locally, for free, before anything is billed.
rce_device_name() {
  local name
  name="$(device_field "$1" rce_device_name)"
  if [ -n "$name" ]; then
    command -v rce >/dev/null || die "Cloud Devices need the rce CLI on PATH (see its README to install it)"
    rce device resolve "$name" >/dev/null \
      || die "rce does not know the Device Name '$name' of '$1': see rce device list"
  fi
  echo "$name"
}
