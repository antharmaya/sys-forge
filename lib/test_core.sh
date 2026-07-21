#!/usr/bin/env bash
# Dependency-free test harness for core.sh (no bats required).
# Run: bash lib/test_core.sh

set -uo pipefail  # deliberately NOT -e: a failing assertion must not kill the runner
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/core.sh"

pass_count=0
fail_count=0

assert_eq() {
  local expected=$1 actual=$2 msg=$3
  if [[ "$expected" == "$actual" ]]; then
    echo "  ok: $msg"
    ((pass_count++))
  else
    echo "  FAIL: $msg (expected '$expected', got '$actual')"
    ((fail_count++))
  fi
}

assert_success() {
  local msg=$1; shift
  if "$@"; then
    echo "  ok: $msg"
    ((pass_count++))
  else
    echo "  FAIL: $msg (expected success, got failure)"
    ((fail_count++))
  fi
}

assert_failure() {
  local msg=$1; shift
  if "$@"; then
    echo "  FAIL: $msg (expected failure, got success)"
    ((fail_count++))
  else
    echo "  ok: $msg"
    ((pass_count++))
  fi
}

echo "== sf_best_tool =="
assert_eq "bash" "$(sf_best_tool nonexistent_xyz bash)" "picks the first available candidate, skipping missing ones"
assert_eq "bash" "$(sf_best_tool bash sh)" "picks the first candidate when it's available, ignoring later ones"
assert_failure "returns failure when NO candidate is available" sf_best_tool nonexistent_xyz nonexistent_abc

echo "== sf_retry =="
attempt_count=0
flaky_succeeds_on_third() {
  ((attempt_count++))
  [[ $attempt_count -ge 3 ]]
}
attempt_count=0
assert_success "retry succeeds after transient failures" sf_retry 5 0 flaky_succeeds_on_third
assert_eq 3 "$attempt_count" "retry stopped calling once it succeeded"

assert_failure "retry gives up and fails after max_attempts" sf_retry 2 0 false

echo "== sf_with_lock =="
lockfile=$(mktemp -u)
assert_success "with_lock runs the command when lock is free" sf_with_lock "$lockfile" true
rm -f "$lockfile"

# Concurrent-run test: hold the lock in a background subshell, confirm a
# second attempt to acquire it fails immediately instead of blocking.
lockfile=$(mktemp -u)
(
  exec 9>"$lockfile"
  flock 9
  sleep 0.3
) &
holder_pid=$!
sleep 0.05  # let the background process acquire the lock first
assert_failure "with_lock fails fast when already locked" sf_with_lock "$lockfile" true
wait "$holder_pid"
rm -f "$lockfile"

echo "== sf_circuit_call =="
circuit_name="test-circuit-$$"
rm -f "$(sf_circuit_state_file "$circuit_name")"
assert_failure "circuit call propagates a real failure" sf_circuit_call "$circuit_name" 10 false
assert_failure "circuit is now open and skips the call" sf_circuit_call "$circuit_name" 10 true
# even though the underlying command (true) would succeed, the circuit
# should be OPEN and skip calling it at all — verify by checking a marker
call_happened=0
mark_call() { call_happened=1; return 0; }
sf_circuit_call "$circuit_name" 10 mark_call >/dev/null 2>&1
assert_eq 0 "$call_happened" "circuit open: underlying command was never actually invoked"
rm -f "$(sf_circuit_state_file "$circuit_name")"

circuit_name2="test-circuit-cooldown-$$"
rm -f "$(sf_circuit_state_file "$circuit_name2")"
sf_circuit_call "$circuit_name2" 0 false >/dev/null 2>&1  # cooldown=0: reopens instantly
assert_success "circuit closes again once cooldown elapses" sf_circuit_call "$circuit_name2" 0 true
rm -f "$(sf_circuit_state_file "$circuit_name2")"

echo "== sf_parallel_run =="
work_dir=$(mktemp -d)
record_success() { touch "$work_dir/done-$1"; return 0; }
sf_parallel_run 3 record_success a b c d e
count=$(find "$work_dir" -name 'done-*' | wc -l)
assert_eq 5 "$count" "parallel_run executed all 5 jobs"
rm -rf "$work_dir"

fail_on_c() { [[ "$1" != "c" ]]; }
assert_failure "parallel_run reports failure if any job fails" sf_parallel_run 2 fail_on_c a b c d

# Regression test for a real bug: this harness deliberately runs WITHOUT
# set -e (so one failing assertion doesn't kill the whole runner) — which
# is exactly why an earlier version of sf_parallel_run passed every test
# above while still crashing any REAL caller that used `set -e` (every
# scaffold in this skill recommends `set -e`). `((running++))` from 0
# evaluates false and kills the calling script on the very first job
# dispatched, before the function ever reaches its own job-tracking logic
# — verified by tracing it live, not assumed. This block spawns a real
# `set -euo pipefail` subprocess specifically to close that blind spot.
set_e_child_result=$(bash -c '
  set -euo pipefail
  source "'"$SCRIPT_DIR"'/core.sh"
  ok_job() { return 0; }
  sf_parallel_run 3 ok_job a b c d e >/dev/null 2>&1
  echo "all-success-exit:$?"
' 2>&1)
assert_eq "all-success-exit:0" "$set_e_child_result" \
  "sf_parallel_run all-success case does not crash a caller running under real set -e"

set_e_child_result=$(bash -c '
  set -euo pipefail
  source "'"$SCRIPT_DIR"'/core.sh"
  fail_job() { [[ "$1" != "c" ]]; }
  if sf_parallel_run 2 fail_job a b c d >/dev/null 2>&1; then
    echo "unexpected-success"
  else
    echo "correctly-caught-failure:$?"
  fi
')
assert_eq "correctly-caught-failure:1" "$set_e_child_result" \
  "sf_parallel_run partial-failure case returns 1 to a properly-guarded caller under real set -e, instead of crashing it"

echo "== sf_with_tmpdir =="
# sf_with_tmpdir runs the callback in a subshell (see core.sh comment), so
# results must come back via stdout, not a mutated variable.
capture_dir_file=$(mktemp -u)
capture_tmpdir() { echo "$SF_TMPDIR" > "$capture_dir_file"; [[ -d "$SF_TMPDIR" ]]; }
assert_success "with_tmpdir provides an existing directory via SF_TMPDIR" sf_with_tmpdir capture_tmpdir
tmpdir_capture=$(<"$capture_dir_file")
assert_failure "with_tmpdir cleans up the directory immediately after returning, not deferred to script exit" \
  bash -c "[[ -d '$tmpdir_capture' ]]"
rm -f "$capture_dir_file"

echo ""
echo "== Results: $pass_count passed, $fail_count failed =="
(( fail_count == 0 ))
