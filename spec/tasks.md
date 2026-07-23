# Tasks — AI-Powered Hardware Onboarding for ardconfig

## Dependency Graph

```
TASK-001 (config)
    │
TASK-002 (detect changes) ──────────────────────┐
    │                                            │
TASK-003 (agent package + tools)                 │
    │                                            │
TASK-004 (onboard script)  ◄─── TASK-001,002,003│
    │                                            │
TASK-005 (Nucleo-F411RE end-to-end test) ◄──────┘
    │
TASK-006 (README update)
```

---

## TASK-001: Configuration additions

**Objective:** Add Bedrock model and AWS region settings to ardconfig.conf.

**Requirements:** FR-11, FR-12

**Write Lease:** `conf/ardconfig.conf`

**Change Budget:** max_files: 1, max_new_symbols: 2, interface_policy: extend_only

**Steps:**
1. Append `ARDCONFIG_BEDROCK_MODEL` and `ARDCONFIG_AWS_REGION` settings to `conf/ardconfig.conf` with comments and empty defaults.

**Verification:**
- `source conf/ardconfig.conf` succeeds without errors
- New variables are defined (empty = use default)

**Risk:** Low

**Dependencies:** None

---

## TASK-002: Generalize ardconfig-detect vendor ID matching

**Objective:** Remove the hardcoded `vid == "2341"` filter in ardconfig-detect. Match all USB devices against loaded profiles. Report unrecognized devices as `unknown`.

**Requirements:** FR-1, FR-2, NFR-6

**Write Lease:** `bin/ardconfig-detect`

**Change Budget:** max_files: 1, max_new_symbols: 3, interface_policy: extend_only

**Steps:**
1. Remove the `[[ "$vid" == "2341" ]]` primary check.
2. For every `/dev/ttyACM*` and `/dev/ttyUSB*` device with a non-empty vendor ID, call `profiles_match_usb "$vid" "$pid"`.
3. If matched: existing behavior (enrich from profile, add to `boards` array).
4. If not matched: add to a new `unknown_boards` array with `status: "unknown"`, device path, vendor ID, product ID, USB model string. Emit an `[INFO]` step suggesting `ardconfig-onboard`.
5. Include `unknown_boards` in the JSON output alongside `boards`.

**Verification:**
- With an Arduino board (vendor 2341) connected: output is identical to before (NFR-6).
- With Nucleo-F411RE (vendor 0483) connected and no profile: it appears in `unknown_boards`.
- With no devices connected: exit code 3, empty arrays.

**Risk:** Medium — must not break existing detection. Test with real hardware.

**Dependencies:** None

---

## TASK-003: Create Python agent package

**Objective:** Create the `agent/` package with the Strands AI agent and tool definitions.

**Requirements:** FR-7, FR-8, FR-9, FR-10, FR-13, FR-15, FR-19, FR-20, FR-21

**Write Lease:** `agent/**`

**Change Budget:** max_files: 3, max_new_symbols: 15, interface_policy: new_component

**Steps:**
1. Create `agent/__init__.py` (empty package marker).
2. Create `agent/tools.py` with tool functions:
   - `arduino_cli_search(command: str) → str` — runs arduino-cli subcommands
   - `web_search(query: str) → str` — web search for board docs (use Strands built-in or simple implementation)
   - `read_file(path: str) → str` — read files within project directory
   - `write_file(path: str, content: str) → str` — write files to profiles/ only
   - `validate_profile(profile_path: str) → str` — invoke jq validation via subprocess
   - `run_setup(board_id: str) → str` — invoke ardconfig-setup --boards <id> --non-interactive --json
   - `run_verify(board_id: str) → str` — invoke ardconfig-verify --boards <id> --json
3. Create `agent/onboard_agent.py` with:
   - System prompt (board identification agent instructions)
   - `create_agent()` — instantiate Strands Agent with BedrockModel and tools
   - `main()` — read JSON from stdin, invoke agent, parse profile from response, write JSON to stdout
   - `build_prompt(input_data)` — construct the research prompt from vendor/product/name
   - `parse_agent_output(result)` — extract profile JSON from agent response

**Verification:**
- `python -c "from agent.onboard_agent import create_agent"` succeeds (with deps installed)
- `python -c "from agent.tools import arduino_cli_search, validate_profile"` succeeds
- Tools can be called independently (unit-testable)

**Risk:** Medium — Strands AI SDK API surface may differ from design assumptions. Verify tool decorator syntax against SDK docs.

**Dependencies:** None (can be developed in parallel with TASK-001 and TASK-002)

---

## TASK-004: Create bin/ardconfig-onboard script

**Objective:** Create the bash wrapper script that orchestrates the onboarding flow.

**Requirements:** FR-3, FR-4, FR-5, FR-6, FR-14, FR-16, FR-17, FR-18, FR-22, FR-23, FR-24, NFR-1, NFR-2, NFR-3

**Write Lease:** `bin/ardconfig-onboard`

**Change Budget:** max_files: 1, max_new_symbols: 12, interface_policy: new_component

**Steps:**
1. Create `bin/ardconfig-onboard` with:
   - Shebang, set -euo pipefail, source common.sh + output.sh + board-profiles.sh
   - `usage()` — help text with all flags
   - Arg parsing: `--vendor-id`, `--product-id`, `--board-name`, plus standard flags
   - `ensure_ai_deps()` — JIT install strands-agents and boto3 (FR-22)
   - `check_aws_credentials()` — verify AWS creds via Python boto3 sts get-caller-identity (FR-23)
   - `scan_unknown_devices()` — find USB devices not matching any profile (FR-4)
   - `invoke_agent()` — call Python agent via subprocess, pass JSON stdin, read JSON stdout
   - `confirm_profile()` — display profile, prompt y/n, allow id override (FR-16, FR-14)
   - `write_profile()` — write to profiles/<id>.json, check conflicts (FR-17)
   - `update_udev_rules()` — append vendor ID rule if new (FR-18)
   - `handle_partial_failure()` — output TODO template, suggest Kiro (FR-24)
   - `main()` — orchestrate the full flow
2. Make executable: `chmod +x bin/ardconfig-onboard`

**Verification:**
- `bin/ardconfig-onboard --help` exits 0 with usage text
- `bin/ardconfig-onboard --json --help` exits 0
- Without AWS creds: exits 2 with clear error
- Without venv: exits 2 with clear error
- With `--vendor-id 0483 --product-id 374b`: invokes agent and produces output

**Risk:** Medium — integration of bash wrapper with Python subprocess. Test the stdin/stdout JSON contract carefully.

**Dependencies:** TASK-001 (config), TASK-002 (detect for scan logic reference), TASK-003 (agent package)

---

## TASK-005: End-to-end test with Nucleo-F411RE

**Objective:** Run the complete onboarding flow with the Nucleo-F411RE hardware to validate the entire pipeline.

**Requirements:** AC-001 through AC-009

**Write Lease:** `profiles/nucleo-f411re.json` (generated output)

**Change Budget:** max_files: 2, max_new_symbols: 0, interface_policy: extend_only

**Steps:**
1. Ensure Nucleo-F411RE is connected via USB.
2. Run `bin/ardconfig-onboard` (hardware-present mode) — verify it detects the unknown device.
3. Verify the agent researches and generates a valid profile.
4. Confirm the profile at the prompt.
5. Verify `profiles/nucleo-f411re.json` is written and passes validation (AC-001).
6. Verify `udev/99-arduino.rules` contains vendor `0483` (AC-005).
7. Run `bin/ardconfig-detect --json` — verify Nucleo appears in `boards` (AC-002).
8. Verify `ardconfig-setup --boards nucleo-f411re` installed the stm32duino core (AC-003).
9. Verify `ardconfig-verify --boards nucleo-f411re` compiles Blink successfully (AC-004).
10. Also test headless mode: `bin/ardconfig-onboard --vendor-id 0483 --product-id 374b --board-name "Nucleo-F411RE"` (AC-007).

**Verification:**
- All 9 acceptance criteria pass.
- Generated profile matches expected values (FQBN, core, core_url, vendor/product IDs).

**Risk:** High — depends on AI agent producing correct output, Bedrock availability, and hardware being connected. This is the integration test.

**Dependencies:** TASK-004 (all components must be in place)

---

## TASK-006: Update README and documentation

**Objective:** Update README.md to document the new onboarding feature, the Nucleo-F411RE board, and the updated detect behavior.

**Requirements:** Docs completeness

**Write Lease:** `README.md`

**Change Budget:** max_files: 1, max_new_symbols: 0, interface_policy: extend_only

**Steps:**
1. Add `ardconfig-onboard` to the Scripts section with usage and description.
2. Add Nucleo-F411RE to the Supported Boards table.
3. Add a "Adding New Boards" section explaining both manual (JSON) and AI-assisted (onboard) methods.
4. Document the AI prerequisites (AWS credentials, Bedrock access).
5. Update the ardconfig-detect section to mention unknown device reporting.

**Verification:**
- README accurately describes all new functionality.
- No broken markdown formatting.

**Risk:** Low

**Dependencies:** TASK-005 (need final profile and confirmed behavior to document accurately)

---

## Summary

| Task | Description | Risk | Dependencies | Est. Complexity |
|---|---|---|---|---|
| TASK-001 | Config additions | Low | None | Small |
| TASK-002 | Detect vendor generalization | Medium | None | Small |
| TASK-003 | Python agent package | Medium | None | Medium |
| TASK-004 | Onboard bash script | Medium | 001, 002, 003 | Medium |
| TASK-005 | E2E test with Nucleo-F411RE | High | 004 | Medium |
| TASK-006 | README update | Low | 005 | Small |

**Parallelizable:** TASK-001, TASK-002, and TASK-003 can be developed in parallel.

**Critical path:** TASK-003 → TASK-004 → TASK-005 → TASK-006

---

## Delta: Ollama LLM Provider Support (2026-07-20)

Source: `spec/design.md`'s 2026-07-20 amendment (FR-25–FR-28, NFR-8; amended
FR-7, FR-11, FR-12, FR-22, FR-23) plus the bundled config-precedence
corrective fix (governance call: bundled inline into this delta rather than
split into a separate corrective-requirements packet, resolving design.md's
Open Design Question New-3). This delta touches exactly four existing files
(`conf/ardconfig.conf`, `agent/onboard_agent.py`, `bin/ardconfig-onboard`,
`README.md`) plus new test infrastructure (no test framework currently
exists in this repo — confirmed absent: no `tests/`, no `pyproject.toml`, no
`requirements*.txt`). Task numbering continues from the pre-existing
TASK-001–006 above; no prior task is modified.

### Delta Dependency Graph

```
TASK-007 (conf/ardconfig.conf: provider vars + precedence fix)  ─┐
TASK-008 (onboard_agent.py: provider branch + precedence fix)    │  (both independent
                                                                   │   of each other)
TASK-009 (resolve_llm_provider())                                │
    │                                                             │
TASK-010 (check_ollama_available())                               │
    │                                                             │
TASK-011 (ensure_ai_deps() + prereq dispatch)                     │
    │                                                             │
TASK-012 (invoke_agent() env passthrough)                         │
    │                                                             │
TASK-013 (usage() heredoc)                                        │
    │                                                             │
    └──────────────┬────────────────────────────────────────────┘
                    │
TASK-014 (README.md updates)  ◄── needs 007, 008, 011, 012, 013

TASK-015 (test framework scaffold)  ── independent, no production code touched
    │
TASK-016 (unit tests: create_agent() branching, precedence fix, NFR-8)  ◄── 007, 008, 015
    │
TASK-017 (bash prereq-check tests, mocked)  ◄── 009, 010, 011, 015
    │
TASK-018 (manual/integration: real Ollama + Bedrock regression)  ◄── 012, 013, 016, 017
```

Note: TASK-009 through TASK-013 all modify `bin/ardconfig-onboard` and are
chained sequentially even where the underlying functional dependency is
soft, to avoid parallel-edit/write-lease conflicts on the same file. See
"Sequencing risk" in the completion summary.

---

## TASK-007: conf/ardconfig.conf — provider variables and precedence fix

**Objective:** Fix the env-var-precedence defect in the AI-settings block (a
plain `VAR=""` assignment silently clobbers a caller-supplied environment
variable on every `load_config()` source) and add the three new
Ollama-related settings, using the exact conditional-assignment replacement
block specified in design.md's Public Interfaces §2.

**Requirements:** FR-25, FR-26 (new); config-precedence fix (bundled per
orchestrator governance call — resolves design.md Open Design Question
New-3); enables correct FR-11/FR-12 behavior (regression fix).

**Files/Areas expected to change:** `conf/ardconfig.conf` — the "AI
onboarding settings" block (currently 2 lines at ~L16-18 in the current
file; will grow to 7 lines including comments). No other line in the file
should change.

**Write Lease:**
```
^conf/ardconfig\.conf$
```

**Change Budget:** max_files: 1, max_new_symbols: 5, interface_policy: extend-only

**Steps:**
1. Replace the current two-line block:
   ```bash
   ARDCONFIG_BEDROCK_MODEL=""  # Default: us.anthropic.claude-sonnet-4-6
   ARDCONFIG_AWS_REGION=""     # Default: us-west-2 (falls back to AWS_DEFAULT_REGION)
   ```
   with the exact 7-line block from design.md's Public Interfaces §2
   ("Exact lines to add/change"):
   ```bash
   # AI onboarding settings (used by ardconfig-onboard)
   # LLM provider: "bedrock" or "ollama". Default: ollama (see FR-25).
   : "${ARDCONFIG_LLM_PROVIDER:=}"
   # Bedrock model ID. Default: us.anthropic.claude-sonnet-4-6 (provider=bedrock only)
   : "${ARDCONFIG_BEDROCK_MODEL:=}"
   # AWS region for Bedrock calls. Default: us-west-2, falls back to AWS_DEFAULT_REGION (provider=bedrock only)
   : "${ARDCONFIG_AWS_REGION:=}"
   # Ollama server URL. Default: http://localhost:11434 (provider=ollama only)
   : "${ARDCONFIG_OLLAMA_HOST:=}"
   # Ollama model tag. Default: gpt-oss:latest (provider=ollama only)
   : "${ARDCONFIG_OLLAMA_MODEL:=}"
   ```
2. Do not add hardcoded default *values* anywhere in this file. Per
   design.md, each default lives in exactly one place: the bash
   `${VAR:-default}` reads in `bin/ardconfig-onboard` (TASK-009–012) and the
   Python `os.environ.get(KEY) or default` reads in `agent/onboard_agent.py`
   (TASK-008). This file only documents defaults in comments.
3. Do not touch `ARDCONFIG_BOARDS`, `ARDCONFIG_VENV_PATH`,
   `ARDCONFIG_PYTHON_PACKAGES`, or `ARDCONFIG_CLI_VERSION`.

**Verification:**
- `bash -n conf/ardconfig.conf` exits 0.
- `bash -c 'source conf/ardconfig.conf; echo "[$ARDCONFIG_LLM_PROVIDER][$ARDCONFIG_OLLAMA_HOST]"'` prints `[][]` — placeholders remain empty, no default value leaked into the conf file.
- Precedence regression check: `bash -c 'ARDCONFIG_BEDROCK_MODEL=custom-model; source conf/ardconfig.conf; echo "$ARDCONFIG_BEDROCK_MODEL"'` prints `custom-model`, not empty — this is the literal defect being fixed (compare against the old `VAR=""` behavior, which would print nothing).
- `git diff conf/ardconfig.conf` touches only the AI-onboarding block.

**Rollback:** `git checkout conf/ardconfig.conf` — single file, no downstream state (conf file is read-only at runtime per design.md's Data Model section).

**Risk:** Low — pure syntax change to already-inert placeholder lines; design.md specifies the exact literal replacement text, leaving no implementation ambiguity. Main risk is a bash quoting slip, caught by the `bash -n` check.

**Recommended Mode:** executor

**Dependencies:** None (parallelizable with TASK-008)

---

## TASK-008: agent/onboard_agent.py — provider-conditional create_agent()

**Objective:** Rewrite `create_agent()`'s body to branch on
`ARDCONFIG_LLM_PROVIDER`, lazily import the selected model class inside its
branch only, and fix the env-var-precedence defect in every env read
(`os.environ.get(KEY, default)` → `os.environ.get(KEY) or default`), per the
exact function listing in design.md's Public Interfaces §3.

**Requirements:** FR-7 (amended), FR-11/FR-12 (unchanged external behavior —
regression), FR-25, FR-26, FR-28; config-precedence fix (bundled).

**Files/Areas expected to change:** `agent/onboard_agent.py` — the
module-level import block (currently line 8:
`from strands.models.bedrock import BedrockModel`) and `create_agent()`'s
body (currently lines ~46-61).

**Write Lease:**
```
^agent/onboard_agent\.py$
```

**Change Budget:** max_files: 1, max_new_symbols: 0 (`create_agent()`'s
signature `() -> Agent` is unchanged; no new public functions, per
design.md's Simplicity Budget), interface_policy: extend-only

**Steps:**
1. Remove the module-level `from strands.models.bedrock import BedrockModel`.
   Keep `from strands import Agent` at module level (confirmed safe for
   both providers — design.md's Public Interfaces §3 note explains
   `strands/models/__init__.py` itself eagerly imports `BedrockModel` but
   never touches `ollama`, so this line does not reintroduce the leak
   FR-28 guards against).
2. Replace `create_agent()`'s body with the exact listing from design.md
   §3: read `provider = os.environ.get("ARDCONFIG_LLM_PROVIDER") or "ollama"`;
   `if provider == "bedrock":` lazily import `BedrockModel`, resolve
   `model_id`/`region` via `or`-chained `os.environ.get(...)` calls with the
   documented defaults, construct `BedrockModel(model_id=model_id, region_name=region)`;
   `elif provider == "ollama":` lazily import `OllamaModel`, resolve
   `host`/`model_id` the same way, construct
   `OllamaModel(host=host, model_id=model_id)`; `else:` raise
   `ValueError(f"Invalid ARDCONFIG_LLM_PROVIDER: '{provider}' (must be 'bedrock' or 'ollama')")`.
   Return the same `Agent(model=model, system_prompt=SYSTEM_PROMPT, tools=[...])`
   call, unchanged tool list.
3. Add the docstring from design.md's listing documenting the `ValueError`
   contract (unreachable via the normal CLI path — see step 4).
4. Do NOT wrap the `create_agent()` call in `main()` with a
   `try/except ValueError` — leave it uncaught, per design.md's explicit
   note: an invalid provider reaching this point means bash-level
   validation (TASK-009) was bypassed, and this is intentionally not exit
   code 2 in that bypass scenario.
5. Do NOT modify `SYSTEM_PROMPT`, `build_prompt()`, `parse_agent_output()`,
   `main()`, or `agent/tools.py` (NFR-8 scope boundary).

**Verification:**
- `git diff agent/onboard_agent.py` touches only the module-level import
  line and `create_agent()`'s body; `SYSTEM_PROMPT` and every other
  function are byte-identical (this is the pre-check for TASK-016's
  automated NFR-8 test).
- `.venv/bin/python -c "import ast; ast.parse(open('agent/onboard_agent.py').read())"` — syntax check.
- `.venv/bin/python -c "from agent.onboard_agent import create_agent"` succeeds without the `ollama` pip package installed. (Confirmed via repo inspection during planning: this repo's checked-in `.venv` currently has `strands-agents` but *not* `ollama`, making it a ready-made fixture for this check — do not `pip install ollama` into it as part of this task.)
- `ARDCONFIG_LLM_PROVIDER=bedrock .venv/bin/python -c "from agent.onboard_agent import create_agent; create_agent()"` does not raise `ModuleNotFoundError: ollama` (this is AC-016's literal wording — a `boto3`/credentials-level error is an acceptable/expected outcome given `boto3` is also not currently installed in this venv; the assertion is specifically about the `ollama` import).
- `ARDCONFIG_LLM_PROVIDER=nonsense .venv/bin/python -c "from agent.onboard_agent import create_agent; create_agent()"` raises `ValueError` whose message contains `nonsense`.

**Rollback:** `git checkout agent/onboard_agent.py`.

**Risk:** Medium — this file is where the config-precedence fix and the
provider branch intersect; design.md explicitly flags the Bedrock-path
regression here as "elevated risk" (Verification Strategy, final row).
Executor should reproduce the literal listing in design.md §3 rather than
improvise the branch structure.

**Recommended Mode:** executor

**Dependencies:** None (parallelizable with TASK-007; functionally
independent of the conf file since Python reads `os.environ` directly)

---

## TASK-009: bin/ardconfig-onboard — resolve_llm_provider()

**Objective:** Add the new `resolve_llm_provider()` function and call it
from `main()` immediately after `output_init`, before `ensure_ai_deps`.

**Requirements:** FR-25.

**Files/Areas expected to change:** `bin/ardconfig-onboard` — one new
function, one new call site in `main()`.

**Write Lease:**
```
^bin/ardconfig-onboard$
```

**Change Budget:** max_files: 1, max_new_symbols: 1, interface_policy: extend-only

**Steps:**
1. Add `resolve_llm_provider()` per design.md's exact listing (Public
   Interfaces §4): defaults `ARDCONFIG_LLM_PROVIDER` to `ollama` if unset;
   `case` on `bedrock|ollama` → `output_step ok llm_provider ...`; any other
   value → `output_step error llm_provider "Invalid ARDCONFIG_LLM_PROVIDER value: '${ARDCONFIG_LLM_PROVIDER}' ..."`, `output_result "$EXIT_PREREQ"`, `exit "$EXIT_PREREQ"`. Matching is exact-case only (no case-folding).
2. In `main()`, insert a call to `resolve_llm_provider` immediately after
   `output_init "$(get_output_format)" "$ARG_QUIET"` and before the
   existing `ensure_ai_deps` call. Do not reorder anything else — TASK-011
   changes what the subsequent prereq check does, not its position.

**Verification:**
- `bash -n bin/ardconfig-onboard`.
- `ARDCONFIG_LLM_PROVIDER=nonsense bin/ardconfig-onboard --json --vendor-id 0000 --product-id 0000` exits 2; `jq '.steps'` on the output shows only the `llm_provider` step (proves fail-fast before any dependency work — the literal FR-25(c) acceptance test).
- `bin/ardconfig-onboard --help` still exits 0 (confirm the existing `if [[ "$ARG_HELP" == "true" ]]` guard still precedes the new call).
- With `ARDCONFIG_LLM_PROVIDER` unset, confirm execution proceeds past `resolve_llm_provider` (resolves to `ollama` without erroring).

**Rollback:** `git checkout bin/ardconfig-onboard`.

**Risk:** Low — one new function, one call-site insertion, copied verbatim from design.md.

**Recommended Mode:** executor

**Dependencies:** None functionally (independent of TASK-007); sequenced
first among the `bin/ardconfig-onboard` tasks because TASK-010–013 all
assume `$ARDCONFIG_LLM_PROVIDER` is already resolved by this point in
`main()`.

---

## TASK-010: bin/ardconfig-onboard — check_ollama_available()

**Objective:** Add the new `check_ollama_available()` function (definition
only — wiring it into `main()`'s prereq dispatch is TASK-011's job, kept
separate for a smaller, independently reviewable diff).

**Requirements:** FR-27.

**Files/Areas expected to change:** `bin/ardconfig-onboard` — one new
function, no new call site yet.

**Write Lease:**
```
^bin/ardconfig-onboard$
```

**Change Budget:** max_files: 1, max_new_symbols: 1, interface_policy: extend-only

**Steps:**
1. Add `check_ollama_available()` per design.md's exact listing (Public
   Interfaces §4), including the embedded Python heredoc verbatim: pass
   `ARDCONFIG_OLLAMA_HOST`/`ARDCONFIG_OLLAMA_MODEL` into the heredoc via
   explicit env-var assignment on the invoking command (`ARDCONFIG_OLLAMA_HOST="$host" ARDCONFIG_OLLAMA_MODEL="$model" ... <<'PYEOF'`), read them inside via `os.environ[...]`, use the `_name()` helper that checks both `.model` and `.name` attributes, and dispatch on the four-way status (`OK` / `MODEL_MISSING` / `DEPS_MISSING` / unreachable-fallback).
2. Do NOT interpolate `$host`/`$model` directly into the heredoc's Python
   source text — this is a documented injection-defense measure (design.md
   Security Model section), not a style choice.
3. Do NOT wire this function into `main()` in this task.
4. Do NOT add an explicit timeout on `client.list()` (deferred per
   design.md's Open Design Question New-4).
5. Do NOT implement automatic `ollama pull` on `MODEL_MISSING` (explicitly
   rejected — NGO5/OQ15, design.md Alternatives Considered A11).

**Verification:**
- `bash -n bin/ardconfig-onboard`.
- `grep -c 'check_ollama_available' bin/ardconfig-onboard` returns exactly `1` (definition only — TASK-011 brings this to `2`).
- Visual diff review against design.md's listing (the heredoc/env-passthrough shape is new to this codebase and should be reproduced verbatim, not adapted). A full functional smoke test of this function is deferred to TASK-017, since it is not yet reachable from `main()` and exercising it standalone requires `output_init` to have already run.

**Rollback:** `git checkout bin/ardconfig-onboard`.

**Risk:** Low-Medium — the heredoc/env-var-passthrough pattern is more
intricate bash than the rest of this file and has no precedent elsewhere in
the codebase; design.md's listing is exact and worked through the
injection-defense rationale for this specific shape, so deviation risk is
the main concern.

**Recommended Mode:** executor

**Dependencies:** TASK-009 (soft — this function's own local
`${ARDCONFIG_OLLAMA_HOST:-http://localhost:11434}` defaults make it
syntactically self-contained even before TASK-009 lands, but it is
sequenced after it to keep the `bin/ardconfig-onboard` edit history linear)

---

## TASK-011: bin/ardconfig-onboard — provider-conditional ensure_ai_deps() and prereq dispatch

**Objective:** Amend `ensure_ai_deps()` to conditionally install the
`ollama` pip package when `provider=ollama`, and change `main()` to branch
between `check_aws_credentials` and `check_ollama_available` based on the
resolved provider.

**Requirements:** FR-22 (amended), FR-23 (amended).

**Files/Areas expected to change:** `bin/ardconfig-onboard` —
`ensure_ai_deps()`'s body, and the `main()` call site currently reading
`check_aws_credentials` (unconditional).

**Write Lease:**
```
^bin/ardconfig-onboard$
```

**Change Budget:** max_files: 1, max_new_symbols: 0 (amends two existing
call sites; `check_ollama_available` already exists from TASK-010),
interface_policy: extend-only

**Steps:**
1. Amend `ensure_ai_deps()`: after the existing `strands`/`boto3`
   missing-package checks, add
   `if [[ "$ARDCONFIG_LLM_PROVIDER" == "ollama" ]]; then "${venv}/bin/python" -c "import ollama" 2>/dev/null || missing+=("ollama>=0.4.8,<1.0.0"); fi`
   before the existing `if [[ ${#missing[@]} -gt 0 ]]; then ... fi` install
   block. `boto3`'s check/install stays unconditional for both providers
   (C18) — do not gate it.
2. In `main()`, replace the existing unconditional `check_aws_credentials`
   call with:
   ```bash
   if [[ "$ARDCONFIG_LLM_PROVIDER" == "bedrock" ]]; then
     check_aws_credentials       # unchanged — FR-23
   else
     check_ollama_available      # NEW — FR-27
   fi
   ```
3. Do NOT introduce a `check_llm_prereqs()` wrapper/dispatcher function —
   design.md's Rejected Abstractions section explicitly rejects this as
   unneeded indirection for a single call site.
4. Do NOT modify `check_aws_credentials()`'s own body (out of scope, C20/NFR-8).

**Verification:**
- `bash -n bin/ardconfig-onboard`.
- `grep -c 'check_ollama_available' bin/ardconfig-onboard` now returns `2` (definition + call site).
- AC-014 (FR-22 amended): with the `ollama` pip package absent and `ARDCONFIG_LLM_PROVIDER=ollama`, the `deps` install step lists `ollama>=0.4.8,<1.0.0`. With `ARDCONFIG_LLM_PROVIDER=bedrock` and `ollama` absent, the `deps` step never mentions `ollama`.
- AC-010/AC-011 regression (FR-23 amended): `ARDCONFIG_LLM_PROVIDER=ollama` with no AWS credentials present does not fail on an `aws_creds` step (proves the check is skipped). `ARDCONFIG_LLM_PROVIDER=bedrock` reproduces the pre-delta exit-2/message shape when creds are missing.

**Rollback:** `git checkout bin/ardconfig-onboard`.

**Risk:** Medium — this task activates the provider branch's control flow
(previously-added functions from TASK-009/010 become reachable); converting
an unconditional call to a conditional one is the change most likely to
introduce a wrong-branch bug. Test both provider values explicitly.

**Recommended Mode:** executor

**Dependencies:** TASK-009 (needs `$ARDCONFIG_LLM_PROVIDER` resolved before
this code runs), TASK-010 (needs `check_ollama_available` to exist before
this task's `main()` edit can reference it)

---

## TASK-012: bin/ardconfig-onboard — invoke_agent() env passthrough

**Objective:** Pass the 3 new provider-related env vars
(`ARDCONFIG_LLM_PROVIDER`, `ARDCONFIG_OLLAMA_HOST`, `ARDCONFIG_OLLAMA_MODEL`)
through to the Python subprocess in `invoke_agent()`, alongside the existing
2 (`ARDCONFIG_BEDROCK_MODEL`, `ARDCONFIG_AWS_REGION`).

**Requirements:** FR-26 (data-flow completion — the agent must actually
receive the resolved config); completes the FR-25/FR-7 end-to-end path.

**Files/Areas expected to change:** `bin/ardconfig-onboard` —
`invoke_agent()`'s body only.

**Write Lease:**
```
^bin/ardconfig-onboard$
```

**Change Budget:** max_files: 1, max_new_symbols: 0, interface_policy: extend-only

**Steps:**
1. Add three env-var assignments to the subshell invoking
   `"${venv}/bin/python" -m agent.onboard_agent`, alongside the existing
   two:
   ```bash
   ARDCONFIG_LLM_PROVIDER="${ARDCONFIG_LLM_PROVIDER:-}" \
   ARDCONFIG_OLLAMA_HOST="${ARDCONFIG_OLLAMA_HOST:-}" \
   ARDCONFIG_OLLAMA_MODEL="${ARDCONFIG_OLLAMA_MODEL:-}" \
   ```
   per design.md's exact `invoke_agent()` listing (5 env vars passed
   through in total).
2. Do not change the `jq -n` input-JSON construction, the `2>/dev/null`
   suppression, or the `|| { ... exit "$EXIT_FAIL"; }` error handling.

**Verification:**
- `bash -n bin/ardconfig-onboard`.
- `grep -A10 'invoke_agent()' bin/ardconfig-onboard` shows all 5
  `ARDCONFIG_*` assignments in the subshell invocation.
- Full end-to-end confirmation of the passthrough is deferred to TASK-018's
  real-Ollama integration run.

**Rollback:** `git checkout bin/ardconfig-onboard`.

**Risk:** Low — additive lines mirroring the exact pattern of the two
existing lines directly above them.

**Recommended Mode:** executor

**Dependencies:** TASK-009 (provider var must be resolved earlier in
`main()` for this to carry a meaningful value)

---

## TASK-013: bin/ardconfig-onboard — usage() heredoc update

**Objective:** Replace the exit-code-2 description in `usage()`'s heredoc
to describe the new provider-conditional failure modes.

**Requirements:** Public Interfaces §1 (documents FR-25/FR-23/FR-27's
exit-2 conditions).

**Files/Areas expected to change:** `bin/ardconfig-onboard` — `usage()`'s
heredoc body only.

**Write Lease:**
```
^bin/ardconfig-onboard$
```

**Change Budget:** max_files: 1, max_new_symbols: 0, interface_policy: extend-only

**Steps:**
1. Replace the current line
   `  2  Missing prerequisites (no AWS creds, no Python, no venv)`
   with the exact 3-line replacement from design.md's Public Interfaces §1:
   ```
     2  Missing prerequisites (invalid ARDCONFIG_LLM_PROVIDER, no Python/venv,
        missing AI deps, no AWS credentials [provider=bedrock], or Ollama
        server/model unavailable [provider=ollama])
   ```
2. No other line in `usage()` changes — no new CLI flags are added by this
   delta.

**Verification:**
- `bin/ardconfig-onboard --help` exits 0 and shows the new exit-code-2 text verbatim.
- `git diff bin/ardconfig-onboard` for this task touches only `usage()`'s heredoc body.

**Rollback:** `git checkout bin/ardconfig-onboard`.

**Risk:** Low — text-only change, no logic.

**Recommended Mode:** executor

**Dependencies:** TASK-011, TASK-012 (sequenced last purely to keep this
shared-file edit chain linear; no functional dependency on either)

---

## TASK-014: README.md — Ollama provider documentation

**Objective:** Update the target sections identified in design.md's Rollout
Plan ("README.md target sections" table) to document provider selection,
new defaults, and the breaking default-behavior change.

**Requirements:** Rollout Plan / docs completeness (traces to R12's
blast-radius mitigation).

**Files/Areas expected to change:** `README.md` — six locations: the
`### ardconfig-onboard` intro paragraph (currently ~L93), "What it does"
step 2 (~L104), the "**Prerequisites:**" line (~L111), the
`conf/ardconfig.conf` config code block (~L240-247), the Project Structure
tree's `agent/` comment (~L300), plus one new default-flip callout. Exact
line numbers will have drifted since the design pass — locate by content
match, not line number.

**Write Lease:**
```
^README\.md$
```

**Change Budget:** max_files: 1, max_new_symbols: 0, interface_policy: extend-only

**Steps:**
1. Intro paragraph: replace *"a Strands AI agent (backed by Amazon
   Bedrock)"* with wording describing a provider-conditional backend,
   default `ollama`. Exact phrasing is this task's to write.
2. "What it does" step 2: mention the LLM backend is provider-selected via
   `ARDCONFIG_LLM_PROVIDER`.
3. "**Prerequisites:**" line: replace with provider-conditional
   prerequisites — default (`ollama`) needs a local Ollama server plus the
   configured model pulled; `ARDCONFIG_LLM_PROVIDER=bedrock` needs AWS
   credentials with Bedrock access; AI deps (`strands-agents`, `boto3`, and
   `ollama` when provider=ollama) install automatically on first use.
4. `conf/ardconfig.conf` config code block: add
   `ARDCONFIG_LLM_PROVIDER`, `ARDCONFIG_OLLAMA_HOST`,
   `ARDCONFIG_OLLAMA_MODEL` rows; annotate `ARDCONFIG_BEDROCK_MODEL`/
   `ARDCONFIG_AWS_REGION` as "(provider=bedrock only)".
5. Project Structure tree: change the `agent/` comment from
   `# Python AI agent (Strands AI + Bedrock)` to
   `# Python AI agent (Strands AI: Bedrock or Ollama)`.
6. Add a short, clearly-marked note near the top of the
   `ardconfig-onboard` README section flagging the default-provider flip
   for existing callers (R12) — this repo has no `CHANGELOG.md`; place the
   note inline in README.md to keep this task's single-file write lease.
7. Do NOT change the Exit Codes table (~L176-186) — design.md explicitly
   recommends no change there (it is intentionally generic across scripts).

**Verification:**
- Manual read-through: all six items are present and accurate against the
  landed behavior in TASK-007–013.
- `grep -n 'Amazon Bedrock' README.md` no longer shows it as the sole/implied backend in the onboard intro paragraph.
- No broken markdown (balanced fenced code blocks, aligned table pipes).

**Rollback:** `git checkout README.md`.

**Risk:** Low — documentation-only, no runtime effect. Correctness depends
on accurately reflecting TASK-007–013's landed behavior, so this task
should not start until those are done.

**Recommended Mode:** docs-release (per CLAUDE.md's delegation map, this is
user-facing documentation; substituting executor per the pre-existing
TASK-006 precedent in this document is an acceptable fallback if
docs-release is unavailable)

**Dependencies:** TASK-007, TASK-008, TASK-011, TASK-012, TASK-013

---

## TASK-015: Test framework selection and scaffold

**Objective:** Decide on and introduce a minimal test framework/harness
appropriate for this repo's bash+Python CLI shape. **No test framework
currently exists in this repo** (no `tests/`, no `pyproject.toml`, no
`requirements*.txt` — confirmed absent both by design.md's "Discovery
Needed" note and by direct inspection during this planning pass). This
decision is explicitly test-engineer's to make, not prescribed here;
design.md's Verification Strategy section suggests `pytest` for `agent/`
and `bats`/`shellspec`/hand-rolled assertions for `bin/*`, but does not
mandate them.

**Requirements:** Prerequisite for TASK-016/017/018; supports FR-25–28/NFR-8 verification generally.

**Files/Areas expected to change:** Uncertain — test-engineer's call.
Plausible candidates: a `tests/` directory, `pyproject.toml` or
`requirements-dev.txt` (if a Python runner needs pinning), a `Makefile` or
`run-tests.sh` convenience entry point. No CI config exists in this repo
(`.github/workflows/` absent); introducing one is out of scope for this
task unless test-engineer judges it necessary — if so, flag the scope
expansion back to the orchestrator rather than assuming it.

**Write Lease:**
```
^tests/.*$
^pyproject\.toml$
^requirements-dev\.txt$
^requirements-test\.txt$
^Makefile$
^run-tests\.sh$
```
(Intentionally broader than other tasks in this delta since the exact file
set is a test-engineer decision. Expand if test-engineer requests a path
not covered here.)

**Change Budget:** max_files: 6, max_new_symbols: 0 (scaffold/config only —
no test logic yet), interface_policy: extend-only

**Steps:**
1. Choose a Python test framework for `agent/` and document the choice/rationale briefly (e.g. in `tests/README.md`).
2. Choose a bash test approach for `bin/*` and document it similarly.
3. Scaffold the minimal directory/config structure for both, with no test cases yet.
4. Document a single command to run the full suite locally — this becomes the reference command for TASK-016/017/018's Verification sections and for this delta's Gate 5 summary.
5. Do NOT write any test cases in this task — scaffold only, kept separate for an independently reviewable diff.

**Verification:**
- The chosen framework's "collect zero tests, exit 0" smoke check passes.
- The documented run-all command executes without error against an empty suite.

**Rollback:** `git checkout` / `git clean` on any new paths — scaffold-only, no production code touched.

**Risk:** Low — no production code touched. Main risk is scope creep or
under-specification, bounded by the change budget above.

**Recommended Mode:** test-engineer

**Dependencies:** None (can run in parallel with TASK-007–014)

---

## TASK-016: Unit tests — create_agent() branching, precedence fix, NFR-8

**Objective:** Automated, no-live-API unit tests covering
`create_agent()`'s provider branch logic, the config-precedence-fix
regression, and NFR-8's scope-boundary invariant.

**Requirements:** FR-25 (unit portion), FR-26 (unit portion), FR-28/AC-016,
FR-11/FR-12 (regression), NFR-8; the config-precedence fix (design.md's
explicit "New, explicit test" callout in Verification Strategy).

**Files/Areas expected to change:** New test file(s) under TASK-015's
scaffold (e.g. `tests/agent/test_create_agent.py` — exact path is
test-engineer's call).

**Write Lease:**
```
^tests/.*$
```

**Change Budget:** max_files: 4, max_new_symbols: 15, interface_policy: extend-only

**Steps** (mirrors design.md's Verification Strategy table):
1. `ARDCONFIG_LLM_PROVIDER` unset → assert `create_agent()` constructs
   `OllamaModel` (mock/monkeypatch the lazy import; no real Ollama call),
   and makes no `boto3`/Bedrock call.
2. `ARDCONFIG_LLM_PROVIDER=bedrock` → assert `BedrockModel` constructed (mock the lazy import; no real AWS call).
3. `ARDCONFIG_LLM_PROVIDER=nonsense` → assert `ValueError` raised, message contains `nonsense`.
4. AC-016/FR-28 regression: in an environment where `import ollama` would
   raise `ModuleNotFoundError` (this repo's `.venv` currently lacks the
   `ollama` pip package — confirm this is still true at test-run time, or
   use `sys.modules['ollama'] = None`-style mocking as a fallback per
   design.md), assert `create_agent()` with `provider=bedrock` does not
   raise.
5. Config-precedence fix regression: with `ARDCONFIG_BEDROCK_MODEL` and
   `ARDCONFIG_OLLAMA_MODEL` set to non-empty test values as real
   environment variables, assert `create_agent()`'s resolved `model_id`
   matches the injected value in both branches.
6. Default-value regression: with `ARDCONFIG_BEDROCK_MODEL`/
   `ARDCONFIG_OLLAMA_MODEL`/`ARDCONFIG_OLLAMA_HOST`/`ARDCONFIG_AWS_REGION`
   set to the empty string `""` (simulating `invoke_agent()`'s
   `VAR="${VAR:-}"` output when the conf file's placeholder is present but
   unset), assert each resolves to its hardcoded default, not `""`. Cover
   both the unset case (item 5's absence variant) and this empty-string
   case — the bug is specifically about the absent-vs-present-but-empty
   distinction, so both must be tested.
7. NFR-8 automated check: assert `agent/tools.py` and the `SYSTEM_PROMPT`
   constant in `agent/onboard_agent.py` are byte-identical to their
   pre-delta values (golden-file/checksum comparison, or a `git diff`-based
   assertion against a stable base ref). Record which mechanism was chosen
   in the completion summary — a git-history-based check is fragile across
   rebases/squashes.

**Verification:**
- Full suite run (per TASK-015's documented command) passes with 0 failures, exercising all 7 items above.
- No test makes a real network call — confirm no unmocked `boto3.client(`/`ollama.Client(` calls exist outside mock/monkeypatch setup.

**Rollback:** `git checkout` / `git clean` on the new test file(s); no production code touched.

**Risk:** Medium — item 7's golden-file/diff mechanism has design-flagged
ambiguity; item 4's fixture depends on ambient `.venv` state, which a
future unrelated task could invalidate (e.g. installing `ollama` for other
reasons) — consider a dedicated fixture venv and note the decision made.

**Recommended Mode:** test-engineer

**Dependencies:** TASK-007, TASK-008, TASK-015

---

## TASK-017: Bash-level prereq-check tests (mocked)

**Objective:** Automated tests for `resolve_llm_provider()`, the
provider-conditional `ensure_ai_deps()` branch, and
`check_ollama_available()` against a mocked/stubbed Ollama endpoint — no
live Ollama server or live network required.

**Requirements:** FR-25 (bash-level), FR-22 amended/AC-014, FR-27/AC-012.

**Files/Areas expected to change:** New test file(s) under TASK-015's
scaffold (e.g. `tests/bin/test_ardconfig_onboard.bats`).

**Write Lease:**
```
^tests/.*$
```

**Change Budget:** max_files: 4, max_new_symbols: 15, interface_policy: extend-only

**Steps:**
1. FR-25(c): `ARDCONFIG_LLM_PROVIDER=nonsense bin/ardconfig-onboard --json --vendor-id 0000 --product-id 0000` → assert exit 2, output names `nonsense`, and the `--json` steps array contains only the failed `llm_provider` step.
2. AC-014/FR-22 amended: using a fixture venv (or a way to simulate "package absent"), assert `ollama>=0.4.8,<1.0.0` appears in the install list when `ARDCONFIG_LLM_PROVIDER=ollama`, and does NOT appear when `ARDCONFIG_LLM_PROVIDER=bedrock`.
3. FR-27/AC-012: stand up a local mock/stub HTTP endpoint simulating
   Ollama's list-models response, and test: (a) nothing listening → exit 2,
   unreachable message; (b) listening but the configured model absent →
   exit 2, message contains `ollama pull <model>` guidance, and assert no
   `ollama pull` subprocess was invoked; (c) listening with the model
   present → the check passes and execution proceeds.
4. Empirically confirm the real attribute name on Ollama's typed `Model`
   response objects (`.model` vs `.name` — design.md's Open Design Question
   New-1) if the `ollama` pip package is installed as part of this task's
   fixture setup; record the finding rather than leaving it as a guess.

**Verification:**
- Full suite run passes with 0 failures.
- No test depends on a real, running Ollama server or real network reachability — all scenarios are simulated locally.

**Rollback:** `git checkout` / `git clean` on new test files and any throwaway fixture venv paths; no production code touched.

**Risk:** Medium — building a convincing local mock of
`ollama.Client(host).list()`'s typed-object response shape requires care;
a mismatched mock shape could produce a false-positive-passing test.
Cross-check against TASK-018's real-Ollama run before trusting this suite
alone.

**Recommended Mode:** test-engineer

**Dependencies:** TASK-009, TASK-010, TASK-011, TASK-015

---

## TASK-018: Manual/integration check — real local Ollama + Bedrock regression

**Objective:** End-to-end validation against the real local Ollama server
(per the orchestrator's stated local Ollama+`gpt-oss:latest` setup) for the
`ollama` provider path, plus a Bedrock-path regression re-run to confirm
AC-011 (zero behavior change) after the config-precedence fix.

**Requirements:** FR-7 (both provider paths, AC-010/AC-011), FR-25–28
end-to-end, FR-22/FR-23 amended end-to-end, NFR-7 (informational);
design.md's Verification Strategy row "AC-001–AC-011 (regression)" —
flagged there as the single highest-priority regression check for this
delta.

**Files/Areas expected to change:** None (manual/integration run against
already-implemented code; may write a `profiles/*.json` file as a side
effect of a real onboarding run — reuse/extend the existing TASK-005 E2E
flow rather than duplicating it if a suitable test target is available).

**Write Lease:**
```
^profiles/.*\.json$
```

**Change Budget:** max_files: 2, max_new_symbols: 0, interface_policy: extend-only

**Steps:**
1. Confirm local Ollama server is running and reachable at
   `ARDCONFIG_OLLAMA_HOST` (default `http://localhost:11434`) with
   `gpt-oss:latest` pulled (`ollama list` shows it).
2. Ollama-path run: with `ARDCONFIG_LLM_PROVIDER` unset or `=ollama`, run
   `bin/ardconfig-onboard` end-to-end (headless mode via
   `--vendor-id`/`--product-id`/`--board-name` is acceptable if no test
   hardware is connected) and confirm: `resolve_llm_provider` reports
   `ollama`; `ensure_ai_deps` installs the `ollama` pip package if absent;
   `check_ollama_available` passes; the agent produces a profile using the
   Ollama backend; zero AWS network calls occur (AC-010 — verify by running
   with AWS credentials deliberately unset/invalid to prove no AWS
   dependency exists on this path).
3. Bedrock-path regression run: with `ARDCONFIG_LLM_PROVIDER=bedrock` and
   valid AWS credentials + Bedrock access, re-run the equivalent flow and
   confirm behavior is unchanged from pre-delta (AC-011) — specifically
   confirm `ARDCONFIG_BEDROCK_MODEL`/`ARDCONFIG_AWS_REGION` env-var
   overrides now actually take effect (the full-stack precedence-fix
   regression check, complementing TASK-016's unit-level version).
4. Record observed Ollama-path model output quality/reliability informally
   (design.md's carried-forward risk R14 — no AC in this delta tests
   Ollama's board-identification accuracy). Report as a risk note, not a
   blocking failure, if the local model underperforms.
5. Time the run (excluding core-download time) against NFR-7's 5-minute budget, informationally.

**Verification:**
- Ollama-path run reaches a terminal exit code (0/1/4, or a legitimate 2)
  with the expected step sequence (`llm_provider` → `deps` →
  `ollama_reachable` → agent invocation → confirmation/write), with zero
  AWS calls observed.
- Bedrock-path run reproduces pre-delta behavior (same exit-code shape,
  same step sequence plus the new additive `llm_provider`/deps steps), and
  confirms env-var overrides for `ARDCONFIG_BEDROCK_MODEL`/
  `ARDCONFIG_AWS_REGION` now work (previously broken per design.md's
  precedence-bug finding).
- Report both runs' full step output (human or `--json`) in the task
  completion summary for Gate 5 review.

**Rollback:** N/A (verification task) — if a `profiles/*.json` was written
as a side effect and needs cleanup, `git checkout`/`rm` it; an appended
udev rule is additive and generally safe to leave, consistent with
TASK-005's existing precedent.

**Risk:** High — depends on live external systems (a real local Ollama
server + model, and/or real AWS Bedrock access) and on AI-generated output
quality, mirroring TASK-005's rationale. Local-model reliability (R14) is
an accepted, not eliminated, risk for this delta.

**Recommended Mode:** test-engineer

**Dependencies:** TASK-012, TASK-013, TASK-016, TASK-017

---

## Delta Summary

| Task | Description | Risk | Dependencies | Recommended Mode |
|---|---|---|---|---|
| TASK-007 | conf/ardconfig.conf provider vars + precedence fix | Low | None | executor |
| TASK-008 | onboard_agent.py provider branch + precedence fix | Medium | None | executor |
| TASK-009 | resolve_llm_provider() | Low | None (soft: land first in bin/ardconfig-onboard chain) | executor |
| TASK-010 | check_ollama_available() | Low-Medium | TASK-009 | executor |
| TASK-011 | ensure_ai_deps() + prereq dispatch | Medium | TASK-009, TASK-010 | executor |
| TASK-012 | invoke_agent() env passthrough | Low | TASK-009 | executor |
| TASK-013 | usage() heredoc update | Low | TASK-011, TASK-012 | executor |
| TASK-014 | README.md documentation | Low | TASK-007, TASK-008, TASK-011, TASK-012, TASK-013 | docs-release |
| TASK-015 | Test framework scaffold | Low | None | test-engineer |
| TASK-016 | Unit tests: create_agent(), precedence fix, NFR-8 | Medium | TASK-007, TASK-008, TASK-015 | test-engineer |
| TASK-017 | Bash prereq-check tests (mocked) | Medium | TASK-009, TASK-010, TASK-011, TASK-015 | test-engineer |
| TASK-018 | Manual/integration: real Ollama + Bedrock regression | High | TASK-012, TASK-013, TASK-016, TASK-017 | test-engineer |

**Parallelizable:** TASK-007, TASK-008, and TASK-015 can start immediately
and in parallel with each other. TASK-009 can also start immediately
(parallel with 007/008/015); TASK-010 through TASK-013 must follow
sequentially after TASK-009 (same-file chain).

**Critical path:** TASK-009 → TASK-010 → TASK-011 → TASK-012 → TASK-013 →
TASK-014, converging with TASK-015 → TASK-016 → TASK-017 → TASK-018 as the
final gate.
