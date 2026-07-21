# Python Systems Programming — the full depth (2026 baseline)

## Tooling

`uv` is the practical default as of 2026 — a single tool replacing `pip` + `venv` + `pip-tools`, dramatically
faster dependency resolution, and it reads the same `pyproject.toml` everything else uses:

```bash
uv init myproject && cd myproject
uv add httpx pydantic
uv run python script.py
uv run pytest
```

`ruff` replaces `flake8` + `black` + `isort` in one fast tool — `ruff check .` and `ruff format .`. Use
`pyproject.toml` as the single config source; scattered `setup.py`/`setup.cfg`/`requirements.txt` is legacy
friction that `uv` and `ruff` both make unnecessary.

## Paths: `pathlib`, never string concatenation

```python
from pathlib import Path

config_dir = Path.home() / ".config" / "myapp"
config_dir.mkdir(parents=True, exist_ok=True)
for f in config_dir.glob("*.yaml"):
    ...
```
`Path` objects compose with `/` safely across OSes and catch the classic `os.path.join` misuse (passing an
absolute path as a later argument silently discards everything before it) at the type level — a `Path` doesn't
let you do that by accident.

## Subprocess: argument lists, not shell strings

```python
import subprocess

result = subprocess.run(
    ["git", "log", "--oneline", "-5"],
    check=True, capture_output=True, text=True,
)
print(result.stdout)
```
`check=True` raises `CalledProcessError` on non-zero exit instead of silently continuing with a `.returncode`
nobody checks — this is the Python equivalent of bash's `set -e`, and skipping it is the same class of bug.
Only use `shell=True` when you genuinely need shell features (pipes, globbing) — and if any part of the command
string comes from user input or external data, wrap it with `shlex.quote()` first or you have a command
injection vulnerability, not a style issue.

## Concurrency: pick the right one, know why

| Workload | Tool | Why |
|---|---|---|
| I/O-bound (network calls, file I/O, waiting on external services) | `asyncio` | Thousands of concurrent waits without thousands of OS threads |
| CPU-bound (parsing, computation, image processing) | `multiprocessing` / `ProcessPoolExecutor` | The GIL means threads don't parallelize CPU work — only separate processes do |
| CPU-bound but need to share memory efficiently | `multiprocessing.shared_memory` or `concurrent.futures.ProcessPoolExecutor` with care | Avoids the pickling cost of passing large data between processes |
| Never | `threading` for CPU-bound work | It will not go faster; the GIL serializes it anyway, you just paid for the threading overhead |

**Structured concurrency (`asyncio.TaskGroup`, 3.11+)** is the current default over bare `asyncio.gather()`:

```python
async def fetch_all(urls: list[str]) -> list[dict]:
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(fetch_one(url)) for url in urls]
    return [t.result() for t in tasks]
```
The critical difference from `gather()`: if one task in the group raises, `TaskGroup` cancels all the sibling
tasks automatically and raises an `ExceptionGroup`. `asyncio.gather()` by default lets siblings keep running to
completion even after one has failed — which in a real system means a connection you thought was being cleaned
up is still open, still holding a resource, when you thought failure meant "everything stopped."

## Typing

```python
def parse_config(path: Path) -> dict[str, str | int]:
    ...
```
Full type hints, checked with `mypy --strict` or `pyright`, are executable documentation — a caller (human or
another agent generating code against this function) doesn't have to read the implementation to know the shape
of what goes in and comes out. This matters more, not less, in an agentic-coding context: an agent editing this
codebase later benefits from the same signal a human would.

## Data modeling: dataclass vs pydantic

```python
from dataclasses import dataclass

@dataclass
class Point:          # internal, trusted data — no validation needed
    x: float
    y: float

from pydantic import BaseModel

class ToolCallArgs(BaseModel):   # data crossing a trust boundary — needs real validation
    query: str
    max_results: int = 10
```
Use `dataclass` for data that originates inside your own trusted code. Use `pydantic` (or an equivalent real
validator) at every boundary where untrusted structure enters — API request bodies, config files read from disk,
and critically, **LLM tool-call arguments** — a model can hallucinate a field name, the wrong type, or an
out-of-range value, and pydantic turns that into a clear validation error at the boundary instead of a confusing
failure three functions deeper into your code.

## Error handling philosophy

```python
class ConfigError(Exception):
    """Raised when the config file is missing required fields."""

try:
    load_config(path)
except ConfigError:
    logging.exception("Config load failed")
    raise
```
Define exception hierarchies specific to your domain rather than matching on error message strings (which break
silently the moment the message wording changes). Always `logging.exception()` inside an `except` block if
you're not immediately re-raising — it captures the full traceback, unlike `logging.error(str(e))` which throws
away exactly the information you need when this fires at 3am in production. Never a bare `except:` — it catches
`KeyboardInterrupt` and `SystemExit` too, which means Ctrl-C stops doing what the user expects.

## Testing

```python
# pytest — standard unit/integration tests
def test_retry_succeeds_on_third_attempt():
    ...

# hypothesis — property-based testing, generates edge cases you wouldn't think to write by hand
from hypothesis import given, strategies as st

@given(st.lists(st.integers()))
def test_sort_is_idempotent(xs):
    assert sorted(sorted(xs)) == sorted(xs)
```
Property-based testing earns its keep specifically for the kind of code this skill is about — parsers,
serializers, anything with an invariant that should hold for *all* inputs, not just the two or three examples a
human thought to write down. It's how the RateGuard project's conformance-vector testing across three language
SDKs was designed: shared test vectors that pin one behavioral contract, not hand-picked examples per language.

## Packaging (`pyproject.toml`)

```toml
[project]
name = "myservice"
version = "0.1.0"
dependencies = ["httpx>=0.27", "pydantic>=2.0"]

[project.scripts]
myservice = "myservice.cli:main"
```
`[project.scripts]` gives you a real installed CLI entry point (`myservice` becomes a command after `uv pip
install -e .`) instead of a `python path/to/script.py` invocation that breaks the moment the working directory
changes.
