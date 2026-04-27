# Context — ardconfig

## 1. Project Overview

ardconfig is a reusable bootstrap/quickstart package for configuring Ubuntu Linux systems to develop with Arduino hardware. It provides a set of idempotent, scriptable setup scripts and a human+agent-friendly README that can be dropped into any Arduino project to establish a working development environment.

The primary target boards are the Arduino Uno Q — a hybrid board combining a Qualcomm Dragonwing QRB2210 (running Debian Linux) with an STM32U585 real-time microcontroller — and the Arduino Uno R4 WiFi, a Renesas RA4M1-based board with built-in WiFi/Bluetooth via an ESP32-S3 coprocessor. Secondary targets include the Arduino Giga Display Shield and time-of-flight sensors (e.g., VL53L series).

## 2. Goals

- **G1:** Configure system-level access for Arduino hardware on Ubuntu (udev rules, group membership, USB permissions).
- **G2:** Install and configure arduino-cli with board support packages for STM32/Zephyr (Uno Q), Renesas/Arduino UNO R4 (Uno R4 WiFi), and Mbed (Giga).
- **G3:** Set up Python development environment for the Uno Q's Linux side.
- **G4:** Provide serial communication tools — board detection, port verification, serial monitor.
- **G5:** Enable network discovery of the Uno Q for wireless programming workflows.
- **G6:** Provide testing scaffolding — compile, upload, and verify a basic sketch; run health checks.
- **G7:** Produce a README that serves both human developers and AI agents as a configuration reference.
- **G8:** All scripts must be idempotent, callable by AI agents, and return meaningful exit codes.

## 3. Non-Goals

- **NG1:** Firmware management and fleet management (deferred to per-project scope).
- **NG2:** Installing Arduino App Lab (proprietary IDE; user installs separately).
- **NG3:** Project-specific application code, sketches, or Python apps.
- **NG4:** Supporting operating systems other than Ubuntu (may work on Debian derivatives, but not a goal).
- **NG5:** Managing the Uno Q's on-board Debian Linux environment (that's the board's own OS).

## 4. Target Users

- **Primary:** Developers (human or AI agent) starting a new Arduino project on Ubuntu who need a repeatable environment setup.
- **Secondary:** AI coding agents that need to invoke setup scripts as part of a project bootstrap workflow.

## 5. Hardware Context

### Arduino Uno Q (primary target)
- **USB ID:** 2341:0078
- **Architecture:** Dual-brain hybrid
  - **Linux side:** Qualcomm Dragonwing QRB2210 — runs Debian, 2 GB LPDDR4, 16 GB eMMC, dual-band WiFi 5, Bluetooth 5.1
  - **MCU side:** STM32U585 — Arm Cortex-M33, 160 MHz, 2 MB flash, ~786 KB SRAM
- **arduino-cli architecture ID:** `zephyr`
- **Serial port:** Typically `/dev/ttyACM0`
- **Connectivity:** USB-C, WiFi (network programming via App Lab), Bluetooth
- **Dev workflow:** Arduino sketches (C/C++) on STM32 via Zephyr; Python scripts on Linux side; Docker-based "Bricks" for AI/vision/audio

### Arduino Uno R4 WiFi (primary target)
- **USB ID:** 2341:1002 (typical)
- **MCU:** Renesas RA4M1 — Arm Cortex-M4, 48 MHz, 256 KB flash, 32 KB SRAM
- **Wireless coprocessor:** ESP32-S3-MINI-1 — WiFi + Bluetooth LE
- **arduino-cli core:** `arduino:renesas_uno`
- **FQBN:** `arduino:renesas_uno:unor4wifi`
- **Serial port:** Typically `/dev/ttyACM*`
- **Features:** On-board 12x8 LED matrix, Qwiic connector, CAN bus, DAC, OP AMP
- **Connectivity:** USB-C, WiFi, Bluetooth LE
- **Dev workflow:** Standard Arduino sketches (C/C++); well-established library ecosystem

### Arduino Giga Display Shield (secondary target)
- **Board:** Arduino Giga R1 WiFi (Mbed OS based)
- **arduino-cli architecture:** Mbed core
- **Display:** 800x480 capacitive touch display shield

### Time-of-Flight Sensors (secondary target)
- VL53L-series or similar I2C ToF sensors
- Connected via Qwiic/I2C to the Uno Q or Giga

## 6. Software Context (Current System State)

- **OS:** Ubuntu 24.04.4 LTS (Noble Numbat)
- **Board detected:** Yes — Uno Q on `/dev/ttyACM0`, USB bus 002 device 002
- **Serial port permissions:** `/dev/ttyACM0` owned by `root:dialout` (mode 660)
- **User group membership:** User is NOT in the `dialout` group — cannot access serial port without sudo
- **arduino-cli:** Not installed
- **arduino-flasher-cli:** Not installed
- **udev rules:** No Arduino-specific rules in `/etc/udev/rules.d/`
- **Python:** System Python available (Ubuntu 24.04 ships Python 3.12)
- **Git:** No repository initialized in the project directory
- **Docker:** Status unknown (needed for Bricks on the Uno Q's Linux side, not on the host)

## 7. Key Constraints

- **C1:** Scripts must be idempotent — safe to run multiple times without side effects.
- **C2:** Scripts must work without interactive prompts when called by an AI agent (non-interactive mode).
- **C3:** Scripts requiring elevated privileges (sudo) must clearly separate privileged from unprivileged operations.
- **C4:** The Uno Q ecosystem is new (launched ~2025) — tooling and board support packages may be immature or change rapidly.
- **C5:** The Zephyr architecture for arduino-cli on the Uno Q may have limited library compatibility compared to AVR/SAMD/Mbed.
- **C6:** Network discovery depends on the Uno Q being connected to WiFi and on the same local network as the host.

## 8. Assumptions

- **A1:** The host system is Ubuntu 22.04 or later (targeting 24.04).
- **A2:** The user has sudo access for system configuration (group membership, udev rules).
- **A3:** The Arduino Uno Q is connected via USB-C and appears as `/dev/ttyACM*`.
- **A4:** Internet access is available for downloading arduino-cli and board support packages.
- **A5:** Arduino App Lab is installed separately by the user when needed for App Lab-specific workflows.
- **A6:** Python 3.10+ is available on the host system.

## 9. Dependencies

| Dependency | Purpose | Install method |
|---|---|---|
| arduino-cli | Compile, upload, board management | Official install script or apt |
| STM32/Zephyr board core | Uno Q board support in arduino-cli | `arduino-cli core install` |
| Renesas/UNO R4 board core | Uno R4 WiFi board support | `arduino-cli core install` |
| Mbed board core | Giga R1 WiFi board support | `arduino-cli core install` |
| Python 3.10+ | Development on Uno Q Linux side | System package (python3) |
| pip / venv | Python package management | System package (python3-pip, python3-venv) |
| udev | Device permission rules | Pre-installed on Ubuntu |
| avahi / mDNS | Network discovery of Uno Q | System package (avahi-utils) |

## 10. Risks

- **R1:** The Uno Q's arduino-cli board support (Zephyr core) is new and may have breaking changes in updates.
- **R2:** Network discovery may be unreliable if the Uno Q's WiFi configuration is incomplete or the network blocks mDNS.
- **R3:** USB-C PD power delivery issues have been reported with some USB ports/cables — serial detection may fail intermittently.
- **R4:** Library compatibility for the Zephyr architecture is limited — not all Arduino libraries work on the Uno Q's STM32 side.
- **R5:** The supported boards span three different cores (Zephyr, Renesas, Mbed), requiring three separate board support installations and awareness of library compatibility differences across them.

## 11. Open Questions

- **OQ1:** ~~What is the exact arduino-cli board FQBN for the Uno Q?~~ **RESOLVED:** `arduino:zephyr:unoq`. Requires additional board manager URL: `https://downloads.arduino.cc/packages/package_zephyr_index.json`
- **OQ2:** ~~Does the Uno Q advertise itself via mDNS/Avahi?~~ **RESOLVED:** Unclear — App Lab may use proprietary discovery. Design will use a fallback approach: mDNS first, then ARP/nmap scan for Arduino OUI MAC prefix. Lab uses unfabric network with MAC registration for WiFi access, so MAC-based identification is viable.
- **OQ3:** ~~What Python packages are needed for STM32 communication?~~ **RESOLVED:** `pyserial` for serial comms. The Uno Q's Linux↔STM32 RPC bridge is internal to the board's Debian OS and not managed from the host.
- **OQ4:** ~~Which VL53L time-of-flight sensor?~~ **RESOLVED:** CQRobot VL53L1X. Arduino libraries available: Pololu VL53L1X, Adafruit VL53L1X, SparkFun VL53L1X. Zephyr has native HAL support via `hal_st` (VL53L1X driver, BSD-3-Clause). Library compatibility with `arduino:zephyr` core needs runtime validation.
- **OQ5:** ~~Should scripts init git?~~ Deferred — not part of core quickstart scope.

## 12. Resolved Research

### Uno Q FQBN and Core Installation
- FQBN: `arduino:zephyr:unoq` (with option `link_mode=static` available)
- Core: `arduino:zephyr` (currently BETA, v0.54.1 as of March 2026)
- Install: `arduino-cli core install arduino:zephyr --additional-urls https://downloads.arduino.cc/packages/package_zephyr_index.json`
- The Zephyr core requires a bootloader burn on first use (double-click RESET, then `Burn Bootloader`)

### Giga R1 WiFi FQBN and Core
- FQBN: `arduino:mbed_giga:giga`
- Core: `arduino:mbed_giga`
- Install: `arduino-cli core install arduino:mbed_giga`
- Dual-core STM32H747XI (Cortex-M7 + Cortex-M4)

### Uno Q USB Identity (from connected device)
- Vendor: `Arduino` (0x2341)
- Product: `Uno Q - uno-q` (0x0078)
- Serial: `1649515121`
- USB driver: `cdc_acm`
- Symlinks: `/dev/serial/by-id/usb-Arduino_Uno_Q_-_uno-q_1649515121-if01`
- udev properties: `ID_VENDOR_ID=2341`, `ID_MODEL_ID=0078`, `ID_USB_DRIVER=cdc_acm`

### dialout Group Without Logout
- `usermod -aG dialout $USER` requires logout/login to take effect
- `newgrp dialout` activates the group in a subshell (awkward for scripts/agents)
- Best approach for scripts: add udev rule granting `MODE="0666"` or `GROUP="plugdev"` for Arduino devices as an immediate workaround, plus add user to dialout for long-term. Health check should detect and warn if group membership isn't active yet.

### VL53L1X Library Support
- Arduino libraries: Pololu (`VL53L1X`), Adafruit (`Adafruit_VL53L1X`), SparkFun (`SparkFun_VL53L1X`)
- Zephyr native: `hal_st` includes VL53L1X driver (v2.4.5, BSD-3-Clause), uses standard Zephyr I2C
- Architecture compatibility with `arduino:zephyr` core: needs validation (libraries declare `architectures=*` or specific lists; `zephyr` may not be listed)
