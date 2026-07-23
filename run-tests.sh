#!/usr/bin/env bash
# run-tests.sh — single entry point for ardconfig's test suite.
# See tests/README.md for framework rationale and layout.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

VENV_PATH="${ARDCONFIG_VENV_PATH:-.venv}"
VENV_PYTHON="${VENV_PATH}/bin/python"

PY_EXIT=0
BATS_EXIT=0

echo "== Python unit tests (pytest: tests/agent) =="
if [[ -x "$VENV_PYTHON" ]]; then
  "$VENV_PYTHON" -m pytest tests/agent -q || PY_EXIT=$?
  if [[ "$PY_EXIT" -eq 5 ]]; then
    # pytest's "no tests collected" exit code — see tests/README.md.
    echo "(no tests collected — treating as pass)"
    PY_EXIT=0
  fi
else
  echo "SKIP: venv python not found at ${VENV_PYTHON} (run ardconfig-setup, then" >&2
  echo "      ${VENV_PYTHON} -m pip install -r requirements-dev.txt)" >&2
fi

echo ""
echo "== Bash tests (bats: tests/bin) =="
if command -v bats &>/dev/null; then
  bats tests/bin || BATS_EXIT=$?
else
  echo "SKIP: bats not found on PATH (install bats-core, e.g. 'brew install bats-core')" >&2
fi

echo ""
if [[ "$PY_EXIT" -ne 0 || "$BATS_EXIT" -ne 0 ]]; then
  echo "FAILURES: pytest_exit=${PY_EXIT} bats_exit=${BATS_EXIT}" >&2
  exit 1
fi

echo "All tests passed."
