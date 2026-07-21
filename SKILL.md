---
name: systems-forge
description: Real, tested bash+Python systems-engineering library (resilience, concurrency, DSA, modern-CLI detection, agentic-AI/MCP patterns, hooks) plus a cross-agent AGENTS.md — not prose to retype. Use whenever writing, reviewing, or debugging a script, service, microservice, or agent/MCP workflow, or picking a CLI tool, or trying to cut token cost — even on bare requests like "write a script," "automate this," "build an agent," "make this reliable," "clean this up," or "use fewer tokens," with no domain named explicitly.
---

# Systems Forge

Most code that an agent writes *runs*. Far less of it *survives* — a retry storm, a half-written file after a
crash, a shell injection from an unquoted variable, an agent that burns a budget because nothing was watching.
This skill exists to close that gap: not "how do I write bash" but "how does someone who has been paged at 3am
write bash." Apply it whenever the work will run more than once, run unattended, run on someone else's machine,
or run as part of a larger system.

**The one meta-principle that overrides everything else below:** verify, don't assume. Run the script. Read the
real output. A change that "should work" is not the same claim as one you watched work. This applies as much to
using this skill's own patterns as to anything else — don't paste a pattern from here without checking it fits
the actual situation.

## Works outside Claude Code too

This skill's actual capability — `systems_forge/` and `lib/core.sh` — is plain Python and bash with zero
Claude-Code-specific assumptions; any agent that can read a directory and run a shell command can import or
source it. For agents that don't have Claude Code's progressive-disclosure skill system (Codex CLI, Cursor,
Cline, Aider, Windsurf, and others — all of which read the `AGENTS.md` convention natively), this skill also
ships **`AGENTS.md`** at its root: a dense, single-file version of this same guidance meant to be loaded in
full, since those tools don't lazy-load a `references/` directory the way this file does. If you're operating as
one of those agents, or setting this up for one, start there instead of here.

## The library — import it, don't retype it

Everything below is backed by a real, tested, typed library shipped with this skill, not just prose to transcribe
into a fresh implementation every time:

- **`systems_forge/`** — an installable Python package (`uv sync` inside that directory, or `uv pip install -e
  systems_forge/` from anywhere) with `resilience.py` (CircuitBreaker, TokenBucket, retry/async_retry with
  backoff+jitter, IdempotencyStore), `dsa.py` (UnionFind, Trie, ConsistentHashRing, BloomFilter), `concurrency.py`
  (bounded_gather, race), `tooling.py` (modern-CLI-tool detection with fallback), and `agents/` (a real MCP
  server and a real supervisor/worker orchestrator — see below). 53 tests, mypy `--strict` clean, ruff clean —
  run `uv run pytest` inside `systems_forge/` to see them pass.
- **`lib/core.sh`** — a sourceable bash library (`source lib/core.sh`), not a copy-paste template: `sf_log`,
  `sf_retry`, `sf_with_lock`, `sf_circuit_call` (a bash-native circuit breaker backed by a state file — rare to
  see done correctly), `sf_parallel_run` (bounded fan-out with real per-job failure tracking), `sf_with_tmpdir`
  (guaranteed cleanup via a subshell — an earlier version of this function had a real bug where `trap ... EXIT`
  was scoped to the whole calling script instead of just this call, caught by `lib/test_core.sh` actually
  checking the directory was gone immediately, not just trusting the trap existed), `sf_best_tool` (modern-CLI
  detection with fallback, bash side of the same pattern as `tooling.py`). 16 tests, all passing.

**Default to importing/sourcing these over writing the pattern fresh.** Writing it again from the description in
this file risks reintroducing a bug this file's own testing already found and fixed once (the `sf_with_tmpdir`
trap-scoping bug is the clearest example — the fix is subtle enough that a fresh implementation is likely to
repeat it). `scripts/bash-template.sh` and `scripts/python-template.py` are still the right starting point for a
brand-new script's boilerplate (arg parsing, logging setup) — they just shouldn't reimplement retry, circuit
breaking, or rate limiting inline when the library already has a tested one.

## Picking a tool

| Need | Reach for |
|---|---|
| Orchestrating other programs, file/process/text manipulation, glue between CLI tools | Bash |
| Anything with real data structures, error handling depth, or that will grow past ~50 lines | Python |
| Parallel I/O-bound work (API calls, file I/O) | Python `asyncio`, or bash `xargs -P` for simple fan-out |
| CPU-bound parallel work | Python `multiprocessing` (never `threading` — the GIL makes it pointless for CPU work) |
| A tool other agents/services will call programmatically | Python with a real CLI framework (`argparse`/`click`/`typer`), not a bash script with positional args |

If you're reaching for bash past ~100 lines, past your third nested conditional, or past needing a real data
structure (not just arrays), stop and write Python instead. Bash's failure mode past that size is silent and ugly.

## Core principles (apply everywhere, not just to one language)

1. **Fail loud, fail fast.** Bash: `set -euo pipefail` at the top of every script, always — see
   `references/bash-patterns.md` for the gotchas this doesn't cover on its own. Python: let exceptions propagate
   unless you have a specific, named reason to catch one; never a bare `except:`.
2. **Idempotency by default.** Design every script so running it twice produces the same end state as running it
   once — write to a temp file and atomic-rename instead of appending, use `INSERT ... ON CONFLICT` instead of
   `INSERT`, check-then-act only inside a lock. This is what makes retries safe instead of dangerous.
3. **Quote everything, trust nothing.** Every unquoted `$variable` in bash is a word-splitting and glob-expansion
   bug waiting for a filename with a space in it. Every `shell=True` in Python `subprocess` is an injection risk
   waiting for user input. Neither is optional hardening — both are correctness bugs from day one.
4. **Small composable units over monoliths.** A script that does one thing and can be piped, tested, and re-run
   independently is worth more than a 400-line script that does everything — this is true for shell scripts and
   for microservice boundaries alike, same principle at different scales.
5. **Verification is part of the deliverable, not an afterthought.** A script isn't done when it's written; it's
   done when you've run it against something real and read the output. See the checklist at the bottom.

## Bash — the patterns that separate "runs" from "survives"

Every script starts with this header, non-negotiable:

```bash
#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'
trap 'echo "FAILED at line $LINENO: $BASH_COMMAND" >&2' ERR
```

Why each line: `-e` exits on any unhandled non-zero status; `-u` turns unset-variable typos into errors instead
of silent empty strings; `-o pipefail` makes a failure anywhere in a pipe fail the whole pipe (without it,
`false | true` "succeeds"); the `IFS` change stops word-splitting on spaces inside loops; the trap turns a script
that dies silently into one that tells you exactly where. **None of this is enough on its own** — `set -e` does
NOT propagate through a command substitution used as a condition, a function called in an `if`, or the last
command before a pipe unless `pipefail` is also set. Read `references/bash-patterns.md` before assuming `set -e`
alone makes a script safe; that assumption is the single most common bash reliability bug.

Start a brand-new script from `scripts/bash-template.sh` for the boilerplate (arg parsing, logging, cleanup
trap). For retry, locking, circuit-breaking, or parallel fan-out, `source lib/core.sh` and call `sf_retry`,
`sf_with_lock`, `sf_circuit_call`, `sf_parallel_run` directly — tested, don't reimplement:

```bash
source /path/to/systems-forge/lib/core.sh
sf_retry 5 2 curl -sf https://example.com/health
sf_with_lock /tmp/myjob.lock ./do_the_actual_work.sh
sf_circuit_call flaky-api 60 curl -sf https://flaky-api.example.com/status
```

**High-frequency patterns** (full depth, more patterns, and the "why" behind each in `references/bash-patterns.md`):
- Iterate files/args safely: arrays and `find ... -print0 | xargs -0`, never parse `ls`, never bare `for f in $(...)`.
- Parallel fan-out: `sf_parallel_run` (per-job failure tracking) or `xargs -P N` for simple fire-and-forget cases.
- Retry with backoff: `sf_retry` from the library, not a hand-rolled sleep loop copy-pasted per script.
- Cleanup that always runs: `trap cleanup EXIT` (not just `ERR` — EXIT fires on success, failure, and Ctrl-C
  alike) — or `sf_with_tmpdir` if all you need is a scratch directory cleaned up automatically.
- Locking against concurrent runs: `sf_with_lock`, real `flock`-based, not a `.pid` file you check-then-act on.

## Modern tool selection — reach for the better tool, but detect it first

The classic Unix toolkit has faster, more ergonomic 2026 replacements — but a script that calls one directly
with no fallback breaks the moment it runs somewhere those aren't installed (a bare CI container, a teammate's
fresh box). Detect, don't assume:

```bash
grep_cmd=$(sf_best_tool rg grep) || exit 1   # bash: source lib/core.sh first
```
```python
from systems_forge.tooling import best_tool
grep_cmd = best_tool("rg", "grep")
```

| Need | Reach for | Why |
|---|---|---|
| Search text/code | `rg` (ripgrep) | `.gitignore`-aware, 3-5x faster than `grep -r`, skips binaries automatically |
| Find files | `fd` | Regex by default, `.gitignore`-aware, far less punctuation than `find` |
| Find-and-replace | `sd` | No delimiter escaping, familiar regex syntax, 2-11x faster than `sed` |
| Structural code search/rewrite across many files | `ast-grep` (`sg`) | Matches AST shape, not text — survives reformatting and renamed-but-structurally-identical siblings, which a regex-based rename does not |
| Review a diff for the real semantic change | `difftastic` | Diffs by syntax, not lines — a reformat or moved block doesn't drown the actual change |
| Complex parallel fan-out (ordering, retries, odd filenames) | GNU `parallel` | Handles special characters and job control that `xargs -P` struggles with |

Full table, the macOS-bash-3.2 portability gotcha, and the GNU-parallel/moreutils-parallel naming collision are
in `references/modern-cli-tools.md`.

## Editing efficiently — what 2026 research says actually works

- **Anchor edits on unique content, never on line numbers.** Line-numbered diffs are the least reliable LLM edit
  format in controlled comparisons — a line number is a claim about position, the most volatile fact about a
  file mid-edit. Search-and-replace on a unique string (what this skill's own edits, and Claude Code's Edit tool,
  already do) measurably outperforms it.
- **For a refactor spanning many files with the same pattern, prefer structural search (`ast-grep`) over a
  regex-based find-and-replace** — same reasoning as above: anchored on the real shape of the thing being
  changed, immune to reformatting.
- **Verify before declaring anything done** — research on coding-agent behavior specifically identifies this
  (not raw model capability) as the strongest predictor of success vs. failure. See
  `references/agentic-tool-use-efficiency.md` for the full synthesis, including the most dangerous failure mode
  (code that runs without error but silently doesn't do what was asked) and why hallucinating a missing input
  (an env var, an API key) instead of asking or failing loudly is a named, avoidable failure pattern.

## Token efficiency — cut cost without cutting accuracy

Tool output (file reads, command results), not the instructions, is what dominates a long agent session's token
budget — fetch only what's needed (`grep -C5`/`rg -C5` over `cat`), don't re-quote information you already
extracted, don't re-run a search you already have the answer to. Moderate compression (2-6x) of *redundant*
content is safe and can even improve accuracy by cutting noise; aggressive compression (>10x) or compressing
away the *reason* behind a rule measurably hurts — that reasoning is what lets a rule generalize to a case that
doesn't match its example exactly. If you're building anything that calls an LLM API repeatedly, structure the
prompt with static content (instructions, tool schemas) first and dynamic content (the actual per-call data)
last — that's what makes prompt caching work, and it's roughly 10x cheaper per cached token on top of a real
latency win. Full research synthesis: `references/token-efficiency.md`.

## Python — systems programming baseline (2026)

- **Tooling:** `uv` for environments and dependency management (faster and more reliable than `pip`+`venv`
  directly, has been the practical default since 2025). `ruff` for lint+format in one tool. `pyproject.toml` as
  the single source of config, not scattered `setup.py`/`setup.cfg`/`requirements.txt`.
- **Paths:** `pathlib.Path`, never `os.path` string concatenation — `Path` objects compose safely across
  platforms and catch a whole class of path-joining bugs at the type level.
- **Subprocess:** `subprocess.run([...], check=True, capture_output=True, text=True)` — a list of args, never a
  shell string; `shell=True` is only for when you genuinely need shell features (globbing, pipes) and even then
  needs `shlex.quote()` on anything user-influenced.
- **Concurrency:** `asyncio.TaskGroup` (3.11+) for structured concurrency — it cancels sibling tasks automatically
  if one fails, which a bare `asyncio.gather()` does not do by default and is exactly the kind of thing that leaks
  a hung connection in production. For CPU-bound work, `concurrent.futures.ProcessPoolExecutor`, never threads.
- **Typing:** full type hints + `mypy --strict` or `pyright` on anything meant to last — not for pedantry, but
  because a typed function signature is executable documentation the next reader (human or agent) doesn't have
  to reverse-engineer from the implementation.
- **Data modeling:** `dataclasses` for simple internal structures, `pydantic` when you need real validation at a
  boundary (API input, config file, LLM tool-call output — anywhere untrusted structure enters the system).
- **Errors:** custom exception hierarchies over string-matching error messages; log the exception with
  `logging.exception()` inside the `except` block so the traceback isn't lost.

Start a brand-new script from `scripts/python-template.py` for the boilerplate. For resilience/concurrency
primitives, import from the real package instead of rewriting them:

```python
from systems_forge.resilience import CircuitBreaker, TokenBucket, retry_with_backoff
from systems_forge.concurrency import bounded_gather
from systems_forge.dsa import ConsistentHashRing, BloomFilter
```

Full depth (structured concurrency patterns, testing with `pytest` + property-based testing via `hypothesis`,
packaging) is in `references/python-systems.md`.

## DSA patterns — pick by symptom, not by name

The value of these patterns is recognizing *which real problem* they solve, not reciting the algorithm. Real,
tested implementations of the ones not already in the stdlib are in `systems_forge/dsa.py`
(`UnionFind`/`Trie`/`ConsistentHashRing`/`BloomFilter` — import them). Topological sort IS in the stdlib
(`graphlib.TopologicalSorter`, raises `graphlib.CycleError` on a cycle) — don't reimplement it. Full writeups
with the reasoning behind each in `references/dsa-patterns.md`; the lookup:

| Symptom in the system you're building | Pattern | 
|---|---|
| "How many requests in the last N seconds" | Sliding window (counter or log-based) |
| "Is this API call allowed right now" | Token bucket / leaky bucket rate limiting |
| "These N services depend on each other, what order do I start/build/migrate them in" | Topological sort (cycle = your config is broken, not the algorithm) |
| "These items belong to the same group, merge as I discover more links" | Union-Find (disjoint set) |
| "Give me the next-highest-priority job, cheaply, repeatedly" | Heap / priority queue |
| "Route or look up by prefix" (URL routing, config keys, autocomplete) | Trie |
| "Cache with a size limit, evict the right thing" | LRU (recency) or LFU (frequency) — know which one your access pattern actually needs |
| "Which service breaks if this one goes down" (blast radius) | Graph BFS/DFS over the dependency graph |
| "Distribute keys across N nodes, minimize reshuffling when N changes" | Consistent hashing |
| "Has this been seen before, at huge scale, false positives OK" | Bloom filter |
| "Best allocation of a limited resource across competing demands" | Dynamic programming (recognize the overlapping-subproblems shape first, don't force-fit) |

## Microservices resilience patterns

A service that only handles the happy path is a service that pages someone at 3am. `systems_forge/resilience.py`
has real, tested implementations of the circuit breaker and idempotency store below (including the half-open
probe bug fix — see its `release_probe()` docstring). Full depth in `references/microservices-patterns.md`; the
core set:

| Failure mode | Pattern |
|---|---|
| A dependency is slow or down, and you keep calling it anyway | Circuit breaker — stop calling after N failures, half-open probe to recover |
| A transient failure needs a retry, but naive retries synchronize into a thundering herd | Exponential backoff **with jitter** — without jitter, every client retries in lockstep |
| A request got retried and might have already succeeded | Idempotency keys — the caller sends one, the server dedupes on it |
| A multi-step operation crosses service boundaries and can't use a single DB transaction | Saga pattern (orchestrated or choreographed) with compensating actions |
| One slow dependency exhausts the connection pool shared by everything else | Bulkhead — separate pools/threads per dependency |
| A write and an event-publish need to be atomic but hit different systems | Outbox pattern — write the event to the same DB transaction, publish it asynchronously |
| Load exceeds capacity | Backpressure — reject or queue explicitly, don't silently degrade into timeouts everywhere |

## Agentic AI & autonomous agent patterns (2026)

This is the newest and fastest-moving category — the shape of "correct" here has changed significantly even in
the last year. Two real, runnable references ship with this skill, not just described patterns:

- **`systems_forge/agents/mcp_server.py`** — a working MCP server (built on the real `mcp` SDK) with a
  `check_budget` (peek) tool and a `spend_budget` (consume, idempotency-key-aware) tool, demonstrating the
  peek/consume separation below in actual protocol-level code. `uv run python -m systems_forge.agents.mcp_server`
  runs it over stdio; `tests/test_mcp_server.py` exercises it through the real `call_tool` path.
- **`systems_forge/agents/orchestrator.py`** — a real supervisor/worker orchestrator: dispatches independent
  subtasks to a bounded pool of async workers, retries failed subtasks individually with backoff, and returns a
  per-subtask result instead of losing everything to one failure. Copy the pattern of composing
  `bounded_gather` + `async_retry_with_backoff` from here rather than building fan-out-with-retry from scratch.

Full depth, including multi-agent orchestration topologies beyond supervisor/worker, in
`references/agentic-patterns.md`. The load-bearing ideas:

- **Pre-flight over after-the-fact.** Check a budget/permission/rate-limit *before* the action, not just log it
  after — the entire reason tools like RateGuard exist is that "record it after" doesn't stop the runaway loop
  that already spent the money.
- **Peek vs. consume are different operations.** A query that only checks state must never have the side effect
  of a query that consumes it (decrements a budget, marks a rate-limit hit) — conflating them is a subtle,
  hard-to-notice bug class specific to agent tool design.
- **Idempotent tool calls.** An LLM will retry a tool call after a timeout without knowing whether the first call
  actually completed — every tool with a side effect needs the same idempotency-key discipline as a
  microservices API, for the same reason.
- **Kill switches and budgets are not optional for anything autonomous.** Any agent that runs unattended needs an
  enforced ceiling (token budget, iteration count, wall-clock time) checked *inside* the loop, not just a
  polite instruction in the prompt telling it to stop.
- **Verification gates before irreversible actions.** A destructive or hard-to-reverse action (delete, force-push,
  send, pay) gets a distinct code path with an explicit confirmation step — this is a design pattern, not just a
  prompting instruction, because prompting alone is not a reliable safety boundary.
- **Multi-agent orchestration topologies**, pick by shape of the problem: supervisor/worker (one agent plans,
  many execute — good for parallelizable independent subtasks), pipeline (each agent's output is the next's
  input — good for staged transforms), blackboard (agents read/write a shared state store, converge
  asynchronously — good for exploratory/uncertain problems where the order of contributions isn't known upfront).

## Claude Code hooks — deterministic enforcement, not another prompt instruction

A hook runs regardless of what the model decided — that's the entire value over a prompt instruction, which the
model can misread or be talked out of. `PreToolUse` is the real security checkpoint (exit non-zero blocks the
call outright, before the model's intent matters); `PostToolUse` reacts after (auto-format, log); `Stop` is where
a verification pass belongs structurally instead of trusting the agent's own "looks done." The single most
valuable one for client-repo delivery work: a `PreToolUse` hook blocking any write outside the project root —
turns "I set up permissions safely" from a claim into something demonstrable. Full patterns, a real block-writes-
outside-root script, and how hooks relate to skills/subagents/MCP: `references/hooks-patterns.md`.

## Verification checklist — before calling anything from this skill "done"

- [ ] Ran it against real input, read the real output (not "should work")
- [ ] Ran it twice — confirmed the second run doesn't break, corrupt, or double-charge anything
- [ ] Checked what happens on partial failure (killed mid-run, network drop, disk full) — does it leave a
      recoverable state or a corrupted one?
- [ ] For bash: ran `shellcheck` if available; for Python: ran the type checker
- [ ] For anything with a retry: confirmed it has backoff and jitter, not a tight loop
- [ ] For anything autonomous/unattended: confirmed there's an enforced ceiling, not just a documented one
- [ ] If you modified anything under `systems_forge/` or `lib/`, re-ran the real test suites before trusting the
      change: `cd systems_forge && uv run pytest && uv run ruff check src tests && uv run mypy --strict src`,
      and `bash lib/test_core.sh`. The `sf_with_tmpdir` trap-scoping bug documented in its own source comment
      was caught by this exact test suite, not by reading the code and reasoning it looked right.
