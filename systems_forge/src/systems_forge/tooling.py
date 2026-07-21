"""Modern-CLI-tool detection with fallback. See references/modern-cli-tools.md
for the full upgrade table and why each swap is a real improvement, not just
a newer name for the same thing.

Never shell out to a modern tool (rg, fd, sd, ast-grep...) without a
fallback — it isn't installed on every CI runner or fresh box by default.
"""

from __future__ import annotations

import shutil


def best_tool(*candidates: str) -> str | None:
    """Return the first available command from `candidates` (checked in the
    order given — put the preferred/modern tool first, POSIX fallback
    last), or None if none are on PATH.

    >>> best_tool("rg", "grep") in ("rg", "grep", None)
    True
    """
    for candidate in candidates:
        if shutil.which(candidate) is not None:
            return candidate
    return None


def require_tool(*candidates: str) -> str:
    """Like best_tool(), but raises with a clear message instead of
    returning None — use when the script genuinely cannot proceed without
    one of these (fail loud, per the skill's core principle, rather than
    letting a later step fail with a confusing error about a missing
    binary)."""
    found = best_tool(*candidates)
    if found is None:
        raise RuntimeError(f"none of the required tools are installed: {', '.join(candidates)}")
    return found
