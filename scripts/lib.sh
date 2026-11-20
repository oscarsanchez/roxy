# Shared helpers for the lab scripts. Source it; do not run it.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The settings root: the user's secrets, devices and LAN subnets, never in a repo.
# ROXY_CONFIG_DIR overrides it (tests, experiments). Exported: the proxy reads it too.
export ROXY_CONFIG_DIR="${ROXY_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/roxy}"
SECRETS_FILE="$ROXY_CONFIG_DIR/secrets.env"
DEVICES_FILE="$ROXY_CONFIG_DIR/devices.json"
SETTINGS_FILE="$ROXY_CONFIG_DIR/settings.json"
# App Profiles: APPS_DIR/<name>/profile.json ({"repo", "origin_allowlist"}) and
# APPS_DIR/<name>/scenarios/ (its Scenarios and their mocks). proxy/lab/app_profile.py loads one.
APPS_DIR="$ROXY_CONFIG_DIR/apps"
LAB_SCENARIOS_DIR="$REPO_ROOT/proxy/scenarios"  # the lab's own Scenarios
# Saved sessions: the user data directory, in the loaded App Profile's folder (LAB_APP, which
# scripts/start-lab exports), or the one for sessions without a profile.
CAPTURES_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/roxy/captures/${LAB_APP:-no-profile}"

LAB_PORT=8080      # LAN listener (Prefix Routing)
LAB_CHARLES_PORT=8888  # second LAN listener, the same chain: Charles's port, which client hooks hardcode
LAB_WEB_PORT=8081  # mitmweb UI, localhost only
LAB_TUNNEL_PORT=8082  # tunnel listener: only cloudflared dials it, never reachable from the LAN
LAB_CA_ROUTING_PORTS="443 80"  # CA Routing listeners: Origin URLs that DNS sends to the lab
LAB_CA_CERT="$HOME/.mitmproxy/mitmproxy-ca-cert.pem"  # the lab's CA, created by mitmweb's first start
TUNNEL_METRICS="127.0.0.1:20241"  # cloudflared's local metrics server: readiness and the quick tunnel hostname

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

# missing_setting_file FILE : fail, naming FILE and its example.
missing_setting_file() {
  die "missing setting file $1 (copy settings.example/$(basename "$1") there, then fill it in)"
}

load_env() {
  [ -f "$SECRETS_FILE" ] || missing_setting_file "$SECRETS_FILE"
  set -a
  # shellcheck disable=SC1090
  . "$SECRETS_FILE"
  set +a
}

# require_env NAME... : fail fast, naming every missing secret.
require_env() {
  local missing="" name
  for name in "$@"; do
    [ -n "${!name:-}" ] || missing="$missing $name"
  done
  [ -z "$missing" ] || die "missing secrets in $SECRETS_FILE:$missing"
}

# require_settings : fail fast, naming a missing settings file or setting.
require_settings() {
  command -v jq >/dev/null || die "jq is required (brew install jq)"
  [ -f "$DEVICES_FILE" ] || missing_setting_file "$DEVICES_FILE"
  [ -f "$SETTINGS_FILE" ] || missing_setting_file "$SETTINGS_FILE"
  jq -e '.lan_subnets | length > 0' "$SETTINGS_FILE" >/dev/null 2>&1 \
    || die "missing setting lan_subnets (your LAN's subnets, CIDR) in $SETTINGS_FILE"
}

# resolve_app [NAME] : the App Profile to load: NAME (an unknown one fails), else the one
# whose repo holds the current folder (the deepest, for nested repos), else none (empty).
resolve_app() {
  local here f repo best="" best_repo=""
  if [ -n "${1:-}" ]; then
    [ -f "$APPS_DIR/$1/profile.json" ] || die "unknown App Profile '$1' (roxy app list shows them)"
    echo "$1"
    return
  fi
  here="$(pwd -P)"
  for f in "$APPS_DIR"/*/profile.json; do
    [ -f "$f" ] || continue
    repo="$(jq -r .repo "$f")"
    case "$here/" in
      "$repo/"*) [ ${#repo} -le ${#best_repo} ] || { best="$(basename "$(dirname "$f")")"; best_repo="$repo"; } ;;
    esac
  done
  echo "$best"
}

# app_scenarios_dir NAME : the folder of App Profile NAME's Scenarios and their mocks.
app_scenarios_dir() { echo "$APPS_DIR/$1/scenarios"; }

# The Mac's address on the default-route interface.
lan_ip() {
  local iface ip
  iface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')"
  ip="$(ipconfig getifaddr "$iface" 2>/dev/null)" || true
  [ -n "$ip" ] || die "could not find the Mac's LAN IP"
  echo "$ip"
}

lan_proxy_base() { echo "http://$(lan_ip):$LAB_PORT"; }

# print_lan_addresses IP : the Proxy IP and LAN Proxy Bases lines, as start-lab and
# roxy status print them.
print_lan_addresses() {
  echo "Proxy IP:          $1  (for an app's debug proxy setting)"
  echo "LAN Proxy Bases:   http://$1:$LAB_PORT  http://$1:$LAB_CHARLES_PORT  (each takes the / and /; forms)"
}

# tunnel_host : the running quick tunnel's hostname; fails when no tunnel is up.
tunnel_host() {
  curl -fsS "http://$TUNNEL_METRICS/quicktunnel" 2>/dev/null | jq -er '.hostname | select(. != "")'
}

# public_proxy_base : the running tunnel's public Proxy Base, without a device slug;
# fails when no tunnel is up. Needs load_env.
public_proxy_base() {
  local host
  host="$(tunnel_host)" || return 1
  require_env LAB_SECRET
  echo "https://$host/$LAB_SECRET"
}

# mitmweb_get PATH : GET PATH from the running lab's mitmweb API; fails when no lab
# answers. Needs load_env.
mitmweb_get() {
  curl -fsS -H "Authorization: Bearer $MITMWEB_PASSWORD" "http://127.0.0.1:$LAB_WEB_PORT/$1"
}

# set_scenario NAME : make NAME the running lab's active Scenario through mitmweb's API;
# '' clears it. Prints scenario=NAME (or none).
set_scenario() {
  local answer
  load_env
  require_env MITMWEB_PASSWORD
  # Non-GET mitmweb API calls need a matching XSRF cookie and header (any value).
  answer="$(curl -sS -X PUT "http://127.0.0.1:$LAB_WEB_PORT/options" \
    -H "Authorization: Bearer $MITMWEB_PASSWORD" \
    -H "Cookie: _mitmproxy_xsrf=lab" -H "X-XSRFToken: lab" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg s "$1" '{lab_scenario: $s}')" \
    -w '\n%{http_code}')" || die "could not reach mitmweb on port $LAB_WEB_PORT (is the lab running? roxy start)"
  [ "${answer##*$'\n'}" = 200 ] || die "mitmweb refused scenario '$1': ${answer%$'\n'*}"
  echo "scenario=${1:-none}"
}

# device_field DEVICE-NAME FIELD : a field of a named Target Device, empty if unset.
device_field() {
  command -v jq >/dev/null || die "jq is required (brew install jq)"
  [ -f "$DEVICES_FILE" ] || missing_setting_file "$DEVICES_FILE"
  jq -e --arg n "$1" 'has($n)' "$DEVICES_FILE" >/dev/null \
    || die "unknown device '$1'. Known: $(jq -r 'keys | join(", ")' "$DEVICES_FILE")"
  jq -r --arg n "$1" --arg f "$2" '.[$n][$f] // empty' "$DEVICES_FILE"
}

# grid_device SETUP : the Target Device that scripts/grid fills SETUP cells on (physical,
# cloud or ca-routing: grid/verdict.py setup), named in settings.json grid_devices.
grid_device() {
  command -v jq >/dev/null || die "jq is required (brew install jq)"
  [ -f "$SETTINGS_FILE" ] || missing_setting_file "$SETTINGS_FILE"
  jq -er --arg s "$1" '.grid_devices[$s] // empty' "$SETTINGS_FILE" \
    || die "missing setting grid_devices.$1 (a device name from devices.json) in $SETTINGS_FILE"
}

# Percent-encode one value completely, for ECP query parameters.
uri_encode() { jq -rn --arg v "$1" '$v | @uri'; }

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
