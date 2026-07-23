# ardconfig test suite

This repository had no test framework prior to the Ollama LLM Provider delta
(2026-07-20, spec/tasks.md TASK-015). This scaffold introduces one,
deliberately kept minimal for a small bash+Python CLI project.

## Frameworks chosen

**Python side (`agent/`) → [pytest](https://docs.pytest.org/)**

- Already the de facto standard for Python; `strands-agents`'s own
  ecosystem and most Python CLI/agent projects use it, so it's a safe,
  unsurprising default.
- Built-in `monkeypatch`/fixture support is sufficient for this repo's
  needs (patching lazily-imported model classes, faking env vars,
  `sys.modules` tricks for import-absence simulation) — no extra plugin
  (e.g. `pytest-mock`) is required.
- Not vendored/pinned beyond a loose floor in `requirements-dev.txt`
  (`pytest>=8.0,<10`); install into the project venv with:
  ```
  .venv/bin/pip install -r requirements-dev.txt
  ```
- `requirements-dev.txt` also declares `strands-agents`, `boto3`, and
  `ollama>=0.4.8,<1.0.0` — not because the tests make real calls (they
  don't; see "Mocking / no-live-API policy" below), but because
  `agent/onboard_agent.py` unconditionally imports `strands` at module
  load, and every file under `tests/agent/` imports that module at
  *collection* time. Without those packages importable, `pytest
  tests/agent` fails to even collect (`ModuleNotFoundError`, exit code
  2) before a single test runs. These three re-declare, at the same
  version range, what `bin/ardconfig-onboard`'s `ensure_ai_deps()`
  JIT-installs at runtime — so a single `pip install -r
  requirements-dev.txt` on a fresh clone/venv is sufficient to run the
  suite, with no separate `ardconfig-onboard` bootstrap step required
  first.

**Bash side (`bin/`) → [bats-core](https://github.com/bats-core/bats-core)**

- The most widely used bash TAP-based test framework; avoids hand-rolling
  assertion/failure-reporting plumbing for `set -euo pipefail` scripts.
- Installed via Homebrew in this environment (`brew install bats-core`);
  not vendored into the repo. If `bats` is not on `PATH`, install it via
  your platform's package manager (e.g. `brew install bats-core`,
  `apt install bats`, or see the bats-core README for a manual install).
- Chosen over `shellspec` (heavier, RSpec-style DSL not needed for this
  repo's size) and over hand-rolled assertions (bats gives TAP output,
  per-test isolation via subshells, and `run`/`$status`/`$output` helpers
  for free, which matters for testing a script that itself calls `exit`
  and writes JSON).

No CI config (`.github/workflows/`) is introduced by this scaffold — see
spec/tasks.md TASK-015, which scopes CI setup out unless a future task asks
for it.

## Layout

```
tests/
  README.md              this file
  agent/                 pytest suite — agent/onboard_agent.py, agent/tools.py
    golden/               golden-hash fixtures for the NFR-8 scope-boundary check
  bin/                    bats suite — bin/ardconfig-onboard
    fixtures/             helper scripts (e.g. a local mock Ollama HTTP server)
```

## Running the suite

Single entry point (from the repo root):

```
./run-tests.sh
```

This runs the pytest suite (`tests/agent`) against `.venv/bin/python`,
then the bats suite (`tests/bin`) via `bats`, and exits non-zero if either
fails. Each sub-suite can also be run directly:

```
.venv/bin/python -m pytest tests/agent -q
bats tests/bin
```

### Notes on "zero tests" behavior

- `bats` exits `0` when a directory contains no `.bats` files (prints
  `1..0`). No special-casing needed.
- `pytest` exits `5` ("no tests collected") rather than `0` when its
  target directory contains no test files. `run-tests.sh` treats a
  pytest exit code of `5` as a pass — this is a well-known, documented
  pytest behavior (not a masked failure), relevant only during the
  brief scaffold-only window before TASK-016 added real tests to
  `tests/agent/`.

## Mocking / no-live-API policy

Per spec/design.md's Verification Strategy: none of the automated tests in
`tests/agent` or `tests/bin` may make a real network call, real AWS SDK
call, or depend on a real running Ollama server. Real-service checks
(a live local Ollama server, real Bedrock access) are TASK-018's
manual/integration job, not part of `./run-tests.sh`.
