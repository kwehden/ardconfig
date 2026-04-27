#!/usr/bin/env bash
# ardconfig common library
# Shared utilities: arg parsing, exit codes, sudo helpers
# Source this file: source "$(dirname "$0")/../lib/common.sh"

set -euo pipefail

# Exit codes (NFR-3.1)
readonly EXIT_OK=0
readonly EXIT_FAIL=1
readonly EXIT_PREREQ=2
readonly EXIT_NO_HW=3
readonly EXIT_PARTIAL=4

# Resolved paths
ARDCONFIG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARDCONFIG_LIB="${ARDCONFIG_ROOT}/lib"
ARDCONFIG_PROFILES="${ARDCONFIG_ROOT}/profiles"
ARDCONFIG_CONF="${ARDCONFIG_ROOT}/conf"
ARDCONFIG_TEMPLATES="${ARDCONFIG_ROOT}/templates"
ARDCONFIG_UDEV="${ARDCONFIG_ROOT}/udev"

# Parsed flags (set by parse_args)
ARG_JSON=false
ARG_QUIET=false
ARG_NON_INTERACTIVE=false
ARG_BOARDS=""
ARG_HELP=false
ARG_FQBN=""
ARG_PORT=""
ARG_MAC=""
ARG_UPLOAD=false
ARG_VERIFY_SERIAL=false
ARG_EXTRA=()

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json)            ARG_JSON=true ;;
      --quiet|-q)        ARG_QUIET=true ;;
      --non-interactive) ARG_NON_INTERACTIVE=true ;;
      --boards)          shift; ARG_BOARDS="$1" ;;
      --boards=*)        ARG_BOARDS="${1#*=}" ;;
      --fqbn)            shift; ARG_FQBN="$1" ;;
      --fqbn=*)          ARG_FQBN="${1#*=}" ;;
      --port)            shift; ARG_PORT="$1" ;;
      --port=*)          ARG_PORT="${1#*=}" ;;
      --mac)             shift; ARG_MAC="$1" ;;
      --mac=*)           ARG_MAC="${1#*=}" ;;
      --upload)          ARG_UPLOAD=true ;;
      --verify-serial)   ARG_VERIFY_SERIAL=true; ARG_UPLOAD=true ;;
      --help|-h)         ARG_HELP=true ;;
      *)                 ARG_EXTRA+=("$1") ;;
    esac
    shift
  done

  # Auto-detect non-interactive if stdin is not a TTY
  if [[ ! -t 0 ]]; then
    ARG_NON_INTERACTIVE=true
  fi
}

# Load config file if present (values are defaults, flags override)
load_config() {
  local conf_file="${ARDCONFIG_CONF}/ardconfig.conf"
  if [[ -f "$conf_file" ]]; then
    # shellcheck source=/dev/null
    source "$conf_file"
  fi
  # Apply config defaults where flags weren't set
  if [[ -z "$ARG_BOARDS" && -n "${ARDCONFIG_BOARDS:-}" ]]; then
    ARG_BOARDS="$ARDCONFIG_BOARDS"
  fi
}

# Check if a command exists
require_command() {
  local cmd="$1" msg="${2:-Required command '$1' not found}"
  if ! command -v "$cmd" &>/dev/null; then
    echo "[ERROR] $msg" >&2
    return 1
  fi
}

# Check sudo availability; in non-interactive mode, exit if unavailable
require_sudo() {
  if [[ "$ARG_NON_INTERACTIVE" == "true" ]]; then
    if ! sudo -n true 2>/dev/null; then
      echo "[ERROR] sudo required but not available in non-interactive mode" >&2
      exit "$EXIT_PREREQ"
    fi
  else
    if ! sudo -v 2>/dev/null; then
      echo "[ERROR] sudo access required. Please run with sudo privileges." >&2
      exit "$EXIT_PREREQ"
    fi
  fi
}

# Run a command with sudo
run_sudo() {
  if [[ "$ARG_NON_INTERACTIVE" == "true" ]]; then
    sudo -n "$@"
  else
    sudo "$@"
  fi
}

# Check if user is in a group
user_in_group() {
  local group="$1"
  id -nG "$USER" 2>/dev/null | tr ' ' '\n' | grep -qx "$group"
}

# Get the output format string for output_init
get_output_format() {
  if [[ "$ARG_JSON" == "true" ]]; then
    echo "json"
  else
    echo "human"
  fi
}
