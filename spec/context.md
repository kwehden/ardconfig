# Context — AI-Powered Hardware Onboarding for ardconfig

## 1. Problem Statement

ardconfig currently supports only boards with pre-authored JSON profiles in `profiles/`. When a user plugs in an Arduino-compatible board that does not match any existing profile (by USB vendor/product ID), `ardconfig-detect` silently ignores it — the board is invisible to the entire toolchain. Adding support for a new board requires a developer to manually research the board's FQBN, core package, board manager URL, USB identifiers, serial pattern, LED pin, and driver configuration, then hand-author a JSON profile. This is error-prone, time-consuming, and creates a bottleneck: every new board type requires human expertise in the Arduino ecosystem.

The immediate trigger is the Nucleo-F411RE (STMicroelectronics, USB vendor ID `0483`), the first non-Arduino-branded board to be onboarded. It uses a third-party board manager (stm32duino), a different vendor ID than any existing profile, and an ST-Link V2-1 debug interface — none of which the current system handles.

## 2. Goals

- **G1:** When a user plugs in a board whose USB vendor/product ID does not match any existing profile, ardconfig can initiate an AI-assisted onboarding flow that identifies the board and generates a complete, valid profile JSON.
- **G2:** The AI agent correctly determines all required profile fields (id, name, fqbn, core, core_url, usb_vendor_id, usb_product_id, usb_driver, serial_pattern, blink_led_pin, notes) for the Nucleo-F411RE as a proof-of-concept, producing a profile that passes the existing `board-profiles.sh` validation.
- **G3:** The generated profile integrates with the existing system without modifications to `lib/board-profiles.sh` — it is a standard JSON file placed in `profiles/` and auto-discovered on next load.
- **G4:** When a new vendor ID is encountered (e.g., `0483` for STMicroelectronics), the udev rules file is updated to grant device access for that vendor, matching the existing `99-arduino.rules` pattern.
- **G5:** A human-in-the-loop confirmation step exists: the AI generates the profile, presents it to the user, and writes it only after explicit approval.
- **G6:** The onboarding flow can run without physical hardware present (using a user-supplied vendor/product ID or board name) to support testing and CI environments.
- **G7:** The AI agent uses the Strands AI SDK with Amazon Bedrock as the LLM backend, running within the project's existing Python venv infrastructure.

## 3. Non-Goals / Out of Scope

- **NG1:** Replacing manual profile creation. Users who prefer to hand-author profiles can continue doing so.
- **NG2:** Running as a persistent service or daemon. The onboarding flow runs on-demand and exits.
- **NG3:** Providing a GUI. This is a CLI-only tool, consistent with all existing ardconfig scripts.
- **NG4:** Automatically onboarding every unknown USB device. Only devices the user explicitly wants to onboard are processed.
- **NG5:** Modifying the existing `lib/board-profiles.sh` loader or the board profile JSON schema. The generated profiles must conform to the existing schema.
- **NG6:** Supporting non-Arduino-compatible boards (e.g., Raspberry Pi Pico running MicroPython without Arduino core support).
- **NG7:** Automatic firmware upload or board provisioning during onboarding. The flow produces a profile; setup/verify handle the rest.

## 4. Users & Use-Cases

### User: Arduino Developer (Human)

**UC1 — Onboard a physically connected unknown board:**
- Trigger: User plugs in a board; `ardconfig-detect` reports no matching profile (or a new script/command surfaces the unknown device).
- Goal: Get a working board profile so the full ardconfig toolchain (setup, detect, verify, health) works with this board.
- Outcome: A validated JSON profile is written to `profiles/`, udev rules are updated if needed, and the board is usable with all existing ardconfig scripts.

**UC2 — Onboard a board without physical hardware:**
- Trigger: User wants to prepare a profile for a board they don't have connected (e.g., pre-provisioning for a lab, CI setup).
- Goal: Generate a profile by providing the board name or USB IDs as input.
- Outcome: Same as UC1, but driven by user-supplied identifiers rather than USB detection.

### User: AI Coding Agent

**UC3 — Automated environment bootstrap with unknown hardware:**
- Trigger: An AI agent runs `ardconfig-detect --json`, finds an unrecognized device, and invokes the onboarding flow programmatically.
- Goal: Extend ardconfig's board support without human intervention (beyond the confirmation step, which can be auto-approved in non-interactive mode with appropriate flags).
- Outcome: Profile generated and integrated; agent can proceed with `ardconfig-setup` and `ardconfig-verify`.

## 5. Constraints & Invariants

### User-Stated Constraints

- **C1:** The AI agent must be implemented in Python, using the project's existing Python venv.
- **C2:** Strands AI SDK is the agent framework; Amazon Bedrock is the LLM backend.
- **C3:** The Nucleo-F411RE (STM32, vendor `0483`, ST-Link V2-1) is the first board to prove the end-to-end pipeline.
- **C4:** Human-in-the-loop: the AI generates the profile, the user confirms before it is written to disk.

### Codebase Constraints

- **C5:** All existing scripts are bash 4.0+. The AI agent is Python, but integration points with existing bash scripts must use the established patterns (exit codes, `--json` output, `--non-interactive` flag).
- **C6:** The board profile JSON schema is fixed (see `profiles/*.json` for the canonical fields). Generated profiles must include all required fields validated by `board-profiles.sh`: `id`, `fqbn`, `core`, `usb_vendor_id`, `usb_product_id`. Optional fields (`core_url`, `usb_driver`, `serial_pattern`, `network_discoverable`, `mac_oui_prefixes`, `blink_led_pin`, `notes`, `usb_alt_chips`) should be populated when the AI can determine them.
- **C7:** The `profiles_load` function in `board-profiles.sh` auto-discovers all `*.json` in `profiles/` — no loader changes are needed for new profiles.
- **C8:** The existing `ardconfig-detect` filters by vendor ID `2341` (Arduino) as a primary match, with `usb_alt_chips` as a secondary match. A new vendor ID like `0483` will only be detected if a profile with that vendor ID exists or if the detection logic is extended.
- **C9:** The udev rules file (`udev/99-arduino.rules`) currently only covers vendor IDs `2341` (Arduino), `1a86` (CH340), and `0403` (FTDI). New vendor IDs require new rules.
- **C10:** The project uses `jq` for all JSON operations in bash. The Python agent can use native JSON handling.
- **C11:** Configuration lives in `conf/ardconfig.conf`. Any new configuration (e.g., Bedrock model selection, AWS region) should follow this pattern.

### Organizational Constraints

- **C12:** AWS credentials must be available for Bedrock API calls. The agent must not store or log credentials.
- **C13:** The Strands AI SDK and `boto3` (for Bedrock) are additional Python dependencies that must be installed in the venv.

## 6. Success Metrics & Acceptance Criteria

- **AC-001:** Given a Nucleo-F411RE connected via USB, the onboarding flow produces a valid `profiles/nucleo-f411re.json` that passes `board-profiles.sh` validation (all required fields present, valid JSON).
- **AC-002:** After onboarding the Nucleo-F411RE, `ardconfig-detect` identifies the board by its profile, reporting its name, FQBN, and device path.
- **AC-003:** After onboarding, `ardconfig-setup --boards nucleo-f411re` installs the correct core (stm32duino) using the profile's `core_url`.
- **AC-004:** After onboarding, `ardconfig-verify --boards nucleo-f411re` compiles a Blink sketch for the board's FQBN without errors.
- **AC-005:** The udev rules file is updated to include vendor ID `0483` (STMicroelectronics) after onboarding, and the device is accessible without manual rule editing.
- **AC-006:** The onboarding flow presents the generated profile to the user and waits for confirmation before writing any files.
- **AC-007:** The onboarding flow can be invoked without physical hardware by providing a board name or USB vendor/product ID as arguments, and still produces a valid profile.
- **AC-008:** The onboarding flow exits with standard ardconfig exit codes (0 success, 1 failure, 2 missing prerequisites).
- **AC-009:** The onboarding flow produces `--json` structured output consistent with the existing ardconfig JSON output conventions.

## 7. Risks & Edge Cases

| # | Risk / Edge Case | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | AI generates incorrect FQBN or core package name, leading to failed core install or compilation | Med | High | Validate the generated profile by checking the FQBN against `arduino-cli board listall` output and attempting a core install before finalizing. |
| R2 | AI cannot identify the board (obscure clone, new product, insufficient training data) | Med | Med | Provide a graceful failure path: report what was found, suggest manual profile creation, and output a partial profile template the user can complete. |
| R3 | Board manager URL is incorrect or outdated | Med | High | Validate the URL is reachable (HTTP HEAD request) before writing the profile. Flag if unreachable. |
| R4 | AWS credentials not configured or Bedrock access not provisioned | Med | High | Check for valid AWS credentials and Bedrock model access at startup; fail fast with a clear error message and setup instructions. |
| R5 | Strands AI SDK or boto3 not installed in venv | Low | Med | Check for required Python packages at startup; offer to install them or direct user to run setup. |
| R6 | Multiple unknown devices connected simultaneously | Low | Low | Present a selection menu or process each device individually. |
| R7 | Generated profile has an `id` that conflicts with an existing profile filename | Low | Med | Check for filename conflicts before writing; prompt user for an alternative ID if conflict exists. |
| R8 | udev rule update requires sudo but user is in non-interactive mode without sudo access | Med | Med | Follow existing `ardconfig-setup` pattern: use `require_sudo` / `run_sudo` from `common.sh`. Skip udev update with a warning if sudo is unavailable. |
| R9 | Board uses a USB interface that doesn't present a serial port (e.g., ST-Link DFU mode only) | Low | Med | The AI should research the board's USB interface modes and note any special requirements in the profile's `notes` field. |
| R10 | Rate limiting or throttling on Bedrock API calls | Low | Low | Implement retry with backoff. Single onboarding flow should require few LLM calls. |
| R11 | The `usb_alt_chips` field is needed for boards with common clone chips but the AI doesn't know the clone variants | Low | Low | Populate `usb_alt_chips` as empty array by default; note in `notes` if clone variants are known. |

## 8. Observability / Telemetry Expectations

- **Logging:** The onboarding flow should log each step to stderr in the existing `[OK]`/`[WARN]`/`[ERROR]` format, and support `--json` for structured output. Key events to log: USB device detected, AI agent invoked, profile fields determined, validation results, profile written, udev updated.
- **No remote telemetry.** ardconfig is a local development tool. No metrics or traces are sent externally. Bedrock API calls are the only network traffic, and those are governed by the user's AWS account.
- **Debug mode.** Assumption: A `--verbose` or `--debug` flag could expose the AI agent's reasoning steps (tool calls, intermediate results) for troubleshooting. This is a design decision to be made by the design-architect.

## 9. Rollout & Backward Compatibility

- **Not a breaking change.** This is a purely additive feature. No existing scripts, profiles, or configurations are modified in their behavior.
- **No feature flag needed.** The onboarding flow is a new entry point (likely a new script or subcommand). Users who don't invoke it are unaffected.
- **Rollback plan:** Remove the new script and any AI-generated profiles from `profiles/`. The system reverts to its current state.
- **Migration:** None. Existing profiles and configurations are untouched.
- **New dependencies:** Strands AI SDK and boto3 are added to the Python venv. These are optional — the rest of ardconfig works without them. Assumption: The venv setup in `ardconfig-setup` should not install AI dependencies by default; they should be installed on first use of the onboarding flow or via an explicit flag.
- **udev rule changes:** New vendor ID rules are appended to `99-arduino.rules`. Existing rules are preserved. The installed copy in `/etc/udev/rules.d/` is updated via the same `ardconfig-setup` mechanism.

## 10. Open Questions

| # | Question | Suggested Default / Resolution Path | Who Can Answer |
|---|---|---|---|
| OQ1 | What specific Strands AI tools does the agent need? Candidates: web search (for board documentation), arduino-cli introspection (`board listall`, `core search`), USB device database lookup, file read/write. | Start with arduino-cli introspection tools and web search. Add more tools iteratively based on what the agent needs to reliably identify boards. | Design-architect, informed by Strands AI SDK documentation |
| OQ2 | Which Bedrock model should be used? | Claude Sonnet 4 (recommended by user). Confirm model ID and region availability. Make it configurable via `ardconfig.conf` or environment variable. | User / AWS Bedrock documentation |
| OQ3 | How should the system handle boards the AI cannot identify? | Output a partial profile template with the known USB fields pre-filled and unknown fields marked as `"TODO"`. Log a clear message directing the user to complete it manually. | Design-architect |
| OQ4 | What is the testing strategy without physical hardware? | Accept `--vendor-id` / `--product-id` or `--board-name` flags to bypass USB detection. Use the Nucleo-F411RE as a golden test case with expected profile output for integration tests. Mock Bedrock responses for unit tests. | Design-architect / Test-engineer |
| OQ5 | Should this be a new script (`bin/ardconfig-onboard`) or integrated into an existing script (e.g., `ardconfig-detect --onboard`)? | New script `bin/ardconfig-onboard` is cleaner — follows the existing pattern of one script per responsibility. `ardconfig-detect` could suggest running it when unknown devices are found. | Design-architect |
| OQ6 | Should AI dependencies (strands-agents, boto3) be installed by `ardconfig-setup` by default, or only on first use of the onboarding flow? | Only on first use or via explicit `ardconfig-setup --ai` flag. Keeps the base install lightweight for users who don't need AI onboarding. | Design-architect / User preference |
| OQ7 | How should the generated profile `id` be determined? From the AI's research, from the USB product string, or from user input? | AI proposes an `id` based on the board name (lowercased, hyphenated), user can override during the confirmation step. | Design-architect |
| OQ8 | Should the onboarding flow also run `ardconfig-setup --boards <new-id>` automatically after profile creation, or leave that to the user? | Leave it to the user. The onboarding flow's responsibility ends at profile creation and udev update. Print a "next steps" message suggesting `ardconfig-setup --boards <id>`. | User preference |
| OQ9 | What AWS region should be used for Bedrock calls? | Default to `us-east-1` (broadest model availability). Make configurable via `AWS_DEFAULT_REGION` environment variable or `ardconfig.conf`. | User / AWS account setup |
| OQ10 | Should the Python AI agent invoke bash validation scripts (e.g., `board-profiles.sh` validation) via subprocess, or reimplement validation in Python? | Invoke bash scripts via subprocess to avoid duplicating validation logic. This keeps the profile schema definition in one place. | Design-architect |

## 11. Glossary

| Term | Definition |
|---|---|
| **FQBN** | Fully Qualified Board Name — the identifier used by `arduino-cli` to target a specific board (e.g., `arduino:avr:nano`, `STMicroelectronics:stm32:Nucleo_64`). Format: `VENDOR:ARCHITECTURE:BOARD`. |
| **Board Manager URL** | A URL pointing to a JSON index of third-party board packages for `arduino-cli`. Required for non-official Arduino cores (e.g., stm32duino). Configured via `arduino-cli config add board_manager.additional_urls`. |
| **Core** | An `arduino-cli` board support package that provides the toolchain, libraries, and board definitions for a family of boards (e.g., `arduino:avr`, `STMicroelectronics:stm32`). |
| **Strands AI SDK** | An open-source Python SDK for building AI agents with tool use, backed by LLM providers like Amazon Bedrock. |
| **Amazon Bedrock** | AWS managed service providing access to foundation models (LLMs) via API. Used here as the AI backend for the onboarding agent. |
| **ST-Link** | STMicroelectronics' debug/programming interface, used on Nucleo and Discovery boards. Presents as USB vendor `0483`. |
| **Nucleo-F411RE** | An STMicroelectronics development board based on the STM32F411RE microcontroller (Cortex-M4, 100 MHz). The first non-Arduino-branded board to be onboarded through this flow. |
| **stm32duino** | Community-maintained Arduino core for STM32 microcontrollers, providing Arduino API compatibility for STM32 boards. |
| **udev** | Linux subsystem for managing device nodes in `/dev/`. Rules in `/etc/udev/rules.d/` control permissions and naming for USB devices. |
| **Board Profile** | A JSON file in `profiles/` describing a supported board's identity, toolchain configuration, and hardware characteristics. The atomic unit of board support in ardconfig. |
| **Human-in-the-loop** | A workflow pattern where an AI system generates output but requires explicit human approval before taking action (writing files, modifying system state). |
| **Vendor ID / Product ID** | USB identifiers (16-bit hex) assigned by the USB-IF. Used to identify the manufacturer and specific product of a USB device. |
