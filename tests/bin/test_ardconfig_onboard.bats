#!/usr/bin/env bats
# Bash-level prereq-check tests for bin/ardconfig-onboard (TASK-017).
#
# Covers: resolve_llm_provider() (FR-25 bash-level), the provider-
# conditional ensure_ai_deps() branch (FR-22 amended/AC-014), and
# check_ollama_available() against a local mock/stub Ollama endpoint
# (FR-27/AC-012) — no live Ollama server or live network required.
#
# Also covers the orchestrator's regression-critical checks #2 and #4:
# the config-precedence fix surviving load_config()'s sourcing of
# conf/ardconfig.conf, and resolve_llm_provider() failing fast (exit 2)
# before ANY prereq check runs.
#
# These tests run the real bin/ardconfig-onboard as a subprocess (not a
# sourced/stripped copy) so they exercise the actual script exactly as a
# user would invoke it. Determinism/no-live-network is achieved via:
#   - explicit env var isolation (unset ambient ARDCONFIG_*/AWS_* vars)
#   - a local mock Ollama HTTP server (tests/bin/fixtures/mock_ollama_server.py)
#   - a fake venv (tests/bin/fixtures/fake_venv/) whose bin/python shim
#     can simulate "all deps missing" or "delegate to the real venv
#     except block the actual agent invocation" — see that fixture's own
#     header comment for the full rationale.

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  ONBOARD="${REPO_ROOT}/bin/ardconfig-onboard"
  FIXTURES="${BATS_TEST_DIRNAME}/fixtures"
  FAKE_VENV="${FIXTURES}/fake_venv"
  REAL_VENV_PYTHON="${REPO_ROOT}/.venv/bin/python"

  if [[ ! -x "$REAL_VENV_PYTHON" ]]; then
    skip "repo .venv (with strands-agents/boto3/ollama installed) not found at ${REAL_VENV_PYTHON} — required for this suite's mock-server-backed tests"
  fi

  # Isolate from the invoking shell/CI environment: none of these tests
  # should be influenced by ambient ARDCONFIG_*/AWS_* vars.
  unset ARDCONFIG_LLM_PROVIDER ARDCONFIG_BEDROCK_MODEL ARDCONFIG_AWS_REGION \
        ARDCONFIG_OLLAMA_HOST ARDCONFIG_OLLAMA_MODEL ARDCONFIG_VENV_PATH \
        AWS_DEFAULT_REGION AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY \
        AWS_SESSION_TOKEN AWS_PROFILE || true

  MOCK_OLLAMA_PID=""
}

teardown() {
  if [[ -n "${MOCK_OLLAMA_PID:-}" ]]; then
    kill "$MOCK_OLLAMA_PID" 2>/dev/null || true
    wait "$MOCK_OLLAMA_PID" 2>/dev/null || true
  fi
}

# ---------------------------------------------------------------------
# NOTE on venv selection: conf/ardconfig.conf's pre-existing
# `ARDCONFIG_VENV_PATH=".venv"` line (out of this delta's scope — see
# TASK-007's explicit "do not touch ARDCONFIG_VENV_PATH") uses the OLD,
# unconditional-assignment style, so it unconditionally clobbers any
# ARDCONFIG_VENV_PATH *environment variable* passed in — load_config()
# always resets it back to the literal string ".venv" every time.
# Passing ARDCONFIG_VENV_PATH as an env var to bin/ardconfig-onboard is
# therefore a no-op (confirmed empirically while authoring this suite —
# an early version of these tests silently ran against the real repo
# .venv + real local Ollama server instead of the intended fixture,
# hanging on a real agent/LLM call). The correct, and only, way to steer
# venv selection is the mechanism conf/ardconfig.conf's own comment
# documents: ARDCONFIG_VENV_PATH is resolved *relative to the caller's
# working directory*. _run_onboard() below exploits exactly that: it
# runs bin/ardconfig-onboard from a scratch directory containing a
# `.venv` symlink pointing at whichever venv fixture the test needs.
# ---------------------------------------------------------------------

# Runs "$ONBOARD" "$@" from a scratch working directory whose `.venv` is
# a symlink to $1 (a real or fixture venv directory), via bats' `run`.
# Sets $status/$output/$lines in the caller's scope, same as a direct
# `run` call, since this is a plain function call (no subshell).
_run_onboard() {
  local venv_dir="$1"
  shift
  local workdir="${BATS_TEST_TMPDIR}/workdir"
  mkdir -p "$workdir"
  ln -sfn "$venv_dir" "${workdir}/.venv"
  local prev_pwd="$PWD"
  cd "$workdir"
  run env "$@"
  cd "$prev_pwd"
}

_free_port() {
  "$REAL_VENV_PYTHON" -c '
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
'
}

# Starts the mock Ollama server in the background reporting the given
# model names as present. Sets MOCK_OLLAMA_PID and MOCK_OLLAMA_PORT in
# the CALLING shell.
#
# Must be invoked as a plain statement (`_start_mock_ollama foo`), NOT
# via command substitution (`x=$(_start_mock_ollama foo)`) — command
# substitution runs the function in a subshell, so `MOCK_OLLAMA_PID=$!`
# would only ever be visible inside that subshell and be gone by the
# time the function returns, leaving teardown() unable to find/kill the
# background server (confirmed empirically while authoring this suite —
# an earlier version used `port="$(_start_mock_ollama ...)"`, which
# leaked an orphaned mock-server process per test).
_start_mock_ollama() {
  MOCK_OLLAMA_PORT="$(_free_port)"
  "$REAL_VENV_PYTHON" "${FIXTURES}/mock_ollama_server.py" "$MOCK_OLLAMA_PORT" "$@" \
    > "${BATS_TEST_TMPDIR}/mock_ollama.log" 2>&1 &
  MOCK_OLLAMA_PID=$!
  local waited=0
  until grep -q READY "${BATS_TEST_TMPDIR}/mock_ollama.log" 2>/dev/null; do
    sleep 0.1
    waited=$((waited + 1))
    if [[ "$waited" -ge 50 ]]; then
      echo "mock ollama server did not become ready within 5s" >&2
      cat "${BATS_TEST_TMPDIR}/mock_ollama.log" >&2 || true
      return 1
    fi
  done
}

# ---------------------------------------------------------------------
# FR-25(c): invalid ARDCONFIG_LLM_PROVIDER fails fast, before any prereq
# check (regression-critical check #4 from the orchestrator's brief).
# ---------------------------------------------------------------------

@test "FR-25(c): invalid provider exits 2 with only the llm_provider step, before ensure_ai_deps" {
  run env ARDCONFIG_LLM_PROVIDER=nonsense "$ONBOARD" --json --non-interactive \
    --vendor-id 0000 --product-id 0000

  [ "$status" -eq 2 ]
  step_names="$(echo "$output" | jq -r '[.steps[].name] | join(",")')"
  [ "$step_names" = "llm_provider" ]
  step_msg="$(echo "$output" | jq -r '.steps[0].message')"
  [[ "$step_msg" == *"nonsense"* ]]
  step_status="$(echo "$output" | jq -r '.steps[0].status')"
  [ "$step_status" = "error" ]
}

@test "unset ARDCONFIG_LLM_PROVIDER resolves to ollama and does not fail at the llm_provider step" {
  run env "$ONBOARD" --json --non-interactive --help
  [ "$status" -eq 0 ]
}

@test "--help exits 0 even with the new resolve_llm_provider call site (existing ARG_HELP guard still precedes it)" {
  run env ARDCONFIG_LLM_PROVIDER=nonsense "$ONBOARD" --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage: ardconfig-onboard"* ]]
}

@test "usage() heredoc documents the new provider-conditional exit-2 modes" {
  run "$ONBOARD" --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"invalid ARDCONFIG_LLM_PROVIDER"* ]]
  [[ "$output" == *"provider=bedrock"* ]]
  [[ "$output" == *"provider=ollama"* ]]
}

# ---------------------------------------------------------------------
# Config-precedence fix (regression-critical check #2 from the
# orchestrator's brief): an env var passed to ardconfig-onboard must
# survive load_config()'s sourcing of conf/ardconfig.conf, for both a
# pre-existing var (ARDCONFIG_BEDROCK_MODEL) and a new one
# (ARDCONFIG_OLLAMA_MODEL). This exercises the real conf/ardconfig.conf
# file, not a stand-in.
# ---------------------------------------------------------------------

@test "config precedence: ARDCONFIG_BEDROCK_MODEL survives load_config() sourcing conf/ardconfig.conf" {
  run env ARDCONFIG_BEDROCK_MODEL=custom-model bash -c '
    set -euo pipefail
    source "'"${REPO_ROOT}"'/lib/common.sh"
    load_config
    echo "$ARDCONFIG_BEDROCK_MODEL"
  '
  [ "$status" -eq 0 ]
  [ "$output" = "custom-model" ]
}

@test "config precedence: ARDCONFIG_OLLAMA_MODEL survives load_config() sourcing conf/ardconfig.conf" {
  run env ARDCONFIG_OLLAMA_MODEL=custom-ollama-model bash -c '
    set -euo pipefail
    source "'"${REPO_ROOT}"'/lib/common.sh"
    load_config
    echo "$ARDCONFIG_OLLAMA_MODEL"
  '
  [ "$status" -eq 0 ]
  [ "$output" = "custom-ollama-model" ]
}

@test "config precedence: an unset ARDCONFIG_LLM_PROVIDER stays empty after load_config() (no leaked default)" {
  run bash -c '
    set -euo pipefail
    source "'"${REPO_ROOT}"'/lib/common.sh"
    load_config
    echo "[${ARDCONFIG_LLM_PROVIDER}][${ARDCONFIG_OLLAMA_HOST}]"
  '
  [ "$status" -eq 0 ]
  [ "$output" = "[][]" ]
}

# ---------------------------------------------------------------------
# AC-014/FR-22 amended: ollama pip package is added to the install list
# only when provider=ollama.
# ---------------------------------------------------------------------

@test "AC-014: ollama>=0.4.8,<1.0.0 is listed for installation when provider=ollama and deps are missing" {
  _run_onboard "$FAKE_VENV" \
    ARDCONFIG_LLM_PROVIDER=ollama \
    ARDCONFIG_TEST_FIXTURE_MODE=missing_deps \
    ARDCONFIG_TEST_REAL_VENV_PYTHON="$REAL_VENV_PYTHON" \
    ARDCONFIG_TEST_FAKE_PIP_LOG="${BATS_TEST_TMPDIR}/pip.log" \
    "$ONBOARD" --json --non-interactive --vendor-id 0000 --product-id 0000

  # Exit 2 is expected: after the (fake, always-succeeding) deps install,
  # the fake python also fails check_ollama_available()'s heredoc, so the
  # run terminates at the ollama_reachable step. We only assert on the
  # deps step here.
  [ "$status" -eq 2 ]
  deps_msg="$(echo "$output" | jq -r '[.steps[] | select(.name == "deps")][0].message')"
  [[ "$deps_msg" == *"ollama>=0.4.8,<1.0.0"* ]]
  [[ "$deps_msg" == *"strands-agents"* ]]
  [[ "$deps_msg" == *"boto3"* ]]
}

@test "AC-014: ollama is NOT listed for installation when provider=bedrock, even with it absent" {
  _run_onboard "$FAKE_VENV" \
    ARDCONFIG_LLM_PROVIDER=bedrock \
    ARDCONFIG_TEST_FIXTURE_MODE=missing_deps \
    ARDCONFIG_TEST_REAL_VENV_PYTHON="$REAL_VENV_PYTHON" \
    ARDCONFIG_TEST_FAKE_PIP_LOG="${BATS_TEST_TMPDIR}/pip.log" \
    "$ONBOARD" --json --non-interactive --vendor-id 0000 --product-id 0000

  [ "$status" -eq 2 ]
  deps_msg="$(echo "$output" | jq -r '[.steps[] | select(.name == "deps")][0].message')"
  [[ "$deps_msg" != *"ollama"* ]]
  [[ "$deps_msg" == *"strands-agents"* ]]
  [[ "$deps_msg" == *"boto3"* ]]
}

# ---------------------------------------------------------------------
# AC-010/AC-011 regression: the provider-conditional prereq dispatch
# never calls the wrong check (regression-critical check #2 continuation
# from the orchestrator's brief; also FR-23 amended's own AC).
# ---------------------------------------------------------------------

@test "AC-010: provider=ollama never runs an aws_creds step, even with no AWS credentials present" {
  _start_mock_ollama gpt-oss:latest
  port="$MOCK_OLLAMA_PORT"
  _run_onboard "$FAKE_VENV" \
    ARDCONFIG_LLM_PROVIDER=ollama \
    ARDCONFIG_OLLAMA_HOST="http://127.0.0.1:${port}" \
    ARDCONFIG_OLLAMA_MODEL=gpt-oss:latest \
    ARDCONFIG_TEST_FIXTURE_MODE=delegate \
    ARDCONFIG_TEST_REAL_VENV_PYTHON="$REAL_VENV_PYTHON" \
    "$ONBOARD" --json --non-interactive --vendor-id 0000 --product-id 0000

  step_names="$(echo "$output" | jq -r '[.steps[].name] | join(",")')"
  [[ "$step_names" != *"aws_creds"* ]]
  [[ "$step_names" == *"ollama_reachable"* ]]
}

@test "AC-011: provider=bedrock with missing AWS credentials reproduces the pre-delta exit-2/aws_creds shape" {
  _run_onboard "$REPO_ROOT/.venv" \
    ARDCONFIG_LLM_PROVIDER=bedrock \
    "$ONBOARD" --json --non-interactive --vendor-id 0000 --product-id 0000

  [ "$status" -eq 2 ]
  step_names="$(echo "$output" | jq -r '[.steps[].name] | join(",")')"
  [[ "$step_names" == *"aws_creds"* ]]
  [[ "$step_names" != *"ollama_reachable"* ]]
}

# ---------------------------------------------------------------------
# spec/security.md Finding 3 (Low): a non-localhost ARDCONFIG_OLLAMA_HOST
# gets an informational warning, since board/USB metadata and prompts
# will be sent to that unauthenticated endpoint. This is a warning, not
# a hard block — remote Ollama usage is a legitimate use case.
# ---------------------------------------------------------------------

@test "Finding 3: non-local ARDCONFIG_OLLAMA_HOST emits an ollama_host warn step (does not block)" {
  # An address that fails ollama.Client() argument validation instantly
  # (invalid IPv4 literal), so this test needs no live network and no
  # DNS resolution, while still exercising a host string that the
  # localhost/127.0.0.1/::1 allowlist correctly rejects.
  _run_onboard "$REPO_ROOT/.venv" \
    ARDCONFIG_LLM_PROVIDER=ollama \
    ARDCONFIG_OLLAMA_HOST="http://256.256.256.256:11434" \
    ARDCONFIG_OLLAMA_MODEL=gpt-oss:latest \
    "$ONBOARD" --json --non-interactive --vendor-id 0000 --product-id 0000

  [ "$status" -eq 2 ]
  step="$(echo "$output" | jq -r '[.steps[] | select(.name == "ollama_host")][0]')"
  [ "$(echo "$step" | jq -r '.status')" = "warn" ]
  msg="$(echo "$step" | jq -r '.message')"
  [[ "$msg" == *"non-local address"* ]]
  [[ "$msg" == *"256.256.256.256"* ]]
  [[ "$msg" == *"unauthenticated"* ]]
  # It's a warning, not a hard failure by itself — execution still
  # proceeds on to the (unrelated, expected-to-fail) reachability check.
  step_names="$(echo "$output" | jq -r '[.steps[].name] | join(",")')"
  [[ "$step_names" == *"ollama_host"* ]]
  [[ "$step_names" == *"ollama_reachable"* ]]
}

@test "Finding 3: default localhost ARDCONFIG_OLLAMA_HOST does NOT emit an ollama_host warn step" {
  _start_mock_ollama gpt-oss:latest
  port="$MOCK_OLLAMA_PORT"
  _run_onboard "$FAKE_VENV" \
    ARDCONFIG_LLM_PROVIDER=ollama \
    ARDCONFIG_OLLAMA_HOST="http://127.0.0.1:${port}" \
    ARDCONFIG_OLLAMA_MODEL=gpt-oss:latest \
    ARDCONFIG_TEST_FIXTURE_MODE=delegate \
    ARDCONFIG_TEST_REAL_VENV_PYTHON="$REAL_VENV_PYTHON" \
    "$ONBOARD" --json --non-interactive --vendor-id 0000 --product-id 0000

  step_names="$(echo "$output" | jq -r '[.steps[].name] | join(",")')"
  [[ "$step_names" != *"ollama_host"* ]]
  [[ "$step_names" == *"ollama_reachable"* ]]
}

# ---------------------------------------------------------------------
# FR-27/AC-012: check_ollama_available()'s three distinguishable failure
# modes, plus the "OK, execution proceeds" pass-through case
# (regression-critical check #5 from the orchestrator's brief).
# ---------------------------------------------------------------------

@test "FR-27(a): unreachable Ollama server exits 2 with a server-unreachable message" {
  port="$(_free_port)"  # nothing listening on this port
  _run_onboard "$REPO_ROOT/.venv" \
    ARDCONFIG_LLM_PROVIDER=ollama \
    ARDCONFIG_OLLAMA_HOST="http://127.0.0.1:${port}" \
    ARDCONFIG_OLLAMA_MODEL=gpt-oss:latest \
    "$ONBOARD" --json --non-interactive --vendor-id 0000 --product-id 0000

  [ "$status" -eq 2 ]
  step="$(echo "$output" | jq -r '[.steps[] | select(.name == "ollama_reachable")][0]')"
  [ "$(echo "$step" | jq -r '.status')" = "error" ]
  msg="$(echo "$step" | jq -r '.message')"
  [[ "$msg" == *"unreachable"* ]]
  [[ "$msg" != *"pull"* ]]     # distinguishable from the model-missing message
  [[ "$msg" != *"not installed"* ]]  # distinguishable from the deps-missing message
}

@test "FR-27(b): model not pulled exits 2 with 'ollama pull <model>' guidance and never invokes a real pull" {
  _start_mock_ollama other-model:latest
  port="$MOCK_OLLAMA_PORT"

  # A fake `ollama` CLI on PATH that fails the test loudly if ever
  # invoked, so "no automatic pull is attempted" is a genuine behavioral
  # assertion, not just a read of the source.
  mkdir -p "${BATS_TEST_TMPDIR}/fakebin"
  cat > "${BATS_TEST_TMPDIR}/fakebin/ollama" <<'EOS'
#!/usr/bin/env bash
echo "$@" >> "${ARDCONFIG_TEST_OLLAMA_CLI_LOG:?unset}"
exit 0
EOS
  chmod +x "${BATS_TEST_TMPDIR}/fakebin/ollama"

  _run_onboard "$REPO_ROOT/.venv" \
    PATH="${BATS_TEST_TMPDIR}/fakebin:${PATH}" \
    ARDCONFIG_TEST_OLLAMA_CLI_LOG="${BATS_TEST_TMPDIR}/ollama_cli.log" \
    ARDCONFIG_LLM_PROVIDER=ollama \
    ARDCONFIG_OLLAMA_HOST="http://127.0.0.1:${port}" \
    ARDCONFIG_OLLAMA_MODEL=gpt-oss:latest \
    "$ONBOARD" --json --non-interactive --vendor-id 0000 --product-id 0000

  [ "$status" -eq 2 ]
  step="$(echo "$output" | jq -r '[.steps[] | select(.name == "ollama_reachable")][0]')"
  [ "$(echo "$step" | jq -r '.status')" = "error" ]
  msg="$(echo "$step" | jq -r '.message')"
  [[ "$msg" == *"ollama pull gpt-oss:latest"* ]]

  [ ! -f "${BATS_TEST_TMPDIR}/ollama_cli.log" ]
}

@test "FR-27(deps missing): ollama package unimportable inside the check produces a distinguishable DEPS_MISSING message" {
  _run_onboard "$FAKE_VENV" \
    ARDCONFIG_LLM_PROVIDER=ollama \
    ARDCONFIG_OLLAMA_HOST="http://127.0.0.1:1" \
    ARDCONFIG_OLLAMA_MODEL=gpt-oss:latest \
    ARDCONFIG_TEST_FIXTURE_MODE=delegate_no_ollama \
    ARDCONFIG_TEST_REAL_VENV_PYTHON="$REAL_VENV_PYTHON" \
    "$ONBOARD" --json --non-interactive --vendor-id 0000 --product-id 0000

  [ "$status" -eq 2 ]
  step="$(echo "$output" | jq -r '[.steps[] | select(.name == "ollama_reachable")][0]')"
  [ "$(echo "$step" | jq -r '.status')" = "error" ]
  msg="$(echo "$step" | jq -r '.message')"
  [[ "$msg" == *"not installed"* ]]
  [[ "$msg" != *"unreachable"* ]]  # distinguishable from the unreachable-server message
  [[ "$msg" != *"pull"* ]]          # distinguishable from the model-missing message
}

@test "FR-27(c): reachable server with the configured model present passes the check and execution proceeds" {
  _start_mock_ollama gpt-oss:latest
  port="$MOCK_OLLAMA_PORT"
  _run_onboard "$FAKE_VENV" \
    ARDCONFIG_LLM_PROVIDER=ollama \
    ARDCONFIG_OLLAMA_HOST="http://127.0.0.1:${port}" \
    ARDCONFIG_OLLAMA_MODEL=gpt-oss:latest \
    ARDCONFIG_TEST_FIXTURE_MODE=delegate \
    ARDCONFIG_TEST_REAL_VENV_PYTHON="$REAL_VENV_PYTHON" \
    "$ONBOARD" --json --non-interactive --vendor-id 0000 --product-id 0000

  # check_ollama_available() passes (ollama_reachable: ok), so execution
  # proceeds to invoke_agent() — which the fixture's `delegate` mode
  # deliberately short-circuits (see fake_venv/bin/python) rather than
  # attempting a real LLM call. Exit 1 (EXIT_FAIL) here is the expected,
  # intentional result of that fixture boundary, not a real failure.
  [ "$status" -eq 1 ]
  step="$(echo "$output" | jq -r '[.steps[] | select(.name == "ollama_reachable")][0]')"
  [ "$(echo "$step" | jq -r '.status')" = "ok" ]
  step_names="$(echo "$output" | jq -r '[.steps[].name] | join(",")')"
  [[ "$step_names" == *"agent"* ]]  # proves invoke_agent() was actually reached
}
