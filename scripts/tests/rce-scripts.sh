#!/usr/bin/env bash
# scripts/deploy and scripts/launch on a Cloud Device, against a fake rce CLI on PATH:
# the rce commands they run, with which arguments. No RCE, no device.
# Usage: scripts/tests/rce-scripts.sh   (run by scripts/check)
set -euo pipefail
SCRIPTS="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(dirname "$SCRIPTS")"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export LAB_LOCK_DIR="$TMP/locks" RCE_LOG="$TMP/rce.log" ROXY_CONFIG_DIR="$TMP/settings"
unset LAB_LOCK_TOKEN LAB_LOCK_WAIT LAB_LOCK_OWNER
mkdir -p "$ROXY_CONFIG_DIR"
cp -R "$REPO/settings.example/." "$ROXY_CONFIG_DIR"  # its devices, never your own

fail() { echo "FAIL: $*" >&2; exit 1; }

# The fake rce logs each call, one line of shell-quoted arguments, and answers like rce:
# FAKE_RCE_FAIL_ON=<first argument> makes those calls fail with FAKE_RCE_EXIT.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/rce" <<'EOF'
#!/usr/bin/env bash
printf '%q ' "$@" >> "$RCE_LOG"
echo >> "$RCE_LOG"
echo "rce: fake output on stdout"
if [ "$1" = "${FAKE_RCE_FAIL_ON:-}" ]; then echo "rce: fake failure" >&2; exit "$FAKE_RCE_EXIT"; fi
EOF
chmod +x "$TMP/bin/rce"
export PATH="$TMP/bin:$PATH"

device="Cloud Device"
name="$(jq -r --arg d "$device" '.[$d].rce_device_name' "$ROXY_CONFIG_DIR/devices.json")"
slug="$(jq -r --arg d "$device" '.[$d].slug' "$ROXY_CONFIG_DIR/devices.json")"
[ -n "$name" ] && [ "$name" != null ] || fail "devices.json: '$device' has no rce_device_name"

# launch: exit-app, then launch/dev with the public Proxy Base plus the slug, through rce.
: > "$RCE_LOG"
out="$("$SCRIPTS/launch" --proxy-base "https://tunnel.example/secret/" "$device" case=json_get)" || fail "launch: $out"
run="$(sed -n 's/^run=//p' <<< "$out")"
[ -n "$run" ] || fail "launch printed no run id: $out"
[ "$out" = "run=$run" ] || fail "launch let rce's output into its own: $out"
expected="$(printf '%q ' device resolve "$name")
$(printf '%q ' ecp "$name" exit-app/dev --method POST)
$(printf '%q ' launch "$name" --param "proxyBase=https://tunnel.example/secret/$slug" --param case=json_get --param "run=$run")"
[ "$(cat "$RCE_LOG")" = "$expected" ] || fail "launch ran:
$(cat "$RCE_LOG")
expected:
$expected"
echo "ok: launch goes through rce ecp and rce launch"

# A Device Name rce does not know stops launch after the free local lookup, naming it.
: > "$RCE_LOG"
if err="$(FAKE_RCE_FAIL_ON=device FAKE_RCE_EXIT=3 "$SCRIPTS/launch" --proxy-base "https://tunnel.example/secret" "$device" case=json_get 2>&1)"; then
  fail "launch went on with an unknown Device Name: $err"
fi
case "$err" in *"Device Name '$name'"*) ;; *) fail "launch's refusal does not name the Device Name: $err" ;; esac
[ "$(cat "$RCE_LOG")" = "$(printf '%q ' device resolve "$name")" ] || fail "launch ran more than the lookup: $(cat "$RCE_LOG")"
echo "ok: an unknown Device Name stops launch before any billed call"

# deploy: packages the app and sideloads it with rce, which knows the Cloud Device's dev
# password: no secrets.env, no shared ROKU_DEV_PASSWORD. A throwaway app keeps out/ of real builds.
app="$TMP/rce-test-app-$$"
mkdir -p "$app"
printf 'title=rce test\n' > "$app/manifest"
trap 'rm -rf "$TMP" "$REPO/out/$(basename "$app")" "$REPO/out/$(basename "$app").zip"' EXIT
: > "$RCE_LOG"
out="$(cd "$TMP" && env -u ROKU_DEV_PASSWORD "$SCRIPTS/deploy" "$device" "$app" 2>&1)" || fail "deploy: $out"
expected="$(printf '%q ' device resolve "$name")
$(printf '%q ' sideload "$name" "$REPO/out/$(basename "$app").zip")"
[ "$(cat "$RCE_LOG")" = "$expected" ] || fail "deploy ran:
$(cat "$RCE_LOG")
expected:
$expected"
unzip -p "$REPO/out/$(basename "$app").zip" manifest | grep -q '^lab_proxy_base=' || fail "the package has no baked Proxy Base"
echo "ok: deploy sideloads through rce"

# A sideload rce refuses fails deploy.
if err="$(FAKE_RCE_FAIL_ON=sideload FAKE_RCE_EXIT=4 "$SCRIPTS/deploy" "$device" "$app" 2>&1)"; then
  fail "deploy succeeded although rce refused the sideload: $err"
fi
case "$err" in *"rce: fake failure"*"sideload to $device failed"*) ;; *) fail "deploy's failure: $err" ;; esac
echo "ok: a refused sideload fails deploy"
