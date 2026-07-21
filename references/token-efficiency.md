# Token Efficiency (2026 research synthesis)

Cutting tokens is not the goal — cutting tokens *without losing accuracy* is, and the research is specific about
where that line sits. Get this wrong (compress the wrong thing, or too aggressively) and hallucination rate goes
up, not down. Get it right and cost/latency drop 30-90% with equal or better accuracy. This file is about the
second outcome.

## Where the tokens actually go — compress THAT, not the instructions

Tool observations (file contents, command output, search results) dominate an agent's context, "frequently
consuming 70-80% of the available token budget" in long-running sessions — not the system prompt, not the
instructions. **The highest-leverage token-efficiency habit is fetching only what's needed in the first place:**

- `grep -A5 -B5 pattern file` (or `rg -C5`) instead of `cat file` when you only need the match and its
  surroundings — the difference between reading 10 relevant lines and 2,000 irrelevant ones.
- Read a function/section, not a whole file, when you already know where the relevant code lives.
- Once information has been extracted from a tool result and acted on, don't re-paste or re-quote the raw output
  again later in the same task — refer back to the conclusion, not the evidence.
- Don't re-run a search you already have the answer to (this is also a named failure pattern in
  `references/agentic-tool-use-efficiency.md` — it's inefficient AND it's the specific behavior separating
  successful agents from failing ones in the research cited there).

## Compression is safe — in a specific, bounded range

Prompt-compression research found **moderate compression (2-6x) preserves or even improves accuracy** — one
study showed a benchmark score *improve* from 64.1% to 75.0% under 4x compression, because removing redundancy
reduces noise and mitigates the "lost in the middle" effect where a long, padded context makes a model miss
what matters. **Aggressive compression (>10x) is where it breaks** — "pronounced information loss," rising
hallucination. The mechanism matters too: compression has to be *task-aware* — one study found accuracy dropped
35-45 percentage points when the compression step wasn't told what the task actually needed, versus compression
that kept task-relevant content and cut only what wasn't. The takeaway that applies directly to how this skill
itself is written: cutting a redundant sentence is safe and often net-positive; cutting the stated *reason*
behind a rule is not — the reasoning is exactly the "task-relevant" information that lets a rule generalize
correctly to a case that doesn't match its example verbatim (see `SKILL.md`'s own writing style, and
`skill-creator`'s guidance on the same point — this isn't a coincidence, both are the same finding).

## Scheduled compaction beats letting history grow unbounded

For long agent sessions, research on explicit compaction scheduling found compressing every 10-15 tool calls hit
a sweet spot: ~22.7% token savings while matching baseline accuracy — frequent enough to stay ahead of context
pressure, infrequent enough not to pay the compaction cost needlessly on short tasks. The failure mode on the
other side (never compacting) is documented as "working-memory rot": a long-running agent's context degrades
under its own accumulated trace, and in multi-agent chains this cascades — Agent A hands a degraded context to
Agent B, which starts from an already-worse position. Summarizing a completed sub-task's outcome and discarding
its raw transcript (see `references/agentic-patterns.md`'s context-management section) is the practical
implementation of this — do it as a matter of routine on long tasks, not only once something visibly breaks.

## Prompt caching: the single biggest lever if you're calling an LLM API repeatedly

If you're building anything that calls an LLM API more than once with an overlapping prefix (a multi-turn agent,
a batch classifier, a tool-definition-heavy system) — prompt caching is worth designing for from the start, not
retrofitting:

- **Static content first, dynamic content last.** System instructions, tool definitions, and anything that's
  byte-identical across calls go at the front of the prompt; the actual per-call variable content (the user's
  latest message, this call's specific data) goes at the end. The cache is keyed on a byte-identical prefix — if
  dynamic content is interleaved earlier in the prompt, every call invalidates the cache and pays full price.
  This is architecture, not a flag to flip after the fact — restructuring an already-built prompt pipeline to
  separate static from dynamic content is real, avoidable rework.
- **The economics are real, not marginal:** cached input tokens run roughly 10% of the cost of uncached ones on
  major providers as of 2026, and latency on a cache hit drops significantly because the expensive prefill step
  is skipped, not just billed differently. It pays off after as few as 2-3 requests reusing the same prefix — a
  single-shot script doesn't benefit, but anything looping or serving repeat requests does.
- **This directly informs how to write a system prompt or tool-definitions block for any agent you build**
  (see `systems_forge/agents/` for the MCP server / orchestrator patterns this skill ships): keep the
  instructions and tool schemas stable across calls, and put the part that actually changes call-to-call — the
  live task, the current file content, the latest observation — at the end where cache invalidation is
  contained to just that tail.

## Cross-agent portability and this same file's own length

This skill ships an `AGENTS.md` at its root specifically because most non-Claude-Code agents (Codex, Cursor,
Cline, Aider, and others — see `AGENTS.md` for the full list) load a project's agent-instructions file in full,
every time, with no progressive disclosure the way Claude Code's skill system has for `references/*.md`. That's
exactly why `AGENTS.md` is deliberately denser than this file: every token in it is paid on every single load by
every agent that reads it, while this file and the other `references/*.md` files cost nothing until something
actually asks for the depth. Write dense, compressed content for whatever loads unconditionally; write normally
thorough content for whatever loads on demand — the same compression research above says which parts of *that*
dense file should stay reasoning-rich (the load-bearing "why"s) versus which parts are safe to cut (repeated
framing, redundant examples).
