#!/usr/bin/env bash
# The roxy CLI and its install, run as commands (Seam C): a temp settings root, a temp
# HOME, a fake mitmweb on a local port, and fakes on PATH for curl (cloudflared's metrics,
# ECP), rce, and the Mac's network commands. No lab, no device, no network, no real settings.
# proxy/tests/test_lab_session.py covers the Lab Session (status, Scenarios, flows) at
# LabSession's interface; this keeps one smoke check per subcommand.
# Usage: scripts/tests/roxy.sh   (run by scripts/check)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
ROXY="$REPO/bin/roxy"
TMP="$(mktemp -d)"
mitmweb_pid=""
trap '[ -z "$mitmweb_pid" ] || kill "$mitmweb_pid"; rm -rf "$TMP"' EXIT
export LAB_LOCK_DIR="$TMP/locks" ROXY_CONFIG_DIR="$TMP/settings" XDG_DATA_HOME="$TMP/data" ROXY_OUT_DIR="$TMP/out"
unset LAB_LOCK_TOKEN LAB_LOCK_WAIT LAB_LOCK_OWNER MITMWEB_PASSWORD LAB_SECRET

fail() { echo "FAIL: $*" >&2; exit 1; }

# The settings root, seeded from the examples, with a mitmweb password and a tunnel secret.
mkdir -p "$ROXY_CONFIG_DIR"
cp -R "$REPO/settings.example/." "$ROXY_CONFIG_DIR"
sed -i.bak -e 's/^MITMWEB_PASSWORD=.*/MITMWEB_PASSWORD=test-password/' \
  -e 's/^LAB_SECRET=.*/LAB_SECRET=test-secret/' "$ROXY_CONFIG_DIR/secrets.env"

# Fakes on PATH. curl logs the URL of each call to $CURL_LOG.urls and answers for
# cloudflared's metrics (FAKE_TUNNEL_HOST set: a tunnel is up) and ECP; with http_proxy
# set it fails as through a dead proxy, unless the call has --noproxy. rce logs one line
# of shell-quoted arguments per call.
# uv stands in for `uv run mitmweb ...` (roxy start): it logs one argument per line to
# $UV_LOG and, as mitmweb does, creates the file it saves the session to. Any other uv
# command (proxy/cli.py runs Python) goes to the real uv.
# route and ipconfig give the Mac the LAN IP 192.0.2.10.
export CURL_LOG="$TMP/curl.log" RCE_LOG="$TMP/rce.log" UV_LOG="$TMP/uv.log" REAL_UV="$(command -v uv)"
mkdir -p "$TMP/bin"
cat > "$TMP/bin/curl" <<'EOF'
#!/usr/bin/env bash
url="" proxy="${http_proxy:-}"
for a in "$@"; do
  case "$a" in http://*|https://*) url="$a" ;; --noproxy) proxy="" ;; esac
done
echo "$url" >> "$CURL_LOG.urls"
[ -z "$proxy" ] || { echo "curl: (7) Failed to connect to the proxy $proxy" >&2; exit 7; }
case "$url" in
  */quicktunnel) [ -n "${FAKE_TUNNEL_HOST:-}" ] || { echo "curl: (7) Failed to connect" >&2; exit 7; }
    printf '{"hostname": "%s"}\n' "$FAKE_TUNNEL_HOST" ;;
  # A device whose ECP is "limited" refuses exit-app (and keypresses) but still launches.
  *:8060/exit-app/*) [ -z "${FAKE_ECP_LIMITED:-}" ] \
    || { echo "curl: (22) The requested URL returned error: 403" >&2; exit 22; } ;;
  # A Roku in developer mode, unless FAKE_ECP_DOWN is set: then it does not answer.
  *:8060/query/device-info) [ -z "${FAKE_ECP_DOWN:-}" ] || { echo "curl: (28) Connection timed out" >&2; exit 28; }
    printf '<device-info><model-name>Roku Ultra</model-name><developer-enabled>true</developer-enabled></device-info>\n' ;;
esac
EOF
cat > "$TMP/bin/rce" <<'EOF'
#!/usr/bin/env bash
printf '%q ' "$@" >> "$RCE_LOG"
echo >> "$RCE_LOG"
EOF
cat > "$TMP/bin/uv" <<'EOF'
#!/usr/bin/env bash
[ "${1:-} ${2:-}" = "run mitmweb" ] || exec "$REAL_UV" "$@"
printf '%s\n' "$@" > "$UV_LOG"
session="$(sed -n 's/^save_stream_file=//p' "$UV_LOG")"
[ -z "$session" ] || touch "$session"
EOF
printf '#!/usr/bin/env bash\necho "  interface: en0"\n' > "$TMP/bin/route"
printf '#!/usr/bin/env bash\necho 192.0.2.10\n' > "$TMP/bin/ipconfig"
chmod +x "$TMP/bin/"*
export PATH="$TMP/bin:$PATH"

# The fake mitmweb, on a free local port: signed in with test-password, it answers
# options.json from $FAKE_OPTIONS, saves each options PUT's body to $FAKE_OPTIONS.put, and
# has no flows. roxy runs against a port nothing listens on (the lab down) unless lab_up.
export FAKE_OPTIONS="$TMP/options.json"
"$REAL_UV" run --quiet --project "$REPO/proxy" python - "$TMP/mitmweb.port" <<'EOF' &
import os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

OPTIONS = os.environ["FAKE_OPTIONS"]


class Mitmweb(BaseHTTPRequestHandler):
    def do_GET(self):
        self.answer(lambda: open(OPTIONS, "rb").read() if self.path == "/options.json" else b"")

    def do_PUT(self):
        def save():
            with open(OPTIONS + ".put", "wb") as f:
                f.write(self.rfile.read(int(self.headers["Content-Length"])))
            return b""
        self.answer(save)

    def answer(self, body):
        signed_in = self.headers.get("Authorization") == "Bearer test-password"
        body = body() if signed_in else b""
        self.send_response(200 if signed_in else 403)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), Mitmweb)
with open(sys.argv[1] + ".tmp", "w") as f:
    f.write(str(server.server_port))
os.rename(sys.argv[1] + ".tmp", sys.argv[1])
server.serve_forever()
EOF
mitmweb_pid=$!
until [ -s "$TMP/mitmweb.port" ]; do sleep 0.1; done
MITMWEB_PORT="$(cat "$TMP/mitmweb.port")"
export LAB_WEB_PORT="$("$REAL_UV" run --quiet --project "$REPO/proxy" python -c \
  'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
# lab_up APP SCENARIOS COMMAND... : run COMMAND with the fake mitmweb up, App Profile APP
# loaded and SCENARIOS active (comma-separated, '' for none), not in CA Routing, with the
# lab's own Scenarios in $LAB_SCENARIOS.
LAB_SCENARIOS="$REPO/proxy/scenarios"
lab_up() {
  printf '{"lab_app": {"value": "%s"}, "lab_scenario": {"value": "%s"}, "lab_ca_routing": {"value": false}, "lab_proxy_routing_port": {"value": 8090}, "lab_scenarios_dir": {"value": "%s"}}' \
    "$1" "$2" "$LAB_SCENARIOS" > "$FAKE_OPTIONS"
  shift 2
  LAB_WEB_PORT="$MITMWEB_PORT" "$@"
}

# --help works for roxy and every subcommand, on stdout; an unknown subcommand is refused.
for args in "" start status scenario launch flows export console app device; do
  # shellcheck disable=SC2086
  out="$("$ROXY" $args --help)" || fail "roxy $args --help exited non-zero"
  case "$out" in *"usage: roxy ${args:-}"*) ;; *) fail "roxy $args --help printed: $out" ;; esac
done
"$ROXY" >/dev/null 2>&1 && fail "roxy with no subcommand exited 0"
if err="$("$ROXY" explode 2>&1)"; then fail "roxy explode exited 0"; fi
case "$err" in *"unknown subcommand 'explode'"*) ;; *) fail "roxy explode said: $err" ;; esac
"$ROXY" scenario explode >/dev/null 2>&1 && fail "roxy scenario explode exited 0"
echo "ok: --help for roxy and every subcommand; unknown subcommands refused"

# status: the lab down says so, and exits 1.
if out="$("$ROXY" status 2>&1)"; then fail "status exited 0 with the lab down: $out"; fi
case "$out" in *"lab: down"*) ;; *) fail "status with the lab down said: $out" ;; esac
echo "ok: status says when the lab is down"

# status: the lab up (signed in) reports the Proxy IP, the Proxy Bases and the active Scenarios,
# each with its rules and the flows each acted on (none: the fake mitmweb has no flows). The
# public Proxy Base shows its secret segment as <secret>: the secret is nowhere in the output.
out="$(FAKE_TUNNEL_HOST=tunnel.example lab_up "" json-503,hls-404 "$ROXY" status)" \
  || fail "status with the lab up exited non-zero: $out"
want="lab: up (mitmweb UI http://127.0.0.1:$MITMWEB_PORT)
Proxy IP:          192.0.2.10  (for an app's debug proxy setting)
LAN Proxy Bases:   http://192.0.2.10:8080  http://192.0.2.10:8888  (each takes the / and /; forms)
Proxy Routing:     192.0.2.10:8090  (a Proxied Device's HTTP proxy)
Public Proxy Base: https://tunnel.example/<secret>
App Profile:       none
Scenarios:         json-503  (lab)
                     httpbin json fails  0 flows  (acted on nothing yet)
                   hls-404  (lab)
                     mux master playlist missing  0 flows  (acted on nothing yet)"
[ "$out" = "$want" ] || fail "status with the lab up said:
$out
not:
$want"
out="$(FAKE_TUNNEL_HOST=tunnel.example lab_up "" "" "$ROXY" status --show-secret)" || fail "status --show-secret: $out"
case "$out" in *"Public Proxy Base: https://tunnel.example/test-secret"$'\n'*) ;; *) fail "status --show-secret does not show the secret:
$out" ;; esac
out="$("$ROXY" status --help)"
case "$out" in *"--show-secret"*"secret"*) ;; *) fail "status --help does not describe --show-secret: $out" ;; esac
# The Mac's proxies pointed at a dead proxy (as at the lab's Proxy Routing listener): roxy
# still reaches mitmweb and cloudflared's metrics on 127.0.0.1.
out="$(http_proxy=http://127.0.0.1:9 FAKE_TUNNEL_HOST=tunnel.example lab_up "" "" "$ROXY" status)" \
  || fail "status with http_proxy set exited non-zero: $out"
case "$out" in *"Public Proxy Base: https://tunnel.example/<secret>"*) ;; *) fail "status with http_proxy set lost the tunnel:
$out" ;; esac
out="$(lab_up "" "" "$ROXY" status)" || fail "status without a tunnel or Scenario exited non-zero: $out"
for want in "Public Proxy Base: none" "Scenarios:         none"; do
  case "$out" in *"$want"*) ;; *) fail "status without a tunnel or Scenario lacks '$want':
$out" ;; esac
done
out="$(lab_up "" json-503 "$ROXY" status --since 176363286012345)" || fail "status --since a run id: $out"
case "$out" in *"httpbin json fails  0 flows"*) ;; *) fail "status --since a run id lacks the rule: $out" ;; esac
if err="$(lab_up "" "" "$ROXY" status --since yesterday 2>&1)"; then fail "status took --since yesterday"; fi
case "$err" in *"--since"*"yesterday"*) ;; *) fail "status --since yesterday said: $err" ;; esac
echo "ok: status reports the Proxy IP, the Proxy Bases, the Proxy Routing address (the secret only with --show-secret) and the Scenarios in order, with their rules"

# status --json: the lab down says so on stderr; the lab up prints its state as one JSON object.
if err="$("$ROXY" status --json 2>&1 >/dev/null)"; then fail "status --json exited 0 with the lab down"; fi
case "$err" in *"lab: down"*) ;; *) fail "status --json with the lab down said: $err" ;; esac
# App Profile app-x, with no Scenarios of its own: the active ones are the lab's.
mkdir -p "$ROXY_CONFIG_DIR/apps/app-x/scenarios"
echo '{"repo": "/repos/example", "origin_allowlist": []}' > "$ROXY_CONFIG_DIR/apps/app-x/profile.json"
# With a tunnel up: the object holds no secret (compared whole below).
out="$(FAKE_TUNNEL_HOST=tunnel.example lab_up app-x json-503,hls-404 "$ROXY" status --json)" \
  || fail "status --json with the lab up: $out"
rm -r "$ROXY_CONFIG_DIR/apps/app-x"
want="{\"app\": \"app-x\", \"scenarios\": [\"json-503\", \"hls-404\"], \"ca_routing\": false, \"proxy_routing_port\": 8090, \"scenarios_dir\": \"$LAB_SCENARIOS\", \"rules\": [{\"scenario\": \"json-503\", \"rule\": \"httpbin json fails\", \"flows\": 0}, {\"scenario\": \"hls-404\", \"rule\": \"mux master playlist missing\", \"flows\": 0}]}"
[ "$out" = "$want" ] || fail "status --json with the lab up said:
$out
not:
$want"
echo "ok: status --json says when the lab is down, and prints the lab's state"

# status --json --show-secret: refused, as --json carries no Proxy Base to show.
if err="$(lab_up "" "" "$ROXY" status --json --show-secret 2>&1)"; then fail "status --json --show-secret exited 0: $err"; fi
case "$err" in *"--json carries no Proxy Base"*"usage: roxy status"*) ;; *) fail "status --json --show-secret said: $err" ;; esac
echo "ok: status refuses --json with --show-secret"

# The loaded App Profile renamed or deleted since roxy start: status says so on its line and
# still lists the Scenarios, and exits 0, as for a Scenario it cannot read; so does --json.
out="$(lab_up app-gone json-503 "$ROXY" status)" || fail "status with its App Profile gone exited non-zero: $out"
case "$out" in *"App Profile:       app-gone  (cannot read it: "*"app-gone"*) ;; *) fail "status with its App Profile gone does not say so:
$out" ;; esac
case "$out" in *"Scenarios:         json-503  (lab)"$'\n'"                     httpbin json fails  0 flows"*) ;; *) fail "status with its App Profile gone lacks the Scenarios:
$out" ;; esac
out="$(lab_up app-gone json-503 "$ROXY" status --json)" || fail "status --json with its App Profile gone exited non-zero: $out"
[ "$(jq -c '[.app, .rules[].rule]' <<< "$out")" = '["app-gone","httpbin json fails"]' ] \
  || fail "status --json with its App Profile gone said: $out"
echo "ok: status reports a loaded App Profile it cannot read, and exits 0"

# scenario list: the lab's own Scenarios, with or without a running lab.
source_of() { awk -v n="$1" '$1 == n {$1 = ""; sub(/^ +/, ""); print}' <<< "$2"; }
out="$("$ROXY" scenario list)" || fail "scenario list: $out"
for want in json-503 hls-404; do [ "$(source_of "$want" "$out")" = lab ] || fail "scenario list lacks $want from the lab: $out"; done
case "$out" in *"App Profile: none"*) ;; *) fail "scenario list without a profile does not say so: $out" ;; esac
echo "ok: scenario list shows the lab's Scenarios"

# scenario set, add, remove and clear switch the running lab's active Scenarios through
# mitmweb's options API, and print them.
scenario_sent() { jq -c . "$FAKE_OPTIONS.put"; }
out="$(lab_up "" "" "$ROXY" scenario set json-503)" || fail "scenario set: $out"
[ "$out" = scenario=json-503 ] || fail "scenario set said: $out"
[ "$(scenario_sent)" = '{"lab_scenario":"json-503"}' ] || fail "scenario set sent $(scenario_sent)"
out="$(lab_up "" image-404 "$ROXY" scenario set json-503 hls-404)" || fail "scenario set of two: $out"
[ "$out" = scenario=json-503,hls-404 ] || fail "scenario set of two said: $out"
[ "$(scenario_sent)" = '{"lab_scenario":"json-503,hls-404"}' ] || fail "scenario set of two sent $(scenario_sent)"
out="$(lab_up "" json-503 "$ROXY" scenario add hls-404)" || fail "scenario add: $out"
[ "$out" = scenario=json-503,hls-404 ] || fail "scenario add said: $out"
[ "$(scenario_sent)" = '{"lab_scenario":"json-503,hls-404"}' ] || fail "scenario add sent $(scenario_sent)"
out="$(lab_up "" json-503,hls-404 "$ROXY" scenario remove json-503)" || fail "scenario remove: $out"
[ "$out" = scenario=hls-404 ] || fail "scenario remove said: $out"
[ "$(scenario_sent)" = '{"lab_scenario":"hls-404"}' ] || fail "scenario remove sent $(scenario_sent)"
if err="$(lab_up "" json-503 "$ROXY" scenario remove hls-404 2>&1)"; then fail "scenario remove of an inactive one exited 0"; fi
case "$err" in "error: 'hls-404' is not active"*) ;; *) fail "scenario remove of an inactive one said: $err" ;; esac
"$ROXY" scenario set >/dev/null 2>&1 && fail "scenario set with no name exited 0"
out="$(lab_up "" json-503 "$ROXY" scenario clear)" || fail "scenario clear: $out"
[ "$(scenario_sent)" = '{"lab_scenario":""}' ] || fail "scenario clear sent $(scenario_sent)"
[ "$out" = scenario=none ] || fail "scenario clear said: $out"
if err="$("$ROXY" scenario set json-503 2>&1)"; then fail "scenario set with the lab down exited 0"; fi
case "$err" in *"lab: down"*"roxy start"*) ;; *) fail "scenario set with the lab down said: $err" ;; esac
echo "ok: scenario set, add, remove and clear switch the running lab's Scenarios"

# launch on a Physical Device: ECP on the LAN with the LAN Proxy Base and the user's params
# (separator=/; asks the Lab Apps for Charles-style Prefixed URLs).
: > "$CURL_LOG.urls"
out="$("$ROXY" launch "Living Room" case=json_get "note=a b" 'separator=/;')" || fail "launch on a Physical Device: $out"
run="$(sed -n 's/^run=//p' <<< "$out")"
[ -n "$run" ] || fail "launch printed no run id: $out"
want="http://192.0.2.54:8060/launch/dev?proxyBase=http%3A%2F%2F192.0.2.10%3A8080&case=json_get&note=a%20b&separator=%2F%3B&run=$run"
grep -qxF "$want" "$CURL_LOG.urls" || fail "launch on a Physical Device did not ask for
$want
curl asked for:
$(cat "$CURL_LOG.urls")"
echo "ok: launch sends the LAN Proxy Base to a Physical Device"

# launch --scenario, repeated, sets those Scenarios in that order before it launches.
out="$(lab_up "" "" "$ROXY" launch --scenario json-503 --scenario hls-404 "Living Room" case=json_get)" \
  || fail "launch with two --scenario: $out"
[ "$(scenario_sent)" = '{"lab_scenario":"json-503,hls-404"}' ] || fail "launch with two --scenario sent $(scenario_sent)"
echo "ok: launch sets each --scenario, in order"

# A device with ECP set to limited refuses exit-app: launch still launches, without curl's noise.
: > "$CURL_LOG.urls"
out="$(FAKE_ECP_LIMITED=1 "$ROXY" launch "Living Room" case=json_get 2>&1)" \
  || fail "launch on a device with limited ECP: $out"
grep -q '^run=' <<< "$out" || fail "launch on a device with limited ECP printed no run id: $out"
grep -q '/launch/dev?' "$CURL_LOG.urls" || fail "launch on a device with limited ECP did not launch"
case "$out" in *"curl:"*) fail "launch printed curl's refused exit-app: $out" ;; esac
echo "ok: launch on a device with limited ECP launches quietly"

# launch on a Cloud Device: through rce, with the running tunnel's public Proxy Base plus the
# slug. What it prints (here with a Scenario set first) never holds the secret.
: > "$RCE_LOG"
out="$(FAKE_TUNNEL_HOST=tunnel.example lab_up "" "" "$ROXY" launch --scenario json-503 "Cloud Device" \
  case=json_get 'separator=/;' 2>&1)" || fail "launch on a Cloud Device: $out"
case "$out" in *test-secret*) fail "launch on a Cloud Device printed the secret:
$out" ;; esac
run="$(sed -n 's/^run=//p' <<< "$out")"
want="$(printf '%q ' launch player --param "proxyBase=https://tunnel.example/test-secret/cloud-device" \
  --param case=json_get --param 'separator=/;' --param "run=$run")"
grep -qxF "$want" "$RCE_LOG" || fail "launch on a Cloud Device did not run
$want
rce ran:
$(cat "$RCE_LOG")"
echo "ok: launch sends the public Proxy Base plus the device slug to a Cloud Device"

# Without a tunnel, a Cloud Device launch stops before launching, naming the fix.
: > "$RCE_LOG"
if err="$("$ROXY" launch "Cloud Device" case=json_get 2>&1)"; then fail "launch on a Cloud Device without a tunnel exited 0"; fi
case "$err" in *"roxy start --tunnel"*) ;; *) fail "launch without a tunnel said: $err" ;; esac
grep -q '^launch ' "$RCE_LOG" && fail "launch without a tunnel still launched: $(cat "$RCE_LOG")"
# A launch param that is not key=value is refused.
"$ROXY" launch "Living Room" json_get >/dev/null 2>&1 && fail "launch took a param without ="
echo "ok: launch refuses a Cloud Device without a tunnel, and a param without ="

# console on a Cloud Device streams through rce console, by its rce Device Name.
: > "$RCE_LOG"
"$ROXY" console "Cloud Device" >/dev/null || fail "console on a Cloud Device exited non-zero"
[ "$(tail -1 "$RCE_LOG")" = "$(printf '%q ' console player)" ] || fail "console on a Cloud Device ran: $(cat "$RCE_LOG")"
echo "ok: console on a Cloud Device goes through rce console"

# A Proxied Device is no Roku: deploy, launch and console refuse it, naming it, before any
# call to a device (curl) or to rce. Phone, from the examples, is "kind": "proxied"; Old Phone
# is "kind": "mobile", as a 0.2.0 Settings Root has it.
mkdir -p "$TMP/proxied-app"
printf 'title=proxied test\n' > "$TMP/proxied-app/manifest"
jq '. + {"Old Phone": {"ip": "192.0.2.61", "kind": "mobile"}}' "$ROXY_CONFIG_DIR/devices.json" > "$TMP/devices.json"
mv "$TMP/devices.json" "$ROXY_CONFIG_DIR/devices.json"
refuses_proxied() {
  local name="$1" err
  shift
  : > "$CURL_LOG.urls"
  : > "$RCE_LOG"
  if err="$("$@" 2>&1)"; then fail "$* took a Proxied Device: $err"; fi
  case "$err" in *"'$name'"*"not a Roku"*) ;; *) fail "$* refused a Proxied Device saying: $err" ;; esac
  [ ! -s "$CURL_LOG.urls" ] && [ ! -s "$RCE_LOG" ] || fail "$* called a device or rce: $(cat "$CURL_LOG.urls" "$RCE_LOG")"
}
for device in Phone "Old Phone"; do
  refuses_proxied "$device" "$REPO/scripts/deploy" "$device" "$TMP/proxied-app"
  refuses_proxied "$device" "$ROXY" launch "$device" case=json_get
  refuses_proxied "$device" "$ROXY" console "$device"
done
echo "ok: deploy, launch and console refuse a Proxied Device, kind proxied or mobile, before any device or rce call"

# device add, list and remove, with no terminal: one smoke check per kind of Target Device.
# proxy/tests/test_settings_root.py covers validation, warnings and lan_subnets at
# SettingsRoot's interface. Each change says what it did, then to restart a running lab.
RESTART_HINT="restart the lab if it is running (roxy start), to use the change"
device() { "$ROXY" device "$@" < /dev/null; }
# A Roku by its IP, outside lan_subnets (192.0.2.0/24): ECP is asked, never through a proxy.
: > "$CURL_LOG.urls"
out="$(http_proxy=http://127.0.0.1:9 device add Den --ip 198.51.100.7 2>&1)" || fail "device add Den: $out"
[ "$out" = "registered 'Den' (198.51.100.7) as a Physical Device
allowed 198.51.100.7/32 in lan_subnets
$RESTART_HINT" ] || fail "device add Den said: $out"
grep -qx "http://198.51.100.7:8060/query/device-info" "$CURL_LOG.urls" || fail "device add Den did not ask ECP: $(cat "$CURL_LOG.urls")"
[ "$(jq -c .Den "$ROXY_CONFIG_DIR/devices.json")" = '{"ip":"198.51.100.7"}' ] || fail "device add Den wrote: $(cat "$ROXY_CONFIG_DIR/devices.json")"
jq -e '.lan_subnets == ["192.0.2.0/24", "198.51.100.7/32"] and .grid_devices.physical == "Living Room"' \
  "$ROXY_CONFIG_DIR/settings.json" >/dev/null || fail "device add Den left settings.json as: $(cat "$ROXY_CONFIG_DIR/settings.json")"
# A Proxied Device; a Roku that does not answer ECP, registered with a warning on stderr;
# a Cloud Device, checked with rce device resolve, its slug made from its name.
out="$(device add Tablet --ip 192.0.2.80 --proxied)" || fail "device add Tablet --proxied: $out"
[ "$out" = "registered 'Tablet' (192.0.2.80) as a Proxied Device
$RESTART_HINT" ] || fail "device add Tablet --proxied said: $out"
err="$(FAKE_ECP_DOWN=1 device add Attic --ip 192.0.2.81 2>&1 >/dev/null)" || fail "device add Attic, off: $err"
[ "$err" = "warning: Attic (192.0.2.81) did not answer ECP: registered anyway (is it on, and on this network?)" ] \
  || fail "device add of a Roku that does not answer warned: $err"
: > "$RCE_LOG"
out="$(device add "Office Stick" --rce office-player)" || fail "device add Office Stick --rce: $out"
[ "$out" = "registered 'Office Stick' (rce office-player, slug office-stick) as a Cloud Device
$RESTART_HINT" ] || fail "device add Office Stick --rce said: $out"
[ "$(cat "$RCE_LOG")" = "$(printf '%q ' device resolve office-player)" ] || fail "device add --rce ran: $(cat "$RCE_LOG")"
# list: each device with its address or rce Device Name, and its kind.
out="$(device list)" || fail "device list: $out"
for want in "Den  *198.51.100.7  *Physical Device" "Tablet  *192.0.2.80  *Proxied Device" \
  "Office Stick  *rce office-player, slug office-stick  *Cloud Device" "Old Phone  *192.0.2.61  *Proxied Device"; do
  grep -qx "$want" <<< "$out" || fail "device list lacks '$want':
$out"
done
# remove drops the /32 add allowed; refusals are errors, and change nothing.
out="$(device remove Den)" || fail "device remove Den: $out"
[ "$out" = "removed 'Den'
dropped 198.51.100.7/32 from lan_subnets
$RESTART_HINT" ] || fail "device remove Den said: $out"
jq -e '.lan_subnets == ["192.0.2.0/24"]' "$ROXY_CONFIG_DIR/settings.json" >/dev/null || fail "device remove Den left lan_subnets: $(cat "$ROXY_CONFIG_DIR/settings.json")"
before="$(cat "$ROXY_CONFIG_DIR/devices.json")"
refuses_device() {
  local want="$1" err
  shift
  if err="$(device "$@" 2>&1)"; then fail "device $* exited 0: $err"; fi
  case "$err" in *"$want"*) ;; *) fail "device $* said: $err" ;; esac
  [ "$(cat "$ROXY_CONFIG_DIR/devices.json")" = "$before" ] || fail "device $* changed devices.json"
}
refuses_device "error: the device 'Tablet' already exists" add Tablet --ip 192.0.2.82
refuses_device "error: not an IP address: '192.0.2'" add Hall --ip 192.0.2
refuses_device "error: unknown device 'Den'" remove Den
refuses_device "--proxied goes with --ip" add Hall --rce hall-player --proxied
refuses_device "--slug goes with --rce" add Hall --ip 192.0.2.82 --slug hall
refuses_device "usage: roxy device" add Hall
refuses_device "usage: roxy device" explode
case "$(device add --help)" in "usage: roxy device add NAME (--ip IP"*) ;; *) fail "device add --help printed: $(device add --help)" ;; esac
echo "ok: device add, list and remove each kind of Target Device, keeping lan_subnets in step"

# App Profiles, in a temp app repo: one smoke check per command. proxy/tests/test_app_profiles.py
# covers resolution, refusals and clashes at AppProfiles' interface.
# A git hook (scripts/check from the pre-commit hook) exports the checkout's GIT_DIR, which
# would point git in the temp repo at the roxy repo.
unset GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE
repo_a="$TMP/repos/app-a"
git init -q "$repo_a"
mkdir -p "$repo_a/src/nested"
root_a="$(cd "$repo_a" && pwd -P)"
scenarios_a="$ROXY_CONFIG_DIR/apps/app-a/scenarios"

# app new, run in a subfolder of an app's repo, records the repo's git root; app list shows it;
# a refused app new says why, as error: ..., and exits 1.
out="$(cd "$repo_a/src/nested" && "$ROXY" app new app-a)" || fail "app new app-a: $out"
case "$out" in "App Profile 'app-a' for $root_a"*) ;; *) fail "app new app-a said: $out" ;; esac
[ "$("$ROXY" app list | awk '$1 == "app-a" {print $2}')" = "$root_a" ] || fail "app list: $("$ROXY" app list)"
if err="$(cd "$repo_a" && "$ROXY" app new app-a 2>&1)"; then fail "app new took the existing name app-a"; fi
case "$err" in "error: the App Profile 'app-a' already exists"*) ;; *) fail "app new of an existing name said: $err" ;; esac
echo "ok: app new records the repo's git root, app list shows it, and a refusal is an error"

# roxy start loads the profile whose repo holds the current folder, naming it and its repo.
start_in() { local dir="$1"; shift; rm -f "$UV_LOG"; (cd "$dir" && "$ROXY" start "$@" 2>&1); }
started_app() { sed -n 's/^lab_app=//p' "$UV_LOG"; }
out="$(start_in "$repo_a/src/nested")" || fail "start in app-a's repo: $out"
[ "$(started_app)" = app-a ] || fail "start in a folder of app-a's repo loaded '$(started_app)'"
case "$out" in *"App Profile:       app-a  ($root_a)"*) ;; *) fail "start in app-a's repo does not say so: $out" ;; esac
echo "ok: start loads the current repo's App Profile"

# start --tunnel prints the public Proxy Base with its secret segment as <secret>: the secret
# is nowhere in what it prints. A fake cloudflared stands in for the tunnel; its log goes to
# ROXY_OUT_DIR, never to the checkout's out/cloudflared.log (a live tunnel's log, which may
# grow meanwhile but must not appear or shrink).
printf '#!/usr/bin/env bash\n' > "$TMP/bin/cloudflared"
chmod +x "$TMP/bin/cloudflared"
checkout_log_size() { if [ -e "$REPO/out/cloudflared.log" ]; then wc -c < "$REPO/out/cloudflared.log"; else echo -1; fi; }
before="$(checkout_log_size)"
out="$(FAKE_TUNNEL_HOST=tunnel.example start_in "$TMP" --tunnel)" \
  || fail "start --tunnel: $out"
after="$(checkout_log_size)"
[ -e "$ROXY_OUT_DIR/cloudflared.log" ] || fail "start --tunnel did not log to ROXY_OUT_DIR"
if [ "$before" -lt 0 ]; then [ "$after" -lt 0 ]; else [ "$after" -ge "$before" ]; fi \
  || fail "start --tunnel touched the checkout's out/cloudflared.log (size $before, then $after)"
case "$out" in *"Public Proxy Base: https://tunnel.example/<secret>  "*) ;; *) fail "start --tunnel lacks the public Proxy Base:
$out" ;; esac
case "$out" in *test-secret*) fail "start --tunnel printed the secret:
$out" ;; esac
echo "ok: start --tunnel prints the public Proxy Base without its secret"

# The session is saved in the user data directory, under the loaded App Profile's name.
saved="$(ls "$XDG_DATA_HOME/roxy/captures/app-a/"*.mitm 2>/dev/null)" || true
[ -n "$saved" ] || fail "start with app-a saved no session under captures/app-a: $(find "$XDG_DATA_HOME" -name '*.mitm')"
echo "ok: a session is saved under the App Profile's name"

# scenario list --app shows the profile's Scenarios beside the lab's own, each once with its
# source, and a name in both once, refused; that name fails the start, naming both sources.
touch "$scenarios_a/empty-catalog.toml"
printf '[[rule]]\nname = "mine"\nfilter = "~u /json"\nstatus = 500\n' > "$scenarios_a/json-503.toml"
out="$(cd "$TMP" && "$ROXY" scenario list --app app-a)" || fail "scenario list --app app-a: $out"
case "$out" in "App Profile: app-a"*) ;; *) fail "scenario list --app app-a does not name app-a: $out" ;; esac
[ "$(source_of empty-catalog "$out")" = "App Profile app-a" ] || fail "scenario list lacks app-a's empty-catalog: $out"
[ "$(source_of hls-404 "$out")" = lab ] || fail "scenario list lacks the lab's hls-404: $out"
[ "$(source_of json-503 "$out")" = "refused: in both (rename the profile's)" ] || fail "scenario list does not refuse json-503 once: $out"
if out="$(start_in "$repo_a")"; then fail "start with a clashing Scenario name exited 0"; fi
case "$out" in "error: "*"json-503"*"lab"*"app-a"*) ;; *) fail "the clash refusal does not name the Scenario and both sources: $out" ;; esac
[ ! -e "$UV_LOG" ] || fail "start with a clashing Scenario name started mitmweb"
rm "$scenarios_a/json-503.toml"
echo "ok: scenario list shows each Scenario once by source, a clash as refused, and the clash fails the start"

# status names the running lab's App Profile, and where each active Scenario came from.
out="$(lab_up app-a empty-catalog,json-503 "$ROXY" status)" || fail "status with app-a: $out"
for want in "App Profile:       app-a" "Scenarios:         empty-catalog  (App Profile app-a)
                   json-503  (lab)"; do
  case "$out" in *"$want"*) ;; *) fail "status with app-a lacks '$want':
$out" ;; esac
done
printf '[[rule]]\nname = "no filter"\nstatus = 500\n' > "$scenarios_a/broken.toml"
out="$(lab_up app-a broken "$ROXY" status)" || fail "status with a Scenario that no longer loads exited non-zero: $out"
case "$out" in *"broken  (App Profile app-a)
                     cannot read its rules: rule 'no filter': needs a filter expression"*) ;;
  *) fail "status with a Scenario that no longer loads does not say why: $out" ;; esac
rm "$scenarios_a/broken.toml"
echo "ok: status names the App Profile and each active Scenario's source, or why its rules do not load"

# flows --json: the lab down says so; the lab up takes every option and prints a JSON array
# (here empty: the fake mitmweb has no flows). test_lab_session.py covers the flows themselves.
if err="$("$ROXY" flows --json 2>&1)"; then fail "flows --json exited 0 with the lab down: $err"; fi
case "$err" in *"lab: down"*"roxy start"*) ;; *) fail "flows --json with the lab down said: $err" ;; esac
out="$(lab_up "" "" "$ROXY" flows --json --filter '~u /json' --since 176363286012345 --limit 1)" \
  || fail "flows --json with every option: $out"
[ "$out" = "[]" ] || fail "flows --json with no flows printed: $out"
if err="$(lab_up "" "" "$ROXY" flows --json --since yesterday 2>&1)"; then fail "flows --json took --since yesterday"; fi
case "$err" in *"--since"*"yesterday"*) ;; *) fail "flows --json --since yesterday said: $err" ;; esac
echo "ok: flows --json says when the lab is down, and takes its options"

# export --har, against its own user data directory. write_recording FILE [cut|secret] : a
# Recording of known flows, GET https://example.com/one answered 200 "first body",
# GET https://example.org/two answered 503 "second body", and a TCP flow; with cut, then
# a third flow cut short, as a running lab's Recording can end; with secret, then two
# flows holding Prefixed URLs with the lab secret (test-secret), in the URL, a header, a
# text body and a binary one.
export_data="$TMP/export-data"
write_recording() {
  mkdir -p "$(dirname "$1")"
  "$REAL_UV" run --quiet --project "$REPO/proxy" python - "$@" <<'EOF'
import sys
from io import BytesIO
from mitmproxy import io
from mitmproxy.test import tflow, tutils


def http(host, path, status, body):
    request = tutils.treq(host=host, port=443, scheme=b"https", path=path)
    return tflow.tflow(req=request, resp=tutils.tresp(status_code=status, content=body))


with open(sys.argv[1], "wb") as f:
    writer = io.FlowWriter(f)
    writer.add(http("example.com", b"/one", 200, b"first body"))
    writer.add(http("example.org", b"/two", 503, b"second body"))
    writer.add(tflow.ttcpflow())
    if sys.argv[2:] == ["cut"]:
        third = BytesIO()
        io.FlowWriter(third).add(http("example.net", b"/three", 200, b"third body"))
        f.write(third.getvalue()[: len(third.getvalue()) // 2])
    if sys.argv[2:] == ["secret"]:
        prefixed = b"https://tunnel.example/test-secret/cloud-device"
        flow = http("example.com", b"/next?from=" + prefixed, 200, b'{"next": "' + prefixed + b'/https://example.com/two"}')
        flow.request.headers["Referer"] = prefixed.decode()
        writer.add(flow)
        writer.add(http("example.com", b"/blob", 200, bytes(range(8)) * 5 + prefixed))
EOF
}
har_entries() { jq -c '[.log.entries[] | [.request.url, .response.status, .response.content.text]]' "$1"; }
want_entries='[["https://example.com/one",200,"first body"],["https://example.org/two",503,"second body"]]'

# A Recording exports to a HAR with one entry per HTTP flow: its Origin URL, status and body.
write_recording "$TMP/recordings/known.mitm"
out="$(XDG_DATA_HOME="$export_data" "$ROXY" export --har "$TMP/recordings/known.mitm" -o "$TMP/known.har")" \
  || fail "export --har of a Recording: $out"
[ "$(har_entries "$TMP/known.har")" = "$want_entries" ] || fail "export --har wrote: $(har_entries "$TMP/known.har")"
[ "$out" = "wrote $TMP/known.har (2 entries)" ] || fail "export --har said: $out"
echo "ok: export --har writes one HAR entry per HTTP flow, with its Origin URL, status and body"

# Without RECORDING, the newest Recording across every profile folder; without -o, in the
# current folder, named after the Recording.
recordings_root="$export_data/roxy/captures"
mkdir -p "$recordings_root/app-a" "$recordings_root/no-profile" "$recordings_root/app-b"
: > "$recordings_root/app-a/20261101-090000.mitm"
: > "$recordings_root/no-profile/20261102-090000.mitm"
cp "$TMP/recordings/known.mitm" "$recordings_root/app-b/20261103-090000.mitm"
touch -t 202611010900 "$recordings_root/app-a/20261101-090000.mitm"
touch -t 202611020900 "$recordings_root/no-profile/20261102-090000.mitm"
touch -t 202611030900 "$recordings_root/app-b/20261103-090000.mitm"
mkdir -p "$TMP/exports"
out="$(cd "$TMP/exports" && XDG_DATA_HOME="$export_data" "$ROXY" export --har)" || fail "export --har with no RECORDING: $out"
[ "$out" = "wrote $(cd "$TMP/exports" && pwd -P)/20261103-090000.har (2 entries)" ] || fail "export --har with no RECORDING said: $out"
[ "$(har_entries "$TMP/exports/20261103-090000.har")" = "$want_entries" ] || fail "export --har with no RECORDING exported the wrong one"
echo "ok: export --har takes the newest Recording across profile folders, and writes to the current folder"

# A running lab's Recording, its last flow cut short, exports the complete flows.
write_recording "$TMP/recordings/running.mitm" cut
out="$(XDG_DATA_HOME="$export_data" "$ROXY" export --har "$TMP/recordings/running.mitm" -o "$TMP/running.har")" \
  || fail "export --har of a Recording cut short: $out"
[ "$(har_entries "$TMP/running.har")" = "$want_entries" ] || fail "export --har of a Recording cut short wrote: $(har_entries "$TMP/running.har")"
echo "ok: export --har of a Recording still being written exports its complete flows"

# Refusals exit non-zero, say why, and write nothing: an existing FILE (kept as it was), a
# missing RECORDING, a file that is not a Recording, and no Recording at all.
# refused WANT ARGS... : export --har ARGS... in $TMP/exports exits non-zero saying WANT,
# and leaves the folder as it was.
refused() {
  local want="$1" before err
  shift
  before="$(ls "$TMP/exports")"
  if err="$(cd "$TMP/exports" && XDG_DATA_HOME="${data:-$export_data}" "$ROXY" export --har "$@" 2>&1)"; then
    fail "export --har $* exited 0: $err"
  fi
  case "$err" in *"$want"*) ;; *) fail "export --har $* said: $err" ;; esac
  [ "$(ls "$TMP/exports")" = "$before" ] || fail "export --har $* wrote $(ls "$TMP/exports")"
}
echo "someone's notes" > "$TMP/exports/taken.har"
refused "taken.har already exists" "$TMP/recordings/known.mitm" -o taken.har
[ "$(cat "$TMP/exports/taken.har")" = "someone's notes" ] || fail "export --har changed an existing FILE"
refused "no Recording at $TMP/recordings/missing.mitm" "$TMP/recordings/missing.mitm"
echo "not flows" > "$TMP/recordings/notes.txt"
refused "$TMP/recordings/notes.txt is not a mitmproxy Recording" "$TMP/recordings/notes.txt"
data="$TMP/no-data" refused "no Recordings in $TMP/no-data/roxy/captures"
echo "ok: export --har refuses an existing FILE, a missing Recording, a file that is not one, and no Recordings"

# --filter keeps only the flows a mitmproxy filter expression matches; a bad one is refused.
out="$(XDG_DATA_HOME="$export_data" "$ROXY" export --har "$TMP/recordings/known.mitm" --filter '~d example.org' -o "$TMP/filtered.har")" \
  || fail "export --har --filter: $out"
[ "$(har_entries "$TMP/filtered.har")" = '[["https://example.org/two",503,"second body"]]' ] \
  || fail "export --har --filter wrote: $(har_entries "$TMP/filtered.har")"
refused "Invalid filter expression: '~nope'" "$TMP/recordings/known.mitm" --filter '~nope'
echo "ok: export --har --filter keeps the matching flows, and refuses a bad expression"

# The lab secret becomes <secret> everywhere in the HAR: URLs, headers, text and binary bodies.
write_recording "$TMP/recordings/secret.mitm" secret
out="$(XDG_DATA_HOME="$export_data" "$ROXY" export --har "$TMP/recordings/secret.mitm" -o "$TMP/secret.har")" \
  || fail "export --har of a Recording holding the lab secret: $out"
! grep -q test-secret "$TMP/secret.har" || fail "export --har left the lab secret in the HAR: $(grep -c test-secret "$TMP/secret.har") lines"
redacted="https://tunnel.example/<secret>/cloud-device"
[ "$(jq -r '.log.entries[2].request.url' "$TMP/secret.har")" = "https://example.com/next?from=$redacted" ] \
  || fail "export --har redacted the URL as: $(jq -r '.log.entries[2].request.url' "$TMP/secret.har")"
[ "$(jq -r '.log.entries[2].response.content.text' "$TMP/secret.har")" = "{\"next\": \"$redacted/https://example.com/two\"}" ] \
  || fail "export --har redacted the text body as: $(jq -r '.log.entries[2].response.content.text' "$TMP/secret.har")"
case "$(jq -r '.log.entries[3].response.content.text | @base64d' "$TMP/secret.har")" in
  *"$redacted") ;; *) fail "export --har did not redact the binary body" ;;
esac
echo "ok: export --har replaces the lab secret with <secret> everywhere"

# What status, start and the grid print (redact_secret, scripts/lib.sh) shows the secret as
# export --har (proxy/cli.py) does: one placeholder, defined in each language.
shown="$(LAB_SECRET=test-secret bash -c '. "$1"; redact_secret "$2"' lab "$REPO/scripts/lib.sh" \
  "https://tunnel.example/test-secret/cloud-device")"
[ "$shown" = "$redacted" ] || fail "redact_secret shows $shown, export --har $redacted"
echo "ok: redact_secret and export --har show the lab secret alike"

# install, in a temp HOME with the default settings root: links roxy into ~/.local/bin and
# seeds the missing settings from the examples. Run again, it keeps every existing setting.
home="$TMP/home"
run_install() { env -u ROXY_CONFIG_DIR -u XDG_CONFIG_HOME HOME="$home" "$REPO/install.sh"; }
link="$home/.local/bin/roxy" settings="$home/.config/roxy"
out="$(run_install)" || fail "install: $out"
[ -L "$link" ] && [ "$(realpath "$link")" = "$ROXY" ] || fail "install did not link $link to $ROXY"
"$link" --help >/dev/null || fail "the linked roxy does not run"
for file in secrets.env devices.json settings.json; do
  cmp -s "$REPO/settings.example/$file" "$settings/$file" || fail "install did not seed $file from its example"
done
echo '{"Mine": {"ip": "192.0.2.99"}}' > "$settings/devices.json"
rm "$settings/settings.json"
out="$(run_install)" || fail "install, run again: $out"
[ "$(cat "$settings/devices.json")" = '{"Mine": {"ip": "192.0.2.99"}}' ] || fail "install overwrote devices.json"
cmp -s "$REPO/settings.example/settings.json" "$settings/settings.json" || fail "install did not seed the missing settings.json"
[ "$(realpath "$link")" = "$ROXY" ] || fail "install, run again, broke the link"
[ "$(git -C "$REPO" config --get core.hooksPath)" = .githooks ] || fail "install did not switch on the repo's git hooks"
echo "ok: install is idempotent, keeps existing settings and switches on the git hooks"

# A roxy at the link's place that is not a link is someone else's: install refuses, changing nothing.
rm "$link"
echo "someone else's roxy" > "$link"
if err="$(run_install 2>&1)"; then fail "install replaced a file that is not a link"; fi
case "$err" in *"$link"*) ;; *) fail "install's refusal does not name $link: $err" ;; esac
[ "$(cat "$link")" = "someone else's roxy" ] || fail "install changed $link"
echo "ok: install leaves a roxy that is not its link alone"
