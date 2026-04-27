#!/usr/bin/env bash
# ardconfig board profiles library
# Loads and queries board profile JSON files from profiles/
# Source this file: source "$(dirname "$0")/../lib/board-profiles.sh"

set -euo pipefail

_PROFILES_DIR="${ARDCONFIG_PROFILES:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../profiles" && pwd)}"
_PROFILES_LOADED=false
_PROFILES_DATA=""  # Combined JSON array of all profiles

# Check if jq is available
profiles_has_jq() {
  command -v jq &>/dev/null
}

# Load all profile JSON files into a combined array
profiles_load() {
  if ! profiles_has_jq; then
    _PROFILES_LOADED=false
    return 1
  fi

  local combined="[]"
  local f
  for f in "$_PROFILES_DIR"/*.json; do
    [[ -f "$f" ]] || continue
    # Validate required fields
    if ! jq -e '.id and .fqbn and .core and .usb_vendor_id and .usb_product_id' "$f" &>/dev/null; then
      echo "[WARN] Skipping invalid profile: $f" >&2
      continue
    fi
    combined=$(echo "$combined" | jq --slurpfile p "$f" '. + $p')
  done

  _PROFILES_DATA="$combined"
  _PROFILES_LOADED=true
}

# List all loaded board IDs
profiles_list() {
  if [[ "$_PROFILES_LOADED" != "true" ]]; then return 1; fi
  echo "$_PROFILES_DATA" | jq -r '.[].id'
}

# Get a field value for a board
# Usage: profiles_get BOARD_ID FIELD
profiles_get() {
  local board_id="$1" field="$2"
  if [[ "$_PROFILES_LOADED" != "true" ]]; then return 1; fi
  echo "$_PROFILES_DATA" | jq -r --arg id "$board_id" --arg f "$field" \
    '.[] | select(.id == $id) | .[$f] // empty'
}

# Get full profile JSON for a board
profiles_get_json() {
  local board_id="$1"
  if [[ "$_PROFILES_LOADED" != "true" ]]; then return 1; fi
  echo "$_PROFILES_DATA" | jq --arg id "$board_id" '.[] | select(.id == $id)'
}

# Filter profiles by a comma-separated list of board IDs
# If boards_csv is empty, return all profiles
profiles_filter() {
  local boards_csv="$1"
  if [[ "$_PROFILES_LOADED" != "true" ]]; then return 1; fi

  if [[ -z "$boards_csv" ]]; then
    echo "$_PROFILES_DATA"
    return
  fi

  local filter
  filter=$(echo "$boards_csv" | tr ',' '\n' | jq -R . | jq -s .)
  echo "$_PROFILES_DATA" | jq --argjson ids "$filter" '[.[] | select(.id as $id | $ids | index($id))]'
}

# Match a USB product ID to a board profile
# Returns the board ID or empty string
profiles_match_usb() {
  local vendor_id="$1" product_id="$2"
  if [[ "$_PROFILES_LOADED" != "true" ]]; then return 1; fi
  # Try primary vendor/product match first
  local match
  match=$(echo "$_PROFILES_DATA" | jq -r \
    --arg vid "$vendor_id" --arg pid "$product_id" \
    '.[] | select(.usb_vendor_id == $vid and .usb_product_id == $pid) | .id // empty')
  if [[ -n "$match" ]]; then
    echo "$match"
    return
  fi
  # Try alternate chip matches (e.g., CH340, FTDI on Nano clones)
  echo "$_PROFILES_DATA" | jq -r \
    --arg vid "$vendor_id" --arg pid "$product_id" \
    '.[] | select(.usb_alt_chips? // [] | any(.vendor_id == $vid and .product_id == $pid)) | .id // empty'
}

# Get all unique core_url values (non-empty) from selected profiles
profiles_core_urls() {
  local boards_csv="$1"
  local filtered
  filtered=$(profiles_filter "$boards_csv")
  echo "$filtered" | jq -r '[.[].core_url // empty | select(. != "")] | unique | .[]'
}
