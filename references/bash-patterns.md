# Bash Patterns — the full depth

Read this when the script is non-trivial: more than a few commands, will run unattended, will run more than
once, or touches anything you'd be unhappy to lose (files, running processes, another system over the network).

## 1. `set -euo pipefail` is necessary, not sufficient

The standard header:

```bash
set -euo pipefail
IFS=$'\n\t'
```

What each flag actually does, and where it silently doesn't help:

- **`-e` (errexit):** exits on any command returning non-zero — but which commands actually get exempted is
  narrower and more position-dependent than most descriptions of `set -e` suggest, including an earlier version
  of this exact file. See §13 for the precise, empirically-verified rules (they're not what you'd guess) —
  `cmd && other` is only safe to assume exempted in some positions, not others, and `x=$(false)` behaves the
  *opposite* of what's commonly claimed.
- **`-u` (nounset):** references to unset variables become errors. Catches the classic typo (`$FOOO` instead of
  `$FOO`) instantly instead of silently expanding to an empty string. Exception: `${VAR:-default}` and
  `${1:-}` are still safe ways to reference a possibly-unset variable on purpose.
- **`-o pipefail`:** without this, `grep pattern file | wc -l` "succeeds" even if `grep` itself failed (file not
  found), because bash by default only looks at the exit code of the *last* command in a pipe. This is the one
  people forget most often and the one that hides the most real failures.

## 2. Cleanup that actually always runs

```bash
tmpdir=$(mktemp -d)
cleanup() {
  local exit_code=$?
  rm -rf "$tmpdir"
  exit "$exit_code"
}
trap cleanup EXIT
```

`trap ... EXIT` fires on normal exit, `set -e` triggered exit, and Ctrl-C alike — a `trap ... ERR` only fires on
error, so if you only trap `ERR` your temp files leak on the success path's own subsequent failure or a signal.
Capture `$?` at the top of the handler before anything else changes it, and re-`exit` with that code so the
script's own exit status is preserved for whatever's waiting on it.

## 3. Safe iteration — the #1 source of bash bugs in the wild

Never do this:
```bash
for f in $(ls *.txt); do ...       # breaks on spaces, breaks on globs matching nothing
files=$(find . -name '*.log')
for f in $files; do ...            # same problem
```

Do this instead:
```bash
# Arrays for a known, static list
files=(*.txt)
for f in "${files[@]}"; do
  [[ -e "$f" ]] || continue   # guard against the glob matching nothing
  ...
done

# find + null-delimited for dynamic discovery (handles spaces, newlines, anything in a filename)
find . -name '*.log' -print0 | while IFS= read -r -d '' f; do
  ...
done
```

The `-print0` / `read -d ''` pairing is the one to reach for by default whenever filenames come from `find` —
it's the only combination immune to spaces and newlines in names.

## 4. Parallelism

**Simple fan-out, don't need per-job control:**
```bash
printf '%s\n' "${items[@]}" | xargs -P 8 -I {} process_one.sh {}
```
`-P 8` runs up to 8 in parallel; tune to core count for CPU work, higher for I/O-bound work waiting on network.

**Need per-job success/failure tracking, or the jobs are shell functions not separate scripts:**
```bash
pids=()
for item in "${items[@]}"; do
  process_one "$item" &
  pids+=($!)
done
failures=0
for pid in "${pids[@]}"; do
  wait "$pid" || ((failures++))
done
echo "Done: $failures failures out of ${#pids[@]}"
```
`wait "$pid"` returns that specific job's exit code — a bare `wait` with no argument waits for everything but
only tells you if *any* failed, not which one.

## 5. Retry with backoff (as a reusable function, not a copy-pasted sleep loop)

```bash
retry() {
  local max_attempts=$1 delay=$2; shift 2
  local attempt=1
  until "$@"; do
    if (( attempt >= max_attempts )); then
      echo "Failed after $max_attempts attempts: $*" >&2
      return 1
    fi
    echo "Attempt $attempt failed, retrying in ${delay}s..." >&2
    sleep "$delay"
    delay=$(( delay * 2 ))   # exponential backoff
    ((attempt++))
  done
}

retry 5 2 curl -sf https://example.com/health
```
Add jitter (`sleep "$(( delay + RANDOM % delay ))"`) if multiple instances of this script might retry the same
dependency at the same time — without it they all hammer the dependency in lockstep on the same schedule.

## 6. Locking against concurrent runs

```bash
exec 200>/var/lock/myscript.lock
flock -n 200 || { echo "Already running" >&2; exit 1; }
```
This is a real kernel-level advisory lock, released automatically if the process dies — unlike a `.pid` file,
which requires you to check-then-act (a race: two processes can both check "no lock file" before either creates
one) and doesn't clean up after a crash.

## 7. Argument parsing that doesn't fall apart past 3 flags

```bash
usage() { echo "Usage: $0 --input FILE [--verbose]" >&2; exit 1; }

verbose=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --input) input="$2"; shift 2 ;;
    --verbose) verbose=true; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown arg: $1" >&2; usage ;;
  esac
done
[[ -n "${input:-}" ]] || usage
```
Past this level of complexity (subcommands, many flags with types), stop — write it in Python with `argparse`
instead. Bash argument parsing does not scale gracefully.

## 8. Logging

```bash
log() { printf '%s [%s] %s\n' "$(date -u +%FT%TZ)" "${1}" "${*:2}" >&2; }
log INFO "starting run"
log ERROR "connection failed"
```
Logs to stderr (so stdout stays clean for piping actual output), ISO-8601 UTC timestamps (sortable, unambiguous
across timezones), a level tag so you can `grep ERROR` the log later.

## 9. Quoting — the rule that has no exceptions

Every variable expansion gets double quotes: `"$var"`, `"${array[@]}"`, `"$(command)"`. The only place you
*don't* quote is when you specifically want word-splitting or glob expansion, which should be rare enough that
you comment why when you do it. An unquoted `$var` containing a space, `*`, or nothing at all (empty/unset) is
where "works on my machine" scripts go to die on someone else's.

## 10. Portability: bash vs POSIX sh

If the shebang is `#!/bin/sh`, arrays, `[[ ]]`, `local`, and process substitution `<(...)` are not guaranteed —
`sh` might be dash, which doesn't have them. If you need any of those (and you usually will for anything
non-trivial), the shebang must be `#!/usr/bin/env bash`, and the script must actually be run as bash, not
sourced into a POSIX-sh context. Mixing these is a common source of "works when I run it, breaks in CI."

## 11. Testing bash scripts

`shellcheck script.sh` catches the large majority of the bugs in this document automatically — run it as a
matter of course, not just when something's already broken. For actual behavioral tests (not just linting),
`bats` (Bash Automated Testing System) gives you a real test framework:

```bash
@test "retry succeeds on the 3rd attempt" {
  count=0
  fail_twice() { ((count++)); [[ $count -ge 3 ]]; }
  run retry 5 0 fail_twice
  [ "$status" -eq 0 ]
}
```

## 12. Signal handling for long-running scripts

```bash
running=true
trap 'running=false' TERM INT
while $running; do
  do_work
done
echo "Shutting down gracefully"
```
Lets a long-running script finish its current unit of work and exit cleanly on `SIGTERM`/Ctrl-C instead of being
killed mid-write — this is the bash equivalent of graceful shutdown in a microservice, same reasoning: an
in-flight operation killed mid-way is how you get corrupted output.

## 13. `set -e` and `&&`/`||`/assignments — the precise rules, empirically verified

An earlier version of this file had part of this backwards. It was corrected after an independent field test
(a different agent, a different model, running this skill against real production scripts) hit the exact bug
this section used to wave away as safe, and after direct reproduction here confirmed the field test was right
and the doc was wrong. Every claim below was verified by actually running it, not inferred from the bash manual
— if you doubt one, the repro is one line, run it.

**`cmd_that_can_fail && next_cmd` (or `||`) is genuinely unpredictable — don't try to memorize when it's "safe."**
This file tried twice to state a clean positional rule for exactly this ("safe unless it's the last command in
scope") and disproved its own rule both times by just running more examples. Two verified reproductions that look
almost identical and behave oppositely:

```bash
# Crashes — a for-loop body, NOT the function's last statement, more code runs after the loop:
set -e; failures=0
f() { for pid in a b c; do false || ((failures++)); done; echo "after loop"; }
f; echo "after f"                                    # → NEITHER echo prints, exit 1

# Does NOT crash — a boolean-flag guard, also inside a loop, also not the last statement:
set -e; verbose=false
f() { for x in a b c; do $verbose && echo "skipped"; done; echo "after loop"; }
f; echo "after f"                                    # → both echoes print, exit 0
```
The difference turned out to hinge on which side of `&&`/`||` actually *executes* and fails (a failing LHS that
short-circuits away the RHS tends to be exempt; a RHS that runs and itself fails tends not to be) — but by this
point three different "clean rules" attempted for this section have each been falsified by a next example, which
is itself the useful data point: **the actual boundary is inconsistent enough across superficially similar code
that memorizing it is not a reliable engineering strategy.** Two independent sources converged on hitting real
bugs from exactly this pattern (a field test running this skill against production scripts, and this file's own
attempt to precisely characterize the rule) — that convergence is the signal to stop trying to characterize it
and just avoid it.

**Fix: don't use `flag && cmd` / `cmd || side_effect` for control flow or side effects at all.** Use `if`/`fi` —
an `if` condition's exit status is never tested by `-e`, in any position, verified across every case in this
section:
```bash
if $verbose; then sf_log INFO "processing"; fi                    # boolean-flag guard, always safe
if ! wait "$pid"; then ((failures++)) || true; fi                 # side-effecting increment, always safe
```

**`var=$(failing_cmd)` as a plain top-level assignment DOES trigger `-e`** — this is the opposite of what's
commonly claimed (including, previously, here):
```bash
set -e
x=$(false)
echo "reached"                                        # never prints — script already exited, verified
```
**But `local var=$(failing_cmd)` inside a function does NOT trigger `-e` — it silently swallows the failure
instead**, which is arguably worse than exiting:
```bash
set -e
f() { local x=$(false); echo "x=$x, still running"; }
f; echo "reached after f"                              # BOTH echoes print, x is empty, no error anywhere
```
This is `local`'s own exit status masking the assignment's — `local` is a command, and its exit status is what
`-e` actually observes, not the command substitution's. (This is the well-known ShellCheck SC2155 rule —
"declare and assign separately" — for exactly this reason.) Fix: split the declaration from the assignment when
the command can fail and you need to know:
```bash
local x
x=$(some_command_that_can_fail) || { sf_log ERROR "failed"; return 1; }
```

**A command substitution used directly as a test/condition is genuinely exempted**, no caveat:
```bash
set -e
if [[ -n "$(false)" ]]; then echo yes; else echo no; fi
echo "reached"                                         # prints "no" then "reached", exit 0 — this one's fine
```

## 14. Portable library sourcing

A script built against this library should still run if copied somewhere `lib/core.sh` isn't installed
alongside it — don't assume the deployment target has systems-forge. Detect and fall back — but the naive
one-liner for this is itself a live instance of §13's exact bug:

```bash
# BROKEN: this looks like a safe detect-and-fallback, but if ../lib genuinely
# doesn't exist, the `cd` inside the substitution fails, and per §13 that's a
# plain top-level assignment with a failing substitution — it exits the
# WHOLE SCRIPT right here, never reaching the `if` that was supposed to
# handle exactly this case. Caught only by actually running it against a
# copy with no lib/ next to it, not by reading the line.
SF_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")/../lib" 2>/dev/null && pwd)/core.sh"
if [[ -f "$SF_LIB" ]]; then ...
```

```bash
# CORRECT: never `cd` into the maybe-missing directory. Only `cd` into this
# script's OWN directory, which always exists (the script is running from
# there) — then string-append the possibly-missing lib/ path. No command
# substitution can fail here, because there isn't one after the first line.
SF_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SF_LIB="$SF_SCRIPT_DIR/../lib/core.sh"
if [[ -f "$SF_LIB" ]]; then
  source "$SF_LIB"
else
  sf_log() { printf '%s [%s] %s\n' "$(date -u +%FT%TZ)" "${1}" "${*:2}" >&2; }
  # ...inline any other sf_* function this specific script actually calls
fi
```
Both versions were run against a real copy of a script with no sibling `lib/` directory before this claim was
written — the first one exits silently at the `SF_LIB=` line every time; the second reaches the `if` and falls
back correctly every time. `scripts/bash-template.sh` ships the correct version.
