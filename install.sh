#!/usr/bin/env bash
# systems-forge installer — one command, any Unix-like system (macOS, Linux; Windows via WSL/Git-Bash).
# Usage: curl -fsSL https://raw.githubusercontent.com/antharmaya/sys-forge/v0.2.3/install.sh | bash
#    or: SYSTEMS_FORGE_HOME=/custom/path bash install.sh
set -euo pipefail

SF_VERSION="0.2.3"
# Release archive of the tagged source on GitHub (contains no .git directory).
SF_URL="${SYSTEMS_FORGE_URL:-https://github.com/antharmaya/sys-forge/archive/refs/tags/v${SF_VERSION}.tar.gz}"
SF_DEST="${SYSTEMS_FORGE_HOME:-$HOME/.claude/skills/systems-forge}"

log() { echo "[systems-forge] $*"; }
die() { echo "[systems-forge] ERROR: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "missing required tool: $1"; }

need curl
need tar

log "installing v${SF_VERSION} to ${SF_DEST}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

log "downloading from ${SF_URL}"
curl -fsSL "$SF_URL" -o "$TMP_DIR/systems-forge.tar.gz" || die "download failed — check network / URL"

mkdir -p "$SF_DEST"
tar -xzf "$TMP_DIR/systems-forge.tar.gz" -C "$SF_DEST" --strip-components=1
log "skill files installed to $SF_DEST"

# Verify the bash library is actually sourceable and the test suite still passes on THIS machine,
# not just at build time — this skill's own principle (verify, don't assume) applied to its own install.
if bash "$SF_DEST/lib/test_core.sh" >/dev/null 2>&1; then
  log "bash library self-test: passed"
else
  log "WARNING: bash library self-test failed on this system — check bash version (needs 4.0+ for some features)"
fi

# Optional: install the Python library standalone (for direct import/CLI use outside Claude Code).
# Skipped by default if neither uv nor pip is present — the skill files alone are still fully usable.
if command -v uv >/dev/null 2>&1; then
  log "installing systems_forge Python package (uv)"
  (cd "$SF_DEST/systems_forge" && uv sync --quiet) || log "WARNING: uv sync failed, Python package not installed — skill files still work"
elif command -v pip3 >/dev/null 2>&1; then
  log "installing systems_forge Python package (pip)"
  pip3 install --quiet "$SF_DEST/systems_forge" || log "WARNING: pip install failed, Python package not installed — skill files still work"
else
  log "no uv/pip3 found — skipping standalone Python package install (skill files are still fully usable)"
fi

cat <<EOF

Done. systems-forge v${SF_VERSION} is installed at: ${SF_DEST}

  Claude Code:            picked up automatically from ~/.claude/skills/ — no further action.
  Codex / Cursor / other AGENTS.md-aware agents:
                          point your agent at ${SF_DEST}/AGENTS.md, or copy/symlink it
                          into your project root as AGENTS.md.
  Standalone Python use:  import systems_forge.resilience / .concurrency / .dsa / .tooling
  Standalone bash use:    source ${SF_DEST}/lib/core.sh

  Source: https://github.com/antharmaya/sys-forge

EOF
