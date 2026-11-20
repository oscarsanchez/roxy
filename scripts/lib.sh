# Shared helpers for the lab scripts. Source it; do not run it.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEVICES_FILE="$REPO_ROOT/proxy/config/devices.json"
LAB_PORT=8080      # LAN listener (Prefix Routing)
LAB_WEB_PORT=8081  # mitmweb UI, localhost only
LAB_TUNNEL_PORT=8082  # tunnel listener: only cloudflared dials it, never reachable from the LAN
LAB_CA_ROUTING_PORTS="443 80"  # CA Routing listeners: Origin URLs that DNS sends to the lab
LAB_CA_CERT="$HOME/.mitmproxy/mitmproxy-ca-cert.pem"  # the lab's CA, created by mitmweb's first start

LAB_LOCK_DIR="${LAB_LOCK_DIR:-$HOME/.cache/mitm-lab/locks}"  # per user, shared by every checkout

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

load_env() {
  [ -f "$REPO_ROOT/.env" ] || die ".env not found (cp .env.example .env, then fill it in)"
  set -a
  # shellcheck disable=SC1091
  . "$REPO_ROOT/.env"
  set +a
}

# require_env NAME... : fail fast, naming every missing secret.
require_env() {
  local missing="" name
  for name in "$@"; do
    [ -n "${!name:-}" ] || missing="$missing $name"
  done
  [ -z "$missing" ] || die "missing secrets in .env:$missing"
}

# The Mac's address on the default-route interface.
lan_ip() {
  local iface ip
  iface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')"
  ip="$(ipconfig getifaddr "$iface" 2>/dev/null)" || true
  [ -n "$ip" ] || die "could not find the Mac's LAN IP"
  echo "$ip"
}

lan_proxy_base() { echo "http://$(lan_ip):$LAB_PORT"; }

# device_field DEVICE-NAME FIELD : a field of a named Target Device, empty if unset.
device_field() {
  command -v jq >/dev/null || die "jq is required (brew install jq)"
  jq -e --arg n "$1" 'has($n)' "$DEVICES_FILE" >/dev/null \
    || die "unknown device '$1'. Known: $(jq -r 'keys | join(", ")' "$DEVICES_FILE")"
  jq -r --arg n "$1" --arg f "$2" '.[$n][$f] // empty' "$DEVICES_FILE"
}

# Percent-encode one value completely, for ECP query parameters.
uri_encode() { jq -rn --arg v "$1" '$v | @uri'; }

# rce_device_name DEVICE-NAME : the rce Device Name of a Cloud Device in devices.json, empty
# for a Physical Device. The rce CLI (~/projects/roku-rce) does everything RCE for the lab;
# `rce device resolve` checks the name locally, for free, before anything is billed.
rce_device_name() {
  local name
  name="$(device_field "$1" rce_device_name)"
  if [ -n "$name" ]; then
    command -v rce >/dev/null || die "Cloud Devices need the rce CLI on PATH (~/projects/roku-rce: ./install.sh)"
    rce device resolve "$name" >/dev/null \
      || die "rce does not know the Device Name '$name' of '$1': see rce device list"
  fi
  echo "$name"
}
