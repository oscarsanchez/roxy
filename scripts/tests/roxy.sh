#!/usr/bin/env bash
# The roxy CLI and its install, run as commands (Seam C): a temp settings root, a temp
# HOME, and fakes on PATH for curl (mitmweb's API, cloudflared's metrics, ECP), rce,
# and the Mac's network commands. No lab, no device, no network, no real settings.
# Usage: scripts/tests/roxy.sh   (run by scripts/check)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
ROXY="$REPO/bin/roxy"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export LAB_LOCK_DIR="$TMP/locks" ROXY_CONFIG_DIR="$TMP/settings" XDG_DATA_HOME="$TMP/data"
unset LAB_LOCK_TOKEN LAB_LOCK_WAIT LAB_LOCK_OWNER MITMWEB_PASSWORD LAB_SECRET

fail() { echo "FAIL: $*" >&2; exit 1; }

# The settings root, seeded from the examples, with a mitmweb password and a tunnel secret.
mkdir -p "$ROXY_CONFIG_DIR"
cp -R "$REPO/settings.example/." "$ROXY_CONFIG_DIR"
sed -i.bak -e 's/^MITMWEB_PASSWORD=.*/MITMWEB_PASSWORD=test-password/' \
  -e 's/^LAB_SECRET=.*/LAB_SECRET=test-secret/' "$ROXY_CONFIG_DIR/secrets.env"

# Fakes on PATH. curl logs one line of shell-quoted arguments per call (and the URL alone
# to $CURL_LOG.urls, the request body to $CURL_LOG.body) and answers for
# mitmweb's API (FAKE_LAB_UP=1: up, with FAKE_SCENARIO active), cloudflared's metrics
# (FAKE_TUNNEL_HOST set: a tunnel is up) and ECP. rce logs its calls the same way.
# uv stands in for `uv run mitmweb ...` (roxy start): it logs one argument per line to
# $UV_LOG and, as mitmweb does, creates the file it saves the session to.
# route and ipconfig give the Mac the LAN IP 192.0.2.10.
export CURL_LOG="$TMP/curl.log" RCE_LOG="$TMP/rce.log" UV_LOG="$TMP/uv.log"
mkdir -p "$TMP/bin"
cat > "$TMP/bin/curl" <<'EOF'
#!/usr/bin/env bash
printf '%q ' "$@" >> "$CURL_LOG"
echo >> "$CURL_LOG"
url="" prev=""
for a in "$@"; do
  case "$a" in http://*|https://*) url="$a" ;; esac
  if [ "$prev" = -d ]; then printf '%s' "$a" > "$CURL_LOG.body"; fi  # the last request body
  prev="$a"
done
echo "$url" >> "$CURL_LOG.urls"
down() { echo "curl: (7) Failed to connect" >&2; exit 7; }
case "$url" in
  */options.json) [ "${FAKE_LAB_UP:-}" = 1 ] || down
    printf '{"lab_scenario": {"value": "%s"}}\n' "${FAKE_SCENARIO:-}" ;;
  */options) [ "${FAKE_LAB_UP:-}" = 1 ] || down
    case " $* " in *" -w "*) printf '\n200' ;; esac ;;
  */quicktunnel) [ -n "${FAKE_TUNNEL_HOST:-}" ] || down
    printf '{"hostname": "%s"}\n' "$FAKE_TUNNEL_HOST" ;;
esac
EOF
cat > "$TMP/bin/rce" <<'EOF'
#!/usr/bin/env bash
printf '%q ' "$@" >> "$RCE_LOG"
echo >> "$RCE_LOG"
EOF
cat > "$TMP/bin/uv" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$UV_LOG"
session="$(sed -n 's/^save_stream_file=//p' "$UV_LOG")"
[ -z "$session" ] || touch "$session"
EOF
printf '#!/usr/bin/env bash\necho "  interface: en0"\n' > "$TMP/bin/route"
printf '#!/usr/bin/env bash\necho 192.0.2.10\n' > "$TMP/bin/ipconfig"
chmod +x "$TMP/bin/"*
export PATH="$TMP/bin:$PATH"

# --help works for roxy and every subcommand, on stdout; an unknown subcommand is refused.
for args in "" start status scenario launch console app; do
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

# status: the lab up reports the Proxy IP, the Proxy Bases and the active Scenario.
out="$(FAKE_LAB_UP=1 FAKE_SCENARIO=json-503 FAKE_TUNNEL_HOST=tunnel.example "$ROXY" status)" \
  || fail "status with the lab up exited non-zero: $out"
for want in "lab: up" "Proxy IP:          192.0.2.10" \
  "LAN Proxy Bases:   http://192.0.2.10:8080  http://192.0.2.10:8888" \
  "Public Proxy Base: https://tunnel.example/test-secret" "Scenario:          json-503"; do
  case "$out" in *"$want"*) ;; *) fail "status with the lab up lacks '$want':
$out" ;; esac
done
grep -q 'Authorization:\\ Bearer\\ test-password' "$CURL_LOG" || fail "status did not sign in to mitmweb"
out="$(FAKE_LAB_UP=1 "$ROXY" status)" || fail "status without a tunnel or Scenario exited non-zero: $out"
for want in "Public Proxy Base: none" "Scenario:          none"; do
  case "$out" in *"$want"*) ;; *) fail "status without a tunnel or Scenario lacks '$want':
$out" ;; esac
done
echo "ok: status reports the Proxy IP, the Proxy Bases and the Scenario"

# scenario list: the lab's own Scenarios, with or without a running lab.
out="$("$ROXY" scenario list)" || fail "scenario list: $out"
for want in json-503 hls-404; do grep -qx "$want" <<< "$out" || fail "scenario list lacks $want: $out"; done
echo "ok: scenario list shows the lab's Scenarios"

# scenario set and clear switch the running lab's active Scenario through mitmweb's options API.
scenario_sent() { jq -c . "$CURL_LOG.body"; }
out="$(FAKE_LAB_UP=1 "$ROXY" scenario set json-503)" || fail "scenario set: $out"
[ "$(scenario_sent)" = '{"lab_scenario":"json-503"}' ] || fail "scenario set sent $(scenario_sent)"
out="$(FAKE_LAB_UP=1 "$ROXY" scenario clear)" || fail "scenario clear: $out"
[ "$(scenario_sent)" = '{"lab_scenario":""}' ] || fail "scenario clear sent $(scenario_sent)"
if err="$("$ROXY" scenario set json-503 2>&1)"; then fail "scenario set with the lab down exited 0"; fi
case "$err" in *"could not reach mitmweb"*) ;; *) fail "scenario set with the lab down said: $err" ;; esac
echo "ok: scenario set and clear switch the running lab's Scenario"

# launch on a Physical Device: ECP on the LAN with the LAN Proxy Base and the user's params.
: > "$CURL_LOG.urls"
out="$("$ROXY" launch "Living Room" case=json_get "note=a b")" || fail "launch on a Physical Device: $out"
run="$(sed -n 's/^run=//p' <<< "$out")"
[ -n "$run" ] || fail "launch printed no run id: $out"
want="http://192.0.2.54:8060/launch/dev?proxyBase=http%3A%2F%2F192.0.2.10%3A8080&case=json_get&note=a%20b&run=$run"
grep -qxF "$want" "$CURL_LOG.urls" || fail "launch on a Physical Device did not ask for
$want
curl asked for:
$(cat "$CURL_LOG.urls")"
echo "ok: launch sends the LAN Proxy Base to a Physical Device"

# launch on a Cloud Device: through rce, with the running tunnel's public Proxy Base plus the slug.
: > "$RCE_LOG"
out="$(FAKE_TUNNEL_HOST=tunnel.example "$ROXY" launch "Cloud Device" case=json_get)" \
  || fail "launch on a Cloud Device: $out"
run="$(sed -n 's/^run=//p' <<< "$out")"
want="$(printf '%q ' launch player --param "proxyBase=https://tunnel.example/test-secret/cloud-device" \
  --param case=json_get --param "run=$run")"
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

# App Profiles, in two temp app repos. A git hook (scripts/check from the pre-commit hook)
# exports the checkout's GIT_DIR, which would point their git commands at the roxy repo.
unset GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE
repos="$TMP/repos"
for app in app-a app-b; do git init -q "$repos/$app"; mkdir -p "$repos/$app/src/nested"; done
root_a="$(cd "$repos/app-a" && pwd -P)" root_b="$(cd "$repos/app-b" && pwd -P)"
listed_repo() { "$ROXY" app list | awk -v n="$1" '$1 == n {print $2}'; }

# app new, run in a subfolder of an app's repo, records the repo's git root; app list shows
# every profile with its repo.
out="$(cd "$repos/app-a/src/nested" && "$ROXY" app new app-a)" || fail "app new app-a: $out"
out="$(cd "$repos/app-b" && "$ROXY" app new app-b)" || fail "app new app-b: $out"
[ "$(listed_repo app-a)" = "$root_a" ] || fail "app list shows app-a at '$(listed_repo app-a)', not its git root $root_a"
[ "$(listed_repo app-b)" = "$root_b" ] || fail "app list shows app-b at '$(listed_repo app-b)', not $root_b"
echo "ok: app new records the repo's git root, and app list shows each profile"

# app new refuses a name that exists, keeping that profile; and a folder outside any repo.
if err="$(cd "$repos/app-b" && "$ROXY" app new app-a 2>&1)"; then fail "app new took the existing name app-a"; fi
case "$err" in *"app-a"*"exists"*) ;; *) fail "app new of an existing name said: $err" ;; esac
[ "$(listed_repo app-a)" = "$root_a" ] || fail "a refused app new changed app-a's repo to $(listed_repo app-a)"
if err="$(cd "$TMP" && "$ROXY" app new loose 2>&1)"; then fail "app new outside a git repo exited 0"; fi
case "$err" in *"git repo"*) ;; *) fail "app new outside a git repo said: $err" ;; esac
"$ROXY" app new ../escape >/dev/null 2>&1 && fail "app new took the name ../escape"
echo "ok: app new refuses an existing name, a folder outside a repo, and a name that is a path"

# roxy start loads --app NAME from anywhere, else the profile whose repo holds the current
# folder, else none; an unknown --app fails before mitmweb starts.
start_in() { local dir="$1"; shift; rm -f "$UV_LOG"; (cd "$dir" && "$ROXY" start "$@" 2>&1); }
started_app() { sed -n 's/^lab_app=//p' "$UV_LOG"; }
out="$(start_in "$TMP" --app app-b)" || fail "start --app app-b: $out"
[ "$(started_app)" = app-b ] || fail "start --app app-b loaded '$(started_app)'"
case "$out" in *"App Profile:       app-b"*) ;; *) fail "start --app app-b does not say so: $out" ;; esac
out="$(start_in "$repos/app-a/src/nested")" || fail "start in app-a's repo: $out"
[ "$(started_app)" = app-a ] || fail "start in a folder of app-a's repo loaded '$(started_app)'"
out="$(start_in "$repos/app-a" --app app-b)" || fail "start --app app-b in app-a's repo: $out"
[ "$(started_app)" = app-b ] || fail "start --app app-b in app-a's repo loaded '$(started_app)'"
out="$(start_in "$TMP")" || fail "start outside every profile's repo: $out"
[ -e "$UV_LOG" ] && [ -z "$(started_app)" ] || fail "start outside every profile's repo loaded '$(started_app)'"
case "$out" in *"App Profile:       none"*) ;; *) fail "start without a profile does not say so: $out" ;; esac
if out="$(start_in "$TMP" --app nope)"; then fail "start --app nope exited 0"; fi
case "$out" in *"unknown App Profile 'nope'"*) ;; *) fail "start --app nope said: $out" ;; esac
[ ! -e "$UV_LOG" ] || fail "start --app nope started mitmweb"
echo "ok: start loads the App Profile named, else the current repo's, else none; an unknown name fails"

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
echo "ok: install is idempotent and keeps existing settings"

# A roxy at the link's place that is not a link is someone else's: install refuses, changing nothing.
rm "$link"
echo "someone else's roxy" > "$link"
if err="$(run_install 2>&1)"; then fail "install replaced a file that is not a link"; fi
case "$err" in *"$link"*) ;; *) fail "install's refusal does not name $link: $err" ;; esac
[ "$(cat "$link")" = "someone else's roxy" ] || fail "install changed $link"
echo "ok: install leaves a roxy that is not its link alone"
