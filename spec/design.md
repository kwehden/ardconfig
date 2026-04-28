# Design — AI-Powered Hardware Onboarding for ardconfig

## 1. Architecture Overview

The onboarding feature adds a single new entry point (`bin/ardconfig-onboard`) and a Python agent package (`agent/`). It modifies one existing script (`bin/ardconfig-detect`) and one config file (`conf/ardconfig.conf`). No existing libraries or profile schema are changed.

```
┌─────────────────────────────────────────────────────────────────┐
│                        User / AI Agent                          │
│                     ardconfig-onboard [args]                    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                ┌──────────▼──────────┐
                │  bin/ardconfig-     │  Bash wrapper
                │  onboard            │  - arg parsing, config
                │                     │  - JIT dep install
                │                     │  - scan for unknown USB
                │                     │  - invoke Python agent
                │                     │  - human confirmation
                │                     │  - udev rule update
                └──────────┬──────────┘
                           │ subprocess (Python)
                ┌──────────▼──────────┐
                │  agent/             │  Strands AI agent
                │  onboard_agent.py   │  - research board
                │  tools.py           │  - generate profile JSON
                │                     │  - validate via bash
                │                     │  - run setup & verify
                │                     │  - iterate on failure
                └──────────┬──────────┘
                           │ tools call
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
   arduino-cli        web search     existing scripts
   board listall      (board docs)   ardconfig-setup
   core search                       ardconfig-verify
   core install                      board-profiles.sh
```

### Modified Existing Components

| Component | Change | Requirement |
|---|---|---|
| `bin/ardconfig-detect` | Remove `vid == "2341"` guard; match all profile vendor IDs; report unknown devices | FR-1, FR-2 |
| `conf/ardconfig.conf` | Add `ARDCONFIG_BEDROCK_MODEL` and `ARDCONFIG_AWS_REGION` | FR-11, FR-12 |
| `udev/99-arduino.rules` | Appended at runtime by onboard script for new vendor IDs | FR-18 |

### New Components

| Component | Purpose | Requirement |
|---|---|---|
| `bin/ardconfig-onboard` | Bash entry point for onboarding flow | FR-3 |
| `agent/__init__.py` | Package marker | — |
| `agent/onboard_agent.py` | Strands AI agent: research, generate, validate, setup, verify | FR-7 through FR-10, FR-13, FR-19–21 |
| `agent/tools.py` | Tool definitions for the Strands agent | FR-8, FR-9, FR-10 |

---

## 2. Component Design: bin/ardconfig-onboard

Bash wrapper script. Follows the same patterns as all existing ardconfig scripts.

### Responsibilities

1. Parse args (`--vendor-id`, `--product-id`, `--board-name`, `--json`, `--quiet`, `--non-interactive`, `--help`)
2. Load config (`load_config` from common.sh)
3. JIT install AI dependencies if missing (FR-22)
4. Determine onboarding input:
   - If `--vendor-id`/`--product-id` or `--board-name` provided: use those (headless mode)
   - Otherwise: scan USB for unknown devices (hardware-present mode)
5. Check for existing profile conflict (FR-17)
6. Invoke the Python agent via subprocess, passing input as JSON on stdin
7. Receive agent output (profile JSON + status) on stdout
8. Display profile to user, prompt for confirmation (FR-16) — skip in `--non-interactive`
9. Allow user to override profile `id` (FR-14)
10. Write profile to `profiles/<id>.json`
11. Update udev rules if new vendor ID (FR-18)
12. The agent handles setup and verify internally (FR-19, FR-20)
13. Emit final result via output.sh

### CLI Interface

```
Usage: ardconfig-onboard [OPTIONS]

Onboard a new Arduino-compatible board using AI-assisted research.

Options:
  --vendor-id VID     USB vendor ID (hex, e.g., 0483)
  --product-id PID    USB product ID (hex, e.g., 374b)
  --board-name NAME   Board name for research (e.g., "Nucleo-F411RE")
  --json              Output JSON instead of human-readable text
  --quiet, -q         Suppress informational output
  --non-interactive   Run without prompts (auto-approve confirmation)
  --help, -h          Show this help

Exit codes:
  0  Board onboarded successfully
  1  Onboarding failed
  2  Missing prerequisites (no AWS creds, no Python, no venv)
  3  No unknown hardware found (hardware-present mode)
  4  Partial success (profile created but setup/verify failed)
```

### Unknown Device Scanning

When no `--vendor-id`/`--product-id`/`--board-name` flags are provided, the script scans `/dev/ttyACM*` and `/dev/ttyUSB*` using `udevadm info`, loads all profiles via `board-profiles.sh`, and identifies devices whose vendor/product ID does not match any profile (via `profiles_match_usb`). If multiple unknown devices are found, presents a selection menu (or processes the first one in `--non-interactive` mode).

### JIT Dependency Install (FR-22)

```bash
ensure_ai_deps() {
  local venv="${ARDCONFIG_VENV_PATH:-.venv}"
  if [[ ! -f "${venv}/bin/python" ]]; then
    output_step error venv "Python venv not found. Run ardconfig-setup first."
    exit "$EXIT_PREREQ"
  fi
  local missing=()
  "${venv}/bin/python" -c "import strands" 2>/dev/null || missing+=(strands-agents)
  "${venv}/bin/python" -c "import boto3" 2>/dev/null || missing+=(boto3)
  if [[ ${#missing[@]} -gt 0 ]]; then
    output_step info deps "Installing AI dependencies: ${missing[*]}"
    "${venv}/bin/pip" install --quiet "${missing[@]}" || {
      output_step error deps "Failed to install: ${missing[*]}"
      exit "$EXIT_PREREQ"
    }
    output_step ok deps "AI dependencies installed"
  fi
}
```

### Udev Rule Update (FR-18)

```bash
update_udev_rules() {
  local vendor_id="$1"
  local rules_src="${ARDCONFIG_UDEV}/99-arduino.rules"
  if grep -q "idVendor==\"${vendor_id}\"" "$rules_src" 2>/dev/null; then
    return 0  # Already covered
  fi
  local comment="# Vendor ${vendor_id} (added by ardconfig-onboard)"
  local rule="SUBSYSTEM==\"tty\", ATTRS{idVendor}==\"${vendor_id}\", MODE=\"0666\""
  local rule2="SUBSYSTEM==\"usb\", ATTRS{idVendor}==\"${vendor_id}\", MODE=\"0666\""
  echo "" >> "$rules_src"
  echo "$comment" >> "$rules_src"
  echo "$rule" >> "$rules_src"
  echo "$rule2" >> "$rules_src"
  require_sudo
  run_sudo cp "$rules_src" /etc/udev/rules.d/99-arduino.rules
  run_sudo udevadm control --reload-rules
  run_sudo udevadm trigger
}
```

---

## 3. Component Design: Python Strands AI Agent

### File Structure

```
agent/
├── __init__.py
├── onboard_agent.py    # Agent definition, system prompt, main entry point
└── tools.py            # Strands tool definitions
```

### Agent System Prompt

```
You are an Arduino board identification agent. Given a USB device's vendor ID
and product ID (and optionally a board name), your job is to research the board
and produce a complete ardconfig board profile JSON.

The profile must contain these fields:
- id: short identifier (lowercase, hyphenated, e.g., "nucleo-f411re")
- name: human-readable name (e.g., "STM32 Nucleo-F411RE")
- fqbn: Fully Qualified Board Name for arduino-cli
- core: arduino-cli core package identifier
- core_url: board manager URL (empty string if official Arduino core)
- usb_vendor_id: 4-digit hex USB vendor ID
- usb_product_id: 4-digit hex USB product ID
- usb_driver: Linux kernel driver (typically "cdc_acm" or "ch341-uart")
- serial_pattern: glob for serial device (typically "/dev/ttyACM*" or "/dev/ttyUSB*")
- network_discoverable: boolean
- mac_oui_prefixes: array of MAC prefixes (usually empty)
- blink_led_pin: "LED_BUILTIN" or a pin number
- notes: brief description of the board

Workflow:
1. Use arduino_cli_search to find matching boards and cores
2. Use web_search to find board documentation, pinouts, and board manager URLs
3. Read existing profiles with read_file for schema reference
4. Generate the profile JSON
5. Validate it with validate_profile
6. Run setup with run_setup to install the core
7. Run verify with run_verify to compile a test sketch
8. If setup or verify fails, analyze the error and retry with corrected values (max 2 retries)

Output the final profile JSON as your last message, wrapped in ```json fences.
If you cannot determine all fields, set unknown fields to "TODO" and explain what's missing.
```

### Tool Definitions (agent/tools.py)

Each tool is a Python function decorated with `@tool` from the Strands AI SDK.

**arduino_cli_search(command: str) → str**
Runs an arduino-cli command and returns stdout. Allowed commands:
- `board listall` — list all known boards and FQBNs
- `board listall <search>` — search for a specific board
- `core search <query>` — search for core packages
- `core list` — list installed cores
- `config dump` — show current config including board manager URLs

Implementation: `subprocess.run(["arduino-cli"] + command.split(), capture_output=True, text=True)`

**web_search(query: str) → str**
Searches the web for board documentation. Implementation: uses a simple HTTP search API or the Strands built-in web search tool if available. Returns top results as text.

**read_file(path: str) → str**
Reads a file and returns its contents. Restricted to the ardconfig project directory for security.

**write_file(path: str, content: str) → str**
Writes content to a file. Restricted to `profiles/` directory.

**validate_profile(profile_path: str) → str**
Validates a profile JSON by invoking the bash validation:
```python
result = subprocess.run(
    ["bash", "-c", f"""
        source lib/board-profiles.sh
        jq -e '.id and .fqbn and .core and .usb_vendor_id and .usb_product_id' {profile_path}
    """],
    capture_output=True, text=True, cwd=ARDCONFIG_ROOT
)
```
Returns "valid" or the validation error.

**run_setup(board_id: str) → str**
Runs `bin/ardconfig-setup --boards <board_id> --non-interactive --json` and returns the JSON output.

**run_verify(board_id: str) → str**
Runs `bin/ardconfig-verify --boards <board_id> --json` and returns the JSON output.

### Agent Entry Point (agent/onboard_agent.py)

```python
"""ardconfig AI-powered board onboarding agent."""
import json
import sys
import os

from strands import Agent
from strands.models.bedrock import BedrockModel
from agent.tools import (
    arduino_cli_search, web_search, read_file,
    write_file, validate_profile, run_setup, run_verify
)

SYSTEM_PROMPT = """..."""  # As defined above

def create_agent():
    model_id = os.environ.get(
        "ARDCONFIG_BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-6"
    )
    region = os.environ.get("ARDCONFIG_AWS_REGION",
             os.environ.get("AWS_DEFAULT_REGION", "us-west-2"))

    model = BedrockModel(
        model_id=model_id,
        region_name=region
    )
    return Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[
            arduino_cli_search, web_search, read_file,
            write_file, validate_profile, run_setup, run_verify
        ]
    )

def main():
    """Entry point called by bin/ardconfig-onboard.

    Reads JSON input from stdin:
      {"vendor_id": "0483", "product_id": "374b", "board_name": "Nucleo-F411RE"}

    Writes JSON output to stdout:
      {"status": "success", "profile": {...}, "setup_result": {...}, "verify_result": {...}}
    """
    input_data = json.loads(sys.stdin.read())
    agent = create_agent()

    prompt = build_prompt(input_data)
    result = agent(prompt)

    # Parse the profile JSON from the agent's response
    output = parse_agent_output(result)
    json.dump(output, sys.stdout, indent=2)

def build_prompt(input_data):
    parts = ["Research and create a board profile for an Arduino-compatible board."]
    if input_data.get("vendor_id") and input_data.get("product_id"):
        parts.append(f"USB Vendor ID: {input_data['vendor_id']}")
        parts.append(f"USB Product ID: {input_data['product_id']}")
    if input_data.get("board_name"):
        parts.append(f"Board name: {input_data['board_name']}")
    parts.append("Read an existing profile from profiles/ to understand the schema.")
    parts.append("Then research this board and generate a complete profile.")
    return "\n".join(parts)

def parse_agent_output(result):
    # Extract JSON from the agent's response text
    text = str(result)
    # Look for ```json ... ``` block
    import re
    match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        profile = json.loads(match.group(1))
        return {"status": "success", "profile": profile}
    return {"status": "failure", "error": "Could not parse profile from agent response", "raw": text}

if __name__ == "__main__":
    main()
```

### Interface Contract: Bash ↔ Python

**Input** (stdin to Python, JSON):
```json
{
  "vendor_id": "0483",
  "product_id": "374b",
  "board_name": "Nucleo-F411RE"
}
```
All fields optional. At least one of `vendor_id`+`product_id` or `board_name` must be present.

**Output** (stdout from Python, JSON):
```json
{
  "status": "success|failure|partial",
  "profile": { /* complete profile JSON */ },
  "setup_result": { "exit_code": 0, "output": "..." },
  "verify_result": { "exit_code": 0, "output": "..." },
  "error": "...",
  "retries": 1
}
```

The bash wrapper reads this, handles confirmation, writes the profile file, and updates udev rules.

---

## 4. Modification: ardconfig-detect (FR-1, FR-2)

### Current Behavior (lines 35-43)

```bash
if [[ "$vid" == "2341" ]]; then
  is_arduino=true
elif [[ "$_HAS_PROFILES" == "true" && -n "$vid" ]]; then
  pid=$(echo "$info" | grep -oP 'ID_MODEL_ID=\K.*' || echo "")
  local alt_match
  alt_match=$(profiles_match_usb "$vid" "$pid" 2>/dev/null || echo "")
  [[ -n "$alt_match" ]] && is_arduino=true
fi
[[ "$is_arduino" == "true" ]] || continue
```

### New Behavior

```bash
pid=$(echo "$info" | grep -oP 'ID_MODEL_ID=\K.*' || echo "")

local is_known=false
if [[ "$_HAS_PROFILES" == "true" && -n "$vid" && -n "$pid" ]]; then
  local match
  match=$(profiles_match_usb "$vid" "$pid" 2>/dev/null || echo "")
  [[ -n "$match" ]] && is_known=true
fi

if [[ "$is_known" == "true" ]]; then
  # Existing behavior: enrich from profile, report as known board
  found=true
  # ... (existing enrichment code unchanged)
elif [[ -n "$vid" ]]; then
  # NEW: Report as unknown device (FR-1)
  found_unknown=true
  local board_entry
  board_entry=$(jq -n \
    --arg dev "$dev" --arg vid "$vid" --arg pid "$pid" \
    --arg model "$model" --arg serial "$serial" \
    '{device: $dev, vendor_id: $vid, product_id: $pid, name: $model, board_id: "", fqbn: "", status: "unknown"}')
  unknown_json=$(echo "$unknown_json" | jq --argjson b "$board_entry" '. + [$b]')
  output_step info "unknown_${dev##*/}" "Unknown device on ${dev} [vendor=${vid} product=${pid}] — run ardconfig-onboard"
fi
```

The JSON output gains an `unknown_boards` array alongside the existing `boards` array:
```json
{
  "status": "success",
  "boards": [...],
  "unknown_boards": [
    {"device": "/dev/ttyACM0", "vendor_id": "0483", "product_id": "374b", "name": "ST-Link", "status": "unknown"}
  ]
}
```

### Backward Compatibility (NFR-6)

- Boards with vendor `2341` are now matched via `profiles_match_usb()` instead of a hardcoded check. Since all 3 Arduino-vendor profiles (uno-q, r4wifi, giga) have `usb_vendor_id: "2341"`, they match identically.
- The nano profile (vendor `2341` primary, alt chips `1a86`/`0403`) also matches identically since `profiles_match_usb` checks primary first, then alt chips.
- The only behavioral change: devices with unknown vendor IDs now appear in output as `unknown` instead of being silently skipped.

---

## 5. Configuration Additions (FR-11, FR-12)

Append to `conf/ardconfig.conf`:

```bash
# AI onboarding settings (used by ardconfig-onboard)
ARDCONFIG_BEDROCK_MODEL=""  # Default: us.anthropic.claude-sonnet-4-6
ARDCONFIG_AWS_REGION=""     # Default: us-west-2 (falls back to AWS_DEFAULT_REGION)
```

Empty values mean "use default." Environment variables override config file values.

Resolution order for model:
1. `ARDCONFIG_BEDROCK_MODEL` env var
2. `ARDCONFIG_BEDROCK_MODEL` in ardconfig.conf
3. Default: `us.anthropic.claude-sonnet-4-6`

Resolution order for region:
1. `ARDCONFIG_AWS_REGION` env var
2. `ARDCONFIG_AWS_REGION` in ardconfig.conf
3. `AWS_DEFAULT_REGION` env var
4. Default: `us-west-2`

---

## 6. Data Flow

```
1. INPUT RESOLUTION
   ┌─────────────────────┐     ┌──────────────────────┐
   │ --vendor-id/         │     │ Scan /dev/ttyACM*    │
   │ --product-id/        │ OR  │ /dev/ttyUSB* for     │
   │ --board-name         │     │ unknown devices      │
   └──────────┬──────────┘     └──────────┬───────────┘
              └──────────┬───────────────┘
                         ▼
2. JIT DEPS          Check & install strands-agents, boto3
                         │
3. CREDENTIAL CHECK  Verify AWS credentials & Bedrock access
                         │
4. AGENT INVOCATION  Pass {vendor_id, product_id, board_name} to Python agent
                         │
                         ▼
5. AI RESEARCH       ┌─────────────────────────────────────┐
                     │ Strands Agent:                       │
                     │  a. Read existing profile (schema)   │
                     │  b. arduino-cli board listall/search │
                     │  c. Web search for board docs        │
                     │  d. Generate profile JSON            │
                     │  e. Validate via bash subprocess     │
                     │  f. Run ardconfig-setup              │
                     │  g. Run ardconfig-verify             │
                     │  h. If f/g fail: adjust & retry (×2) │
                     └──────────────┬──────────────────────┘
                                    │
6. CONFIRMATION      Display profile → user approves (or auto in --non-interactive)
                                    │
7. WRITE             Write profiles/<id>.json
                                    │
8. UDEV UPDATE       Append vendor ID rule if new → reload udev
                                    │
9. RESULT            Emit success/failure via output.sh
```

---

## 7. Error Handling & Retry

### Agent Retry Logic (FR-21)

The agent has a retry budget of **2 additional attempts** after the initial try. Retries are triggered when:
- `ardconfig-setup` fails (e.g., wrong core name, bad board manager URL)
- `ardconfig-verify` fails (e.g., wrong FQBN, compilation error)

On each retry, the agent receives the error output and is prompted to diagnose and correct the profile. The agent can modify any profile field and re-run the failed step.

After 3 total attempts (1 initial + 2 retries), the agent reports failure with the last error.

### Failure Modes

| Failure | Exit Code | Behavior |
|---|---|---|
| No Python venv | 2 | Fail fast, suggest `ardconfig-setup` |
| AI deps install fails | 2 | Fail fast, show pip error |
| No AWS credentials | 2 | Fail fast, show credential setup instructions |
| Bedrock API error | 1 | Report error, suggest checking model access |
| No unknown USB devices | 3 | Report "no unknown hardware found" |
| AI can't identify board | 4 | Output partial template with TODO fields, suggest Kiro (FR-24) |
| Profile validation fails | 1 | Agent retries; if exhausted, report validation error |
| Setup fails after retries | 4 | Profile written but setup incomplete |
| Verify fails after retries | 4 | Profile written, core installed, but verify failed |
| Profile ID conflict | — | Prompt user for override (FR-17) |

---

## 8. Security Considerations

- **AWS credentials**: Never logged, echoed, or written to files. The Python agent uses boto3's default credential chain.
- **File write restriction**: The `write_file` tool is restricted to the `profiles/` directory. Path traversal attempts are rejected.
- **Subprocess execution**: Tools that run shell commands use explicit argument lists (no shell=True) to prevent injection.
- **Udev rule update**: Requires sudo, follows existing `require_sudo`/`run_sudo` pattern from common.sh.

---

## 9. Alternatives Considered

### A1: Pure Python implementation (no bash wrapper)

**Rejected.** All existing ardconfig scripts are bash. A pure Python entry point would break the uniform CLI pattern (arg parsing via common.sh, output via output.sh, exit codes). The bash wrapper maintains consistency while delegating AI work to Python.

### A2: Integrate onboarding into ardconfig-detect

**Rejected.** Violates single-responsibility. Detect should detect; onboard should onboard. Detect can suggest running onboard when unknown devices are found.

### A3: Use LangChain instead of Strands AI SDK

**Rejected.** User specified Strands AI SDK. It's also lighter-weight and purpose-built for Bedrock.

### A4: Reimplement profile validation in Python

**Rejected.** Duplicates logic. The bash validation in board-profiles.sh is the single source of truth (OQ10). Calling it via subprocess keeps validation consistent.

### A5: Have the agent write the profile directly without bash wrapper confirmation

**Rejected.** Human-in-the-loop is a stated requirement (G5, FR-16). The bash wrapper handles confirmation because it owns the user interaction.

### A6: Store agent tools as separate script files

**Rejected.** Adds unnecessary file sprawl. A single `tools.py` module with decorated functions is the Strands AI SDK convention and keeps the agent self-contained.
