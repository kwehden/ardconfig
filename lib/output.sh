#!/usr/bin/env bash
# ardconfig shared output library
# Canonical output is JSON; human-readable is derived from it.
# Source this file: source "$(dirname "$0")/../lib/output.sh"

set -euo pipefail

_OUTPUT_FORMAT="human"  # human | json
_OUTPUT_QUIET=false
_OUTPUT_STEPS="[]"

output_init() {
  local fmt="${1:-human}"
  local quiet="${2:-false}"
  _OUTPUT_FORMAT="$fmt"
  _OUTPUT_QUIET="$quiet"
  _OUTPUT_STEPS="[]"
}

# Record a step result
# Usage: output_step STATUS NAME MESSAGE [DETAIL]
# STATUS: ok, skip, warn, error, info
output_step() {
  local status="$1" name="$2" message="$3" detail="${4:-}"
  local step
  step=$(jq -n \
    --arg s "$status" \
    --arg n "$name" \
    --arg m "$message" \
    --arg d "$detail" \
    '{status: $s, name: $n, message: $m} + (if $d != "" then {detail: $d} else {} end)')
  _OUTPUT_STEPS=$(echo "$_OUTPUT_STEPS" | jq --argjson step "$step" '. + [$step]')

  # Stream human-readable output as steps happen
  if [[ "$_OUTPUT_FORMAT" == "human" && "$_OUTPUT_QUIET" != "true" ]]; then
    _output_human_step "$status" "$message"
  elif [[ "$_OUTPUT_FORMAT" == "human" && "$_OUTPUT_QUIET" == "true" && "$status" == "error" ]]; then
    _output_human_step "$status" "$message"
  fi
}

# Emit final result
# Usage: output_result EXIT_CODE [EXTRA_JSON_FIELDS]
output_result() {
  local exit_code="$1"
  local extra="${2:-{\}}"
  local overall_status
  case "$exit_code" in
    0) overall_status="success" ;;
    2) overall_status="missing_prerequisites" ;;
    3) overall_status="hardware_not_found" ;;
    4) overall_status="partial" ;;
    *) overall_status="failure" ;;
  esac

  local result
  result=$(jq -n \
    --arg s "$overall_status" \
    --argjson c "$exit_code" \
    --argjson steps "$_OUTPUT_STEPS" \
    --argjson extra "$extra" \
    '{status: $s, exit_code: $c, steps: $steps} + $extra')

  if [[ "$_OUTPUT_FORMAT" == "json" ]]; then
    echo "$result"
  else
    # Final summary line for human output
    local ok err skip warn
    ok=$(echo "$_OUTPUT_STEPS" | jq '[.[] | select(.status == "ok")] | length')
    err=$(echo "$_OUTPUT_STEPS" | jq '[.[] | select(.status == "error")] | length')
    skip=$(echo "$_OUTPUT_STEPS" | jq '[.[] | select(.status == "skip")] | length')
    warn=$(echo "$_OUTPUT_STEPS" | jq '[.[] | select(.status == "warn")] | length')
    if [[ "$_OUTPUT_QUIET" != "true" ]]; then
      echo ""
      echo "--- Summary: ${ok} ok, ${skip} skipped, ${warn} warnings, ${err} errors ---"
    fi
  fi
}

# Degraded mode: output without jq (used by detect when jq is missing)
output_step_plain() {
  local status="$1" message="$2"
  if [[ "$_OUTPUT_FORMAT" == "human" ]]; then
    _output_human_step "$status" "$message"
  fi
}

_output_human_step() {
  local status="$1" message="$2"
  local tag
  case "$status" in
    ok)    tag="[OK]   " ;;
    skip)  tag="[SKIP] " ;;
    warn)  tag="[WARN] " ;;
    error) tag="[ERROR]" ;;
    info)  tag="[INFO] " ;;
    *)     tag="[????] " ;;
  esac
  echo "${tag} ${message}"
}
