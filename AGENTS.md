# systems-forge — agent instructions

Bash/Python systems-engineering library + patterns. Read by any AGENTS.md-aware agent (Codex CLI, Cursor,
Cline, Aider, Windsurf, Copilot, Zed, Devin, Claude Code, Junie). No progressive disclosure here — this whole
file loads every time, so it's dense on purpose. Deeper reasoning lives in `references/*.md`, loaded only when
you open it; don't hesitate to open one, it costs nothing until you do.

**Meta-principle, overrides everything below:** verify, don't assume. Run it, read the real output. Research
on coding-agent behavior (`references/agentic-tool-use-efficiency.md`) found this is THE strongest predictor of
success vs. failure — not raw model capability.

## Use the library. Don't retype the pattern.

- **`systems_forge/`** — installable Python package (`uv sync` in that dir, or `uv pip install -e systems_forge/`).
  `resilience.py` (CircuitBreaker, TokenBucket, retry/async_retry+jitter, IdempotencyStore), `dsa.py` (UnionFind,
  Trie, ConsistentHashRing, BloomFilter), `concurrency.py` (bounded_gather, race), `tooling.py` (CLI-tool
  detection+fallback), `agents/` (real MCP server + supervisor/worker orchestrator). 53 tests, mypy `--strict`
  clean, ruff clean. `uv run pytest` to re-verify before trusting any change.
- **`lib/core.sh`** — sourceable bash (`source lib/core.sh`): `sf_log`, `sf_retry`, `sf_with_lock`,
  `sf_circuit_call`, `sf_parallel_run`, `sf_with_tmpdir`, `sf_best_tool`. 16 tests, `bash lib/test_core.sh`.
- Writing the pattern fresh risks reintroducing a bug this library's own tests already found and fixed once
  (e.g. `sf_with_tmpdir`'s trap-scoping bug — `trap ... EXIT` is process-scoped, not function-scoped; the fix
  needed a subshell). Import/source instead of retyping.

## Core rules

1. **Fail loud, fail fast.** Bash: `set -euo pipefail` always (but know its gaps — doesn't propagate through a
   command-sub used as a condition, or the pre-pipefail last-pipe-stage; see `references/bash-patterns.md`).
   Python: let exceptions propagate; never a bare `except:`.
2. **Idempotent by default.** Same input run twice → same end state. Atomic write+rename, not append.
   `INSERT ... ON CONFLICT`, not `INSERT`. This is what makes retries safe instead of dangerous.
3. **Quote everything, trust nothing.** Unquoted `"$var"` in bash = word-splitting bug waiting for a space in a
   filename. `shell=True` in Python `subprocess` = injection risk. Both are correctness bugs, not hardening.
4. **Small composable units over monoliths.** Same principle at script scale and at microservice scale.
5. **Never hallucinate a missing input.** Unknown env var / API key / config value → ask or raise, never
   fabricate a plausible placeholder and continue. Named, documented failure pattern in production coding
   agents — silent-wrong is worse than loud-broken.
6. **Detect tools before using them.** `rg`/`fd`/`sd`/`ast-grep` aren't installed everywhere. `sf_best_tool` /
   `systems_forge.tooling.best_tool()` — never call a modern tool with no POSIX fallback.

## Bash quick reference

```bash
source lib/core.sh
set -euo pipefail; IFS=$'\n\t'
sf_retry 5 2 curl -sf https://example.com/health
sf_with_lock /tmp/job.lock ./work.sh
sf_circuit_call flaky-api 60 curl -sf https://flaky.example.com
grep_cmd=$(sf_best_tool rg grep) || exit 1
```
Safe iteration: arrays, `find ... -print0 | xargs -0` — never parse `ls`, never bare `for f in $(...)`.
Cleanup: `trap cleanup EXIT` (fires on success/failure/Ctrl-C, unlike `ERR`-only). Full depth:
`references/bash-patterns.md`.

## Python quick reference

```python
from systems_forge.resilience import CircuitBreaker, TokenBucket, retry_with_backoff
from systems_forge.concurrency import bounded_gather
from systems_forge.tooling import best_tool
```
`uv` for env/deps. `pathlib.Path`, never string-joined paths. `subprocess.run([...], check=True)`, arg list not
shell string. `asyncio.TaskGroup` (cancels siblings on failure — `gather()` alone doesn't). `mypy --strict` on
anything meant to last. Full depth: `references/python-systems.md`.

## Modern tools — reach for these, but detect first

| Need | Tool | Why |
|---|---|---|
| Search text/code | `rg` | `.gitignore`-aware, 3-5x faster than `grep -r` |
| Find files | `fd` | Regex default, `.gitignore`-aware |
| Find-and-replace | `sd` | No delimiter escaping, familiar regex syntax |
| Structural rewrite across files | `ast-grep` | Matches AST shape — survives reformatting, regex doesn't |
| Review a diff's real change | `difftastic` | Diffs by syntax not lines |
| Ordered/robust parallel fan-out | GNU `parallel` | Handles odd filenames `xargs -P` chokes on |

Full table + macOS-bash-3.2 gotcha + GNU-parallel/moreutils naming collision: `references/modern-cli-tools.md`.

## Editing: anchor on content, never on line numbers

Line-numbered diffs are the least reliable LLM edit format (line number = a claim about position, the most
volatile fact mid-edit). Exact-string search-replace on a unique anchor is measurably more reliable — this is
why Claude Code's own edit tool works this way. Include enough context to make the "old" string uniquely match
one place. For refactors across many files with the same pattern, prefer `ast-grep` over regex for the same
reason. Full research: `references/agentic-tool-use-efficiency.md`.

## Token efficiency

Tool output (file reads, command results) is 70-80% of a long agent session's token budget — not the
instructions. Fetch only what's needed (`grep -C5`, not `cat`), don't re-quote extracted info later, don't
re-run a search you already answered. Compress moderately (2-6x is safe, often improves accuracy by cutting
noise) — never strip the *reason* behind a rule, that's the part that lets it generalize to an edge case, not
redundant filler. Full depth incl. prompt-caching architecture (static-content-first for any repeat LLM calls
you build): `references/token-efficiency.md`.

## DSA — pick by symptom (real implementations in `systems_forge/dsa.py`)

| Symptom | Pattern |
|---|---|
| Rate/count in last N seconds | Sliding window or token bucket |
| Services depend on each other, need build/start order | `graphlib.TopologicalSorter` (stdlib — don't reimplement) |
| Merge groups as more links discovered | Union-Find |
| Next-highest-priority item, repeatedly | Heap |
| Lookup by prefix | Trie |
| Cache with eviction | LRU (recency) vs LFU (frequency) — know which fits the access pattern |
| Distribute keys across nodes, minimize reshuffle on scale | Consistent hashing |
| Seen-before at huge scale, false-positives OK | Bloom filter |

Full depth: `references/dsa-patterns.md`.

## Microservices resilience (real implementations in `systems_forge/resilience.py`)

Circuit breaker (with the half-open-probe release fix — see `CircuitBreaker.release_probe()` docstring),
retry+backoff+jitter, idempotency keys, saga w/ compensating actions, bulkhead, outbox, explicit backpressure.
Full depth: `references/microservices-patterns.md`.

## Agentic AI / autonomous agents (2026)

Real, runnable: `systems_forge/agents/mcp_server.py` (peek vs. consume tool separation + idempotency, on the
real `mcp` SDK), `systems_forge/agents/orchestrator.py` (supervisor/worker fan-out, bounded concurrency,
per-subtask retry, partial-failure results). Any autonomous/unattended agent needs an enforced budget/iteration
ceiling checked *inside* the loop — a prompt instruction to stop is not a reliable boundary. Full depth incl.
orchestration topologies: `references/agentic-patterns.md`.

## Deterministic enforcement layer (Claude Code: hooks; others: your agent's equivalent)

A prompt instruction is a request the model can misread or be talked out of; a deterministic enforcement layer
runs regardless of what the model decided. In Claude Code this is **hooks** (`PreToolUse` blocks a tool call
outright by exiting non-zero, before intent matters; `PostToolUse` reacts after; `Stop` is where a real
verification pass belongs instead of trusting the agent's own "looks done"). If you're a different agent
(Codex's approval policies, Cursor's rules, etc.), the exact mechanism differs but the principle transfers: for
anything where "the model usually gets this right" isn't a strong enough guarantee — most importantly, blocking
writes outside a project's own root during client-repo delivery work — use whatever deterministic layer your
harness provides, don't rely on a prompt line alone. Real example hook script + full depth (Claude Code
specifically): `references/hooks-patterns.md`.

## Wiring this into a project

If a project wants this library/guidance and uses its own `AGENTS.md`, add one line pointing here (e.g.
`See ~/.claude/skills/systems-forge/AGENTS.md for the bash/Python resilience+DSA+agentic library`) — AGENTS.md
resolution uses the nearest file to what's being edited, so this doesn't replace a project's own file, it
supplements it.

## Before calling anything done

Ran it against real input, read the real output. Ran it twice, confirmed idempotency. Checked partial-failure
behavior. Ran `shellcheck`/`mypy --strict` if touching bash/Python here. Retries have backoff+jitter. Anything
autonomous has an enforced ceiling. If you touched `systems_forge/` or `lib/`: `cd systems_forge && uv run
pytest && uv run ruff check src tests && uv run mypy --strict src`, and `bash lib/test_core.sh`.
