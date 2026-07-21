# Agentic Tool-Use Efficiency (2026 research synthesis)

This file exists because "the model is smart enough" is not the bottleneck for most agent failures in
production — the harness and the habits around tool use are. Multiple independent 2026 studies converge on the
same core finding: **behavioral differences between agents (verification habits, exploration order, tool
selection, edit format) predict success far better than raw model capability does.** The patterns below are
grounded in that research, not generic advice.

## Editing: exact-string search-replace beats line-number diffs

Research comparing LLM code-edit output formats (full-file rewrite, unified diff, search-replace blocks,
structure-aware block/function-level diffs) found a consistent pattern: **unified diffs with line-number offsets
are the least reliable format** — "fragile offsets and fragmented hunks make generation highly unnatural,"
because a line number drifts the moment any earlier edit in the same file shifts it, and the model has to track
that drift perfectly across the whole generation. Exact-string search-and-replace, anchored on the literal
content being changed rather than its position, is measurably more reliable — this is precisely why
Claude Code's own edit tool works this way (match a unique string, replace it, no line numbers involved) rather
than accepting a line-numbered patch.

**What this means for writing an edit, whether by hand or generating one:**
- Anchor on content, never on a line number — a line number is a claim about position, which is the single
  most volatile fact about a file being edited.
- Include enough surrounding context in the "old" string to make it uniquely identify one location — a short,
  common fragment (`return true`) will match multiple places and either fail to apply or apply to the wrong one.
- For changes spanning a large, syntactically coherent unit (a whole function, a whole control-block), prefer
  rewriting that unit wholesale over a scattered multi-hunk diff across it — research on structure-aware formats
  (block-level and function-level rewrites) found this matches full-file-rewrite accuracy while cutting cost
  ~30% versus either a naive line diff or regenerating the entire file.
- For refactors spanning many files with the same pattern, structural search-and-replace (`ast-grep`, see
  `references/modern-cli-tools.md`) beats a regex-based `sd`/`sed` pass for the same reason exact-string beats
  line-number diffs: it's anchored on the actual thing being changed (a matching AST shape), immune to
  reformatting, renamed-but-structurally-identical siblings, and whitespace differences that break a regex.

## Verification is the single strongest predictor of success

A 2026 study comparing behavioral drivers of coding-agent success (not just pass/fail resolution rates) found
that the agents which *tested their own solutions before declaring done* consistently outperformed agents with
otherwise similar capability that skipped this step. Failing agents showed "insufficient verification... relying
on incomplete testing," "inadequate context understanding... resulting in fixes that miss critical
dependencies," and "inefficient tool application... redundant tool use, excessive repetition." None of this is
about the model being less capable — it's about what the agent *did* with the turns it had.

**Concretely:** run the code. Read the actual output. Don't infer success from the diff looking plausible. This
is the same meta-principle stated at the top of `SKILL.md`, and it's not restated here for emphasis alone — it's
restated because the research specifically identifies it as the behavioral gap between agents that succeed and
agents that look like they should.

## Silent failure is the most dangerous failure mode, not the loudest

Documented failure-pattern research across production coding agents (Cline, Claude, Cursor, Replit, and others)
found the most damaging pattern isn't a crash — it's **code that runs without error but doesn't do what was
asked**, concentrated in error handling and business logic. A crash is self-reporting; a silently-wrong
implementation looks finished. The same research flags a specific, avoidable variant: an agent hallucinating a
fake input (an environment variable, an API key, a config value) instead of asking for the real one or failing
loudly when it's missing — producing code that runs against fabricated data and looks done.

**Concretely:** when a required value is genuinely unknown (not inferable from the codebase), stop and ask or
raise a clear error naming exactly what's missing — never fabricate a plausible-looking placeholder and continue
silently. When testing a change, test the actual behavior the user asked for, not just "did it exit 0."

## Structured exploration before edits, not speculative changes

The same behavioral-drivers research found successful agents "systematically understand repository structure
and dependencies before attempting fixes," while failing agents made "speculative changes" without that
grounding. This is the concrete justification for reaching for a fast, structural search tool
(`rg`/`ast-grep`, see `references/modern-cli-tools.md`) to map out what actually calls/depends-on/tests the code
you're about to touch, before touching it — not as a formality, but because it's the specific habit that
correlates with getting the fix right the first time instead of missing a dependency.

## Batch independent operations, don't serialize them

Harness-engineering research on agentic coding tools specifically recommends batching operations to reduce
round-trip cost — reading three independent files one-at-a-time when they could be requested together burns
turns and latency for no benefit, since nothing about file B depends on having already read file A. The same
applies to independent searches, independent test runs across unrelated modules, or independent subagent
dispatches (see `systems_forge/agents/orchestrator.py` for the pattern that fans these out with bounded
concurrency instead of a serial loop).

## Context: density over volume

The same body of research is consistent on this point: more injected context does not reliably improve output —
optimal *density* wins over exhaustive inclusion. Practically: prioritize what's recent and directly relevant
over dumping full history; prefer scannable structure (a lookup table, a short bulleted rule) for things that
need to be found quickly, paired with a brief stated *reason* for each rule — the reasoning is specifically what
lets an agent apply a rule correctly to an edge case that doesn't exactly match the example it was given, rather
than pattern-matching the rule too literally or too loosely. This is also, not coincidentally, the same style
this entire skill is written in.

## Don't repeat a tool call you already have the answer to

A specific, named inefficiency in the failure-pattern research: agents re-running searches or re-reading content
they already retrieved earlier in the same task, rather than referring back to what's already in context. If
you've already found where something is defined, don't re-search for it three tool calls later out of caution —
that's wasted latency and budget with no new information gained, and it's a measured, named failure pattern, not
a hypothetical one.
