#!/usr/bin/env bash
# PreToolUse hook for shell tool
# Blocks dangerous commands that could cause irreversible damage.
# Exit 0 = allow, Exit 2 = block with JSON error
#
# Environment:
#   TOOL_INPUT — JSON string with "command" field

set -euo pipefail

# Extract command from TOOL_INPUT
if [ -z "${TOOL_INPUT:-}" ]; then
  exit 0
fi

COMMAND=$(printf '%s' "$TOOL_INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('command',''))" 2>/dev/null || echo "")

if [ -z "$COMMAND" ]; then
  exit 0
fi

# Check user-provided allowlist
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALLOWLIST_FILE="$SCRIPT_DIR/dangerous-commands-allowlist.txt"

if [ -f "$ALLOWLIST_FILE" ]; then
  while IFS= read -r pattern || [ -n "$pattern" ]; do
    # Skip comments and empty lines
    [[ "$pattern" =~ ^#.*$ || -z "$pattern" ]] && continue
    if [[ "$COMMAND" == *"$pattern"* ]]; then
      exit 0
    fi
  done < "$ALLOWLIST_FILE"
fi

# Check against dangerous patterns
block_with_reason() {
  printf '{"error":"Blocked dangerous command: %s"}' "$1" >&2
  exit 2
}

# rm -rf with dangerous targets
if [[ "$COMMAND" =~ rm[[:space:]]+-[a-zA-Z]*r[a-zA-Z]*f[[:space:]]+/ ]] || \
   [[ "$COMMAND" =~ rm[[:space:]]+-[a-zA-Z]*f[a-zA-Z]*r[[:space:]]+/ ]] || \
   [[ "$COMMAND" =~ rm[[:space:]]+-rf[[:space:]]+[~\*] ]] || \
   [[ "$COMMAND" =~ rm[[:space:]]+-rf[[:space:]]+/[[:space:]]*$ ]]; then
  block_with_reason "rm -rf with dangerous target"
fi

# chmod 777
if [[ "$COMMAND" =~ chmod[[:space:]]+777 ]]; then
  block_with_reason "chmod 777"
fi

# git push --force to main/master
if [[ "$COMMAND" =~ git[[:space:]]+push[[:space:]]+--force[[:space:]]+(.*[[:space:]])?main ]] || \
   [[ "$COMMAND" =~ git[[:space:]]+push[[:space:]]+--force[[:space:]]+(.*[[:space:]])?master ]] || \
   [[ "$COMMAND" =~ git[[:space:]]+push[[:space:]]+-f[[:space:]]+(.*[[:space:]])?main ]] || \
   [[ "$COMMAND" =~ git[[:space:]]+push[[:space:]]+-f[[:space:]]+(.*[[:space:]])?master ]]; then
  block_with_reason "git push --force to main/master"
fi

# SQL destructive operations
if [[ "${COMMAND^^}" =~ DROP[[:space:]]+TABLE ]]; then
  block_with_reason "DROP TABLE"
fi

if [[ "${COMMAND^^}" =~ DELETE[[:space:]]+FROM ]] && ! [[ "${COMMAND^^}" =~ WHERE ]]; then
  block_with_reason "DELETE FROM without WHERE clause"
fi

# Filesystem destruction
if [[ "$COMMAND" =~ mkfs[[:space:]] ]]; then
  block_with_reason "mkfs (filesystem format)"
fi

# Fork bomb
if [[ "$COMMAND" =~ :\(\)\{[[:space:]]*:\|:& ]]; then
  block_with_reason "fork bomb"
fi

# dd with if= (disk overwrite risk)
if [[ "$COMMAND" =~ dd[[:space:]]+if= ]]; then
  block_with_reason "dd with if= (potential disk overwrite)"
fi

# Command is allowed
exit 0
