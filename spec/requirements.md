# Requirements — AI-Powered Hardware Onboarding for ardconfig

## EARS Format Reference

- **Ubiquitous:** The system SHALL [action].
- **Event-driven:** WHEN [event], the system SHALL [action].
- **State-driven:** WHILE [state], the system SHALL [action].
- **Optional:** WHERE [feature is enabled], the system SHALL [action].
- **Complex:** Combinations of the above.

Priority: **Must** (required for MVP), **Should** (expected), **Could** (nice-to-have).

---

## Functional Requirements

### Unknown Device Detection

**FR-1: Detect unrecognized USB devices**
WHEN a USB device is connected to `/dev/ttyACM*` or `/dev/ttyUSB*` AND its vendor/product ID does not match any loaded board profile, `ardconfig-detect` SHALL include it in its output as an unrecognized device with status `unknown`, reporting the device path, vendor ID, product ID, and USB model string.

- Rationale: Currently, unknown vendor IDs are silently skipped (line 37 of ardconfig-detect filters on `vid == "2341"`). Users and agents have no visibility into unrecognized hardware.
- Traces to: G1, AC-002
- Priority: **Must**
- Testable: Plug in Nucleo-F411RE (vendor 0483) with no profile present; verify ardconfig-detect reports it as unknown.

**FR-2: Generalize vendor ID matching in ardconfig-detect**
The `ardconfig-detect` script SHALL match USB devices against ALL vendor/product IDs present in loaded board profiles via `profiles_match_usb()`, removing the hardcoded filter for vendor ID `2341`.

- Rationale: The existing `profiles_match_usb()` function already supports arbitrary vendor/product matching. The bottleneck is the `[[ "$vid" == "2341" ]]` guard in ardconfig-detect.
- Traces to: G1, G3, AC-002, NFR-6
- Priority: **Must**
- Testable: Create a profile with vendor ID `0483`; verify ardconfig-detect finds the board without code changes beyond the vendor filter removal.

### Onboarding Entry Point

**FR-3: New script bin/ardconfig-onboard**
The system SHALL provide a new executable script `bin/ardconfig-onboard` as the entry point for AI-powered board onboarding.

- Rationale: Follows the existing pattern of one script per responsibility (detect, setup, verify, health, discover).
- Traces to: G1, OQ5
- Priority: **Must**
- Testable: `bin/ardconfig-onboard --help` exits 0 and prints usage.

**FR-4: Hardware-present mode**
WHEN `ardconfig-onboard` is invoked without `--vendor-id`, `--product-id`, or `--board-name` flags, the system SHALL scan for USB devices not matching any existing profile and offer to onboard them.

- Rationale: Primary use case — plug in a board, run onboard.
- Traces to: G1, G6, UC1
- Priority: **Must**
- Testable: With Nucleo-F411RE connected and no profile present, `ardconfig-onboard` detects and offers to onboard it.

**FR-5: Headless mode via vendor/product ID**
WHEN `ardconfig-onboard` is invoked with `--vendor-id VID --product-id PID` flags, the system SHALL initiate onboarding for a board with those USB identifiers without requiring physical hardware.

- Rationale: Supports CI, pre-provisioning, and testing without hardware.
- Traces to: G6, UC2, AC-007
- Priority: **Must**
- Testable: `ardconfig-onboard --vendor-id 0483 --product-id 374b` produces a valid profile without hardware connected.

**FR-6: Headless mode via board name**
WHEN `ardconfig-onboard` is invoked with `--board-name NAME` flag, the system SHALL initiate onboarding using the board name as the primary research input.

- Rationale: Users may know the board name but not USB IDs.
- Traces to: G6, UC2, AC-007
- Priority: **Should**
- Testable: `ardconfig-onboard --board-name "Nucleo-F411RE"` produces a valid profile.

### AI Agent

**FR-7: Strands AI agent with Bedrock backend**
The onboarding flow SHALL use a Strands AI agent implemented with the Strands AI SDK, backed by Amazon Bedrock, to research the board and determine profile fields.

- Rationale: User-stated requirement. Strands AI provides tool-use agent capabilities; Bedrock provides the LLM.
- Traces to: G7, C1, C2
- Priority: **Must**
- Testable: The agent makes at least one Bedrock API call during onboarding and uses the response to populate profile fields.

**FR-8: Agent tools — arduino-cli introspection**
The Strands AI agent SHALL have access to tools that invoke `arduino-cli board listall` and `arduino-cli core search` to look up FQBNs and core packages.

- Rationale: arduino-cli is the authoritative source for board/core information.
- Traces to: G2, OQ1, R1
- Priority: **Must**
- Testable: During onboarding, the agent invokes arduino-cli and uses its output to determine the FQBN.

**FR-9: Agent tools — web search**
The Strands AI agent SHALL have access to a web search tool to research board documentation, pinouts, board manager URLs, and hardware specifications.

- Rationale: Not all board information is available via arduino-cli (e.g., LED pin, driver type, board manager URLs for third-party cores).
- Traces to: G2, OQ1
- Priority: **Must**
- Testable: During onboarding of a board with a third-party core, the agent uses web search to find the board manager URL.

**FR-10: Agent tools — file read/write**
The Strands AI agent SHALL have access to tools for reading existing profiles (as examples) and writing the generated profile to `profiles/`.

- Rationale: The agent needs to read existing profiles to understand the schema and write the output.
- Traces to: G2, G3, OQ1
- Priority: **Must**
- Testable: The agent reads at least one existing profile during onboarding and writes the new profile to the correct path.

**FR-11: Configurable Bedrock model**
The Bedrock model ID SHALL default to Claude Sonnet 4.6 and be configurable via the `ARDCONFIG_BEDROCK_MODEL` environment variable or a setting in `conf/ardconfig.conf`.

- Rationale: Model availability varies by account and region; users may want to use a different model.
- Traces to: G7, OQ2
- Priority: **Must**
- Testable: Set `ARDCONFIG_BEDROCK_MODEL` to a different model ID; verify the agent uses it.

**FR-12: Configurable AWS region**
The AWS region for Bedrock calls SHALL default to `us-west-2` and be configurable via `AWS_DEFAULT_REGION` environment variable or `conf/ardconfig.conf`.

- Rationale: Bedrock model availability varies by region.
- Traces to: G7, OQ9
- Priority: **Must**
- Testable: Set `AWS_DEFAULT_REGION=us-east-1`; verify Bedrock calls go to that region.

### Profile Generation & Validation

**FR-13: Generate complete profile JSON**
The AI agent SHALL generate a board profile JSON containing all fields defined in the existing schema: `id`, `name`, `fqbn`, `core`, `core_url`, `usb_vendor_id`, `usb_product_id`, `usb_driver`, `serial_pattern`, `network_discoverable`, `mac_oui_prefixes`, `blink_led_pin`, `notes`.

- Rationale: Generated profiles must be indistinguishable from hand-authored ones.
- Traces to: G2, G3, AC-001, C6
- Priority: **Must**
- Testable: Generated profile for Nucleo-F411RE contains all schema fields and is valid JSON.

**FR-14: Profile ID proposal and override**
The AI agent SHALL propose a profile `id` derived from the board name (lowercased, hyphenated). WHEN the user is in interactive mode, the system SHALL allow the user to override the proposed ID before confirmation.

- Rationale: Consistent naming convention; user retains control.
- Traces to: OQ7
- Priority: **Must**
- Testable: Agent proposes `nucleo-f411re` for the Nucleo-F411RE; user can change it to a custom value.

**FR-15: Profile validation via bash subprocess**
After generating the profile JSON, the system SHALL validate it by invoking the existing `board-profiles.sh` validation logic (required fields check) via subprocess.

- Rationale: Single source of truth for validation — no duplicated logic in Python.
- Traces to: G3, AC-001, OQ10, C7
- Priority: **Must**
- Testable: A profile missing a required field (e.g., no `fqbn`) is rejected by validation.

**FR-16: Human-in-the-loop confirmation**
WHEN the profile is generated and validated, the system SHALL display the complete profile JSON to the user and prompt for confirmation before writing any files. WHILE in `--non-interactive` mode, confirmation SHALL be auto-approved.

- Rationale: Safety — AI-generated content should be reviewed before modifying the system.
- Traces to: G5, AC-006, C4
- Priority: **Must**
- Testable: In interactive mode, the profile is displayed and the system waits for y/n. In non-interactive mode, it proceeds without prompting.

**FR-17: Profile filename conflict detection**
WHEN the proposed profile ID matches an existing file in `profiles/`, the system SHALL warn the user and offer to either overwrite or choose a different ID.

- Rationale: Prevents accidental overwrite of existing profiles.
- Traces to: R7, NFR-5
- Priority: **Must**
- Testable: Run onboard for a board whose proposed ID matches an existing profile; verify warning is shown.

### System Integration

**FR-18: Udev rule update for new vendor IDs**
WHEN the generated profile contains a `usb_vendor_id` not present in `udev/99-arduino.rules`, the system SHALL append a new udev rule granting access for that vendor ID, following the existing rule format, and reinstall the rules file to `/etc/udev/rules.d/`.

- Rationale: Without udev rules, the device won't be accessible to non-root users.
- Traces to: G4, AC-005, C9
- Priority: **Must**
- Testable: After onboarding Nucleo-F411RE, `udev/99-arduino.rules` contains a rule for vendor `0483`.

**FR-19: Auto-run setup after profile creation**
After writing the profile and updating udev rules, the system SHALL automatically invoke `ardconfig-setup --boards <new-id>` to install the board core and any required board manager URLs.

- Rationale: User wants end-to-end onboarding — no manual steps between profile creation and a working environment.
- Traces to: AC-003, OQ8
- Priority: **Must**
- Testable: After onboarding Nucleo-F411RE, the stm32duino core is installed and `arduino-cli core list` shows it.

**FR-20: Auto-run verify after setup**
After setup completes successfully, the system SHALL automatically invoke `ardconfig-verify --boards <new-id>` to compile a Blink test sketch for the new board's FQBN.

- Rationale: Proves the toolchain works end-to-end.
- Traces to: AC-004, OQ8
- Priority: **Must**
- Testable: After onboarding Nucleo-F411RE, a Blink sketch compiles successfully for its FQBN.

**FR-21: Agent iteration on failure**
WHEN setup or verify fails, the Strands AI agent SHALL analyze the error output, adjust the profile fields if needed (e.g., correct FQBN, fix core_url), and retry the failed step up to 2 additional times before reporting failure.

- Rationale: AI agents can self-correct — a wrong FQBN can be fixed by re-researching.
- Traces to: OQ8, R1, R3
- Priority: **Should**
- Testable: Provide a board where the first FQBN guess is wrong; verify the agent corrects it and retries.

### Dependency Management

**FR-22: JIT install of AI dependencies**
WHEN `ardconfig-onboard` is invoked and `strands-agents` or `boto3` are not installed in the Python venv, the system SHALL install them automatically before proceeding.

- Rationale: JIT — keeps the base install lightweight; AI deps are only needed for onboarding.
- Traces to: OQ6, R5, C13
- Priority: **Must**
- Testable: Remove strands-agents from venv; run ardconfig-onboard; verify it installs the package and proceeds.

**FR-23: AWS credential validation**
WHEN `ardconfig-onboard` is invoked, the system SHALL verify that AWS credentials are available and Bedrock access is functional before starting the AI research phase. WHEN credentials are missing or invalid, the system SHALL exit with code 2 (missing prerequisites) and a clear error message.

- Rationale: Fail fast rather than failing mid-onboarding.
- Traces to: R4, NFR-4, AC-008
- Priority: **Must**
- Testable: Unset AWS credentials; run ardconfig-onboard; verify exit code 2 and descriptive error.

### Graceful Failure

**FR-24: Partial profile for unidentifiable boards**
WHEN the AI agent cannot determine all required profile fields, the system SHALL output a partial profile template with known fields (USB vendor/product ID) pre-filled and unknown fields set to `"TODO"`, and suggest the user ask Kiro to complete it.

- Rationale: Even a failed identification provides value — the USB fields are known from detection.
- Traces to: OQ3, R2
- Priority: **Must**
- Testable: Mock an AI response that cannot determine the FQBN; verify partial template is output with TODO fields and Kiro suggestion.

---

## Non-Functional Requirements

**NFR-1: CLI flag consistency**
`ardconfig-onboard` SHALL support `--json`, `--quiet`, `--non-interactive`, and `--help` flags, consistent with all existing ardconfig scripts.

- Rationale: Uniform CLI interface across the toolchain.
- Traces to: AC-009, C5
- Priority: **Must**
- Testable: Each flag is accepted and produces the expected behavior.

**NFR-2: Exit code consistency**
`ardconfig-onboard` SHALL use the standard ardconfig exit codes: 0 (success), 1 (failure), 2 (missing prerequisites), 3 (hardware not found), 4 (partial success).

- Rationale: Agents and scripts depend on consistent exit codes.
- Traces to: AC-008, C5
- Priority: **Must**
- Testable: Each exit condition produces the correct code.

**NFR-3: Output format consistency**
`ardconfig-onboard` SHALL produce output using the existing `lib/output.sh` library — `[OK]`/`[WARN]`/`[ERROR]` tags for human-readable output, structured JSON for `--json` mode.

- Rationale: Consistent output format across the toolchain.
- Traces to: AC-009, C5
- Priority: **Must**
- Testable: Human output contains status tags; JSON output is valid and contains `status`, `exit_code`, `steps` fields.

**NFR-4: Credential security**
The system SHALL NOT store, log, or echo AWS credentials, API keys, or session tokens in any output, log, or generated file.

- Rationale: Security — credentials must not leak.
- Traces to: R4, C12
- Priority: **Must**
- Testable: Run onboard with `--json` and `--verbose`; grep output for credential patterns; verify none present.

**NFR-5: Idempotency**
WHEN `ardconfig-onboard` is invoked for a board that already has a profile in `profiles/`, the system SHALL detect the existing profile and inform the user, offering to regenerate or skip.

- Rationale: Safe to run repeatedly, consistent with ardconfig-setup's idempotency.
- Traces to: R7
- Priority: **Should**
- Testable: Run onboard twice for the same board; verify second run detects existing profile.

**NFR-6: Backward compatibility**
The modification to `ardconfig-detect` (FR-2) SHALL NOT change detection behavior for boards with vendor ID `2341`. All existing profiles SHALL continue to be detected identically.

- Rationale: No regressions for existing users.
- Traces to: G3, C8
- Priority: **Must**
- Testable: Run ardconfig-detect before and after the change with an Arduino board connected; diff the output.

**NFR-7: Performance**
The onboarding flow SHALL complete within 5 minutes for a typical board, excluding core download time (which depends on network speed and core size).

- Rationale: Reasonable user experience — AI research and validation should not take excessively long.
- Traces to: R10
- Priority: **Should**
- Testable: Time the onboarding of Nucleo-F411RE end-to-end; verify < 5 minutes excluding download.

---

## Traceability Matrix

| Requirement | Goals | Acceptance Criteria | Open Questions | Risks |
|---|---|---|---|---|
| FR-1 | G1 | AC-002 | — | — |
| FR-2 | G1, G3 | AC-002 | — | — |
| FR-3 | G1 | — | OQ5 | — |
| FR-4 | G1, G6 | — | — | — |
| FR-5 | G6 | AC-007 | OQ4 | — |
| FR-6 | G6 | AC-007 | OQ4 | — |
| FR-7 | G7 | — | OQ2 | R4, R10 |
| FR-8 | G2 | — | OQ1 | R1 |
| FR-9 | G2 | — | OQ1 | R3 |
| FR-10 | G2, G3 | — | OQ1 | — |
| FR-11 | G7 | — | OQ2 | — |
| FR-12 | G7 | — | OQ9 | — |
| FR-13 | G2, G3 | AC-001 | — | R1 |
| FR-14 | — | — | OQ7 | — |
| FR-15 | G3 | AC-001 | OQ10 | — |
| FR-16 | G5 | AC-006 | — | — |
| FR-17 | — | — | — | R7 |
| FR-18 | G4 | AC-005 | — | R8 |
| FR-19 | — | AC-003 | OQ8 | — |
| FR-20 | — | AC-004 | OQ8 | — |
| FR-21 | — | — | OQ8 | R1, R3 |
| FR-22 | G7 | — | OQ6 | R5 |
| FR-23 | — | AC-008 | — | R4 |
| FR-24 | — | — | OQ3 | R2 |
| NFR-1 | — | AC-009 | — | — |
| NFR-2 | — | AC-008 | — | — |
| NFR-3 | — | AC-009 | — | — |
| NFR-4 | — | — | — | R4 |
| NFR-5 | — | — | — | R7 |
| NFR-6 | G3 | AC-002 | — | — |
| NFR-7 | — | — | — | R10 |
