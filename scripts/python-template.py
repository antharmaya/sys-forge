#!/usr/bin/env python3
"""Systems Forge Python scaffold.

Copy this as the starting point for any non-trivial script instead of a
blank file. Delete what you don't need. See references/python-systems.md
for the reasoning behind each piece below.

Run with: uv run python this_file.py --input path/to/file
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")


class ConfigError(Exception):
    """Raised when input/config doesn't meet requirements. Add domain-specific
    exceptions like this instead of matching on error message strings."""


@dataclass
class Args:
    input: Path
    verbose: bool
    dry_run: bool


def parse_args(argv: list[str] | None = None) -> Args:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="path to input")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print what would happen, don't do it")
    ns = parser.parse_args(argv)
    return Args(input=ns.input, verbose=ns.verbose, dry_run=ns.dry_run)


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        stream=sys.stderr,
    )


def run_subprocess(cmd: list[str]) -> str:
    """Example of the safe subprocess pattern: argument list (never a shell
    string), check=True so failures raise instead of being silently ignored."""
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout


def retry_with_backoff(fn: Callable[[], T], max_attempts: int = 5, base_delay: float = 1.0) -> T:
    """Exponential backoff with jitter. Use for anything hitting a network
    dependency that can transiently fail."""
    import random
    import time

    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception:
            if attempt == max_attempts - 1:
                raise
            delay = base_delay * (2**attempt)
            delay *= 0.5 + random.random() * 0.5  # jitter
            logging.warning("attempt %d failed, retrying in %.1fs", attempt + 1, delay)
            time.sleep(delay)
    raise AssertionError("unreachable: last attempt always returns or re-raises")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)

    if not args.input.exists():
        logging.error("input does not exist: %s", args.input)
        return 1

    if args.dry_run:
        logging.info("[dry-run] would process %s", args.input)
        return 0

    try:
        # Replace this with the script's actual work.
        logging.info("processing %s", args.input)
        logging.info("done: %s", args.input)
    except ConfigError:
        logging.exception("config error")  # logs full traceback, not just str(e)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
