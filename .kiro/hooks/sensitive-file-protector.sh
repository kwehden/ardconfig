#!/usr/bin/env bash
# PreToolUse hook for read, write, and shell tools
# Blocks access to sensitive files (credentials, keys, secrets).
# Exit 0 = allow, Exit 2 = block with JSON error
#
# Environment:
#   TOOL_INPUT — JSON string with "path" or "command" field

set -euo pipefail

if [ -z "${TOOL_INPUT:-}" ]; then
  exit 0
fi

# Extract paths to check based on tool type
PATHS_TO_CHECK=()

# Try to extract "path" field (read/write tools)
FILE_PATH=$(printf '%s' "$TOOL_INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('path',''))" 2>/dev/null || echo "")
if [ -n "$FILE_PATH" ]; then
  PATHS_TO_CHECK+=("$FILE_PATH")
fi

# Try to extract "file_path" field (alternate format)
FILE_PATH2=$(printf '%s' "$TOOL_INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('file_path',''))" 2>/dev/null || echo "")
if [ -n "$FILE_PATH2" ]; then
  PATHS_TO_CHECK+=("$FILE_PATH2")
fi

# Try to extract paths from "command" field (shell tool)
COMMAND=$(printf '%s' "$TOOL_INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('command',''))" 2>/dev/null || echo "")
if [ -n "$COMMAND" ]; then
  # Extract potential file paths from command arguments
  for word in $COMMAND; do
    if [[ "$word" == /* ]] || [[ "$word" == ~/* ]] || [[ "$word" == .* ]]; then
      PATHS_TO_CHECK+=("$word")
    fi
  done
fi

if [ ${#PATHS_TO_CHECK[@]} -eq 0 ]; then
  exit 0
fi

block_with_reason() {
  printf '{"error":"Blocked access to sensitive file: %s"}' "$1" >&2
  exit 2
}

# Built-in sensitive patterns
is_sensitive() {
  local path="$1"
  local basename
  basename=$(basename "$path" 2>/dev/null || echo "$path")
  local resolved
  resolved=$(realpath "$path" 2>/dev/null || echo "$path")

  # .env files
  [[ "$basename" == ".env" ]] && return 0
  [[ "$basename" == .env.* ]] && return 0

  # Private keys and certificates
  [[ "$basename" == *.pem ]] && return 0
  [[ "$basename" == *.key ]] && return 0
  [[ "$basename" == *.p12 ]] && return 0
  [[ "$basename" == *.pfx ]] && return 0

  # SSH keys
  [[ "$basename" == id_rsa* ]] && return 0
  [[ "$basename" == id_ed25519* ]] && return 0
  [[ "$basename" == id_ecdsa* ]] && return 0

  # Auth config files
  [[ "$basename" == ".netrc" ]] && return 0
  [[ "$basename" == ".npmrc" ]] && return 0
  [[ "$basename" == ".pypirc" ]] && return 0

  # Credential and secret files (by filename substring)
  [[ "$basename" == *credentials* ]] && return 0
  [[ "$basename" == *secrets* ]] && return 0

  # Sensitive directories
  [[ "$resolved" == "$HOME/.ssh/"* ]] && return 0
  [[ "$resolved" == "$HOME/.aws/"* ]] && return 0
  [[ "$resolved" == "$HOME/.gnupg/"* ]] && return 0
  [[ "$path" == *"/.ssh/"* ]] && return 0
  [[ "$path" == *"/.aws/"* ]] && return 0
  [[ "$path" == *"/.gnupg/"* ]] && return 0

  return 1
}

# Check user-provided additional patterns
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATTERNS_FILE="$SCRIPT_DIR/sensitive-patterns.txt"

matches_user_pattern() {
  local path="$1"
  if [ ! -f "$PATTERNS_FILE" ]; then
    return 1
  fi
  while IFS= read -r pattern || [ -n "$pattern" ]; do
    [[ "$pattern" =~ ^#.*$ || -z "$pattern" ]] && continue
    # Use bash glob matching
    if [[ "$path" == "$pattern" ]] || [[ "$(basename "$path")" == "$pattern" ]]; then
      return 0
    fi
  done < "$PATTERNS_FILE"
  return 1
}

# Check all extracted paths
for path in "${PATHS_TO_CHECK[@]}"; do
  if is_sensitive "$path"; then
    block_with_reason "$path"
  fi
  if matches_user_pattern "$path"; then
    block_with_reason "$path"
  fi
done

exit 0
