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
