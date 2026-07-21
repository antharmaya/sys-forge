# Claude Code hooks — deterministic enforcement, not another prompt instruction

A hook is a shell command Claude Code runs at a defined lifecycle point, regardless of what the model decided —
that's the entire value. A prompt instruction ("don't write outside the repo") is a request the model can
misread, forget mid-session, or be talked out of by a convincing-sounding user message. A `PreToolUse` hook that
exits non-zero blocks the tool call at the harness level, before the model's intent matters at all. Use hooks for
anything where "the model usually gets this right" isn't a strong enough guarantee — the same reasoning this
skill already applies to idempotency and circuit breakers, just at the agent-harness layer instead of the
service layer.

## The lifecycle points that matter

- **`PreToolUse`** — fires before any tool call executes; the primary security checkpoint. Exit non-zero to block
  the call outright. This is where a permission boundary becomes real instead of aspirational.
- **`PostToolUse`** — fires after a tool call completes; can't block what already happened, but can react
  (auto-format a file that was just edited, log what changed, kick off a partial test run).
- **`Stop`** — fires when the agent is about to end its turn; a natural place for a final verification pass
  (run the test suite once more, check nothing was left half-done) rather than trusting the agent's own "looks
  done" judgment.
- **`UserPromptSubmit`** — fires on the incoming prompt itself, before the model sees it; useful for redacting
  secrets out of what gets logged/sent, or blocking a prompt that matches a known-dangerous pattern before it
  ever reaches the model.

## Apply this skill's own principles to writing the hook script itself

A hook script is exactly the kind of small, high-stakes, run-unattended bash this skill already covers — the same
header (`set -euo pipefail`, quote everything), the same "fail loud" principle, applies here with one twist:
**a hook that fails open is worse than no hook at all** — it creates false confidence that a boundary exists.
Exit codes have specific meaning to Claude Code (0 = allow, non-zero = block/flag) — get this backwards and a
"blocking" hook silently permits everything, which is a much worse failure mode than the hook not existing,
because nobody thinks to check it. Verify a new hook actually blocks by deliberately trying the thing it's
supposed to stop, the same "run it against real input, read the real output" discipline this skill applies
everywhere else — don't just read the hook script and reason that it looks right.

## Concrete patterns worth having ready

**Block writes outside a project root** (the single most valuable hook for exactly the kind of client-repo
delivery work this skill's agentic-patterns section is aimed at — an agent with write access to a client's
machine should never be able to touch anything outside the repo it was scoped to):

```bash
#!/usr/bin/env bash
set -euo pipefail
# PreToolUse hook: reject Write/Edit calls whose target path resolves outside $PROJECT_ROOT.
target="${CLAUDE_TOOL_INPUT_FILE_PATH:-}"
[[ -z "$target" ]] && exit 0   # not a file-path tool call, nothing to check
resolved="$(readlink -f -- "$target" 2>/dev/null || realpath -- "$target")"
case "$resolved" in
  "$PROJECT_ROOT"/*) exit 0 ;;   # inside the boundary, allow
  *) echo "BLOCKED: $target resolves outside $PROJECT_ROOT" >&2; exit 1 ;;
esac
```

**Redact secrets before they reach a log or a shell command** (`UserPromptSubmit` or `PreToolUse` on Bash calls) —
pattern-match common credential shapes (API keys, tokens, connection strings with embedded passwords) and refuse
or scrub rather than passing them through verbatim; the same "quote everything, trust nothing" principle from
this skill's bash section, applied to what the agent itself might echo back into a log.

**Run the real test suite on `Stop`**, not just on request — the same "verification is part of the deliverable"
principle from this skill's core, enforced structurally instead of relying on the agent remembering to check.
A `Stop` hook that runs `pytest`/`bash lib/test_core.sh`-equivalent and exits non-zero on failure turns "I ran the
tests" from a claim into something that can't be skipped.

**Auto-format after every edit** (`PostToolUse` on Write/Edit) — run the project's formatter (`ruff format`,
`prettier`, `gofmt`) unconditionally after any file write. Low-stakes, but removes an entire category of
noisy, non-functional diff churn from every session.

## Where this fits with skills, subagents, and MCP

Hooks, skills, subagents, and MCP servers are separate layers that change different things: a skill changes what
guidance the model sees for a task; a subagent isolates context and can carry its own persistent memory across
invocations; an MCP server exposes new tools/resources/prompts the model can call; a hook is the only one of the
four that runs deterministically regardless of what the model decided. Reach for a hook specifically when the
requirement is "this must always happen" or "this must never be allowed" — not "the model should generally do
this," which a skill or a line in `AGENTS.md`/`CLAUDE.md` already covers.
