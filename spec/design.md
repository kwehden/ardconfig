# Design — ardconfig

## 1. Architecture Overview

ardconfig is a collection of bash scripts organized around a **board profile** abstraction. Each supported board is described by a JSON profile file. Scripts read these profiles to determine FQBNs, core packages, USB identifiers, and discovery methods — so adding or updating board support requires no script changes.

```
ardconfig/
├── bin/                        # Executable scripts (user-facing)
│   ├── ardconfig-setup         # FR-1, FR-2, FR-3, FR-5.1
│   ├── ardconfig-detect        # FR-4
│   ├── ardconfig-discover      # FR-5
│   ├── ardconfig-verify        # FR-6
│   └── ardconfig-health        # FR-7
├── lib/                        # Shared libraries (sourced by scripts)
│   ├── output.sh               # NFR-5: JSON-canonical output, human formatting
│   ├── common.sh               # Arg parsing, exit codes, sudo helpers
│   └── board-profiles.sh       # Board profile loader
├── profiles/                   # Board profile JSON files
│   ├── uno-q.json
│   ├── r4wifi.json
│   └── giga.json
├── templates/                  # Test sketch templates
│   └── blink.ino
├── conf/                       # User-editable configuration
│   ├── ardconfig.conf          # Defaults (venv path, board selection)
│   └── known-macs.conf         # MAC addresses for network discovery (FR-5.3)
├── udev/                       # udev rule templates
│   └── 99-arduino.rules
└── README.md                   # NFR-6
```

## 2. Board Profile Schema

Each profile in `profiles/` is a JSON file:

```json
{
  "id": "uno-q",
  "name": "Arduino Uno Q",
  "fqbn": "arduino:zephyr:unoq",
  "core": "arduino:zephyr",
  "core_url": "https://downloads.arduino.cc/packages/package_zephyr_index.json",
  "usb_vendor_id": "2341",
  "usb_product_id": "0078",
  "usb_driver": "cdc_acm",
  "serial_pattern": "/dev/ttyACM*",
  "network_discoverable": true,
  "mac_oui_prefixes": [],
  "blink_led_pin": 50,
  "notes": "Zephyr core is BETA. Requires bootloader burn on first use."
}
```

Fields:
- `id` — Short identifier used in `--boards` flag
- `fqbn` — Fully Qualified Board Name for arduino-cli
- `core` — arduino-cli core package name
- `core_url` — Additional board manager URL (empty string if not needed)
- `usb_vendor_id` / `usb_product_id` — USB device identification
- `serial_pattern` — Glob for expected serial device paths
- `network_discoverable` — Whether to include in network discovery
- `mac_oui_prefixes` — Known MAC OUI prefixes for ARP/nmap fallback (empty if unknown; populate via `known-macs.conf` or discover at runtime)
- `blink_led_pin` — LED pin for the Blink test sketch. If set to `"LED_BUILTIN"` (string) or omitted, the template uses the core's built-in `LED_BUILTIN` constant. Numeric values override for boards where `LED_BUILTIN` is incorrect (e.g., Uno Q uses pin 50).

### Adding a new board

Create a new JSON file in `profiles/`. No script changes needed. The `board-profiles.sh` library auto-discovers all `*.json` files in the profiles directory.

### Note on the Giga Display Shield

The `giga` profile represents the **Arduino Giga R1 WiFi** board, which the Giga Display Shield (ASX00039) attaches to. The display shield is a peripheral — it doesn't need its own profile. The README should clarify that users need the Giga R1 WiFi board to use the display shield.

## 3. Component Design

### 3.1 Shared Output Library (`lib/output.sh`)

Implements NFR-5. All output goes through this library.

**Internal model:** Scripts build a result object as a bash associative array / JSON string. At script exit, the library emits either raw JSON or human-readable text derived from it.

Key functions:
- `output_init` — Initialize output state, parse `--json` / `--quiet` flags
- `output_step STATUS MESSAGE [DETAIL]` — Record a step result (STATUS: ok/skip/warn/error/info)
- `output_result` — Emit final output (JSON or human-readable)
- `output_json_raw KEY VALUE` — Append raw key-value to the JSON result

Human-readable format derives from JSON:
```
[OK]   dialout group membership
[SKIP] udev rules (already installed)
[WARN] logout required for group membership
[ERROR] arduino-cli core install failed: arduino:zephyr
```

JSON format:
```json
{
  "status": "partial",
  "exit_code": 4,
  "steps": [
    {"name": "dialout_group", "status": "ok", "message": "Added user to dialout"},
    {"name": "udev_rules", "status": "skip", "message": "Already installed"},
    {"name": "core_install_zephyr", "status": "error", "message": "Install failed", "detail": "..."}
  ]
}
```

### 3.2 Common Library (`lib/common.sh`)

Shared utilities:
- `parse_args "$@"` — Standard flag parsing (`--json`, `--quiet`, `--non-interactive`, `--boards`, `--help`)
- `require_command CMD` — Check if a command exists, exit 2 if not
- `require_sudo` — Check sudo availability; in non-interactive mode, exit 2 if unavailable
- `run_sudo CMD...` — Run a command with sudo, respecting non-interactive mode
- Exit code constants: `EXIT_OK=0`, `EXIT_FAIL=1`, `EXIT_PREREQ=2`, `EXIT_NO_HW=3`, `EXIT_PARTIAL=4`

### 3.3 Board Profiles Library (`lib/board-profiles.sh`)

- `profiles_load` — Read all `profiles/*.json` files into memory
- `profiles_list` — List all available board IDs
- `profiles_get BOARD_ID FIELD` — Get a field value for a board
- `profiles_filter_by_flag BOARDS_CSV` — Return profiles matching the `--boards` selection
- Uses `jq` for JSON parsing (declared dependency)

### 3.4 `ardconfig-setup` (FR-1, FR-2, FR-3, FR-5.1)

**Flow:**
1. Parse args (`--boards`, `--non-interactive`, `--json`, `--quiet`)
2. **System access (FR-1):**
   - Check dialout group → `usermod -aG dialout $USER` if needed (sudo)
   - Install `udev/99-arduino.rules` → `/etc/udev/rules.d/` (sudo)
   - Reload udev rules (sudo)
   - Verify serial port access
3. **Tool installation (FR-2):**
   - Install `arduino-cli` if missing (curl + install script to `~/.local/bin`, no sudo needed)
   - Verify `~/.local/bin` is on `$PATH`; warn if not and suggest adding it
   - Configure additional board manager URLs from selected profiles
   - Install selected board cores (skip if already installed)
4. **Python environment (FR-3):**
   - Verify Python 3.10+
   - Install `python3-venv`, `python3-pip` via apt if missing (sudo)
   - Create `.venv` if not present
   - Install `pyserial` into venv
5. **Network discovery deps (FR-5.1):**
   - Install `avahi-utils`, `nmap` via apt if missing (sudo)
6. Emit result

**Sudo operations** (collected and run together to minimize sudo prompts):
- `usermod -aG dialout $USER`
- `cp 99-arduino.rules /etc/udev/rules.d/`
- `udevadm control --reload-rules && udevadm trigger`
- `apt-get install -y python3-venv python3-pip avahi-utils nmap`

### 3.5 `ardconfig-detect` (FR-4)

**Flow:**
1. Scan `/dev/ttyACM*` and `/dev/ttyUSB*`
2. For each device, read udev properties via `udevadm info`
3. Filter by vendor ID `2341`
4. Match against board profiles by `usb_product_id` (if `jq` and profiles are available)
5. Check read/write permission on each device
6. Emit results (device path, product ID, board name, FQBN, accessible)

**Degraded mode (no jq or profiles):** If `jq` is not installed or profiles are not found, detect still works using pure udev scanning. It reports device path, vendor/product ID, USB model string, and accessibility — but cannot resolve FQBN or board name. A `[WARN]` is emitted advising the user to run `ardconfig-setup` or install `jq` for full board identification.

**No sudo required.**

### 3.6 `ardconfig-discover` (FR-5)

**Fallback chain:**
1. **mDNS:** `avahi-browse -t -r _arduino._tcp 2>/dev/null` — look for Arduino service advertisements
2. **Known MACs:** If `conf/known-macs.conf` or `--mac` provided, check ARP table (`ip neigh`) for those MACs
3. **ARP scan:** Scan ARP table for entries matching Arduino OUI prefixes from board profiles
4. **nmap:** `nmap -sn <subnet> | grep -i arduino` — ping sweep as last resort

Results are deduplicated by MAC address. Each result includes the discovery method used.

**No sudo required** (nmap ping sweep works without sudo on local subnet).

### 3.7 `ardconfig-verify` (FR-6)

**Flow:**
1. If `--fqbn` and `--port` provided, verify that specific board
2. Otherwise, detect connected boards (call detect logic), verify each
3. For each board:
   - Generate a Blink sketch from `templates/blink.ino`, substituting the board's `blink_led_pin`
   - Compile: `arduino-cli compile --fqbn <fqbn> <sketch_dir>`
   - If board connected and `--upload` flag: upload via `arduino-cli upload --fqbn <fqbn> --port <port>`
4. Report compile/upload results per board

### 3.8 `ardconfig-health` (FR-7)

**Orchestrator script.** Runs checks in sequence, aggregates results:

1. **System access:** dialout group membership, udev rules present, serial port permissions
2. **Tools:** arduino-cli installed + version, board cores installed + versions
3. **Python:** Python version, venv exists, pyserial installed
4. **Board detection:** Run detect, report connected boards
5. **Network discovery deps:** avahi-utils and nmap installed
6. **Build verification:** Compile Blink for each installed core (no upload by default)

Each check is a function that returns a step result. The health script aggregates all steps and emits a summary.

## 4. udev Rules Design

File: `udev/99-arduino.rules`

```
# Arduino devices — grant all users access
SUBSYSTEM=="tty", ATTRS{idVendor}=="2341", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="2341", MODE="0666"
```

This provides immediate access without requiring the user to be in the dialout group. The dialout group addition is a belt-and-suspenders approach for long-term correctness.

## 5. Configuration File

File: `conf/ardconfig.conf`

```bash
# Default boards to install (comma-separated)
# Options: uno-q, r4wifi, giga
ARDCONFIG_BOARDS="uno-q,r4wifi,giga"

# Python virtual environment path (relative to project root)
ARDCONFIG_VENV_PATH=".venv"

# Additional Python packages to install in venv
ARDCONFIG_PYTHON_PACKAGES="pyserial"

# arduino-cli version (empty = install latest, record what was installed)
# Set to pin a specific version, e.g., "1.1.1"
ARDCONFIG_CLI_VERSION=""
```

Scripts read this file if present, with command-line flags taking precedence.

## 6. Known MACs Configuration

File: `conf/known-macs.conf`

```bash
# Known Arduino board MAC addresses for network discovery
# Format: MAC_ADDRESS BOARD_ID LABEL
# Used in environments with MAC-based WiFi registration (e.g., unfabric)
DA:E3:4A:01:23:45 uno-q "Lab Uno Q #1"
2C:AB:33:67:89:AB r4wifi "Bench R4 WiFi"
```

The discover script reads this file and checks the ARP table for these specific MACs before falling back to broader scans.

## 7. Blink Template

File: `templates/blink.ino`

```cpp
// ardconfig verification sketch
// LED pin resolved from board profile or LED_BUILTIN
#ifndef ARDCONFIG_LED_PIN
#define ARDCONFIG_LED_PIN LED_BUILTIN
#endif

void setup() {
  pinMode(ARDCONFIG_LED_PIN, OUTPUT);
  Serial.begin(115200);
  Serial.println("ardconfig: verify OK");
}

void loop() {
  digitalWrite(ARDCONFIG_LED_PIN, HIGH);
  delay(500);
  digitalWrite(ARDCONFIG_LED_PIN, LOW);
  delay(500);
}
```

The verify script adds `-DARDCONFIG_LED_PIN=<pin>` to the compile flags only when the board profile specifies a numeric `blink_led_pin`. Otherwise `LED_BUILTIN` is used via the `#ifndef` fallback.

## 8. Dependency Summary

| Dependency | Required by | Install method |
|---|---|---|
| bash 4.0+ | All scripts | Pre-installed |
| jq | Board profile parsing | apt (installed by setup) |
| curl | arduino-cli install | Pre-installed on Ubuntu |
| arduino-cli | FR-2, FR-6 | Official install script |
| python3, python3-venv, python3-pip | FR-3 | apt |
| avahi-utils | FR-5 (mDNS) | apt |
| nmap | FR-5 (fallback scan) | apt |
| pyserial | FR-3, FR-4 | pip (in venv) |
| udevadm | FR-1 | Pre-installed (systemd) |

## 9. Error Handling Strategy

- Each script wraps operations in functions that return step results
- On failure, the step is recorded with status `error` and the detail message
- Scripts continue to the next step unless the failure is fatal (e.g., no sudo when required)
- The final exit code reflects the worst status: all ok → 0, any error → 1, missing prereqs → 2, no hardware → 3, mixed → 4
- Stderr is captured for failed commands and included in the JSON `detail` field

## 10. Alternatives Considered

### Monolithic setup script vs. separate scripts
**Chosen: Separate scripts.** Each script has a single responsibility and can be invoked independently by agents. A monolithic script would be harder to invoke selectively and harder to test.

### Python-based tooling vs. bash
**Chosen: Bash.** The scripts configure system-level resources (udev, groups, apt packages) where bash is the natural tool. Python would add a bootstrap dependency problem (need Python to install Python). The shared output library keeps bash manageable.

### Hardcoded board support vs. profile-based
**Chosen: Profile-based.** Board profiles decouple board knowledge from script logic. Adding the Uno R4 WiFi was trivial — just a new JSON file. When the Zephyr core stabilizes or new boards arrive, only a profile needs updating.

### arduino-cli `board list` for detection vs. udev scanning
**Chosen: udev scanning.** `arduino-cli board list` requires arduino-cli to be installed and configured. The detect script needs to work before setup is complete (for diagnostics). udev properties are always available.

## 11. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Zephyr core BETA instability | Board profile includes `notes` field; health check warns about beta cores |
| arduino-cli install script changes | Install to `~/.local/bin`; pin version via `ARDCONFIG_CLI_VERSION` in conf; install latest by default and record installed version in health check output |
| nmap not available or blocked | nmap is the last fallback; mDNS and ARP work without it |
| jq not pre-installed | Setup installs jq as first apt operation; detect/discover work in degraded mode without jq (pure udev/ARP scan, no profile enrichment) with a clear warning |
| Board profile schema changes | Profiles are versioned; `board-profiles.sh` validates required fields on load |
| MAC OUI prefixes unknown for new boards | Ship profiles with empty OUI lists; rely on `known-macs.conf` for lab environments; document how to discover and populate OUIs |
| `~/.local/bin` not on PATH | Setup checks PATH after install; emits warning with shell-specific instructions to add it |
