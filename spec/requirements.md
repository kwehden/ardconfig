# Requirements — ardconfig

Requirements use [EARS syntax](https://alistairmavin.com/ears/) (Easy Approach to Requirements Syntax):
- **Ubiquitous:** "The \<system\> shall \<action\>."
- **Event-driven:** "When \<trigger\>, the \<system\> shall \<action\>."
- **State-driven:** "While \<state\>, the \<system\> shall \<action\>."
- **Unwanted behavior:** "If \<condition\>, then the \<system\> shall \<action\>."
- **Optional:** "Where \<feature\>, the \<system\> shall \<action\>."

---

## Functional Requirements

### FR-1: System Access Configuration

**FR-1.1** The setup script shall add the current user to the `dialout` group if the user is not already a member.

**FR-1.2** The setup script shall install a udev rules file to `/etc/udev/rules.d/` that grants non-root access to Arduino USB devices (vendor ID `2341`), setting `MODE="0666"` for immediate access without logout.

**FR-1.3** When udev rules are installed or updated, the setup script shall reload udev rules (`udevadm control --reload-rules && udevadm trigger`).

**FR-1.4** The setup script shall verify that `/dev/ttyACM*` devices are accessible by the current user without sudo after configuration.

**FR-1.5** If the user was added to the `dialout` group during this run, the setup script shall warn that a logout/login is required for group membership to take full effect, while noting that the udev rule provides immediate access.

### FR-2: Tool Installation

**FR-2.1** The setup script shall install `arduino-cli` if it is not already installed, using the official Arduino install script.

**FR-2.2** The setup script shall configure the additional board manager URL `https://downloads.arduino.cc/packages/package_zephyr_index.json` in the arduino-cli configuration.

**FR-2.3** The setup script shall accept a `--boards` flag (comma-separated list of board identifiers: `uno-q`, `r4wifi`, `giga`) to install only the requested board cores. If omitted, all cores are installed.

**FR-2.4** The setup script shall install the following board cores via `arduino-cli core install` based on the `--boards` selection:
- `arduino:zephyr` (for Uno Q) — requires the additional board manager URL
- `arduino:renesas_uno` (for Uno R4 WiFi)
- `arduino:mbed_giga` (for Giga R1 WiFi + Giga Display Shield)

**FR-2.5** When `arduino-cli` is already installed, the setup script shall verify the installed version and report it, without reinstalling.

**FR-2.6** When a board core is already installed, the setup script shall skip installation and report the installed version.

### FR-3: Python Environment

**FR-3.1** The setup script shall verify that Python 3.10+ is available on the system.

**FR-3.2** The setup script shall install `python3-venv` and `python3-pip` system packages if not already present.

**FR-3.3** The setup script shall create a Python virtual environment in the project directory (at a configurable path, default `.venv`) if one does not already exist.

**FR-3.4** The setup script shall install `pyserial` into the virtual environment for serial communication with Arduino boards.

### FR-4: Board Detection and Serial Communication

**FR-4.1** The detect script shall enumerate all connected Arduino boards by scanning USB devices for vendor ID `2341`.

**FR-4.2** The detect script shall report for each detected board: device path (e.g., `/dev/ttyACM0`), USB product ID, board name, and FQBN.

**FR-4.3** The detect script shall output results in both human-readable and machine-parseable (JSON) formats, selectable via a flag.

**FR-4.4** If no Arduino boards are detected, then the detect script shall exit with a non-zero exit code and print a diagnostic message.

**FR-4.5** The detect script shall verify serial port accessibility (read/write permission) for each detected board.

### FR-5: Network Discovery

**FR-5.1** The setup script shall install `avahi-utils` and `nmap` if not already present, for network discovery.

**FR-5.2** The discover script shall attempt board discovery using a fallback chain: (1) mDNS/Avahi browse, (2) ARP table scan for Arduino OUI MAC prefixes, (3) nmap ping sweep of the local subnet filtered by Arduino MAC OUI.

**FR-5.3** The discover script shall support configuring known MAC addresses for environments using MAC-based WiFi registration (e.g., unfabric networks), via a configuration file or `--mac` flag.

**FR-5.4** The discover script shall report for each discovered board: hostname (if available), IP address, MAC address, and discovery method used.

**FR-5.5** The discover script shall output results in JSON format (canonical), with human-readable output derived from the JSON.

**FR-5.6** If no boards are discovered on the network, then the discover script shall exit with a non-zero exit code and print a diagnostic message suggesting WiFi configuration checks.

### FR-6: Build and Upload Verification

**FR-6.1** The verify script shall compile a minimal test sketch (Blink) for each installed board core to confirm the toolchain is functional.

**FR-6.2** Where a board is connected via USB, the verify script shall upload the test sketch and confirm successful upload.

**FR-6.3** The verify script shall accept a board FQBN and port as arguments to target a specific board.

**FR-6.4** When compilation fails, the verify script shall output the full compiler error and exit with a non-zero code.

### FR-7: Health Check

**FR-7.1** The health check script shall run all verification steps in sequence: system access, tool installation, board detection, serial access, and build verification.

**FR-7.2** The health check script shall produce a summary report with pass/fail status for each check.

**FR-7.3** The health check script shall output results in both human-readable and JSON formats, selectable via a flag.

**FR-7.4** The health check script shall exit with code 0 if all checks pass, and non-zero if any check fails.

---

## Non-Functional Requirements

### NFR-1: Idempotency

**NFR-1.1** The setup script shall be safe to run multiple times without side effects — repeated runs shall not duplicate group memberships, udev rules, core installations, or virtual environments.

### NFR-2: Non-Interactive Execution

**NFR-2.1** All scripts shall complete without interactive prompts when invoked by an AI agent or in a CI environment.

**NFR-2.2** All scripts shall accept a `--non-interactive` or equivalent flag (or detect non-TTY stdin) to suppress any confirmation prompts.

### NFR-3: Exit Codes

**NFR-3.1** All scripts shall use the following exit code convention:
- `0` — success
- `1` — general failure
- `2` — missing prerequisites (e.g., no sudo, no internet)
- `3` — hardware not found (e.g., no board detected)
- `4` — partial success (e.g., some boards configured, others failed)

### NFR-4: Privilege Separation

**NFR-4.1** Scripts shall clearly separate operations requiring `sudo` from unprivileged operations.

**NFR-4.2** Scripts shall request `sudo` only for specific commands (udev rules, group membership, apt install), never run entirely as root.

**NFR-4.3** While running with `--non-interactive`, if sudo is required and not available, the script shall exit with code 2 and report which operations need elevated privileges.

### NFR-5: Logging and Output

**NFR-5.1** All scripts shall use a shared output library (sourced bash file) for consistent formatting across all scripts.

**NFR-5.2** The canonical output format shall be JSON. Human-readable output shall be derived from the JSON output.

**NFR-5.3** All scripts shall default to human-readable output, with a `--json` flag to emit raw JSON instead.

**NFR-5.4** Human-readable output shall prefix lines with a category tag: `[INFO]`, `[WARN]`, `[ERROR]`, `[OK]`, `[SKIP]`.

**NFR-5.5** All scripts shall support a `--quiet` flag that suppresses informational output, emitting only errors and the final status.

### NFR-6: Documentation

**NFR-6.1** The README shall document: supported boards, prerequisites, script usage (with examples), exit codes, troubleshooting, and how to invoke from an AI agent context.

**NFR-6.2** The README shall include a "Quick Start" section that gets a user from zero to a working environment in under 5 commands.

**NFR-6.3** Each script shall support a `--help` flag that prints usage information.

### NFR-7: Portability

**NFR-7.1** Scripts shall target bash (4.0+) and use only POSIX-compatible utilities plus explicitly declared dependencies.

**NFR-7.2** Scripts shall not hardcode absolute paths to user home directories or project locations.

---

## Traceability

| Requirement | Context Goal | Context Constraint |
|---|---|---|
| FR-1.1–1.5 | G1 | C3 |
| FR-2.1–2.6 | G2 | C4, C5 |
| FR-3.1–3.4 | G3 | — |
| FR-4.1–4.5 | G4 | C2 |
| FR-5.1–5.6 | G5 | C6 |
| FR-6.1–6.4 | G6 | C4, C5 |
| FR-7.1–7.4 | G6, G8 | C1, C2 |
| NFR-1.1 | G8 | C1 |
| NFR-2.1–2.2 | G8 | C2 |
| NFR-3.1 | G8 | — |
| NFR-4.1–4.3 | G1 | C3 |
| NFR-5.1–5.5 | G7, G8 | C2 |
| NFR-6.1–6.3 | G7 | — |
| NFR-7.1–7.2 | G8 | — |
