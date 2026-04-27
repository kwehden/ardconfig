# Tasks — ardconfig

Tasks are ordered by dependency. Each task produces a testable artifact.

---

## TASK-001: Project scaffolding and shared libraries

**Description:** Create the directory structure, shared output library (`lib/output.sh`), common library (`lib/common.sh`), and board profiles library (`lib/board-profiles.sh`).

**Requirements:** NFR-3.1, NFR-5.1–5.5, NFR-7.1–7.2

**Inputs:** spec/design.md §1 (Architecture Overview), §3.1–3.3

**Outputs:**
- `bin/` (empty, placeholder)
- `lib/output.sh`
- `lib/common.sh`
- `lib/board-profiles.sh`
- `profiles/` (empty, placeholder)
- `conf/` (empty, placeholder)
- `templates/` (empty, placeholder)
- `udev/` (empty, placeholder)
- `.gitignore` (exclude `.venv/`, build artifacts, `conf/known-macs.conf`)

**Write lease:** `lib/**`, `bin/.gitkeep`, `profiles/.gitkeep`, `conf/.gitkeep`, `templates/.gitkeep`, `udev/.gitkeep`, `.gitignore`

**Change budget:** max_files: 7, max_new_symbols: 20, interface_policy: new

**Verification:**
- `bash -n lib/output.sh` — no syntax errors
- `bash -n lib/common.sh` — no syntax errors
- `bash -n lib/board-profiles.sh` — no syntax errors
- Source all three libraries in a test script and call `output_init`, `parse_args`, `profiles_load` without error

**Risk:** Low

**Dependencies:** None

---

## TASK-002: Board profiles

**Description:** Create the three board profile JSON files and the blink template.

**Requirements:** FR-2.3, FR-2.4, FR-4.2, FR-6.1

**Inputs:** spec/design.md §2 (Board Profile Schema), §7 (Blink Template), spec/context.md §12 (Resolved Research)

**Outputs:**
- `profiles/uno-q.json`
- `profiles/r4wifi.json`
- `profiles/giga.json`
- `templates/blink.ino`

**Write lease:** `profiles/**`, `templates/**`

**Change budget:** max_files: 4, max_new_symbols: 0, interface_policy: new

**Verification:**
- Each JSON file is valid: `jq . profiles/*.json`
- Each JSON file contains required fields: `id`, `fqbn`, `core`, `usb_vendor_id`, `usb_product_id`
- `board-profiles.sh` can load all profiles and resolve fields
- `blink.ino` compiles conceptually (valid C++ syntax)

**Risk:** Low

**Dependencies:** TASK-001

---

## TASK-003: Configuration files and udev rules

**Description:** Create `conf/ardconfig.conf`, `conf/known-macs.conf`, and `udev/99-arduino.rules`.

**Requirements:** FR-1.2, FR-5.3, NFR-1.1

**Inputs:** spec/design.md §4 (udev Rules), §5 (Configuration File), §6 (Known MACs)

**Outputs:**
- `conf/ardconfig.conf`
- `conf/known-macs.conf`
- `udev/99-arduino.rules`

**Write lease:** `conf/**`, `udev/**`

**Change budget:** max_files: 3, max_new_symbols: 0, interface_policy: new

**Verification:**
- `udevadm verify udev/99-arduino.rules` or manual syntax check
- `conf/ardconfig.conf` is valid bash (sourceable without error)
- `conf/known-macs.conf` has correct format with comments

**Risk:** Low

**Dependencies:** None (parallel with TASK-001/002)

---

## TASK-004: `ardconfig-setup`

**Description:** Implement the main setup script covering system access, tool installation, Python environment, and network discovery dependencies.

**Requirements:** FR-1.1–1.5, FR-2.1–2.6, FR-3.1–3.4, FR-5.1, NFR-1.1, NFR-2.1–2.2, NFR-4.1–4.3

**Inputs:** spec/design.md §3.4

**Outputs:**
- `bin/ardconfig-setup`

**Write lease:** `bin/ardconfig-setup`

**Change budget:** max_files: 1, max_new_symbols: 12, interface_policy: new

**Verification:**
- `bash -n bin/ardconfig-setup` — no syntax errors
- `bin/ardconfig-setup --help` prints usage
- `bin/ardconfig-setup --json --non-interactive` produces valid JSON output
- Idempotency: run twice, second run reports all steps as `[SKIP]` or `[OK]`
- On the live system: after running, `ls -la /dev/ttyACM0` shows accessible permissions
- `arduino-cli version` works after setup
- `arduino-cli core list` shows installed cores matching `--boards` selection
- `.venv/bin/python -c "import serial"` succeeds

**Risk:** Medium — requires sudo, installs system packages, modifies udev rules

**Dependencies:** TASK-001, TASK-002, TASK-003

---

## TASK-005: `ardconfig-detect`

**Description:** Implement USB board detection with degraded mode (no jq) support.

**Requirements:** FR-4.1–4.5

**Inputs:** spec/design.md §3.5

**Outputs:**
- `bin/ardconfig-detect`

**Write lease:** `bin/ardconfig-detect`

**Change budget:** max_files: 1, max_new_symbols: 6, interface_policy: new

**Verification:**
- `bash -n bin/ardconfig-detect` — no syntax errors
- `bin/ardconfig-detect --help` prints usage
- With Uno Q connected: outputs device path, product ID, board name, FQBN
- `bin/ardconfig-detect --json` produces valid JSON with board array
- With no boards connected: exits with code 3
- Degraded mode: temporarily hide jq (`PATH` manipulation), verify detect still works with warning

**Risk:** Low

**Dependencies:** TASK-001, TASK-002

---

## TASK-006: `ardconfig-discover`

**Description:** Implement network discovery with the mDNS → known MACs → ARP → nmap fallback chain.

**Requirements:** FR-5.2–5.6

**Inputs:** spec/design.md §3.6

**Outputs:**
- `bin/ardconfig-discover`

**Write lease:** `bin/ardconfig-discover`

**Change budget:** max_files: 1, max_new_symbols: 8, interface_policy: new

**Verification:**
- `bash -n bin/ardconfig-discover` — no syntax errors
- `bin/ardconfig-discover --help` prints usage
- `bin/ardconfig-discover --json` produces valid JSON (even if empty results)
- With a known MAC in `conf/known-macs.conf` and the board on WiFi: discovers the board
- With no boards on network: exits with code 3 and diagnostic message

**Risk:** Medium — depends on network environment, mDNS availability

**Dependencies:** TASK-001, TASK-002, TASK-003

---

## TASK-007: `ardconfig-verify`

**Description:** Implement build and upload verification using board profiles and the blink template.

**Requirements:** FR-6.1–6.4

**Inputs:** spec/design.md §3.7

**Outputs:**
- `bin/ardconfig-verify`

**Write lease:** `bin/ardconfig-verify`

**Change budget:** max_files: 1, max_new_symbols: 6, interface_policy: new

**Verification:**
- `bash -n bin/ardconfig-verify` — no syntax errors
- `bin/ardconfig-verify --help` prints usage
- Compiles blink for each installed core without errors
- `bin/ardconfig-verify --json` produces valid JSON with per-board compile results
- With `--fqbn arduino:renesas_uno:unor4wifi --port /dev/ttyACM0`: targets specific board
- Compilation failure (bad FQBN): exits with code 1 and shows compiler error

**Risk:** Medium — depends on arduino-cli and cores being installed (TASK-004)

**Dependencies:** TASK-001, TASK-002, TASK-004 (cores must be installed)

---

## TASK-008: `ardconfig-health`

**Description:** Implement the health check orchestrator that runs all checks and produces an aggregated report.

**Requirements:** FR-7.1–7.4

**Inputs:** spec/design.md §3.8

**Outputs:**
- `bin/ardconfig-health`

**Write lease:** `bin/ardconfig-health`

**Change budget:** max_files: 1, max_new_symbols: 8, interface_policy: new

**Verification:**
- `bash -n bin/ardconfig-health` — no syntax errors
- `bin/ardconfig-health --help` prints usage
- On a fully configured system: all checks pass, exit code 0
- `bin/ardconfig-health --json` produces valid JSON with per-check results
- On a fresh system (before setup): reports failures for missing tools, exit code 1 or 4

**Risk:** Low — orchestration only, no system modifications

**Dependencies:** TASK-005, TASK-006, TASK-007 (uses detect/discover/verify logic)

---

## TASK-009: README

**Description:** Write the human+agent-friendly README covering supported boards, prerequisites, quick start, script usage, exit codes, troubleshooting, and agent invocation.

**Requirements:** NFR-6.1–6.2

**Inputs:** All spec files, all scripts (for usage examples)

**Outputs:**
- `README.md`

**Write lease:** `README.md`

**Change budget:** max_files: 1, max_new_symbols: 0, interface_policy: new

**Verification:**
- README renders correctly as markdown
- Quick Start section has ≤5 commands
- All scripts are documented with usage examples
- Exit codes table matches NFR-3.1
- Agent invocation section explains JSON mode and non-interactive flags
- Giga Display Shield clarification is present

**Risk:** Low

**Dependencies:** TASK-004–008 (needs final script interfaces)

---

## Task Dependency Graph

```
TASK-001 (scaffolding) ──┬──→ TASK-004 (setup) ──→ TASK-007 (verify) ──┐
                         │                                               │
TASK-002 (profiles)  ────┤──→ TASK-005 (detect) ──────────────────────┤
                         │                                               ├──→ TASK-008 (health) ──→ TASK-009 (README)
TASK-003 (config/udev) ──┴──→ TASK-006 (discover) ────────────────────┘
```

## Execution Order

| Phase | Tasks | Can parallelize? |
|---|---|---|
| 1 | TASK-001, TASK-002, TASK-003 | Yes — independent |
| 2 | TASK-004, TASK-005, TASK-006 | Partially — 005/006 can parallel, 004 first if testing on live system |
| 3 | TASK-007 | No — needs cores from TASK-004 |
| 4 | TASK-008 | No — needs 005/006/007 |
| 5 | TASK-009 | No — needs all scripts finalized |

## Summary

- **9 tasks** total
- **3 low-risk**, **3 medium-risk**, **3 low-risk** (docs/scaffolding)
- **1 task requires sudo** (TASK-004)
- Estimated implementation: Phase 1–3 are the core work; Phase 4–5 are integration and docs
