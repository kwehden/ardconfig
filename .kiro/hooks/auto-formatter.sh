#!/usr/bin/env bash
# PostToolUse hook for write tool
# Runs the appropriate code formatter after a file is written.
# Always exits 0 (informational, never blocks).
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
  js|jsx|ts|tsx|json|css|html|md|yaml|yml)
    if [ -x "./node_modules/.bin/prettier" ]; then
      ./node_modules/.bin/prettier --write "$FILE_PATH" &>/dev/null || true
    elif command -v prettier &>/dev/null; then
      prettier --write "$FILE_PATH" &>/dev/null || true
    fi
    ;;
  py)
    if command -v python3 &>/dev/null && python3 -m black --version &>/dev/null 2>&1; then
      python3 -m black --quiet "$FILE_PATH" &>/dev/null || true
    fi
    ;;
  go)
    if command -v gofmt &>/dev/null; then
      gofmt -w "$FILE_PATH" &>/dev/null || true
    fi
    ;;
esac

exit 0
