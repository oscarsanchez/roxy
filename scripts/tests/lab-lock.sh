#!/usr/bin/env bash
# lab_lock (scripts/lib.sh) without a device: contention, re-entry, release, stale reclaim, wait.
# Usage: scripts/tests/lab-lock.sh   (run by scripts/check)
set -euo pipefail
LIB="$(cd "$(dirname "$0")/.." && pwd)/lib.sh"
LAB_LOCK_DIR="$(mktemp -d)"
export LAB_LOCK_DIR LIB
unset LAB_LOCK_TOKEN LAB_LOCK_WAIT LAB_LOCK_OWNER
trap 'kill $(jobs -p) 2>/dev/null || true; rm -rf "$LAB_LOCK_DIR"' EXIT
LOCK="$LAB_LOCK_DIR/devices"

fail() { echo "FAIL: $*" >&2; exit 1; }
# with_lock SNIPPET : a fresh script that takes the devices lock, then runs SNIPPET.
with_lock() { bash -c '. "$LIB"; lab_lock devices; '"$1"; }
wait_for_lock() {
  local i
  for i in $(seq 50); do [ -e "$LOCK" ] && return; sleep 0.1; done
  fail "the holder never took the lock"
}

# A second holder fails fast, naming the first.
LAB_LOCK_OWNER=alpha with_lock 'sleep 1' &
holder=$!
wait_for_lock
if err="$(with_lock 'echo got' 2>&1)"; then fail "second holder got the lock: $err"; fi
case "$err" in *"alpha, pid "*"sleep 1"*) ;; *) fail "the refusal does not name the holder: $err" ;; esac
echo "ok: contention fails fast naming the holder"

# LAB_LOCK_WAIT=1 waits for the holder to finish instead.
out="$(LAB_LOCK_WAIT=1 with_lock 'echo got' 2>&1)" || fail "waiting holder failed: $out"
case "$out" in *waiting*alpha*got*) ;; *) fail "waiting holder: $out" ;; esac
wait "$holder"
echo "ok: LAB_LOCK_WAIT=1 waits"

# A child of the holder re-enters, and only the outer holder releases the lock.
out="$(with_lock 'with_inner() { bash -c ". \"\$LIB\"; lab_lock devices; echo inner"; }; with_inner; [ -e "$LAB_LOCK_DIR/devices" ] && echo still-held')" \
  || fail "nested call: $out"
[ "$out" = "$(printf 'inner\nstill-held')" ] || fail "nested call: $out"
[ ! -e "$LOCK" ] || fail "the lock outlived its holder"
echo "ok: nested call re-enters; release on exit"

# A dead holder's lock is reclaimed.
bash -c 'exit 0' &
dead=$!
wait "$dead"
printf 'pid=%s\nowner=ghost\ncommand=gone\nsince=then\ntoken=old\n' "$dead" > "$LOCK"
out="$(with_lock 'echo got' 2>&1)" || fail "stale lock not reclaimed: $out"
case "$out" in *reclaiming*got*) ;; *) fail "stale lock: $out" ;; esac
echo "ok: stale lock reclaimed"
