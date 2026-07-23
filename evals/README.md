# ardconfig evals

Agentic-behavior regression checks for `agent/onboard_agent.py`, added for
the 2026-07-20 Ollama LLM Provider delta (`spec/design.md` Risk R14). See
`spec/evals.md` for the full decision writeup, rationale, and traceability.

This is deliberately separate from `tests/` (`./run-tests.sh`) and is
**not** part of the default fast, mock-based test suite. Nothing here is
wired into `run-tests.sh`, `pyproject.toml`'s pytest `testpaths`, or any CI
trigger. See "Why kept separate" below.

## Two tiers

### 1. `offline/` — fast, deterministic, safe for CI

```
.venv/bin/python -m pytest evals/offline -q
```

No network, no live model call, no subprocess — reads static fixture text
and asserts `agent.onboard_agent.parse_agent_output()`'s behavior against
it. Runs in well under a second. Safe to add as an optional CI step if
desired.

### 2. `run_golden_eval.py` + `goldens/` — live, slow, MANUAL/opt-in only

```
# cheap cases only (boards whose core is already installed — fast):
.venv/bin/python evals/run_golden_eval.py

# a single case:
.venv/bin/python evals/run_golden_eval.py --boards uno-r3

# include the heavier case (real network core install on first run):
.venv/bin/python evals/run_golden_eval.py --weight all --timeout 900

# list available cases without running anything:
.venv/bin/python evals/run_golden_eval.py --list

# optional Bedrock-provider comparison (needs real AWS credentials;
# auto-skips, not fails, if unavailable):
.venv/bin/python evals/run_golden_eval.py --provider bedrock
```

Requires, at minimum:
- A local Ollama server reachable at `ARDCONFIG_OLLAMA_HOST`
  (default `http://localhost:11434`) with `ARDCONFIG_OLLAMA_MODEL`
  (default `gpt-oss:latest`) pulled.
- `arduino-cli` on `PATH` (read-only commands only for the "cheap" cases;
  the "heavy" `nucleo-f411re` case also needs network access to install a
  third-party core).
- The project's own `.venv` with `strands-agents`, `boto3`, `ollama`
  installed (same venv `bin/ardconfig-onboard` itself uses).

Each golden case runs the **real** `agent/onboard_agent.py` end-to-end
(`create_agent()` with the real, unmocked provider branch; the real
6-tool Strands loop; real `arduino_cli_search`/`run_setup`/`run_verify`
calls) — inside an **isolated temporary copy of the repository**, so
nothing under the real `profiles/` directory is ever touched. See
`run_golden_eval.py`'s module docstring and `_make_sandbox()` for why
this isolation is necessary (`agent/tools.py`'s `write_file`/`run_setup`/
`run_verify` resolve their target paths relative to their own file
location, not a configurable root).

Takes roughly 30-90 seconds per "cheap" case on this project's reference
hardware (observed while authoring this suite), several minutes for the
"heavy" case on first run (real core install). This is why it is opt-in,
not part of `./run-tests.sh`.

## Why kept separate from `tests/`

`tests/agent` and `tests/bin` are fast (seconds) and fully mocked — no
live network, AWS, or Ollama calls (see `tests/README.md`'s "Mocking /
no-live-API policy"). Folding a real-LLM eval into that suite would make
every routine `./run-tests.sh` invocation slow, flaky (subject to model
sampling variance and local Ollama-server availability), and dependent on
multi-GB model weights being pulled — none of which is appropriate for a
suite meant to run on every change. See `spec/evals.md`'s Regression
Policy for the full reasoning and for when a maintainer should actually
run `evals/run_golden_eval.py` by hand.

## Scoring philosophy

Golden-case scoring is **structural/schema-based**, not exact-string-match
against a reference profile. A real gpt-oss:latest run observed while
authoring this suite (see `evals/goldens/*.json` and `spec/evals.md`)
chose a different `id` value (`arduino-uno`) than the project's existing
`uno-r3.json` for the same board — semantically fine (the schema only
requires `id` to be a lowercase-hyphenated slug), but an exact-match
scorer would have falsely failed it. Hard failures are reserved for
things that are unambiguously wrong regardless of model choice or
phrasing: a missing required field, a `"TODO"` placeholder despite
`status: success`, or a USB vendor/product ID that doesn't match the
input. FQBN/core mismatches against the reference profile are reported as
warnings, not hard failures — see `run_golden_eval.py`'s `_score()` for
the reasoning (the real authority on FQBN/core correctness is whether
`run_verify`'s compile step passed, not a string comparison).
