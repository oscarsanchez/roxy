#!/usr/bin/env bash
# The kit's example apps build with and without the kit's build-time constant, and a
# release build without it carries no proxy code: nothing that reads the proxyBase launch
# param, builds a `/;` Prefixed URL or ships the lab's CA. No device, no network.
# - classic: scripts/deploy packages kit/example-classic for a fake rce; the package's
#   BrightScript is then read as the compiler does with the manifest's roxy_kit value.
# - RSG 2.0: rk builds kit/example-rsg from pnpm's offline store. Skipped, with a note,
#   without Node 24+ or the packages in the store. The release preset is checked for proxy
#   code: the debug preset does not minify, so the kit's code stays in, dead. Source maps
#   (.map) hold source text, not code, and are not checked.
# Usage: scripts/tests/kit-build.sh   (run by scripts/check)
set -euo pipefail
SCRIPTS="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(dirname "$SCRIPTS")"
TMP="$(mktemp -d)"
classic="example-classic"
trap 'rm -rf "$TMP"' EXIT
export LAB_LOCK_DIR="$TMP/locks" ROXY_CONFIG_DIR="$TMP/settings" ROXY_OUT_DIR="$TMP/out" RCE_LOG="$TMP/rce.log"
unset LAB_LOCK_TOKEN LAB_LOCK_WAIT LAB_LOCK_OWNER ROXY_KIT ROXY_CA_BUNDLE
mkdir -p "$ROXY_CONFIG_DIR"
cp -R "$REPO/settings.example/." "$ROXY_CONFIG_DIR"

fail() { echo "FAIL: $*" >&2; exit 1; }

# proxy_code [GREP-OPTION...] FILE... : the lines that show proxy code: a read of the
# proxyBase launch param, the `/;` separator or the lab's CA bundle.
proxy_code() { grep -nE '\.proxyBase|/;|lab-ca' "$@" || true; }

# --- classic ---

# The fake rce accepts the sideload; deploy has then left the package in ROXY_OUT_DIR.
mkdir -p "$TMP/bin"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "$RCE_LOG"\n' > "$TMP/bin/rce"
chmod +x "$TMP/bin/rce"
cp -R "$REPO/kit/example-classic" "$TMP/$classic"
printf 'fake lab CA\n' > "$TMP/lab-ca.pem"  # for RSG 2.0's ROXY_CA_BUNDLE

# compiled ON FILE : the code lines the BrightScript compiler keeps with roxy_kit=ON
# (comment lines left out).
compiled() {
  awk -v on="$1" -v quote="'" '
    { code = $0; sub(/^[ \t]+/, "", code); if (substr(code, 1, 1) == quote) next }
    /^[ \t]*#if[ \t]+roxy_kit[ \t]*$/ { inkit = 1; keep = (on == "true"); next }
    inkit && /^[ \t]*#else[ \t]*$/ { keep = !keep; next }
    inkit && /^[ \t]*#end[ \t]*if[ \t]*$/ { inkit = 0; next }
    /^[ \t]*#/ { print "unexpected directive: " $0; next }
    !inkit || keep { print }
  ' "$2"
}

# classic_build KIT : deploy the example with ROXY_KIT=KIT; unpack it in $TMP/pkg-KIT and
# write what the compiler sees to $TMP/compiled-KIT.brs.
classic_build() {
  local pkg="$TMP/pkg-$1" on
  PATH="$TMP/bin:$PATH" ROXY_KIT="$1" "$SCRIPTS/deploy" "Cloud Device" "$TMP/$classic" >/dev/null || fail "deploy with ROXY_KIT=$1"
  rm -rf "$pkg" && mkdir -p "$pkg" && unzip -q "$ROXY_OUT_DIR/$classic.zip" -d "$pkg"
  on="$(sed -n 's/^bs_const=.*roxy_kit=\([a-z]*\).*/\1/p' "$pkg/manifest")"
  [ -n "$on" ] || fail "the classic package's manifest declares no roxy_kit constant"
  : > "$TMP/compiled-$1.brs"
  while IFS= read -r f; do compiled "$on" "$f" >> "$TMP/compiled-$1.brs"; done < <(find "$pkg" -name '*.brs')
  ! grep -n 'unexpected directive' "$TMP/compiled-$1.brs" || fail "the kit gates code only with #if roxy_kit"
}

classic_build ""
grep -q 'roxy_kit=false' "$TMP/pkg-/manifest" || fail "the classic example's release default is not roxy_kit=false"
[ -z "$(proxy_code "$TMP/compiled-.brs")" ] || fail "the classic build without the kit compiles proxy code:
$(proxy_code "$TMP/compiled-.brs")"
echo "ok: classic without ROXY_KIT compiles no proxy code"

classic_build 1
[ -n "$(proxy_code "$TMP/compiled-1.brs")" ] || fail "the classic build with ROXY_KIT=1 compiles no kit code"
echo "ok: classic with ROXY_KIT=1 compiles the kit"

# --- RSG 2.0 ---

if [ -d /opt/homebrew/opt/node@24/bin ]; then PATH="/opt/homebrew/opt/node@24/bin:$PATH"; fi
if [ "$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)" -lt 24 ]; then
  echo "skipped RSG 2.0: needs Node 24+" >&2
  exit 0
fi
rsg="$TMP/example-rsg"
mkdir -p "$rsg"
(cd "$REPO/kit/example-rsg" && tar cf - --exclude node_modules --exclude out .) | (cd "$rsg" && tar xf -)
# pnpm's default store: scripts/check points XDG_DATA_HOME at a temp folder for roxy's data.
if ! (cd "$rsg" && env -u XDG_DATA_HOME pnpm install --frozen-lockfile --offline >/dev/null 2>&1); then
  echo "skipped RSG 2.0: its packages are not in pnpm's store (run pnpm install in kit/example-rsg once)" >&2
  exit 0
fi

# rsg_build NAME ARGS... : rk build, with the environment given before it, into
# $TMP/NAME; the package's files are then in $TMP/NAME/pkg-dir.
rsg_build() {
  local out="$TMP/$1"
  shift
  (cd "$rsg" && ./node_modules/.bin/rk build --local --out-dir "$out" "$@" >/dev/null 2>&1) || fail "rk build $*"
}

export ROXY_CA_BUNDLE="$TMP/lab-ca.pem"  # set, as if by accident: only the kit may ship it
rsg_build rsg-release --release
pkg="$TMP/rsg-release/pkg-dir"
[ -z "$(proxy_code -r --exclude='*.map' "$pkg")" ] || fail "the RSG 2.0 release build without the kit has proxy code:
$(proxy_code -r --exclude='*.map' "$pkg" | cut -c1-200)"
[ -z "$(find "$pkg" -name '*.crt')" ] || fail "the RSG 2.0 release build without the kit ships a CA bundle"
echo "ok: RSG 2.0 release build without ROXY_KIT has no proxy code"

# With the kit: release (the same markers survive minifying) and debug (what deploy builds).
for preset in --release --debug; do
  ROXY_KIT=1 rsg_build "rsg-kit$preset" "$preset"
  pkg="$TMP/rsg-kit$preset/pkg-dir"
  [ -n "$(proxy_code -r --exclude='*.map' "$pkg")" ] || fail "the RSG 2.0 $preset build with ROXY_KIT=1 has no kit code"
  [ -n "$(find "$pkg" -name '*.crt')" ] || fail "the RSG 2.0 $preset build with ROXY_KIT=1 and ROXY_CA_BUNDLE ships no CA bundle"
done
echo "ok: RSG 2.0 with ROXY_KIT=1 has the kit and its CA bundle (release and debug)"
