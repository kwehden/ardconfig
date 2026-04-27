# ardconfig

Reusable bootstrap package for configuring Ubuntu systems to develop with Arduino hardware. Drop these scripts into any Arduino project to get a working environment — for humans and AI agents alike.

## Supported Boards

| Board | Profile ID | FQBN | Core |
|---|---|---|---|
| Arduino Uno Q | `uno-q` | `arduino:zephyr:unoq` | `arduino:zephyr` (BETA) |
| Arduino Uno R4 WiFi | `r4wifi` | `arduino:renesas_uno:unor4wifi` | `arduino:renesas_uno` |
| Arduino Giga R1 WiFi | `giga` | `arduino:mbed_giga:giga` | `arduino:mbed_giga` |
| STM32 Nucleo-F411RE | `nucleo-f411re` | `STMicroelectronics:stm32:Nucleo_64:pnum=NUCLEO_F411RE` | `STMicroelectronics:stm32` |

The **Giga Display Shield** (ASX00039) is a peripheral that attaches to the Giga R1 WiFi board — the `giga` profile covers both.

The **Nucleo-F411RE** is the first non-Arduino-branded board, onboarded via the AI-powered `ardconfig-onboard` flow.

## Prerequisites

- Ubuntu 22.04+ (targeting 24.04)
- `sudo` access (for udev rules, group membership, apt packages)
- USB-C cable and an Arduino board
- Internet access (for downloading arduino-cli and board cores)

## Quick Start

```bash
git clone <this-repo> ardconfig
cd ardconfig
bin/ardconfig-setup                    # Configure system, install tools
bin/ardconfig-detect                   # Verify board is detected
bin/ardconfig-health                   # Run all checks
```

That's it. Three commands from zero to a working Arduino development environment.

## Scripts

### `ardconfig-setup`

Configures the system for Arduino development. Idempotent — safe to run repeatedly.

```bash
bin/ardconfig-setup                        # Install everything
bin/ardconfig-setup --boards uno-q,r4wifi  # Only install specific board cores
bin/ardconfig-setup --json --non-interactive  # Agent/CI mode
```

What it does:
1. Adds user to `dialout` group + installs udev rules for immediate serial access
2. Installs `arduino-cli` to `~/.local/bin`
3. Installs board cores for selected boards (hardware does NOT need to be connected)
4. Creates a Python virtual environment with `pyserial`
5. Installs network discovery tools (`avahi-utils`, `nmap`)

Setup is fully idempotent. Run it again to add cores for new boards — existing installs are skipped.

**Multiple boards:** Install support for all boards upfront, connect hardware whenever you're ready:
```bash
bin/ardconfig-setup                          # Installs all 3 cores (no hardware needed)
bin/ardconfig-setup --boards uno-q,r4wifi    # Or just the ones you want
# Plug in any supported board at any time — it just works
```

### `ardconfig-detect`

Detects Arduino boards connected via USB.

```bash
bin/ardconfig-detect           # Human-readable output
bin/ardconfig-detect --json    # JSON output for agents
```

Works in **degraded mode** without `jq` — reports USB device info without board profile enrichment.

Unrecognized USB devices (vendor/product ID not matching any profile) are reported as `unknown` with a suggestion to run `ardconfig-onboard`:

```json
{
  "unknown_boards": [
    {"device": "/dev/ttyACM0", "vendor_id": "0483", "product_id": "374b", "name": "STM32_STLink", "status": "unknown"}
  ]
}
```

### `ardconfig-onboard`

AI-powered board onboarding. Plug in an unknown board and let a Strands AI agent (backed by Amazon Bedrock) research it, generate a board profile, install the core, and verify compilation.

```bash
bin/ardconfig-onboard                                          # Auto-detect unknown USB device
bin/ardconfig-onboard --vendor-id 0483 --product-id 374b       # Headless mode (no hardware needed)
bin/ardconfig-onboard --board-name "Nucleo-F411RE"             # Research by name
bin/ardconfig-onboard --non-interactive --json                 # Agent/CI mode
```

What it does:
1. Scans USB for unrecognized devices (or accepts `--vendor-id`/`--product-id`/`--board-name`)
2. Invokes a Strands AI agent to research the board (FQBN, core, board manager URL, driver, LED pin, etc.)
3. Generates and validates a board profile JSON
4. Prompts for confirmation (auto-approved in `--non-interactive` mode)
5. Writes the profile to `profiles/`, updates udev rules for new vendor IDs
6. Runs `ardconfig-setup` to install the core and `ardconfig-verify` to compile a test sketch
7. If setup or verify fails, the agent iterates (adjusts profile, retries)

**Prerequisites:** AWS credentials configured with Amazon Bedrock access. AI dependencies (`strands-agents`, `boto3`) are installed automatically on first use.

### `ardconfig-discover`

Discovers Arduino boards on the local network using a fallback chain:
1. mDNS/Avahi service browse
2. Known MAC addresses (from `conf/known-macs.conf` or `--mac` flag)
3. ARP table scan for Arduino OUI prefixes
4. nmap ping sweep

```bash
bin/ardconfig-discover                              # Scan network
bin/ardconfig-discover --mac AA:BB:CC:DD:EE:FF      # Look for specific MAC
bin/ardconfig-discover --json                        # JSON output
```

For MAC-registered networks (e.g., unfabric), configure `conf/known-macs.conf`:
```
DA:E3:4A:01:23:45 uno-q "Lab Uno Q #1"
```

### `ardconfig-verify`

Compiles a Blink test sketch for each installed board core.

```bash
bin/ardconfig-verify                                          # Compile for all installed cores
bin/ardconfig-verify --fqbn arduino:renesas_uno:unor4wifi      # Specific board
bin/ardconfig-verify --upload --port /dev/ttyACM0              # Compile and upload
bin/ardconfig-verify --json                                    # JSON output
```

### `ardconfig-health`

Runs all checks and produces a summary report.

```bash
bin/ardconfig-health           # Full health check
bin/ardconfig-health --json    # JSON for agents
bin/ardconfig-health --quiet   # Errors only
```

Checks: dialout group, udev rules, serial permissions, arduino-cli, board cores, Python/venv, board detection, network deps, build verification.

## Exit Codes

All scripts use consistent exit codes:

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | General failure |
| `2` | Missing prerequisites (no sudo, no internet) |
| `3` | Hardware not found (no board detected) |
| `4` | Partial success (some checks passed, others failed) |

## Output Formats

All scripts default to human-readable output with status tags:

```
[OK]    Arduino Uno Q on /dev/ttyACM0 [arduino:zephyr:unoq]
[SKIP]  Core arduino:renesas_uno already installed (1.2.0)
[WARN]  Logout required for dialout group
[ERROR] Compilation failed for giga
```

Use `--json` for structured JSON output (canonical format):

```json
{
  "status": "success",
  "exit_code": 0,
  "steps": [
    {"status": "ok", "name": "board_ttyACM0", "message": "Arduino Uno Q detected"}
  ],
  "boards": [
    {"device": "/dev/ttyACM0", "fqbn": "arduino:zephyr:unoq", "accessible": true}
  ]
}
```

## Agent Invocation

For AI agents calling these scripts:

```bash
# Non-interactive mode (no prompts, fails if sudo unavailable)
bin/ardconfig-setup --json --non-interactive

# Check if environment is ready
bin/ardconfig-health --json --quiet

# Detect boards and parse JSON
BOARDS=$(bin/ardconfig-detect --json | jq -r '.boards[].fqbn')
```

Key flags for agents:
- `--json` — structured output for parsing
- `--non-interactive` — no prompts (auto-detected when stdin is not a TTY)
- `--quiet` — errors only

## Configuration

### `conf/ardconfig.conf`

Default settings (command-line flags override):

```bash
ARDCONFIG_BOARDS="uno-q,r4wifi,giga"   # Boards to install
ARDCONFIG_VENV_PATH=".venv"            # Python venv location
ARDCONFIG_PYTHON_PACKAGES="pyserial"   # Python packages
ARDCONFIG_CLI_VERSION=""               # arduino-cli version (empty = latest)
ARDCONFIG_BEDROCK_MODEL=""             # Bedrock model (default: us.anthropic.claude-sonnet-4-6)
ARDCONFIG_AWS_REGION=""                # AWS region (default: us-west-2)
```

### `conf/known-macs.conf`

MAC addresses for network discovery on MAC-registered networks. Copy from `conf/known-macs.conf.example`.

### Board Profiles (`profiles/*.json`)

Each board is described by a JSON profile. To add a new board, you have two options:

1. **AI-assisted (recommended):** Run `bin/ardconfig-onboard` — the AI agent researches the board and generates a validated profile automatically.
2. **Manual:** Create a new JSON file in `profiles/` following the existing schema — no script changes needed.

## Troubleshooting

**"Serial port not accessible"** — Run `ardconfig-setup`. If you just ran it, the udev rule provides immediate access but you may need to replug the USB cable. For full `dialout` group membership, logout and login.

**"arduino-cli not found" after setup** — Add `~/.local/bin` to your PATH: `export PATH="${HOME}/.local/bin:${PATH}"`. Add this to your `~/.bashrc` for persistence.

**"Core install failed"** — Check internet connectivity. The Zephyr core (Uno Q) requires the additional board manager URL which setup configures automatically. Run `arduino-cli core update-index` to refresh.

**"No boards discovered on network"** — Ensure the board is powered, connected to WiFi, and on the same network. For MAC-registered networks, add the board's MAC to `conf/known-macs.conf`.

**Uno Q notes** — The Zephyr core is BETA. First use requires a bootloader burn (double-click RESET button, then use `arduino-cli burn-bootloader`). Library compatibility is limited compared to R4 WiFi and Giga.

## Project Structure

```
ardconfig/
├── bin/                    # Executable scripts
│   ├── ardconfig-setup
│   ├── ardconfig-detect
│   ├── ardconfig-discover
│   ├── ardconfig-onboard   # AI-powered board onboarding
│   ├── ardconfig-verify
│   └── ardconfig-health
├── agent/                  # Python AI agent (Strands AI + Bedrock)
│   ├── __init__.py
│   ├── onboard_agent.py    # Agent definition and entry point
│   └── tools.py            # Agent tool definitions
├── lib/                    # Shared bash libraries
│   ├── output.sh           # JSON-canonical output formatting
│   ├── common.sh           # Arg parsing, exit codes, sudo helpers
│   └── board-profiles.sh   # Board profile loader
├── profiles/               # Board profile JSON files
│   ├── uno-q.json
│   ├── r4wifi.json
│   ├── giga.json
│   └── nucleo-f411re.json  # AI-generated
├── conf/                   # Configuration
│   ├── ardconfig.conf
│   └── known-macs.conf.example
├── templates/              # Sketch templates
│   └── blink.ino
├── udev/                   # udev rule templates
│   └── 99-arduino.rules
└── spec/                   # Design documents
```
