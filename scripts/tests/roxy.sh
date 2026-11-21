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
export LAB_LOCK_DIR="$TMP/locks" ROXY_CONFIG_DIR="$TMP/settings" XDG_DATA_HOME="$TMP/data"
unset LAB_LOCK_TOKEN LAB_LOCK_WAIT LAB_LOCK_OWNER MITMWEB_PASSWORD LAB_SECRET

fail() { echo "FAIL: $*" >&2; exit 1; }

# The settings root, seeded from the examples, with a mitmweb password and a tunnel secret.
mkdir -p "$ROXY_CONFIG_DIR"
cp -R "$REPO/settings.example/." "$ROXY_CONFIG_DIR"
sed -i.bak -e 's/^MITMWEB_PASSWORD=.*/MITMWEB_PASSWORD=test-password/' \
  -e 's/^LAB_SECRET=.*/LAB_SECRET=test-secret/' "$ROXY_CONFIG_DIR/secrets.env"

# Fakes on PATH. curl logs the URL of each call to $CURL_LOG.urls and answers for
# cloudflared's metrics (FAKE_TUNNEL_HOST set: a tunnel is up) and ECP. rce logs one line
# of shell-quoted arguments per call.
# uv stands in for `uv run mitmweb ...` (roxy start): it logs one argument per line to
# $UV_LOG and, as mitmweb does, creates the file it saves the session to. Any other uv
# command (proxy/cli.py runs Python) goes to the real uv.
# route and ipconfig give the Mac the LAN IP 192.0.2.10.
export CURL_LOG="$TMP/curl.log" RCE_LOG="$TMP/rce.log" UV_LOG="$TMP/uv.log" REAL_UV="$(command -v uv)"
mkdir -p "$TMP/bin"
cat > "$TMP/bin/curl" <<'EOF'
#!/usr/bin/env bash
url=""
for a in "$@"; do
  case "$a" in http://*|https://*) url="$a" ;; esac
done
echo "$url" >> "$CURL_LOG.urls"
case "$url" in
  */quicktunnel) [ -n "${FAKE_TUNNEL_HOST:-}" ] || { echo "curl: (7) Failed to connect" >&2; exit 7; }
    printf '{"hostname": "%s"}\n' "$FAKE_TUNNEL_HOST" ;;
  # A device whose ECP is "limited" refuses exit-app (and keypresses) but still launches.
  *:8060/exit-app/*) [ -z "${FAKE_ECP_LIMITED:-}" ] \
    || { echo "curl: (22) The requested URL returned error: 403" >&2; exit 22; } ;;
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
  printf '{"lab_app": {"value": "%s"}, "lab_scenario": {"value": "%s"}, "lab_ca_routing": {"value": false}, "lab_scenarios_dir": {"value": "%s"}}' \
    "$1" "$2" "$LAB_SCENARIOS" > "$FAKE_OPTIONS"
  shift 2
  LAB_WEB_PORT="$MITMWEB_PORT" "$@"
}

# --help works for roxy and every subcommand, on stdout; an unknown subcommand is refused.
for args in "" start status scenario launch flows console app; do
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

# status: the lab up (signed in) reports the Proxy IP, the Proxy Bases and the active Scenarios.
out="$(FAKE_TUNNEL_HOST=tunnel.example lab_up "" json-503,hls-404 "$ROXY" status)" \
  || fail "status with the lab up exited non-zero: $out"
want="lab: up (mitmweb UI http://127.0.0.1:$MITMWEB_PORT)
Proxy IP:          192.0.2.10  (for an app's debug proxy setting)
LAN Proxy Bases:   http://192.0.2.10:8080  http://192.0.2.10:8888  (each takes the / and /; forms)
Public Proxy Base: https://tunnel.example/test-secret
App Profile:       none
Scenarios:         json-503  (lab)
                   hls-404  (lab)"
[ "$out" = "$want" ] || fail "status with the lab up said:
$out
not:
$want"
out="$(lab_up "" "" "$ROXY" status)" || fail "status without a tunnel or Scenario exited non-zero: $out"
for want in "Public Proxy Base: none" "Scenarios:         none"; do
  case "$out" in *"$want"*) ;; *) fail "status without a tunnel or Scenario lacks '$want':
$out" ;; esac
done
echo "ok: status reports the Proxy IP, the Proxy Bases and the Scenarios in order"

# status --json: the lab down says so on stderr; the lab up prints its state as one JSON object.
if err="$("$ROXY" status --json 2>&1 >/dev/null)"; then fail "status --json exited 0 with the lab down"; fi
case "$err" in *"lab: down"*) ;; *) fail "status --json with the lab down said: $err" ;; esac
out="$(lab_up app-x json-503,hls-404 "$ROXY" status --json)" || fail "status --json with the lab up: $out"
want="{\"app\": \"app-x\", \"scenarios\": [\"json-503\", \"hls-404\"], \"ca_routing\": false, \"scenarios_dir\": \"$LAB_SCENARIOS\"}"
[ "$out" = "$want" ] || fail "status --json with the lab up said:
$out
not:
$want"
echo "ok: status --json says when the lab is down, and prints the lab's state"

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

# launch on a Cloud Device: through rce, with the running tunnel's public Proxy Base plus the slug.
: > "$RCE_LOG"
out="$(FAKE_TUNNEL_HOST=tunnel.example "$ROXY" launch "Cloud Device" case=json_get 'separator=/;')" \
  || fail "launch on a Cloud Device: $out"
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
echo "ok: status names the App Profile and each active Scenario's source"

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
