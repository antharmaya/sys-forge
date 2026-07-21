#!/usr/bin/env bash
# systems-forge bash library — source this, don't copy-paste from it.
#   source /path/to/systems-forge/lib/core.sh
#
# Every function here is independently tested in lib/test_core.sh — run it
# after modifying anything in this file.

# ── Modern-tool detection with fallback ──────────────────────────────────
sf_best_tool() {
  # Usage: cmd=$(sf_best_tool rg grep) || { echo "neither found" >&2; exit 1; }
  # Returns the first available command from the candidate list (checked in
  # the order given — put your preferred/modern tool first, POSIX fallback
  # last). Never call a modern tool (rg, fd, sd, ast-grep...) directly
  # without a fallback — see references/modern-cli-tools.md for why: it's
  # not installed on every CI runner or fresh box by default.
  local candidate
  for candidate in "$@"; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

# ── Logging ──────────────────────────────────────────────────────────────
sf_log() {
  # Usage: sf_log INFO "message" | sf_log ERROR "message"
  printf '%s [%s] %s\n' "$(date -u +%FT%TZ)" "${1}" "${*:2}" >&2
}

# ── Retry with exponential backoff + jitter ──────────────────────────────
sf_retry() {
  # Usage: sf_retry <max_attempts> <base_delay_seconds> <command> [args...]
  local max_attempts=$1 delay=$2; shift 2
  local attempt=1
  until "$@"; do
    if (( attempt >= max_attempts )); then
      sf_log ERROR "failed after $max_attempts attempts: $*"
      return 1
    fi
    local jittered
    jittered=$(awk -v d="$delay" 'BEGIN{srand(); print d * (0.5 + rand()*0.5)}')
    sf_log WARN "attempt $attempt failed, retrying in ${jittered}s: $*"
    sleep "$jittered"
    delay=$(( delay * 2 ))
    ((attempt++))
  done
}

# ── Locking against concurrent runs ──────────────────────────────────────
sf_with_lock() {
  # Usage: sf_with_lock /path/to/lockfile some_command args...
  # Real kernel-level advisory lock via flock — released automatically if
  # the process dies, unlike a .pid file which requires check-then-act
  # (a race between two processes checking "no lock" at the same time).
  local lockfile=$1; shift
  (
    exec 9>"$lockfile"
    if ! flock -n 9; then
      sf_log ERROR "could not acquire lock: $lockfile (already running?)"
      exit 1
    fi
    "$@"
  )
}

# ── Circuit breaker (bash-native, backed by a state file) ────────────────
# Skip calling a known-broken dependency for a cooldown window instead of
# re-attempting (and re-timing-out) on every single invocation. Real use:
# wrap a flaky network call in a cron job so a persistent outage doesn't
# cost a full timeout on every single run of the job.
sf_circuit_state_file() {
  local name=$1
  printf '%s/systems-forge-circuit-%s' "${TMPDIR:-/tmp}" "$name"
}

sf_circuit_is_open() {
  # Usage: sf_circuit_is_open <name> <cooldown_seconds>
  local name=$1 cooldown=$2
  local state_file; state_file=$(sf_circuit_state_file "$name")
  [[ -f "$state_file" ]] || return 1  # no failure recorded, circuit closed
  local opened_at now
  opened_at=$(<"$state_file")
  now=$(date +%s)
  if (( now - opened_at >= cooldown )); then
    rm -f "$state_file"  # cooldown elapsed, circuit closes again
    return 1
  fi
  return 0  # still open
}

sf_circuit_record_failure() {
  local name=$1
  date +%s > "$(sf_circuit_state_file "$name")"
}

sf_circuit_record_success() {
  local name=$1
  rm -f "$(sf_circuit_state_file "$name")"
}

sf_circuit_call() {
  # Usage: sf_circuit_call <name> <cooldown_seconds> <command> [args...]
  local name=$1 cooldown=$2; shift 2
  if sf_circuit_is_open "$name" "$cooldown"; then
    sf_log WARN "circuit '$name' open, skipping call: $*"
    return 1
  fi
  if "$@"; then
    sf_circuit_record_success "$name"
    return 0
  else
    sf_circuit_record_failure "$name"
    return 1
  fi
}

# ── Parallel fan-out with per-job result collection ──────────────────────
sf_parallel_run() {
  # Usage: sf_parallel_run <max_concurrency> <function_name> arg1 arg2 arg3...
  # Runs <function_name> once per remaining arg, at most <max_concurrency>
  # at a time, and returns non-zero if ANY job failed (unlike a bare `wait`
  # with no args, which only tells you if the LAST-checked job failed).
  #
  # Every arithmetic increment/decrement below uses `if ...; then ((x++)); fi`
  # rather than a bare `((x++))` or `cmd || ((x++))` — verified real bug (see
  # bash-patterns.md §13): `((x++))` evaluates FALSE when x is 0 pre-increment,
  # which kills the whole calling script under `set -e` on the very first
  # call, before this function ever gets to its actual job-tracking logic.
  # `lib/test_core.sh` deliberately doesn't run under `set -e` (so one failing
  # assertion doesn't kill the test runner), which is exactly why this stayed
  # broken until a field test used this function under real `set -e` — the
  # existing test suite never actually exercised the failure path it's
  # supposed to prove works.
  local max_concurrency=$1 fn=$2; shift 2
  local pids=() failures=0 running=0
  for item in "$@"; do
    "$fn" "$item" &
    pids+=($!)
    running=$((running + 1))
    if (( running >= max_concurrency )); then
      if ! wait "${pids[0]}"; then
        failures=$((failures + 1))
      fi
      pids=("${pids[@]:1}")
      running=$((running - 1))
    fi
  done
  for pid in "${pids[@]}"; do
    if ! wait "$pid"; then
      failures=$((failures + 1))
    fi
  done
  if (( failures > 0 )); then
    sf_log ERROR "$failures job(s) failed"
    return 1
  fi
  return 0
}

# ── Safe temp file/dir with guaranteed cleanup ───────────────────────────
sf_with_tmpdir() {
  # Usage: sf_with_tmpdir some_function args...
  # Creates a tmpdir, exports it as SF_TMPDIR for the duration of the call,
  # and removes it afterward NO MATTER how the function exits (success,
  # failure, or a signal).
  #
  # Runs the function in a SUBSHELL so its own `trap ... EXIT` is scoped to
  # just this call, not the whole script — `trap` is process-scoped, not
  # function-scoped, so setting it directly in the current shell would only
  # fire when the ENTIRE calling script exits, not right after this
  # function returns. (An earlier version of this function had exactly that
  # bug — caught by lib/test_core.sh actually checking the directory was
  # gone immediately after the call, not just trusting the trap was there.)
  #
  # Consequence of the subshell: the called function can't mutate variables
  # in the caller's shell (subshells don't share variable scope) — return
  # data via stdout or a file under SF_TMPDIR instead, then read it after
  # sf_with_tmpdir returns, before the directory is removed... actually
  # it's already removed by then, so persist anything you need OUTSIDE
  # SF_TMPDIR if the caller needs it afterward.
  local tmpdir; tmpdir=$(mktemp -d)
  (
    trap 'rm -rf "$tmpdir"' EXIT
    SF_TMPDIR="$tmpdir" "$@"
  )
}
