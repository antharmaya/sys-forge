# Modern CLI Tools (2026) — and how to use them safely from a script

The classic Unix toolkit (`grep`, `find`, `sed`, `diff`, `ls`) has faster, more ergonomic replacements that are now
standard on most developer machines. The upgrade is real — but a script or agent that assumes they're installed
will break on a bare CI container or a fresh Linux box. **Every use below needs a detection-and-fallback, not a
blind call.** `lib/core.sh`'s `sf_best_tool()` and `systems_forge.tooling.best_tool()` do this automatically —
use those rather than hand-rolling `command -v` checks per script.

## The upgrades, and why each one is a real improvement, not just new

| Classic | Modern | Why it's actually better |
|---|---|---|
| `grep -r` | **ripgrep** (`rg`) | Recursive and `.gitignore`-aware by default, skips binary files automatically, 3-5x faster on large repos via SIMD + parallelism. The single highest-value swap on this list for anyone searching code regularly. |
| `find` | **fd** | Regex by default, `.gitignore`-aware, far less punctuation to remember (`fd pattern` vs `find . -name '*pattern*'`). |
| `sed` | **sd** | `sd 'old' 'new' file` instead of `sed 's/old/new/g' file` — no delimiter escaping, familiar regex syntax (JS/Python-style, not POSIX BRE), reports 2-11x faster on large files. |
| `diff` | **difftastic** | Structurally aware — diffs based on syntax, not lines, so a pure reformat or a moved block doesn't drown the real change in noise. Genuinely useful for an agent reviewing its own diff before committing: `difft old.py new.py` surfaces the actual semantic change. |
| `cat` (for humans) | **bat** | Syntax highlighting + git-status markers. **Not a replacement for piping to another program** — `bat`'s decoration breaks a script expecting plain text; use plain `cat`/`< file` when the output feeds another command, `bat` only for a human to read directly. |
| `ls` | **eza** | Git-aware, tree view, icons — a human-facing upgrade, same caveat as `bat`: don't parse its output programmatically. |
| grep/sed at the code-structure level | **ast-grep** (`sg`) | Matches AST nodes, not text — `sg -p 'console.log($ARG)'` finds every call regardless of formatting, variable names, or whitespace, and REWRITES safely the same way. This is the single biggest upgrade for any refactor spanning many files: a regex-based rename breaks on reformatted code or a variable that happens to share a substring; a structural match doesn't. |
| `xargs -P` for anything nontrivial | **GNU parallel** | Better special-character handling (xargs "deals badly with space, `\`, `'`, `"`" in filenames), `--keep-order` to preserve input ordering in output, built-in progress/retry. Use plain `xargs -P` for simple fire-and-forget fan-out; reach for `parallel` once you need ordered output, per-job retry, or handling filenames with unusual characters. |
| watching files + rerun on change | **watchexec** | Works out of the box without an explicit file list or a `find`-based watch loop (unlike `entr`), better cross-platform defaults. |
| `jq` | `jq` is still fine; **jaq** if you want a faster/stricter Rust reimplementation | Drop-in compatible for the common case. For non-JSON structured data (YAML, TOML, CSV) in the same query language, **dasel** covers all of them instead of needing a separate `yq`/`toml`-specific tool per format. |

## Debugging and verification tools — the ones that back up a claim instead of just looking modern

These don't replace a classic command 1:1 — they fill a gap the classic toolkit has no answer for at all, and
they map directly onto this skill's own "verify, don't assume" principle and the "paged at 3am" framing:

| Need | Reach for | Why |
|---|---|---|
| "Is X actually faster than Y" | **hyperfine** | Runs each command enough times to give a real mean + stddev with outlier detection, including automatic warmup runs — the difference between "felt faster" and a number you'd put in a doc. Use this before writing "3-5x faster" anywhere, including in this file. |
| Reviewing a `git diff` for the real change, with syntax highlighting | **delta** | A pager for `git`/`diff`/`grep` output specifically — side-by-side view, syntax-highlighted, configured as `core.pager` once and it applies everywhere. Complements `difftastic` (which restructures the diff around syntax) rather than replacing it — delta is a better *pager*, difftastic is a better *diff algorithm*; reasonable to use both, delta for routine review, difftastic when a reformat is drowning the real change. |
| "What's actually eating disk space" (the 3am "disk full" page) | **dust** | Visual, sorted-by-size tree in one command — `du -sh * \| sort -h` gets there but takes three tools and doesn't recurse sensibly by default. |
| "What's actually eating CPU/memory right now" | **bottom** (`btm`) or **procs** | `bottom` is `top`/`htop` with a better default layout and per-core graphs; `procs` is `ps` with human-readable columns and tree view by default. Both are read-only inspection — reach for these before guessing which process to kill. |
| Running a project's common commands consistently (setup, test, lint, deploy) without remembering flags | **just** | A `justfile` next to a `Makefile`'s job without make's whitespace-sensitivity footguns or its file-target semantics fighting a task that isn't producing a file. Worth it the moment a README's "how to run this" section has more than 2-3 commands people keep forgetting the exact invocation of. |

**Deliberately not included:** `zoxide` (smarter `cd`) and `fzf` (fuzzy interactive selection) are genuinely good tools, but they optimize *interactive human terminal navigation* — this skill's scope is scripts and agents, which don't benefit from an interactive fuzzy-picker the way a person typing commands does. Worth having personally; not part of what an agent should reach for when automating something.

## The rule: detect, don't assume

```bash
source lib/core.sh
grep_cmd=$(sf_best_tool rg grep) || { echo "neither rg nor grep found" >&2; exit 1; }
"$grep_cmd" -n "pattern" file.txt
```

```python
from systems_forge.tooling import best_tool

grep_cmd = best_tool("rg", "grep")
if grep_cmd is None:
    raise RuntimeError("neither rg nor grep found")
subprocess.run([grep_cmd, "-n", "pattern", "file.txt"], check=True)
```

Never write a script that calls `rg` directly with no fallback unless you've confirmed the specific environment
it'll run in has it installed — a script that works on your dev machine and fails silently (or loudly) on a
teammate's CI runner is a real, recurring failure mode, not a hypothetical one.

## Portability gotchas that are still real in 2026

- **macOS ships bash 3.2 by default**, frozen there since 2007 because Apple won't ship GPLv3-licensed software
  — no associative arrays, no `mapfile`, none of the 5.x features `references/bash-patterns.md` and `lib/core.sh`
  assume. A script using modern bash features needs `#!/usr/bin/env bash` PLUS either a documented requirement
  to `brew install bash` (and confirm the shebang resolves to the Homebrew one, not `/bin/bash`), or needs to be
  written to the POSIX/bash-3.2-compatible subset if it must run unmodified on stock macOS.
- **zsh has been the default *interactive* shell on macOS since Catalina (2019)** — irrelevant to a script with an
  explicit `#!/usr/bin/env bash` shebang (that shebang wins regardless of the user's interactive shell), but worth
  knowing if you're debugging "works when I paste it, breaks in the script."
- **There are two different `parallel` commands**: GNU Parallel and the `parallel` that ships with `moreutils`
  have different flags and behavior — `command -v parallel` finding *something* is not proof it's GNU Parallel;
  check `parallel --version` if the distinction matters to what you're about to run.
