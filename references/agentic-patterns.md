# Agentic AI & Autonomous Agent Patterns (2026)

This is the fastest-moving category in this skill — "correct" here has shifted meaningfully even in the last
year as agents moved from single-shot chat to long-running, tool-wielding, multi-agent systems. The patterns
below are the load-bearing ones as of 2026, each grounded in a specific failure mode it prevents.

## The tool-use loop: ReAct and its descendants

The base pattern almost everything else builds on: **Reason → Act → Observe → repeat.** The agent reasons about
what to do next, calls a tool, observes the real result, and reasons again with that new information — as
opposed to planning the entire sequence upfront and executing blind. The reason this beats upfront planning for
most real tasks: the *observation* from step N often changes what step N+1 should be (a file didn't exist, an
API returned an unexpected shape, a search turned up something that reframes the task) — a plan made without
that information is a plan made with less information than is available by the time it matters.

```
loop:
    thought = reason_about(task, history)
    if thought.is_final_answer:
        return thought.answer
    observation = execute_tool(thought.tool_call)
    history.append((thought, observation))
```

## Planner-executor separation

For tasks big enough that a single flat ReAct loop loses coherence (loses track of the overall goal across many
steps), split into two roles: a **planner** that maintains the high-level goal and breaks it into subtasks, and
an **executor** (or several) that carries out each subtask with its own tight ReAct loop and reports back a
result, not a raw transcript. This is a context-management technique as much as an architecture one — the
planner's context stays small and focused on orchestration; each executor's context is scoped to just its
subtask and gets thrown away (or compacted to a summary) once it reports back, instead of one ever-growing
transcript that eventually crowds out the model's ability to attend to what actually matters.

## Multi-agent orchestration topologies — pick by problem shape

| Topology | Shape | When it fits |
|---|---|---|
| **Supervisor / worker** | One agent plans and delegates, N workers execute independent subtasks in parallel | Subtasks are genuinely independent and parallelizable — a broad research sweep, a refactor across many files |
| **Pipeline** | Agent A's output is Agent B's input, is Agent C's input | Staged transformation where each stage needs a different lens/expertise — draft → fact-check → copy-edit |
| **Blackboard** | Agents read and write a shared state store asynchronously, no central coordinator, solution emerges as contributions accumulate | Exploratory or uncertain problems where the right order of contributions isn't known upfront — competing hypotheses that need to be reconciled |
| **Adversarial / verification panel** | One agent produces, N independent agents critique or attempt to refute | Correctness-critical output where a single agent's confidence is not trustworthy evidence on its own — this is precisely why "a green test suite proves self-consistency, not truth" as a standalone check |

Picking the wrong topology for the problem shape is a common, avoidable inefficiency: a pipeline forced onto an
exploratory problem produces a plausible-sounding but under-explored answer; a supervisor/worker split forced
onto a genuinely sequential problem just adds coordination overhead with no parallelism to show for it.

## MCP server design — a few rules that keep tools safe to call

Since MCP (Model Context Protocol) became the standard way agents expose tools to each other in 2025-2026, a few
design rules have proven load-bearing across real deployments:

- **Peek and consume must be distinct tools, never conflated in one.** A tool that only *checks* state (is there
  budget left? is this rate-limited?) must never have the side effect of a tool that *consumes* it (decrements
  the budget, records the rate-limit hit). An agent calling what it believes is a read-only check should never
  accidentally spend something by asking — this exact conflation is a real, subtle bug class, not a hypothetical.
- **Every side-effecting tool needs an idempotency story.** The calling agent will retry after a timeout without
  knowing whether the first call actually completed server-side — the tool needs to either be naturally
  idempotent (setting a value is idempotent; incrementing a counter is not) or accept an idempotency key the
  same way a microservices API would (see `references/microservices-patterns.md`).
- **Transports should be byte-transparent where the payload isn't the tool's business.** A tool that proxies or
  wraps another API should pass bytes through unmodified rather than parsing, re-serializing, and re-emitting —
  every unnecessary parse/re-serialize step is a place subtle corruption or reformatting can creep in for data
  the tool was never meant to interpret in the first place.
- **Tool descriptions are the primary trigger mechanism, and they undertrigger by default.** An agent deciding
  whether to reach for a tool is reading the tool's description, not its implementation — a vague or
  conservative description gets skipped even when the tool is exactly right for the task. Err toward describing
  concrete trigger contexts explicitly rather than assuming the agent will infer relevance from a terse name.

## Autonomous agent guardrails — not optional past a certain point

Any agent that runs unattended (no human approving each step) needs enforcement, not just instruction:

- **Budget ceilings enforced in the loop, not just documented in the prompt.** A system prompt that says "stop
  after $10 of spend" is a suggestion the model can lose track of over a long context; an actual check inside
  the tool-call loop that refuses to proceed past the ceiling is a guarantee. The gap between these two is
  exactly the failure mode behind real "runaway agent" cost incidents — the fix is architectural (pre-flight
  enforcement in-process, checked before the spend, not a log line written after).
- **Iteration/wall-clock ceilings for the same reason** — an agent stuck in an unproductive loop (retrying the
  same failing action, or two agents passing work back and forth without converging) needs a hard stop that
  doesn't depend on the model itself noticing it's stuck.
- **A distinct, harder-to-reach code path for irreversible actions.** Deleting data, force-pushing, sending a
  message externally, moving money — these get an explicit confirmation gate in the code, not just a "please be
  careful" instruction, because an instruction is not a reliable boundary against a model that's confidently
  wrong.
- **Kill switches reachable from outside the agent's own loop.** If the agent itself is the only thing that can
  stop the agent, a bug in the agent's own reasoning has no external check on it — a real kill switch is a
  control an operator (or another supervising process) can trigger without depending on the agent's cooperation.

## Memory architectures for long-running agents

Three distinct kinds of memory solve different problems, and conflating them is a common design mistake:

- **Episodic** — what happened in this specific session/conversation. Naturally decays or gets compacted; not
  meant to persist forever.
- **Semantic** — facts and relationships that should persist across sessions (user preferences, project state,
  domain knowledge). This is what a durable memory system is for, and it needs explicit curation — not
  everything episodic should graduate to semantic, or the semantic store fills with noise that crowds out what
  actually matters.
- **Procedural** — learned patterns about *how* to do something well in this context (a workflow that worked, a
  mistake to avoid repeating). Distinct from semantic facts because it's about process, not content, and often
  needs to be phrased as a rule with its *reasoning* attached, not just the rule alone — the reasoning is what
  lets a future decision generalize correctly to a slightly different situation instead of being applied rigidly
  to the wrong case.

## Context management as a first-class concern

For any agent whose task spans enough steps to risk filling its context window: **compaction beats accumulation.**
Summarizing completed sub-work into a compact result and discarding the raw transcript preserves the
budget for what's still ahead, and is usually the right default over just letting the transcript grow — the
exception is when the raw detail itself might be needed later (debugging, audit trail), in which case persist it
externally (a file, a log) rather than keeping it live in the context that has to be re-read on every subsequent
turn.

## Verification, not self-report

The single highest-leverage habit across everything above: an agent's own claim that something works is not
evidence that it works. Run the thing. Read the real output. Check the edge case, not just the happy path. A
test suite passing is evidence of self-consistency — the code agrees with itself — which is not the same claim
as the code being correct against reality. This is true whether it's one agent checking its own work or a panel
of agents checking each other's — the discipline is the same, the panel just makes it harder for a single
agent's specific blind spot to go unchecked.
