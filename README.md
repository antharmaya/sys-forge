# systems-forge

**Code an agent writes should survive, not just run.**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-71%20passing-brightgreen)](systems_forge/tests)

A real, tested bash + Python systems-engineering library — circuit breakers, retry with jitter, an MCP server, a
supervisor/worker orchestrator, Claude Code hooks — plus a cross-agent operating contract (`AGENTS.md`) read by
Claude Code, Codex, Cursor, Cline, Aider, and Windsurf alike. Not prose to paste into a fresh implementation
every time. Import it.

```bash
curl -fsSL https://raw.githubusercontent.com/antharmaya/sys-forge/v0.2.3/install.sh | bash
```

Installs the skill to `~/.claude/skills/systems-forge`, self-tests the bash library on your machine, and
installs the Python package if `uv` or `pip` is present. Set `SYSTEMS_FORGE_HOME` to install elsewhere.

## What's inside

| Path | What it is |
|---|---|
| `SKILL.md` | The Claude Code skill entry point — progressive-disclosure guidance, points into `references/` as needed. |
| `AGENTS.md` | A dense, single-file version of the same guidance for any agent that reads that convention natively instead of loading `references/` lazily. |
| `systems_forge/` | The installable Python package — `resilience.py` (CircuitBreaker, TokenBucket, retry/async_retry with backoff+jitter, IdempotencyStore), `dsa.py` (UnionFind, Trie, ConsistentHashRing, BloomFilter), `concurrency.py` (bounded_gather, race), `tooling.py` (modern-CLI detection with fallback), `agents/` (a real MCP server + a supervisor/worker orchestrator). 53 pytest tests, mypy `--strict` clean, ruff clean. |
| `lib/core.sh` | A sourceable bash library, not a copy-paste template — `sf_retry`, `sf_with_lock`, `sf_circuit_call`, `sf_parallel_run`, `sf_with_tmpdir`, `sf_best_tool`. 18 tests via a dependency-free harness. |
| `references/` | Full-depth reference docs: bash patterns, Python systems programming, DSA, microservices resilience, agentic AI patterns, modern CLI tooling, token efficiency, Claude Code hooks. |
| `scripts/` | Boilerplate starting points (`bash-template.sh`, `python-template.py`) — arg parsing and logging setup, not reimplementations of what the library already has. |

## Install methods

```bash
# One command — installs the Claude Code skill + Python package
curl -fsSL https://raw.githubusercontent.com/antharmaya/sys-forge/v0.2.3/install.sh | bash

# From a clone of the tagged source
git clone --branch v0.2.3 https://github.com/antharmaya/sys-forge.git ~/.claude/skills/systems-forge

# Python library only (from a clone)
uv pip install ./systems_forge

# Bash library only
source lib/core.sh
```

## Verify it yourself

```bash
cd systems_forge && uv run pytest && uv run ruff check src tests && uv run mypy --strict src
bash lib/test_core.sh
```

71 tests, all passing, re-run before every change lands — see `SKILL.md`'s own verification checklist.

## License

MIT — see [LICENSE](LICENSE).
