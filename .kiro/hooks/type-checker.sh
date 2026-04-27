#!/usr/bin/env bash
# PostToolUse hook for write tool
# Runs the appropriate type checker after a file is written.
# Informational only — always exits 0, never blocks.
#
# Environment:
#   TOOL_INPUT — JSON string with "path" or "file_path" field

set -uo pipefail

if [ -z "${TOOL_INPUT:-}" ]; then
  exit 0
fi

# Extract file path
FILE_PATH=$(printf '%s' "$TOOL_INPUT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('path', data.get('file_path', '')))
" 2>/dev/null || echo "")

if [ -z "$FILE_PATH" ] || [ ! -f "$FILE_PATH" ]; then
  exit 0
fi

# Determine extension
EXT="${FILE_PATH##*.}"

case "$EXT" in
  ts|tsx)
    if [ -x "./node_modules/.bin/tsc" ]; then
      echo "[type-checker] Running tsc project-wide check" >&2
      ./node_modules/.bin/tsc --noEmit 2>&1 | head -20 >&2 || true
    elif command -v tsc &>/dev/null; then
      echo "[type-checker] Running tsc project-wide check" >&2
      tsc --noEmit 2>&1 | head -20 >&2 || true
    fi
    ;;
  py)
    if command -v python3 &>/dev/null && python3 -m mypy --version &>/dev/null 2>&1; then
      echo "[type-checker] Running mypy on $FILE_PATH" >&2
      python3 -m mypy "$FILE_PATH" 2>&1 | head -20 >&2 || true
    fi
    ;;
esac

exit 0
