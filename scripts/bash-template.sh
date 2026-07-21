#!/usr/bin/env bash
#
# Systems Forge bash scaffold — copy this file as the starting point for any
# non-trivial script instead of a blank page. Delete what you don't need;
# adding safety back in later is much harder than removing unused scaffolding.
#
# See references/bash-patterns.md for the reasoning behind each piece below.

set -euo pipefail
IFS=$'\n\t'

# ── Portable library sourcing (works whether systems-forge is installed
#    alongside this script or not — verified pattern, see bash-patterns.md
#    §13) ─────────────────────────────────────────────────────────────────
# Two steps on purpose: only `cd` into THIS script's own directory, which
# always exists (the script is running from there) — never into the
# possibly-missing lib/ dir itself. A one-line version that does
# `cd ".../../lib" && pwd` inside the same substitution looks equivalent
# but silently exits the whole script under `set -e` when that lib/ dir
# doesn't exist (verified — see bash-patterns.md §13/§14); this doesn't.
SF_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SF_LIB="$SF_SCRIPT_DIR/../lib/core.sh"
if [[ -f "$SF_LIB" ]]; then
  source "$SF_LIB"
else
  # Minimal inline fallback so this script still runs standalone if copied
  # somewhere systems-forge isn't installed. sf_retry here matches
  # lib/core.sh's real one (same backoff+jitter) — keep them in sync if you
  # ever change one.
  sf_log() { printf '%s [%s] %s\n' "$(date -u +%FT%TZ)" "${1}" "${*:2}" >&2; }
  sf_retry() {
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
fi

# ── Cleanup: runs on success, failure, AND signals (trap EXIT, not just ERR) ─
tmpdir=$(mktemp -d)
cleanup() {
  local exit_code=$?
  rm -rf "$tmpdir"
  exit "$exit_code"
}
trap cleanup EXIT
trap 'sf_log ERROR "failed at line $LINENO: $BASH_COMMAND"' ERR

# ── Argument parsing ─────────────────────────────────────────────────────
usage() {
  cat >&2 <<EOF
Usage: $(basename "$0") --input FILE [--verbose] [--dry-run]

  --input FILE   required. path to input.
  --verbose      optional. print extra logging.
  --dry-run      optional. print what would happen, don't do it.
EOF
  exit 1
}

verbose=false
dry_run=false
input=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input) input="$2"; shift 2 ;;
    --verbose) verbose=true; shift ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage ;;
    *) sf_log ERROR "unknown argument: $1"; usage ;;
  esac
done

[[ -n "$input" ]] || usage
[[ -e "$input" ]] || { sf_log ERROR "input does not exist: $input"; exit 1; }

# ── Optional: lock against concurrent runs (uncomment if this script must
#    not run twice at once — e.g. it mutates shared state) ─────────────────
# exec 200>/tmp/"$(basename "$0")".lock
# flock -n 200 || { sf_log ERROR "already running"; exit 1; }

# Retry: sf_retry from the sourced library (or the fallback above) —
# exponential backoff + jitter. Example: sf_retry 5 2 curl -sf "$url"

# ── Main work ─────────────────────────────────────────────────────────────
main() {
  # NOT `$verbose && sf_log ...` — verified real bug (bash-patterns.md §13):
  # if that && chain is ever the LAST command run in this function (e.g.
  # after deleting the lines below during a rewrite), a false left-hand
  # side makes the function's own return status 1, and set -e kills the
  # script even though nothing "failed." `if`/`fi` has no such trap.
  if $verbose; then
    sf_log INFO "processing $input"
  fi

  if $dry_run; then
    sf_log INFO "[dry-run] would process $input"
    return 0
  fi

  # Replace this with the script's actual work. Use "$tmpdir" for any
  # scratch files — cleanup() removes it automatically no matter how the
  # script exits.
  sf_log INFO "done: $input"
}

main
