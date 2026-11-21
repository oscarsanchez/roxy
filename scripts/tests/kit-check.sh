#!/usr/bin/env bash
# scripts/kit-check against fakes: a checkout of its own in a temp folder whose deploy and
# roxy are fakes, curl answering a Physical Device's ECP, and the Mac's network commands.
# No lab, no device, no network, no real settings.
# Usage: scripts/tests/kit-check.sh   (run by scripts/check)
set -euo pipefail
SCRIPTS="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(dirname "$SCRIPTS")"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export LAB_LOCK_DIR="$TMP/locks" ROXY_CONFIG_DIR="$TMP/settings" XDG_DATA_HOME="$TMP/data" ROXY_OUT_DIR="$TMP/out" \
  EVENTS="$TMP/events" SCREEN="$TMP/screen"
unset LAB_LOCK_TOKEN LAB_LOCK_WAIT LAB_LOCK_OWNER ROXY_KIT
mkdir -p "$ROXY_CONFIG_DIR"
cp -R "$REPO/settings.example/." "$ROXY_CONFIG_DIR"  # Living Room: a Physical Device

fail() { echo "FAIL: $*" >&2; exit 1; }

# The checkout: the real kit-check and lib.sh, a fake deploy and a fake roxy. Each fake logs
# one line of shell-quoted arguments to $EVENTS. The device's screen is $SCREEN: what
# the app shows after its last launch, as the kit example does with or without proxyBase.
# FAKE_FLOWS=none: the lab sees no flow, whatever the launch.
# FAKE_STATUS: the status the app shows (default 200).
checkout="$TMP/checkout"
mkdir -p "$checkout/scripts" "$checkout/bin" "$TMP/bin"
ln -s "$SCRIPTS/lib.sh" "$SCRIPTS/kit-check" "$checkout/scripts/"
cat > "$checkout/scripts/deploy" <<'EOF'
#!/usr/bin/env bash
printf '%q ' "ROXY_KIT=${ROXY_KIT:-}" deploy "$@" >> "$EVENTS"; echo >> "$EVENTS"
EOF
cat > "$checkout/bin/roxy" <<'EOF'
#!/usr/bin/env bash
printf '%q ' roxy "$@" >> "$EVENTS"; echo >> "$EVENTS"
case "$1" in
  launch) printf 'GET http://192.0.2.10:8080/;https://httpbin.org/json\nstatus=%s length=429\n' "${FAKE_STATUS:-200}" > "$SCREEN"
    echo "run=17000000001234" ;;
  flows) if [ "${FAKE_FLOWS:-}" != none ] && grep -q '/;' "$SCREEN"; then
      echo '[{"device": "Living Room", "url": "https://httpbin.org/json", "status": 200}, {"device": "Bedroom", "url": "https://httpbin.org/json", "status": 200}]'
    else
      echo '[{"device": "Bedroom", "url": "https://httpbin.org/json", "status": 200}]'
    fi ;;
esac
EOF
cat > "$TMP/bin/curl" <<'EOF'
#!/usr/bin/env bash
url=""
for a in "$@"; do case "$a" in http://*) url="$a" ;; esac; done
printf '%q ' curl "$url" >> "$EVENTS"; echo >> "$EVENTS"
case "$url" in
  */query/app-ui) echo '<app-ui><topscreen><plugin>'
    while IFS= read -r line; do echo "<Label text=\"$line\" />"; done < "$SCREEN"
    echo '</plugin></topscreen></app-ui>' ;;
  */launch/dev) printf 'GET https://httpbin.org/json\nstatus=%s length=429\n' "${FAKE_STATUS:-200}" > "$SCREEN" ;;
esac
EOF
printf '#!/usr/bin/env bash\necho "  interface: en0"\n' > "$TMP/bin/route"
printf '#!/usr/bin/env bash\necho 192.0.2.10\n' > "$TMP/bin/ipconfig"
chmod +x "$checkout/scripts/deploy" "$checkout/bin/roxy" "$TMP/bin/"*
export PATH="$TMP/bin:$PATH"
: > "$SCREEN"

kit_check() { : > "$EVENTS"; "$checkout/scripts/kit-check" "$@" 2>&1; }

# Both kit examples, built with the kit, launched with proxyBase (roxy launch) and then
# without (ECP launch/dev): every check matches, and it exits 0.
out="$(kit_check "Living Room")" || fail "kit-check on a kit that works: $out"
deploys="$(grep ' deploy ' "$EVENTS")"
[ "$deploys" = "$(printf '%q ' ROXY_KIT=1 deploy "Living Room" "$checkout/kit/example-classic")
$(printf '%q ' ROXY_KIT=1 deploy "Living Room" "$checkout/kit/example-rsg")" ] || fail "kit-check deployed:
$deploys"
[ "$(grep -c '^roxy launch Living\\ Room $' "$EVENTS")" = 2 ] || fail "kit-check did not launch each example with proxyBase:
$(cat "$EVENTS")"
[ "$(grep -c ':8060/launch/dev $' "$EVENTS")" = 2 ] || fail "kit-check did not launch each example without proxyBase:
$(cat "$EVENTS")"
case "$out" in *MISMATCH*) fail "kit-check found a mismatch in a kit that works:
$out" ;; esac
echo "ok: kit-check passes both examples, with and without proxyBase"

# The lab sees no flow from the device with proxyBase: a mismatch, and it exits 1.
if out="$(FAKE_FLOWS=none kit_check "Living Room")"; then fail "kit-check passed with no flow in the lab: $out"; fi
case "$out" in *"MISMATCH: 0 flows from Living Room to httpbin.org"*) ;; *) fail "kit-check's mismatch without flows:
$out" ;; esac
echo "ok: no flow in the lab with proxyBase is a mismatch"

# The app shows another status: a mismatch.
if out="$(FAKE_STATUS=503 kit_check "Living Room")"; then fail "kit-check passed with status=503: $out"; fi
case "$out" in *"MISMATCH: the app shows status=200"*) ;; *) fail "kit-check's mismatch on the status:
$out" ;; esac
echo "ok: another status on the screen is a mismatch"

# A Cloud Device is refused before anything is deployed.
if out="$(kit_check "Cloud Device")"; then fail "kit-check took a Cloud Device: $out"; fi
case "$out" in *"Physical Devices"*) ;; *) fail "kit-check's refusal of a Cloud Device: $out" ;; esac
[ ! -s "$EVENTS" ] || fail "kit-check ran commands for a Cloud Device: $(cat "$EVENTS")"
echo "ok: a Cloud Device is refused"
