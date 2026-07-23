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
| **Ollama** | An open-source tool for running LLMs locally, exposing an HTTP API (default `http://localhost:11434`). Introduced as a second onboarding-agent backend in the §12 scope delta. |
| **LLM Provider** | In this document (§12), "provider" means the onboarding agent's LLM backend selection (`bedrock` or `ollama`) — distinct from "board manager"/USB "vendor" terminology used elsewhere in this glossary. |

---

## 12. Scope Delta: Ollama as a Second LLM Provider (2026-07-20)

**Status:** Approved at Gate 0 by the user. This section is additive to the Bedrock-only scope defined in §§1–11 above, which remains valid and unmodified. Nothing below removes or contradicts G7, C1–C13, FR-7/FR-11/FR-12/FR-22/FR-23, or AC-001–AC-009; it extends the LLM-backend boundary of the existing onboarding flow.

### 12.1 Problem Statement (Delta)

The existing onboarding agent (`agent/onboard_agent.py::create_agent()`) hardcodes `strands.models.bedrock.BedrockModel`, requiring AWS credentials and Bedrock model access for every onboarding run. The user's day-to-day workflow is local-first via Ollama (confirmed running locally: `gpt-oss:latest` is pulled and serving per `ollama list`/`ollama ps`). Requiring AWS for a task that can run entirely offline against a local model is an unnecessary barrier. The Strands SDK already ships a built-in `strands.models.ollama.OllamaModel` (confirmed at `.venv/lib/python3.14/site-packages/strands/models/ollama.py`, strands-agents 1.40.0) that wraps the `ollama` PyPI client — this delta wires it in as a selectable, default backend.

### 12.2 Goals (Delta)

- **GO1:** WHEN `ARDCONFIG_LLM_PROVIDER` is unset or set to `ollama` (the new default), the onboarding agent SHALL use `strands.models.ollama.OllamaModel` against a locally-configured Ollama server, requiring no AWS credentials and no AWS network egress.
- **GO2:** WHEN `ARDCONFIG_LLM_PROVIDER=bedrock`, the onboarding agent SHALL behave identically to the pre-delta implementation (BedrockModel, AWS credential check, FR-7/FR-11/FR-12/FR-23 unchanged) — this is now the explicit opt-in path rather than the implicit default.
- **GO3:** Prerequisite checks in `bin/ardconfig-onboard` SHALL become provider-conditional: `check_aws_credentials` runs only for `bedrock`; a new Ollama-reachability check runs only for `ollama`, failing fast (exit 2) before the agent is invoked.
- **GO4:** `ensure_ai_deps()` SHALL JIT-install the `ollama` PyPI package only when provider=`ollama`, mirroring the existing strands-agents/boto3 JIT-install pattern (FR-22).
- **GO5:** New configuration (`ARDCONFIG_LLM_PROVIDER`, `ARDCONFIG_OLLAMA_HOST`, `ARDCONFIG_OLLAMA_MODEL`) SHALL follow the existing `ARDCONFIG_*` env-var and `conf/ardconfig.conf` convention (C11), mirroring `ARDCONFIG_BEDROCK_MODEL`/`ARDCONFIG_AWS_REGION`.
- **GO6:** No other part of the onboarding pipeline changes: agent tools (FR-8–FR-10), system prompt, profile schema (C6), validation (FR-15), udev handling (FR-18), or the setup/verify auto-run loop (FR-19–FR-21) are unaffected by provider selection.

### 12.3 Non-Goals / Out of Scope (Delta)

- **NGO1:** No support for any LLM provider other than `bedrock`/`ollama` in this pass, even though the Strands SDK's lazy `strands.models.__getattr__` loader exposes several others (Anthropic direct, Gemini, LiteLLM, OpenAI, etc.).
- **NGO2:** No changes to `ardconfig-detect`, `ardconfig-discover`, `ardconfig-health`, `ardconfig-monitor`, `ardconfig-verify`, the board profile JSON schema, or udev rule handling.
- **NGO3:** No new board profiles.
- **NGO4:** No automatic cross-provider fallback (e.g., "try Ollama, fall back to Bedrock if unreachable"). Provider selection is explicit and single-valued per run.
- **NGO5:** No management of Ollama itself — installing it, starting the server, or pulling models is the user's responsibility. `ensure_ai_deps()` installs the `ollama` **Python client package**, not the Ollama server/binary.
- **NGO6:** No changes to agent tool definitions (`agent/tools.py`) or the system prompt in `agent/onboard_agent.py` — only the model-backend construction in `create_agent()` changes.

### 12.4 Users & Use-Cases (Delta)

- **UC4 — Local-first onboarding without AWS:** A developer without AWS credentials (or who prefers not to send hardware-research prompts to a cloud LLM) runs `ardconfig-onboard` with no special flags; it uses the local Ollama server by default and produces a profile with zero AWS network traffic.
- **UC5 (extends UC3) — CI/agent explicitly pinning Bedrock:** An automated agent or CI pipeline without a local Ollama server sets `ARDCONFIG_LLM_PROVIDER=bedrock` explicitly to preserve pre-delta behavior.

### 12.5 Constraints & Invariants (Delta)

- **C14:** Provider selection SHALL be governed by a new env var `ARDCONFIG_LLM_PROVIDER` ∈ {`bedrock`, `ollama`}. An unrecognized value is a prerequisite/configuration error (exit 2), not a silent fallback to either provider. **Default: `ollama`** — this reverses the implicit Bedrock-only default of the pre-delta implementation (see R12, OQ11).
- **C15:** New env vars `ARDCONFIG_OLLAMA_HOST` (default `http://localhost:11434`) and `ARDCONFIG_OLLAMA_MODEL` (default `gpt-oss:latest`) follow the `ARDCONFIG_*` naming convention and `conf/ardconfig.conf` pattern (C11).
- **C16:** `bin/ardconfig-onboard`'s prereq phase becomes provider-conditional: `check_aws_credentials` (existing) runs only when provider=`bedrock`; a new reachability check runs only when provider=`ollama` and must exit 2 with a clear message if the Ollama server at `ARDCONFIG_OLLAMA_HOST` is unreachable, mirroring FR-23's fail-fast contract.
- **C17:** `ensure_ai_deps()` JIT-installs the `ollama` PyPI package only when provider=`ollama`, following the existing missing-package-detection pattern used for `strands-agents`/`boto3`.
- **C18 (verified):** `boto3` is an **unconditional** (non-`extra`) install dependency of `strands-agents` — confirmed via `.venv/lib/python3.14/site-packages/strands_agents-1.40.0.dist-info/METADATA`: `Requires-Dist: boto3<2.0.0,>=1.26.0` has no `extra ==` qualifier, whereas `ollama` is gated behind `Requires-Dist: ollama<1.0.0,>=0.4.8; extra == 'ollama'`. **Conclusion: `boto3` will already be present whenever `strands-agents` is installed, regardless of selected provider.** `ensure_ai_deps()` MUST NOT be changed to skip the boto3 presence check for provider=`ollama` — the check is harmless/idempotent and skipping it would not reduce the actual install footprint. This closes the Gate-0 "can boto3 be skipped for ollama" question: verified, and the answer is no skip is needed or beneficial.
- **C19 (load-bearing for design/executor):** `strands/models/ollama.py` performs an **unconditional** `import ollama` (the PyPI client) at module load time (line 12). `strands.models`' own lazy-loading `__getattr__` (in `strands/models/__init__.py`) is bypassed by any `from strands.models.ollama import OllamaModel` or `from strands.models import OllamaModel` statement placed at **module top-level** in `agent/onboard_agent.py`, because `from X import Y` resolves the attribute immediately at import time. A naive top-level import would force the `ollama` pip package to be installed even for `bedrock`-only runs, breaking GO2/C20. The `OllamaModel` import MUST be deferred inside the provider-conditional branch of `create_agent()` (i.e., imported only when provider=`ollama` is actually selected).
- **C20:** Existing Bedrock behavior (FR-7, FR-11, FR-12, R4, NFR-4) SHALL be preserved unchanged when `ARDCONFIG_LLM_PROVIDER=bedrock`. This delta is additive, not a replacement.
- **C21:** `conf/ardconfig.conf` and README.md's env-var documentation (currently lines ~244–246 and the "Prerequisites" line under `ardconfig-onboard`, ~line 111) need corresponding entries for the three new env vars and the reversed default. Flagged for requirements-engineer/docs-release; not edited in this pass.
- **C22:** IF the `ollama` PyPI package is pinned, it SHOULD match the range strands-agents itself validates against for its `ollama` extra: `ollama<1.0.0,>=0.4.8` (per `strands_agents-1.40.0.dist-info/METADATA`), to avoid installing an incompatible major version relative to what the installed `strands-agents` release was tested with.

### 12.6 Success Metrics & Acceptance Criteria (Delta)

- **AC-010:** With `ARDCONFIG_LLM_PROVIDER` unset (or `=ollama`) and a local Ollama server running the configured model, `ardconfig-onboard` proceeds through onboarding without invoking `check_aws_credentials` and without requiring AWS credentials to be present.
- **AC-011:** With `ARDCONFIG_LLM_PROVIDER=bedrock`, `ardconfig-onboard`'s prereq checks, agent construction, and exit codes are identical to the pre-delta implementation (regression check against AC-001–AC-009).
- **AC-012:** With `ARDCONFIG_LLM_PROVIDER=ollama` and no server reachable at `ARDCONFIG_OLLAMA_HOST`, `ardconfig-onboard` exits with code 2 and a clear error message before the agent is invoked.
- **AC-013:** Setting `ARDCONFIG_LLM_PROVIDER` to a value other than `bedrock`/`ollama` exits with code 2 and a clear error message identifying the invalid value.
- **AC-014:** `ensure_ai_deps()` installs the `ollama` PyPI package when provider=`ollama` and it is missing, and does not attempt to install it when provider=`bedrock`.
- **AC-015:** `ARDCONFIG_OLLAMA_HOST` and `ARDCONFIG_OLLAMA_MODEL` are configurable via environment variable and `conf/ardconfig.conf`, defaulting to `http://localhost:11434` and `gpt-oss:latest` respectively when unset.
- **AC-016:** A venv with `strands-agents` installed but **without** the `ollama` pip package present can still successfully run `ardconfig-onboard` with `ARDCONFIG_LLM_PROVIDER=bedrock` (regression test for C19's lazy-import requirement).

### 12.7 Risks & Edge Cases (Delta)

| # | Risk / Edge Case | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R12 | **Default-flip breaking change.** Existing callers of `ardconfig-onboard` that rely on today's implicit Bedrock-only behavior (no env var needed) will silently switch to Ollama after this delta ships, and either fail (exit 2, no local server) or produce materially different results (different model, different reliability) with no code change on their end. | Med-High | High | docs-release must prominently flag the default flip (README, CHANGELOG). Confirm at Gate 1 this is the intended UX (see OQ11) — user has approved it at Gate 0, but the blast radius (any non-interactive/CI caller) warrants an explicit second confirmation. |
| R13 | Ambiguous failure mode when both the `ollama` pip package is missing **and** the Ollama server is unreachable. | Low | Med | Error messages must distinguish "dependency install failure" (JIT-install step) from "server unreachable" (prereq-check step) so users know which layer to fix. |
| R14 | Local Ollama models (e.g., `gpt-oss:latest`) may be materially less reliable than Bedrock's Claude models at structured JSON output and multi-step tool-calling (FR-8–FR-21 assume a capable tool-using model). No AC in this delta tests Ollama's actual board-identification accuracy. | Med | Med | Carry into requirements/test-engineer phases; consider a golden-test comparison (Nucleo-F411RE) across both providers before declaring parity. |
| R15 | **Import-order bug.** A naive top-level `from strands.models.ollama import OllamaModel` in `agent/onboard_agent.py` would crash at import time for any environment lacking the `ollama` pip package — including `bedrock`-only runs — because `strands.models`' lazy loader is bypassed by top-level `from X import Y` (see C19). | Med (if not explicitly called out to executor) | High (breaks the previously-working Bedrock flow) | C19 mandates deferred/conditional import; AC-016 is the regression test for this. |
| R16 | **No established HTTP-reachability-check convention in this codebase.** A grep of all `*.sh` files found zero existing `curl`/`wget` usage, so there is no precedent for how `check_ollama_reachable`-equivalent logic should be implemented (stdlib `urllib` via the venv Python, the `ollama` pip client's own connectivity call, or introducing `curl` as a new bash-level dependency). | Med | Low-Med | Resolve mechanism choice in design phase (OQ12). |
| R17 | `ARDCONFIG_OLLAMA_MODEL`'s default (`gpt-oss:latest`) is a fact about the user's local machine (confirmed via `ollama list`/`ollama ps` at spec time), not a guarantee for other installs/CI — onboarding will fail with a model-not-found error on any machine that hasn't pulled it. | Med | Med | Error-on-model-not-found should suggest `ollama pull gpt-oss:latest`; reconsider whether this should be the shipped repo-wide default vs. a purely personal override (OQ13). |

### 12.8 Observability / Telemetry (Delta)

- The new provider-conditional prereq checks SHALL log via the existing `[OK]`/`[WARN]`/`[ERROR]` step-tag convention (e.g., a new step name parallel to `aws_creds`, such as `ollama_reachable`), consistent with §8.
- No new remote telemetry is introduced. Ollama calls stay local by default (`http://localhost:11434`); if `ARDCONFIG_OLLAMA_HOST` is pointed at a remote server, that becomes the first non-AWS, non-board-manager network dependency this tool has — the selected provider and host SHOULD be logged (host is not a secret; NFR-4's credential-security constraint is not implicated since Ollama has no credentials to leak).

### 12.9 Rollout & Backward Compatibility (Delta)

- **Breaking change in default behavior** (not in CLI surface, flags, or exit-code shape): callers that don't set `ARDCONFIG_LLM_PROVIDER` move from Bedrock to Ollama. See R12.
- No new feature flag is introduced beyond `ARDCONFIG_LLM_PROVIDER` itself, which doubles as the opt-back-in mechanism (`=bedrock`).
- Rollback plan: same as §9 (remove new script/profiles), plus setting `ARDCONFIG_LLM_PROVIDER=bedrock` fully reverts runtime behavior with no code changes.
- New dependency: `ollama` PyPI package, JIT-installed like strands-agents/boto3 (C17, C22). `boto3` presence/behavior is unaffected (C18).
- Docs: README.md's onboarding "Prerequisites" line and env-var table need a docs-release pass to reflect the new default and env vars (C21) — not performed in this update.

### 12.10 Open Questions (Delta)

| # | Question | Suggested Default / Resolution Path | Who Can Answer |
|---|---|---|---|
| OQ11 | Given R12's blast radius (any caller not setting `ARDCONFIG_LLM_PROVIDER`), should the default really be `ollama`, or should the pre-delta implicit default (Bedrock) be preserved with Ollama as pure opt-in? | User has approved `ollama` as default at Gate 0. Re-confirm explicitly at Gate 1 approval of this context.md delta, given the scope of who is affected. | User (karl@wehden.com) |
| OQ12 | What mechanism should the Ollama reachability check use — stdlib `urllib` via the venv Python (matching `check_aws_credentials`'s `python -c "..."` style), the `ollama` pip client's own connectivity call (available only after JIT-install), or a new `curl` dependency (no precedent in this codebase per R16)? | Prefer stdlib `urllib` or the `ollama` client (avoids adding `curl` as a new system dependency); decide ordering relative to `ensure_ai_deps()`. | design-architect |
| OQ13 | Should `ARDCONFIG_OLLAMA_MODEL`'s shipped default be `gpt-oss:latest` (confirmed only on the user's machine) in `conf/ardconfig.conf`, or should the repo ship no default (fail with an explicit "set ARDCONFIG_OLLAMA_MODEL" error) to avoid silent model-not-found failures on other machines/CI? | Lean toward keeping `gpt-oss:latest` as the code-level fallback (matches user's environment) but ensure the model-not-found error message is actionable. | User / requirements-engineer |
| OQ14 | Should `ARDCONFIG_LLM_PROVIDER` also be settable via `conf/ardconfig.conf` (like `ARDCONFIG_BEDROCK_MODEL`), or environment-variable-only? C15 assumes the conf-file pattern applies to all three new vars — confirm this extends to the provider switch itself. | Yes, follow C11's established pattern for all three vars for consistency. | requirements-engineer |
| OQ15 | Does the JIT-install philosophy (FR-22) extend to auto-pulling the configured Ollama model (`ollama pull <model>`) if absent locally, or is model management explicitly out of scope (NGO5)? | Out of scope for this pass — surface a clear "model not found, run `ollama pull <model>`" error instead of auto-pulling (which could download several GB unexpectedly). | User / requirements-engineer |
| OQ16 | Existing G7 (§2) states the agent "uses the Strands AI SDK with Amazon Bedrock as the LLM backend" — this is no longer true for the default configuration after this delta. Should requirements-engineer amend G7's wording (and FR-7) when `spec/requirements.md` is updated for this scope, or is G7 understood as scoped to the `bedrock` provider path only? | Amend FR-7 (not G7's historical text) when requirements.md is next revised, to read as provider-conditional; leave §2 of this document as the historical record of the original Bedrock-only scope. | requirements-engineer |
