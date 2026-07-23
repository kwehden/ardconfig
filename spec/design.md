# Design — AI-Powered Hardware Onboarding for ardconfig

> **Amendment (2026-07-20):** This revision restructures the document under a
> standard section template and adds the **Ollama LLM Provider** delta
> (FR-25–FR-28, NFR-8; amended FR-7, FR-11, FR-12, FR-22, FR-23; traces to
> `spec/context.md` §12 and `spec/requirements.md`'s Amendment History). All
> prior Bedrock-only design content is preserved and, where the delta changes
> it, marked inline as **(AMENDED)**. Sections with no delta impact are
> carried forward unchanged from the pre-delta design.

---

## Overview

`ardconfig-onboard` is a new CLI entry point that uses a Strands AI agent to
research an unrecognized Arduino-compatible board and generate a validated
board profile JSON, following the existing bash-script conventions of the
`ardconfig` toolchain (exit codes, `--json` output, `--non-interactive` mode).
The agent has tools for `arduino-cli` introspection, file read/write, profile
validation, and running `ardconfig-setup`/`ardconfig-verify`.

**This delta (context.md §12)** makes the agent's LLM backend
provider-selectable rather than hardcoded to Amazon Bedrock:

- A new `ARDCONFIG_LLM_PROVIDER` setting (`bedrock` | `ollama`, **default
  `ollama`**) selects between `strands.models.bedrock.BedrockModel` and
  `strands.models.ollama.OllamaModel`.
- `ollama` becomes the default, local-first path — no AWS credentials, no AWS
  network egress (GO1).
- `bedrock` remains fully supported as an explicit opt-in, behaviorally
  unchanged from the pre-delta implementation (GO2, C20).
- Prerequisite checks, JIT dependency installation, and model construction
  all become provider-conditional, with the provider-specific model class
  imported lazily so neither provider's SDK/pip dependency is required by
  the other's code path (FR-28, C19).
- No other part of the pipeline changes: agent tools, system prompt, profile
  schema, validation, udev handling, and the setup/verify auto-run loop are
  explicitly out of scope (NFR-8, GO6).

This is a small, single-process CLI feature. It does not warrant a
distributed-systems treatment; the DDD/Reactive-architecture sections below
are included per the design template and answered honestly at the scale that
applies — mostly "not applicable, and here is why."

---

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        User / AI Agent                          │
│                     ardconfig-onboard [args]                    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                ┌──────────▼──────────┐
                │  bin/ardconfig-     │  Bash wrapper
                │  onboard            │  - arg parsing, config
                │                     │  - resolve_llm_provider() (NEW, FR-25)
                │                     │  - JIT dep install (provider-conditional, FR-22)
                │                     │  - provider-conditional prereq check
                │                     │    (check_aws_credentials | check_ollama_available)
                │                     │  - scan for unknown USB
                │                     │  - invoke Python agent
                │                     │  - human confirmation
                │                     │  - udev rule update
                └──────────┬──────────┘
                           │ subprocess (Python), env vars passed explicitly
                ┌──────────▼──────────┐
                │  agent/             │  Strands AI agent
                │  onboard_agent.py   │  - create_agent(): provider-conditional,
                │  tools.py           │    lazy-imported model backend (FR-25, FR-28)
                │                     │  - research board / generate profile JSON
                │                     │  - validate via bash
                │                     │  - run setup & verify
                │                     │  - iterate on failure
                └──────────┬──────────┘
                           │ tools call                     model call
          ┌────────────────┼────────────────┐          ┌─────┴─────┐
          ▼                ▼                ▼          ▼           ▼
   arduino-cli        web search     existing scripts  Bedrock   Ollama server
   board listall      (board docs)   ardconfig-setup    API      (local, default
   core search                       ardconfig-verify            http://localhost:11434)
   core install                      board-profiles.sh
```

### Modified Existing Components

| Component | Change | Requirement |
|---|---|---|
| `bin/ardconfig-detect` | Remove `vid == "2341"` guard; match all profile vendor IDs; report unknown devices | FR-1, FR-2 |
| `conf/ardconfig.conf` | Add `ARDCONFIG_BEDROCK_MODEL`, `ARDCONFIG_AWS_REGION` (pre-delta) **(AMENDED)**: add `ARDCONFIG_LLM_PROVIDER`, `ARDCONFIG_OLLAMA_HOST`, `ARDCONFIG_OLLAMA_MODEL`; change all five AI-related lines to conditional-assignment syntax (see [Public Interfaces §2](#2-environment-variables--confardconfigconf-schema) — this corrects a pre-existing env-var-precedence defect, see the callout there) | FR-11, FR-12, FR-25, FR-26 |
| `udev/99-arduino.rules` | Appended at runtime by onboard script for new vendor IDs | FR-18 (unaffected by this delta) |
| `bin/ardconfig-onboard` **(AMENDED)** | Add `resolve_llm_provider()` (FR-25), make `ensure_ai_deps()` provider-conditional for the `ollama` pip package (FR-22), add `check_ollama_available()` (FR-27) and branch prereq checks on provider (FR-23), pass 3 new env vars through `invoke_agent()`, update `usage()` heredoc | FR-22, FR-23, FR-25, FR-27 |
| `agent/onboard_agent.py` **(AMENDED)** | `create_agent()`: read `ARDCONFIG_LLM_PROVIDER`, lazily import and construct `BedrockModel` or `OllamaModel` per branch; remove top-level `from strands.models.bedrock import BedrockModel` | FR-7, FR-25, FR-26, FR-28 |

### New Components

| Component | Purpose | Requirement |
|---|---|---|
| `bin/ardconfig-onboard` | Bash entry point for onboarding flow (pre-delta) | FR-3 |
| `agent/__init__.py` | Package marker (pre-delta) | — |
| `agent/onboard_agent.py` | Strands AI agent: research, generate, validate, setup, verify (pre-delta) | FR-7 through FR-10, FR-13, FR-19–21 |
| `agent/tools.py` | Tool definitions for the Strands agent (pre-delta, **unmodified by this delta** — NFR-8) | FR-8, FR-9, FR-10 |

**This delta adds zero new files.** It is entirely a modification of the four
files above (see [Simplicity Budget](#simplicity-budget)).

---

## Data Flow

### Step-by-Step (updated for provider selection)

```
1. ARG PARSING & CONFIG LOAD
   parse_onboard_args → load_config (sources conf/ardconfig.conf)

2. PROVIDER RESOLUTION (NEW, FR-25)
   resolve_llm_provider(): ARDCONFIG_LLM_PROVIDER defaults to "ollama" if
   unset/empty. If set to anything other than "bedrock"/"ollama" → exit 2
   immediately, before any dependency install or prereq check.

3. JIT DEPS (FR-22, provider-conditional for `ollama` package)
   ensure_ai_deps(): always checks/installs strands-agents, boto3.
   If provider=ollama: also checks/installs the `ollama` pip package.

4. PROVIDER-CONDITIONAL PREREQ CHECK (FR-23, FR-27)
   provider=bedrock → check_aws_credentials()          [unchanged]
   provider=ollama  → check_ollama_available() (NEW)   [reachability + model presence]
   Either failure path → exit 2 with a distinguishable message.

5. INPUT RESOLUTION
   --vendor-id/--product-id/--board-name  OR  scan /dev/ttyACM*/ttyUSB* for
   unknown devices [[unchanged]]

6. AGENT INVOCATION (env vars now include the 3 new ones)
   invoke_agent(): passes ARDCONFIG_LLM_PROVIDER, ARDCONFIG_BEDROCK_MODEL,
   ARDCONFIG_AWS_REGION, ARDCONFIG_OLLAMA_HOST, ARDCONFIG_OLLAMA_MODEL
   explicitly into the python subprocess environment.

7. AI RESEARCH
   ┌─────────────────────────────────────────────────────────┐
   │ create_agent() (FR-25, FR-28):                           │
   │   read ARDCONFIG_LLM_PROVIDER (already validated by      │
   │   step 2, but re-validated defensively — see note below) │
   │   if bedrock: lazy `from strands.models.bedrock import   │
   │     BedrockModel`; construct with model_id/region_name   │
   │   if ollama:  lazy `from strands.models.ollama import    │
   │     OllamaModel`; construct with host/model_id            │
   │ Strands Agent (unchanged tools/system prompt, NFR-8):     │
   │  a. Read existing profile (schema)                        │
   │  b. arduino-cli board listall/search                      │
   │  c. Web search for board docs                             │
   │  d. Generate profile JSON                                 │
   │  e. Validate via bash subprocess                          │
   │  f. Run ardconfig-setup                                   │
   │  g. Run ardconfig-verify                                  │
   │  h. If f/g fail: adjust & retry (×2)                       │
   └───────────────────────────┬────────────────────────────┘
                                │
8. CONFIRMATION      Display profile → user approves (or auto in --non-interactive)
                                │
9. WRITE             Write profiles/<id>.json
                                │
10. UDEV UPDATE      Append vendor ID rule if new → reload udev
                                │
11. RESULT           Emit success/failure via output.sh
```

### Sequence Diagram

```mermaid
sequenceDiagram
    participant User
    participant Onboard as bin/ardconfig-onboard
    participant Agent as agent/onboard_agent.py
    participant Bedrock as Amazon Bedrock
    participant Ollama as Local Ollama server

    User->>Onboard: ardconfig-onboard [flags]
    Onboard->>Onboard: load_config()
    Onboard->>Onboard: resolve_llm_provider() (FR-25)
    alt ARDCONFIG_LLM_PROVIDER invalid
        Onboard-->>User: exit 2 "Invalid ARDCONFIG_LLM_PROVIDER: '<value>'"
    end
    Onboard->>Onboard: ensure_ai_deps() (FR-22; +ollama pip pkg if provider=ollama)
    alt provider == bedrock
        Onboard->>Bedrock: check_aws_credentials() → sts.get_caller_identity()
    else provider == ollama
        Onboard->>Ollama: check_ollama_available() → ollama.Client(host).list()
    end
    alt prereq check failed
        Onboard-->>User: exit 2 (distinguishable message per FR-23/FR-27)
    end
    Onboard->>Agent: python -m agent.onboard_agent (stdin JSON; env vars incl. provider config)
    Agent->>Agent: create_agent() — lazy-import BedrockModel or OllamaModel (FR-28)
    alt provider == bedrock
        Agent->>Bedrock: Converse API calls (via BedrockModel)
        Bedrock-->>Agent: model responses
    else provider == ollama
        Agent->>Ollama: chat API calls (via OllamaModel)
        Ollama-->>Agent: model responses
    end
    Agent-->>Onboard: stdout JSON {status, profile, ...}
    Onboard->>User: display profile, confirm, write profiles/<id>.json, update udev
```

---

## Public Interfaces

### 1. CLI Interface (`bin/ardconfig-onboard`)

```
Usage: ardconfig-onboard [OPTIONS]

Onboard a new Arduino-compatible board using AI-assisted research.

Options:
  --vendor-id VID     USB vendor ID (hex, e.g., 0483)
  --product-id PID    USB product ID (hex, e.g., 374b)
  --board-name NAME   Board name for research (e.g., "Nucleo-F411RE")
  --json              Output JSON instead of human-readable text
  --quiet, -q         Suppress informational output
  --non-interactive   Run without prompts (auto-approve confirmation)
  --help, -h          Show this help

Exit codes:
  0  Board onboarded successfully
  1  Onboarding failed
  2  Missing prerequisites (invalid ARDCONFIG_LLM_PROVIDER, no Python/venv,
     missing AI deps, no AWS credentials [provider=bedrock], or Ollama
     server/model unavailable [provider=ollama])
  3  No unknown hardware found (hardware-present mode)
  4  Partial success (profile created but setup/verify failed)
```

**(AMENDED)** Exact `usage()` heredoc replacement — this is the literal text
to substitute for the current exit-code-2 line
(`  2  Missing prerequisites (no AWS creds, no Python, no venv)`):

```
Exit codes:
  0  Board onboarded successfully
  1  Onboarding failed
  2  Missing prerequisites (invalid ARDCONFIG_LLM_PROVIDER, no Python/venv,
     missing AI deps, no AWS credentials [provider=bedrock], or Ollama
     server/model unavailable [provider=ollama])
  3  No unknown hardware found (hardware-present mode)
  4  Partial success (profile created but setup/verify failed)
```

No new CLI flags are added by this delta (NFR-1 unaffected). Provider
selection is env-var/conf-file only, not a flag — consistent with
`ARDCONFIG_BEDROCK_MODEL`/`ARDCONFIG_AWS_REGION` precedent (C11).

### 2. Environment Variables & `conf/ardconfig.conf` Schema

| Env Var | `conf/ardconfig.conf` key | Default | Applies when | Requirement |
|---|---|---|---|---|
| `ARDCONFIG_LLM_PROVIDER` | `ARDCONFIG_LLM_PROVIDER` | `ollama` | always | FR-25 |
| `ARDCONFIG_BEDROCK_MODEL` | `ARDCONFIG_BEDROCK_MODEL` | `us.anthropic.claude-sonnet-4-6` | provider=bedrock | FR-11 (unchanged) |
| `ARDCONFIG_AWS_REGION` | `ARDCONFIG_AWS_REGION` | `us-west-2` (falls back to `AWS_DEFAULT_REGION`) | provider=bedrock | FR-12 (unchanged) |
| `ARDCONFIG_OLLAMA_HOST` | `ARDCONFIG_OLLAMA_HOST` | `http://localhost:11434` | provider=ollama | FR-26 |
| `ARDCONFIG_OLLAMA_MODEL` | `ARDCONFIG_OLLAMA_MODEL` | `gpt-oss:latest` | provider=ollama | FR-26 |

**Exact lines to add/change in `conf/ardconfig.conf`** (replaces the existing
two-line block; see the precedence-bug callout immediately below for why the
syntax changes from plain assignment to conditional assignment):

```bash
# AI onboarding settings (used by ardconfig-onboard)
# LLM provider: "bedrock" or "ollama". Default: ollama (see FR-25).
: "${ARDCONFIG_LLM_PROVIDER:=}"
# Bedrock model ID. Default: us.anthropic.claude-sonnet-4-6 (provider=bedrock only)
: "${ARDCONFIG_BEDROCK_MODEL:=}"
# AWS region for Bedrock calls. Default: us-west-2, falls back to AWS_DEFAULT_REGION (provider=bedrock only)
: "${ARDCONFIG_AWS_REGION:=}"
# Ollama server URL. Default: http://localhost:11434 (provider=ollama only)
: "${ARDCONFIG_OLLAMA_HOST:=}"
# Ollama model tag. Default: gpt-oss:latest (provider=ollama only)
: "${ARDCONFIG_OLLAMA_MODEL:=}"
```

Each variable is left as an empty placeholder by default (`:=` with nothing
after it means "if unset or empty, set to empty" — a no-op that exists only
to document the variable's presence and comment its default). The actual
default values (`ollama`, `us.anthropic.claude-sonnet-4-6`, `us-west-2`,
`http://localhost:11434`, `gpt-oss:latest`) live in exactly one place each:
the bash `${VAR:-default}` reads in `bin/ardconfig-onboard` and the Python
`os.environ.get(KEY) or default` reads in `agent/onboard_agent.py`. This
avoids a default value drifting between the conf file's comment and the
code's actual fallback (a single source of truth per default, per Pike Rule
5's spirit applied to config).

#### Config precedence correction (discovered during design — read before implementing)

**Finding:** The pre-delta implementation's stated precedence
(`env var > conf/ardconfig.conf value > hardcoded default`, as documented in
the original design §5) is **not actually implemented correctly** for
`ARDCONFIG_BEDROCK_MODEL` and partially for `ARDCONFIG_AWS_REGION`. The root
cause:

1. `conf/ardconfig.conf` currently has plain assignments:
   `ARDCONFIG_BEDROCK_MODEL=""`.
2. `lib/common.sh`'s `load_config()` does an **unconditional** `source
   "$conf_file"`. In bash, sourcing a file with a plain `VAR=value`
   assignment always overwrites the current value of `VAR` — including a
   value the caller passed in as an environment variable
   (e.g. `ARDCONFIG_BEDROCK_MODEL=foo bin/ardconfig-onboard`). The env var is
   silently reset to `""` by the conf file's own placeholder.
3. `invoke_agent()` then explicitly passes this (now-empty) value into the
   Python subprocess's environment: `ARDCONFIG_BEDROCK_MODEL="${ARDCONFIG_BEDROCK_MODEL:-}"`.
   This sets the env var in the child process to `""` — **present, not
   absent**.
4. `agent/onboard_agent.py`'s `os.environ.get("ARDCONFIG_BEDROCK_MODEL",
   "us.anthropic.claude-sonnet-4-6")` only applies the default when the key
   is **absent**, not when it is present-but-empty. So it returns `""`, and
   `BedrockModel(model_id="")` is constructed — broken, in the default case,
   with no env var override ever taking effect.

`ARDCONFIG_AWS_REGION` is partially protected because `check_aws_credentials`
happens to use bash's `${ARDCONFIG_AWS_REGION:-${AWS_DEFAULT_REGION:-us-west-2}}`
(the `:-` operator treats empty-or-unset the same way), but the *env-var
override* still never reaches that expression correctly — only editing
`conf/ardconfig.conf` directly, or setting the unrelated `AWS_DEFAULT_REGION`,
currently works.

**This is necessarily in scope for this delta**, not a separate concern,
because FR-26's literal testable criteria require both defaults *and*
env-var overrides to work for the three new variables — and copying the
existing pattern verbatim would reproduce the same defect for
`ARDCONFIG_OLLAMA_HOST`/`ARDCONFIG_OLLAMA_MODEL`/`ARDCONFIG_LLM_PROVIDER`.
Leaving the two pre-existing variables unfixed while fixing only the three
new ones would also create an inconsistent, confusing precedence rule
between the two providers.

**Fix (two parts, both required):**

1. **`conf/ardconfig.conf`**: change all five AI-related lines from
   `VAR=""` to `: "${VAR:=}"` (shown above). This bash idiom only assigns
   when `VAR` is unset or empty — so a real, non-empty environment variable
   passed in by the caller survives `load_config()`'s `source` unchanged.
2. **`agent/onboard_agent.py`**: change every `os.environ.get(KEY, default)`
   read to `os.environ.get(KEY) or default` (shown in the `create_agent()`
   listing below). This treats an explicitly-empty env var the same as an
   absent one, so an empty string passed through by `invoke_agent()`'s
   `KEY="${KEY:-}"` pattern still resolves to the intended hardcoded
   default.

Both changes are backward compatible: a user with an existing, customized
`conf/ardconfig.conf` that predates this delta (lacking the new lines
entirely) still gets correct hardcoded defaults, because an unset bash
variable and an empty one behave identically at every read site above.

**Governance note for the orchestrator:** this is a corrective fix to
already-shipped code (`agent/onboard_agent.py`'s `create_agent()`,
`conf/ardconfig.conf`), discovered while designing FR-26. It is bundled into
this delta because FR-26 cannot be verified as passing without it. If the
project's governance model prefers this to be split into a separate
corrective-requirements packet (per `CLAUDE.md`'s regression/corrective-mode
process) rather than an inline fix, flag that at Gate 3 review — see
[Open Design Questions](#open-design-questions).

### 3. `agent/onboard_agent.py` Python Interface

`create_agent()`'s public signature is unchanged (`() -> strands.Agent`);
only its body changes:

```python
def create_agent():
    """Construct the Strands Agent with a provider-selected LLM backend.

    Reads ARDCONFIG_LLM_PROVIDER (default "ollama"). The provider-specific
    model class is imported lazily, inside the selected branch only
    (FR-28) — this avoids requiring the `ollama` PyPI package when
    provider=bedrock, and avoids requiring `boto3`-backed Bedrock setup
    when provider=ollama.

    Raises:
        ValueError: if ARDCONFIG_LLM_PROVIDER resolves to a value other
            than "bedrock" or "ollama". In the normal CLI path this is
            unreachable — bin/ardconfig-onboard's resolve_llm_provider()
            validates and exits 2 before this function is ever called.
            This guard exists for direct/library-level invocation (e.g.
            unit tests calling create_agent() without going through the
            bash wrapper).
    """
    provider = os.environ.get("ARDCONFIG_LLM_PROVIDER") or "ollama"

    if provider == "bedrock":
        from strands.models.bedrock import BedrockModel

        model_id = os.environ.get("ARDCONFIG_BEDROCK_MODEL") or "us.anthropic.claude-sonnet-4-6"
        region = (
            os.environ.get("ARDCONFIG_AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or "us-west-2"
        )
        model = BedrockModel(model_id=model_id, region_name=region)
    elif provider == "ollama":
        from strands.models.ollama import OllamaModel

        host = os.environ.get("ARDCONFIG_OLLAMA_HOST") or "http://localhost:11434"
        model_id = os.environ.get("ARDCONFIG_OLLAMA_MODEL") or "gpt-oss:latest"
        model = OllamaModel(host=host, model_id=model_id)
    else:
        raise ValueError(
            f"Invalid ARDCONFIG_LLM_PROVIDER: '{provider}' "
            f"(must be 'bedrock' or 'ollama')"
        )

    return Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[arduino_cli_search, read_file, write_file,
               validate_profile, run_setup, run_verify]
    )
```

`OllamaModel(host=host, model_id=model_id)` is confirmed against the
installed SDK source
(`.venv/lib/python3.14/site-packages/strands/models/ollama.py`,
strands-agents 1.40.0): `__init__(self, host: str | None, *,
ollama_client_args=None, **model_config: Unpack[OllamaConfig])` — `host` is
positional-or-keyword (no leading `*`), and `model_id` is a key of
`OllamaConfig` consumed via `**model_config` (keyword-only, after the `*`).
Calling with both as keyword arguments is valid and matches the codebase's
existing keyword-argument style for `BedrockModel(model_id=..., region_name=...)`.

**Module-level import change:** remove the current top-level
`from strands.models.bedrock import BedrockModel` from
`agent/onboard_agent.py`. Keep `from strands import Agent` at module level
(this is safe for both providers — `strands/models/__init__.py` itself does
an unconditional `from .bedrock import BedrockModel`, but never touches
`ollama`; `OllamaModel` is only reachable via that package's lazy
`__getattr__`, which is why a top-level `from strands.models.ollama import
OllamaModel` or `from strands.models import OllamaModel` in
`onboard_agent.py` would defeat the laziness (C19) — importing it inside the
`elif provider == "ollama":` branch, as shown, preserves it).

`main()`, `build_prompt()`, `parse_agent_output()`, and `SYSTEM_PROMPT` are
unchanged (NFR-8). `main()` does not add a `try/except ValueError` around
`create_agent()` — an invalid provider reaching this point indicates the
bash-level validation was bypassed (e.g. direct `python -m
agent.onboard_agent` invocation with a bad env var); the uncaught
`ValueError` will produce a nonzero exit and a Python traceback on stderr,
which `invoke_agent()` maps to `EXIT_FAIL` (1) via its existing `|| { ...
exit "$EXIT_FAIL"; }` handler. This is intentionally not exit code 2 in that
bypass scenario — code 2 for invalid-provider is guaranteed only via the
normal CLI path, which is what FR-25's acceptance criteria test.

### 4. `bin/ardconfig-onboard` Bash Function Interface

**`resolve_llm_provider()` (NEW, FR-25)** — called immediately after
`load_config`, before `ensure_ai_deps`:

```bash
resolve_llm_provider() {
  ARDCONFIG_LLM_PROVIDER="${ARDCONFIG_LLM_PROVIDER:-ollama}"
  case "$ARDCONFIG_LLM_PROVIDER" in
    bedrock|ollama)
      output_step ok llm_provider "LLM provider: ${ARDCONFIG_LLM_PROVIDER}"
      ;;
    *)
      output_step error llm_provider "Invalid ARDCONFIG_LLM_PROVIDER value: '${ARDCONFIG_LLM_PROVIDER}' (must be 'bedrock' or 'ollama')"
      output_result "$EXIT_PREREQ"
      exit "$EXIT_PREREQ"
      ;;
  esac
}
```

Matching is exact-case (`bedrock`/`ollama` only, no case-folding), matching
`create_agent()`'s comparison for consistency between the two entry paths.

**`ensure_ai_deps()` (AMENDED, FR-22)** — provider-conditional `ollama`
package install, appended after the existing `strands`/`boto3` checks
(`boto3`'s check/install stays unconditional per C18):

```bash
ensure_ai_deps() {
  local venv="${ARDCONFIG_VENV_PATH:-.venv}"
  if [[ ! -f "${venv}/bin/python" ]]; then
    output_step error venv "Python venv not found at ${venv}. Run ardconfig-setup first."
    output_result "$EXIT_PREREQ"
    exit "$EXIT_PREREQ"
  fi
  local missing=()
  "${venv}/bin/python" -c "import strands" 2>/dev/null || missing+=(strands-agents)
  "${venv}/bin/python" -c "import boto3" 2>/dev/null || missing+=(boto3)
  if [[ "$ARDCONFIG_LLM_PROVIDER" == "ollama" ]]; then
    "${venv}/bin/python" -c "import ollama" 2>/dev/null || missing+=("ollama>=0.4.8,<1.0.0")
  fi
  if [[ ${#missing[@]} -gt 0 ]]; then
    output_step info deps "Installing AI dependencies: ${missing[*]}"
    if ! "${venv}/bin/pip" install --quiet "${missing[@]}"; then
      output_step error deps "Failed to install: ${missing[*]}"
      output_result "$EXIT_PREREQ"
      exit "$EXIT_PREREQ"
    fi
    output_step ok deps "AI dependencies installed"
  fi
}
```

The `ollama>=0.4.8,<1.0.0` pin follows C22 (matches the range
`strands-agents` 1.40.0 itself declares for its `ollama` extra). Pinning is
a SHOULD per C22, not a MUST; this design recommends pinning it to avoid
installing an untested major version.

**`check_ollama_available()` (NEW, FR-27)** — called only when
`provider == ollama`, in place of `check_aws_credentials`:

```bash
check_ollama_available() {
  local venv="${ARDCONFIG_VENV_PATH:-.venv}"
  local host="${ARDCONFIG_OLLAMA_HOST:-http://localhost:11434}"
  local model="${ARDCONFIG_OLLAMA_MODEL:-gpt-oss:latest}"

  local status
  status=$(ARDCONFIG_OLLAMA_HOST="$host" ARDCONFIG_OLLAMA_MODEL="$model" \
    "${venv}/bin/python" - <<'PYEOF' 2>/dev/null
import os
import sys

host = os.environ["ARDCONFIG_OLLAMA_HOST"]
model = os.environ["ARDCONFIG_OLLAMA_MODEL"]

try:
    import ollama
except ImportError:
    print("DEPS_MISSING")
    sys.exit(0)

try:
    client = ollama.Client(host=host)
    resp = client.list()
except Exception:
    print("UNREACHABLE")
    sys.exit(0)


def _name(m):
    return getattr(m, "model", None) or getattr(m, "name", None) or ""


names = {_name(m) for m in resp.models}
target = model
match = target in names or (":" not in target and f"{target}:latest" in names)
print("OK" if match else "MODEL_MISSING")
PYEOF
  ) || status="UNREACHABLE"

  case "$status" in
    OK)
      output_step ok ollama_reachable "Ollama server reachable at ${host}; model '${model}' available"
      ;;
    MODEL_MISSING)
      output_step error ollama_reachable "Ollama server at ${host} is reachable but model '${model}' is not pulled. Run: ollama pull ${model}"
      output_result "$EXIT_PREREQ"
      exit "$EXIT_PREREQ"
      ;;
    DEPS_MISSING)
      output_step error ollama_reachable "Python 'ollama' package is not installed. Re-run ardconfig-onboard, or manually: ${venv}/bin/pip install 'ollama>=0.4.8,<1.0.0'"
      output_result "$EXIT_PREREQ"
      exit "$EXIT_PREREQ"
      ;;
    *)
      output_step error ollama_reachable "Ollama server unreachable at ${host}. Ensure the Ollama server is running and ARDCONFIG_OLLAMA_HOST is correct."
      output_result "$EXIT_PREREQ"
      exit "$EXIT_PREREQ"
      ;;
  esac
}
```

Design notes on this function (all load-bearing, not left to executor
judgment):

- **Mechanism (resolves OQ12):** the venv's `ollama` pip client
  (`ollama.Client(host).list()`), not `curl` (no precedent, R16) and not raw
  `urllib` (the `ollama` client is already required for the model backend
  itself when provider=ollama, so it is zero *additional* dependency
  footprint).
- **Why a heredoc with env-var pass-through instead of `python -c
  "...${host}..."` string interpolation** (unlike the existing
  `check_aws_credentials`'s `python -c` pattern): interpolating
  `ARDCONFIG_OLLAMA_HOST`/`ARDCONFIG_OLLAMA_MODEL` directly into a Python
  source string risks source injection if either value contains quotes.
  Passing them as environment variables and reading via `os.environ` inside
  the heredoc avoids that class of bug entirely. `check_aws_credentials`
  itself is intentionally left unchanged (out of scope, C20/NFR-8).
- **Three-way distinguishable status** (`OK` / `MODEL_MISSING` /
  `UNREACHABLE` / `DEPS_MISSING`) satisfies FR-27's requirement that
  server-unreachable and model-not-pulled produce different messages (R13).
  `DEPS_MISSING` is a defensive fallback that should be unreachable in the
  normal flow (`ensure_ai_deps` already guarantees the package is present
  before this function runs); it exists so a failure here is still
  attributable to the right layer if the JIT-install step is ever bypassed.
- **Model-name matching:** exact string match against each entry's name,
  with a fallback check for the `:latest`-tagged form when the configured
  model has no explicit tag (e.g. `ARDCONFIG_OLLAMA_MODEL=llama3` also
  matches an installed `llama3:latest`). The shipped default
  (`gpt-oss:latest`) already includes an explicit tag and matches exactly.
- **No automatic pull:** confirmed absent by design — `MODEL_MISSING` always
  exits 2 with `ollama pull <model>` guidance, never invokes `ollama pull`
  itself (NGO5, OQ15).
- **No explicit timeout** on `client.list()` — relies on the underlying
  HTTP client's default connect-timeout behavior (a non-listening local
  port fails near-instantly via connection-refused). Flagged in
  [Open Design Questions](#open-design-questions) as a "revisit if observed
  to hang" item rather than pre-emptively engineered (Pike Rule 1).
- **Discovery Needed:** the exact attribute name Ollama's typed `Model`
  response objects expose (`.model` vs. `.name`) should be confirmed once
  the `ollama` package is actually installed in a dev venv — this repo's
  `.venv` does not currently have it (JIT-installed only on first
  `ardconfig-onboard --provider ollama` run). The `_name()` helper above is
  written defensively to handle either attribute name so this is not a
  blocking ambiguity, but test-engineer should assert against the real
  installed package's response shape once available.

**`invoke_agent()` (AMENDED)** — pass the 3 new env vars through to the
Python subprocess, alongside the existing 2:

```bash
invoke_agent() {
  local venv="${ARDCONFIG_VENV_PATH:-.venv}"
  local agent_input
  agent_input=$(jq -n \
    --arg vid "$_ONBOARD_VENDOR_ID" \
    --arg pid "$_ONBOARD_PRODUCT_ID" \
    --arg name "$_ONBOARD_BOARD_NAME" \
    --arg model "${_SCAN_MODEL:-}" \
    '{vendor_id: $vid, product_id: $pid, board_name: $name, usb_model: $model}')

  output_step info agent "Invoking AI agent to research board..."

  local agent_output
  agent_output=$(echo "$agent_input" | \
    PYTHONPATH="$ARDCONFIG_ROOT" \
    ARDCONFIG_LLM_PROVIDER="${ARDCONFIG_LLM_PROVIDER:-}" \
    ARDCONFIG_BEDROCK_MODEL="${ARDCONFIG_BEDROCK_MODEL:-}" \
    ARDCONFIG_AWS_REGION="${ARDCONFIG_AWS_REGION:-}" \
    ARDCONFIG_OLLAMA_HOST="${ARDCONFIG_OLLAMA_HOST:-}" \
    ARDCONFIG_OLLAMA_MODEL="${ARDCONFIG_OLLAMA_MODEL:-}" \
    "${venv}/bin/python" -m agent.onboard_agent 2>/dev/null) || {
    output_step error agent "AI agent failed to execute"
    output_result "$EXIT_FAIL"
    exit "$EXIT_FAIL"
  }

  echo "$agent_output"
}
```

**`main()` ordering (AMENDED)** — the required order per the delegation
(cheap validation first, then deps, then provider branch):

```bash
main() {
  _SCAN_DEV=""
  _SCAN_MODEL=""

  parse_onboard_args "$@"
  if [[ "$ARG_HELP" == "true" ]]; then usage; exit 0; fi
  load_config
  output_init "$(get_output_format)" "$ARG_QUIET"

  resolve_llm_provider          # NEW — FR-25, cheap, before any dep work

  ensure_ai_deps                # FR-22 (provider-conditional ollama pkg)

  if [[ "$ARDCONFIG_LLM_PROVIDER" == "bedrock" ]]; then
    check_aws_credentials       # unchanged — FR-23
  else
    check_ollama_available      # NEW — FR-27
  fi

  # ... unchanged from here: input resolution, invoke_agent, handle_* ...
}
```

### 5. Bash ↔ Python JSON Contract

Unchanged by this delta (NFR-8). For reference:

**Input** (stdin to Python, JSON):
```json
{
  "vendor_id": "0483",
  "product_id": "374b",
  "board_name": "Nucleo-F411RE"
}
```

**Output** (stdout from Python, JSON):
```json
{
  "status": "success|failure|partial",
  "profile": { /* complete profile JSON */ },
  "error": "...",
  "raw": "..."
}
```

The provider selection is entirely internal to `create_agent()` and does not
appear in this contract — the bash wrapper never needs to know which
provider was used to interpret the agent's output.

### 6. Boundary Artifact Schemas

`spec/interfaces.json` (top-level keys):
- `version`: semver string.
- `modules`: object keyed by module path, each with:
  - `description`: string.
  - `public_exports`: array of `{name, kind (function|class|constant|type), signature}`.
  - `internal_only`: array of symbol-name strings.

`spec/module-boundaries.json` (top-level keys):
- `version`: semver string.
- `boundaries`: array of `{module, description, allowed_imports_from,
  forbidden_imports_from}`, where `module` and the two import-path arrays
  are module path prefixes within this repository.

See `spec/interfaces.json` and `spec/module-boundaries.json` (generated
alongside this document) for this feature's concrete values.

---

## Data Model & Storage

There is no database in this system. The relevant persisted artifacts are:

- **`profiles/*.json`** — the board profile schema (C6). **Unchanged by this
  delta** (NFR-8). `id` is the natural key; the file path
  `profiles/<id>.json` is the storage location. Idempotency is handled by
  the pre-existing conflict-detection flow (FR-17), unaffected here.
- **`conf/ardconfig.conf`** — a flat, declarative bash variable file, sourced
  (not parsed) by `load_config()`. No schema versioning; additive lines are
  backward compatible (an old copy of this file without the three new lines
  simply leaves those variables unset, which every read site treats
  identically to "explicitly empty" — see the precedence-bug callout above).
  No migration step is needed for existing installs.
- **`udev/99-arduino.rules`** — append-only rule file. Unaffected by this
  delta.

No new persisted state is introduced by the provider-selection feature
itself — `ARDCONFIG_LLM_PROVIDER` and friends are process-lifetime
configuration, read once per `ardconfig-onboard` invocation, never written
back to disk or cached.

**Irreversible changes:** none. This delta introduces no data migrations and
removes no existing API/field. The one behavior change that is irreversible
*in effect* (though trivially reversible *in configuration*) is the default
LLM provider flip from implicit-Bedrock to explicit-default-Ollama (R12) —
see [Rollout Plan](#rollout-plan).

---

## Concurrency, Ordering, and Consistency

`ardconfig-onboard` is a single short-lived synchronous process per
invocation; there is no concurrency internal to this feature:

- Bash → Python is one blocking subprocess call per run (`invoke_agent`
  waits for the Python process to exit before proceeding).
- The Strands `Agent.__call__` used in `main()` is itself synchronous from
  the caller's perspective (Strands manages any internal async streaming
  from the model provider).
- Ordering of prereq checks (`resolve_llm_provider` → `ensure_ai_deps` →
  provider-conditional check) is strictly sequential and each step can
  terminate the process — no interleaving to reason about.
- **No new shared mutable state.** `conf/ardconfig.conf` is read-only at
  runtime (never written by `ardconfig-onboard`). `profiles/` writes are
  guarded by the pre-existing conflict check (FR-17); this delta does not
  change that.
- **Two concurrent `ardconfig-onboard` invocations** (e.g. two terminals)
  could theoretically race on `profiles/<id>.json` writes — this is
  pre-existing behavior, unaffected by and out of scope for this delta
  (NFR-8).

No locks, transactions, or coordination mechanisms are introduced (see
[Simplicity Budget](#simplicity-budget)).

---

## Bounded Contexts & Context Map

### Context identification

There is exactly **one bounded context** relevant to this entire feature:
**Board Onboarding** (a sub-context of the broader "ardconfig toolchain"
domain, which itself is not being redesigned here). The ubiquitous language
within this context: *Board Profile*, *FQBN*, *Core*, *Board Manager URL*,
*Unknown Device*, *Prerequisite Check*, *Human-in-the-loop Confirmation*.

**LLM Provider selection does not introduce a new bounded context.** The
test for a context boundary is "does the ubiquitous language change, or does
the same concept get modeled differently on each side?" Here it does not:
both branches of `create_agent()` produce the exact same downstream
artifact — a `strands.Agent` object consumed identically by the rest of
`main()` — using the exact same tools, system prompt, and profile schema.
"Provider" is a **configuration/strategy selection within one context**, not
a domain concept with its own aggregate lifecycle or persistence. Treating
it as a separate context (e.g. a "Bedrock Integration" context and an
"Ollama Integration" context) would be infrastructure-driven splitting, not
domain-driven — explicitly the anti-pattern this template warns against.

**Terminology note:** `spec/context.md`'s glossary already flags that
"provider" is overloaded in this domain — "LLM provider" (`bedrock`/`ollama`,
this delta) is unrelated to "board manager"/USB "vendor" terminology used
elsewhere in the same codebase. This design consistently uses "LLM provider"
or just "provider" only in the `ARDCONFIG_LLM_PROVIDER` context to avoid
compounding that ambiguity.

### Aggregate inventory

- **Board Profile** (`id` = identity, `profiles/<id>.json` = persistence) is
  the only domain aggregate in this context. Unaffected by this delta.
- **LLM Model backend** (the constructed `BedrockModel`/`OllamaModel`
  instance) has no aggregate identity — it is process-lifetime
  configuration object, not domain data with invariants to protect across
  transactions.

### Context map (external system relationships)

| External system | Relationship pattern | Notes |
|---|---|---|
| Amazon Bedrock | **Open Host Service**, consumed through an **Anti-Corruption Layer** | The ACL is `strands.models.bedrock.BedrockModel` (third-party, from the Strands SDK) — it translates Strands' uniform message/tool-call format to/from Bedrock's Converse API. ardconfig's own code only selects and configures this ACL (model_id, region); it does not implement translation logic itself. |
| Local Ollama server | **Open Host Service**, consumed through an **Anti-Corruption Layer** | Same pattern: `strands.models.ollama.OllamaModel` is the ACL, translating to/from Ollama's chat API. ardconfig's own code selects and configures it (host, model_id). |
| `arduino-cli`, web search, `bin/ardconfig-setup`, `bin/ardconfig-verify` | Pre-existing, unaffected by this delta | Already documented in the pre-delta design; not re-litigated here (NFR-8 keeps `agent/tools.py` unmodified). |

Both LLM-provider ACLs live in third-party code (the Strands SDK), not in
`ardconfig`'s own tree — `create_agent()`'s job is purely **ACL selection
and configuration**, not ACL implementation. This is why FR-28's lazy-import
constraint matters: selecting the wrong ACL's import eagerly would force an
unwanted dependency (`ollama` pip package) onto the `bedrock`-only path, an
ACL-selection leak across the context boundary.

---

## Communication Topology

Given the scale of this feature (≤1 request per `ardconfig-onboard`
invocation to each external system, interactive human-driven tool, no
sustained throughput), the reactive-architecture concerns below are answered
plainly rather than engineered for:

| Boundary | Pattern | Justification for synchronous coupling | Back-pressure needed? |
|---|---|---|---|
| bash `bin/ardconfig-onboard` → Python `agent/onboard_agent.py` | Synchronous subprocess call, stdin/stdout JSON | The bash wrapper must block for the result to display it, get human confirmation (FR-16), and decide exit code — this is the entire point of the human-in-the-loop invariant (G5). One call per run. | No — single request, far below the 100/sec threshold that would require it. |
| Python agent → Amazon Bedrock | Synchronous (from the Strands `Agent.__call__` caller's perspective) HTTPS request/response, AWS SDK | LLM chat completion is inherently request/response; the agent needs the model's response before deciding its next tool call. Unchanged from pre-delta (C20). | No. |
| Python agent → local Ollama server | Synchronous HTTP request/response via the `ollama` client | Same reasoning as Bedrock. | No. |
| `check_aws_credentials` / `check_ollama_available` → AWS STS / Ollama server | Synchronous, one-shot prereq probe | Must complete (or fail fast) before the agent is invoked at all — this *is* the fail-fast contract (FR-23, FR-27). | No. |

**Failure isolation:** each boundary above fails independently and
visibly — a prereq-check failure never reaches the agent process at all (the
bash wrapper exits 2 first); an Ollama/Bedrock call failure inside the agent
is caught by Strands' own retry/error surface and, at the ardconfig level,
by the pre-existing FR-21 iteration logic (unaffected by this delta,
NFR-8). There is no cascading-failure risk to isolate against, because there
is no shared mutable state or long-lived connection between boundaries.

**Recovery strategy:** none beyond "the user re-runs the command." There is
no persistent queue, event log, or supervisor process to replay from — this
is consistent with the pre-delta design and with NG2 ("no persistent
service or daemon").

**Elasticity:** not applicable. This is a single-instance, on-demand CLI
invocation; there is no unit of horizontal scaling to identify.

---

## Failure Modes & Recovery

### Agent Retry Logic (FR-21, unchanged, NFR-8)

The agent has a retry budget of **2 additional attempts** after the initial
try, triggered by `ardconfig-setup`/`ardconfig-verify` failures. Unaffected
by provider selection — retry logic lives inside the agent's system prompt
and tool-use loop, which this delta does not touch.

### Failure Modes Table (AMENDED — new provider-related rows)

| Failure | Exit Code | Behavior |
|---|---|---|
| `ARDCONFIG_LLM_PROVIDER` invalid value | 2 | Fail fast in `resolve_llm_provider()`, before any dependency work; message names the offending value (FR-25) |
| No Python venv | 2 | Fail fast, suggest `ardconfig-setup` |
| AI deps install fails (strands-agents/boto3, or `ollama` pkg if provider=ollama) | 2 | Fail fast, show pip error; message distinguishes this from prereq-check failures (R13) |
| No AWS credentials (provider=bedrock only) | 2 | Fail fast, show credential setup instructions (FR-23, unchanged) |
| Bedrock API error (provider=bedrock) | 1 | Report error, suggest checking model access (unchanged) |
| Ollama server unreachable (provider=ollama) | 2 | Fail fast, message distinguishable from model-not-pulled and from dependency-install failure (FR-27, R13) |
| Ollama model not pulled (provider=ollama) | 2 | Fail fast, message instructs `ollama pull <model>`; no automatic pull (FR-27, NGO5) |
| No unknown USB devices | 3 | Report "no unknown hardware found" (unchanged) |
| AI can't identify board | 4 | Output partial template with TODO fields, suggest Kiro (FR-24, unchanged) |
| Profile validation fails | 1 | Agent retries; if exhausted, report validation error (unchanged) |
| Setup fails after retries | 4 | Profile written but setup incomplete (unchanged) |
| Verify fails after retries | 4 | Profile written, core installed, but verify failed (unchanged) |
| Profile ID conflict | — | Prompt user for override (FR-17, unchanged) |

**Degraded modes:** there is no degraded/partial mode for provider
selection itself — an invalid or unreachable provider is always a hard
fail-fast (exit 2), consistent with FR-23's pre-existing pattern for
Bedrock. This is appropriate at this scale (a single local dev tool, not a
service with graceful-degradation SLOs) — circuit breakers or fallback
providers are explicitly rejected (NGO4; see
[Rejected Abstractions](#rejected-abstractions)).

---

## Security Model

Unchanged from the pre-delta design (NFR-4), with the following additions
relevant to this delta:

- **AWS credentials** (provider=bedrock): never logged, echoed, or written
  to files. Uses boto3's default credential chain. Unchanged.
- **Ollama has no credential surface.** The local Ollama server (default
  `http://localhost:11434`) has no authentication in this design. `ARDCONFIG_OLLAMA_HOST`
  is logged as part of the `ollama_reachable` step message — this is safe
  per NFR-4 because a host/URL is not a secret (context.md §12.8 already
  confirms this).
- **Remote Ollama hosts:** if `ARDCONFIG_OLLAMA_HOST` is pointed at a
  non-localhost server, this becomes the first non-AWS, non-board-manager
  network dependency this tool has. This design does not add a warning for
  non-TLS remote hosts — flagged as an [Open Design Question](#open-design-questions),
  out of scope for this pass (no requirement calls for it; NGO5 keeps
  Ollama server management itself out of scope).
- **Injection defense in the new reachability check:** `check_ollama_available()`
  deliberately passes `ARDCONFIG_OLLAMA_HOST`/`ARDCONFIG_OLLAMA_MODEL` into
  the Python heredoc via explicit environment-variable assignment and reads
  them with `os.environ[...]` inside the script, rather than interpolating
  their values into the Python source text. This closes a source-injection
  surface that a naive `python -c "...${host}..."` approach would open if
  either value ever contained quote characters (see the design note in
  [Public Interfaces §4](#4-binardconfig-onboard-bash-function-interface)).
- **File write restriction, subprocess argument-list execution, udev
  sudo pattern:** all unchanged (pre-delta design §8), untouched by this
  delta (NFR-8 — `agent/tools.py` is not modified).

---

## Observability

Consistent with the existing `[OK]`/`[WARN]`/`[ERROR]`/`[INFO]` step-tag
convention (`lib/output.sh`):

- New step names: `llm_provider` (from `resolve_llm_provider()`),
  `ollama_reachable` (from `check_ollama_available()`), parallel to the
  existing `aws_creds`, `deps`, `venv` step names.
- `--json` output gains these as additional entries in the existing `steps`
  array — no schema change to the JSON envelope itself (`status`,
  `exit_code`, `steps` fields, per NFR-3).
- No new remote telemetry. Ollama calls stay local by default; if
  `ARDCONFIG_OLLAMA_HOST` is pointed at a remote server, the selected
  provider and host are logged (not a secret, see Security Model above).
- **What to measure post-rollout:** which provider is actually selected in
  practice (via aggregating `llm_provider` step messages if any log
  aggregation exists — none does today, this is a manual/support-request
  signal only, consistent with "no remote telemetry" for this local dev
  tool), and whether `ollama_reachable` failures are common enough to
  warrant relaxing the fail-fast default (feeds back into R12/R14 risk
  tracking, not an automated dashboard).

No dashboards or automated alerts are introduced — this is a local CLI tool
with no fleet to monitor, consistent with the pre-delta design's "no remote
telemetry" stance (context.md §8).

---

## Rollout Plan

- **Breaking change in default *behavior*, not in CLI surface, flags, or
  exit-code shape.** Callers that do not set `ARDCONFIG_LLM_PROVIDER` move
  from Bedrock to Ollama (R12). This is the single highest-risk item in this
  delta.
- **No new feature flag** beyond `ARDCONFIG_LLM_PROVIDER` itself, which
  doubles as the opt-back-in mechanism (`=bedrock`).
- **Staged rollout:**
  1. Land the code changes (this design's four modified files).
  2. Update `README.md` with a **prominent** callout of the default flip —
     this repo has no `CHANGELOG.md`; recommend docs-release either add one
     or place a clearly-marked "Breaking default change" note at the top of
     the `ardconfig-onboard` README section (see
     [README.md target sections](#readmemd-target-sections) below).
  3. No canary/percentage rollout mechanism applies — this is a
     locally-run CLI tool, not a deployed service; "rollout" here means
     "the next `git pull`."
- **Backout:** two options, in order of preference:
  1. Zero-code-change backout: set `ARDCONFIG_LLM_PROVIDER=bedrock` (env
     var or `conf/ardconfig.conf`) — fully reverts runtime behavior.
  2. Full revert: `git revert` this delta's commit(s). No data migration to
     undo (Data Model & Storage section confirms no irreversible storage
     change).
- **New dependency:** `ollama` PyPI package, JIT-installed only when
  provider=ollama (C17, C22). `boto3` behavior is unaffected (C18).

### README.md target sections

Executor/docs-release should update (line numbers as observed during this
design pass on the current `README.md`; confirm exact numbers at
implementation time, they will have drifted):

| Section | Current line(s) | Change needed |
|---|---|---|
| `### ardconfig-onboard` intro paragraph | ~93 | Currently: *"a Strands AI agent (backed by Amazon Bedrock)"* → describe provider-conditional backend, default `ollama` |
| `### ardconfig-onboard` "What it does" step 2 | ~104 | Mention the LLM backend is provider-selected (`ARDCONFIG_LLM_PROVIDER`) |
| `### ardconfig-onboard` "**Prerequisites:**" line | ~111 | Replace with provider-conditional prerequisites: default (`ollama`) needs a local Ollama server + the configured model pulled; `ARDCONFIG_LLM_PROVIDER=bedrock` needs AWS credentials with Bedrock access. AI deps (`strands-agents`, `boto3`, and `ollama` when provider=ollama) installed automatically on first use. |
| `### conf/ardconfig.conf` config block | ~240–247 | Add `ARDCONFIG_LLM_PROVIDER`, `ARDCONFIG_OLLAMA_HOST`, `ARDCONFIG_OLLAMA_MODEL` rows; annotate `ARDCONFIG_BEDROCK_MODEL`/`ARDCONFIG_AWS_REGION` as "(provider=bedrock only)" |
| Project Structure tree, `agent/` comment | ~300 | `# Python AI agent (Strands AI + Bedrock)` → `# Python AI agent (Strands AI: Bedrock or Ollama)` |
| Exit Codes table (~176–186) | — | No change recommended — this table is intentionally generic across all scripts; `ardconfig-onboard --help`'s own heredoc (updated above) carries the onboard-specific detail, matching the existing convention where other scripts' code-2 nuances also aren't spelled out in this shared table. |
| New: default-flip callout | n/a (new content) | Recommend a short, clearly-marked note near the top of the `ardconfig-onboard` section flagging the default provider change for existing callers (R12) |

Full prose is docs-release's/executor's to write; this table constrains
*what* must change, not the exact wording.

---

## Alternatives Considered

Each alternative below is scored against: Domain fit, Scale profile,
Simplicity assessment, Data structure choice — per the design template.
A1–A6 are carried forward from the pre-delta design (retrofitted with the
four required sub-points); A7–A11 are new to this delta.

### A1: Pure Python implementation (no bash wrapper)

**Rejected.** *Domain fit:* poor — a Python-only entry point would speak a
different ubiquitous language (argparse conventions) than the rest of the
`bin/*` scripts, which all share one CLI/output/exit-code convention.
*Scale profile:* N/A — single-invocation CLI tool, no load profile applies
at any multiple. *Simplicity:* actually less simple system-wide: either
duplicate `output.sh`/`common.sh` conventions in Python, or accept an
inconsistent CLI surface. *Data structure:* N/A (organizational choice, not
a data-shape choice).

### A2: Integrate onboarding into `ardconfig-detect`

**Rejected.** *Domain fit:* poor — "detect" (fast, read-only observation)
and "onboard" (slow, stateful, human-confirmed, file-writing) are different
verbs in this domain's ubiquitous language; conflating them blurs a real
responsibility boundary. *Scale profile:* N/A. *Simplicity:* splitting is
simpler per-script (detect stays fast/side-effect-free); merging would
complicate `ardconfig-detect`'s flag surface and exit-code semantics.
*Data structure:* N/A.

### A3: Use LangChain instead of Strands AI SDK

**Rejected.** User specified Strands AI SDK (C2). *Domain fit:* N/A (SDK
choice). *Scale profile:* both frameworks trivially handle this tool's
request volume (≪1 req/sec) at any realistic multiple. *Simplicity:*
Strands is lighter-weight for this specific need (built-in
Bedrock/Ollama/tool-use support) — fewer transitive dependencies than
LangChain's broader surface. *Data structure:* N/A.

### A4: Reimplement profile validation in Python

**Rejected.** Duplicates logic (OQ10). *Domain fit:* would create two
sources of truth for "profile validity," a domain invariant, across two
languages — poor fit. *Scale profile:* N/A. *Simplicity:* superficially
simpler (no subprocess call) but risks long-term schema drift between the
two copies. *Data structure:* the profile JSON schema is already the shared
structure; subprocess-calling the existing bash validator against that same
file reuses it directly (Pike Rule 5) instead of parallel-modeling it.

### A5: Agent writes the profile directly, no bash-wrapper confirmation

**Rejected.** Violates the human-in-the-loop invariant (G5, FR-16). *Domain
fit:* poor — "proposed profile" vs. "confirmed profile" are meaningfully
different states in this domain; skipping confirmation erases that
distinction. *Scale profile:* N/A. *Simplicity:* fewer moving parts, but
this drops a required safety invariant rather than simplifying its
implementation — not a valid trade. *Data structure:* N/A.

### A6: Store agent tools as separate script files instead of `tools.py`

**Rejected.** *Domain fit:* N/A (packaging choice). *Scale profile:* N/A —
6 tool functions; would hold even at a couple dozen tools, matching
Strands' own single-module convention. *Simplicity:* one file with
`@tool`-decorated functions is simpler than N files for 6 tools.
*Data structure:* N/A.

### A7: Keep Bedrock as the default; Ollama as pure opt-in

**Rejected — explicitly, at Gate 0, by the user** (C14, GO1), despite R12's
acknowledged blast-radius risk. *Domain fit:* neutral either way — doesn't
touch context boundaries. *Scale profile:* N/A — this is a default-value
choice, not an architectural one; irrelevant at any load multiple.
*Simplicity:* equally simple as the chosen design; this alternative differs
only in which value ships as the default, not in mechanism. *Data
structure:* N/A. Documented here because it's the most consequential
"simpler-seeming" alternative and its rejection is a deliberate, approved
risk acceptance, not an oversight.

### A8: Provider-strategy class hierarchy (`LLMProviderAdapter` base class + subclasses + registry)

**Rejected.** *Domain fit:* neutral — doesn't change context boundaries
either way. *Scale profile:* not a runtime-load concern; "would this break
at 10x providers?" doesn't apply because NGO1 explicitly caps scope to
exactly 2 providers for the realistic planning horizon. *Simplicity:* a
plain `if/elif` in a ~30-line function is simpler than a class hierarchy +
registry for exactly 2 cases. *Data structure:* the provider selector is
just one of two string literals (`"bedrock"`/`"ollama"`) — an `if/elif` on
that string **is** the self-evident structure (Pike Rule 5); a class
hierarchy would hide this behind unnecessary indirection.

### A9: Auto-detect available provider at runtime (try Ollama, fall back to Bedrock, or vice versa)

**Rejected — explicitly, per NGO4.** *Domain fit:* N/A. *Scale profile:*
N/A. *Simplicity:* actually less simple — requires a runtime probe +
fallback state machine, and produces non-deterministic behavior across runs
of the same command, directly contradicting the "explicit, single-valued
per run" goal (GO1/GO2). *Data structure:* this alternative has no
self-evident data structure — that's part of why it's worse: it replaces an
explicit config value with implicit runtime discovery.

### A10: `curl`-based HTTP reachability check (new system dependency)

**Rejected — per R16/C16.** No existing `curl`/`wget` usage anywhere in
this codebase (confirmed via grep across all `*.sh` files at spec time).
*Domain fit:* N/A (infra choice). *Scale profile:* N/A. *Simplicity:* adds
a **new** external system dependency purely for a check the `ollama` pip
client (already required for the model backend itself) already provides —
strictly less simple than the chosen design. *Data structure:* N/A.

### A11: Auto-pull the missing Ollama model instead of failing

**Rejected — per NGO5/OQ15.** *Domain fit:* N/A. *Scale profile:* the
"load" here is data volume, not request rate — Ollama models range from a
few hundred MB to tens of GB; a silent multi-GB download is a realistic
failure mode that would blow past NFR-7's 5-minute onboarding budget on a
typical connection. *Simplicity:* superficially more convenient, but
introduces a hidden, large, state-changing side effect that undermines the
human-in-the-loop transparency principle (G5) — rejected on
safety/predictability grounds, not just complexity. *Data structure:* N/A.

---

## Open Design Questions

| # | Question | Status / Recommendation |
|---|---|---|
| OQ12 (context.md) | What mechanism should the Ollama reachability check use? | **Resolved by this design:** venv Python + the `ollama` pip client (`ollama.Client(host).list()`), via a heredoc with env-var pass-through — see [Public Interfaces §4](#4-binardconfig-onboard-bash-function-interface). |
| New-1 | Exact attribute name on Ollama's typed `Model` response objects (`.model` vs. `.name`) | Not blocking — `check_ollama_available()`'s `_name()` helper handles both. Confirm empirically once `ollama` is JIT-installed in a real venv; test-engineer should assert against it directly. |
| New-2 | Should `ardconfig-onboard` warn/refuse when `ARDCONFIG_OLLAMA_HOST` is a non-localhost, non-TLS endpoint? | Left unresolved, out of scope for this pass — no requirement calls for it and NGO5 keeps Ollama server/network management out of scope. Flag for a future requirements pass if remote-Ollama usage becomes common. |
| New-3 | Should the config-precedence bug fix (see [Public Interfaces §2](#2-environment-variables--confardconfigconf-schema)) be split into a separate corrective-requirements packet per `CLAUDE.md`'s regression/corrective-mode process, rather than bundled inline with FR-26's implementation? | **Recommendation:** bundle it inline — it's required for FR-26's own acceptance criteria to be satisfiable, and splitting it would leave FR-26 undeliverable in the interim. Flag explicitly at Gate 3/4 review for the orchestrator/user to confirm this reasoning. |
| New-4 | Should `check_ollama_available()`'s `client.list()` call have an explicit timeout? | Not added in this pass (Pike Rule 1 — don't pre-engineer for a bottleneck not yet observed). Revisit if real-world hangs (vs. fast connection-refused) are reported. |
| Carried: R14 (context.md) | Local Ollama models (e.g. `gpt-oss:latest`) may be materially less reliable than Bedrock's Claude models at structured JSON output and multi-step tool-calling; no AC in this delta tests Ollama's actual board-identification accuracy. | Not a design blocker — hand to test-engineer/eval-engineer as a golden-test-parity concern (Nucleo-F411RE profile quality, both providers) for the verification phase. |

---

## Simplicity Budget

- **New modules:** 0. This delta edits exactly four existing files
  (`bin/ardconfig-onboard`, `agent/onboard_agent.py`, `conf/ardconfig.conf`,
  `README.md`) and creates no new ones.
- **New public interfaces:** 2 new bash functions
  (`resolve_llm_provider`, `check_ollama_available`), both internal to
  `bin/ardconfig-onboard` (not sourced by any other script). 0 new Python
  public functions — `create_agent()`'s signature (`() -> Agent`) is
  unchanged; only its body changes.
- **Dependency addition policy:** 1 new dependency, the `ollama` PyPI
  package (`>=0.4.8,<1.0.0` per C22), JIT-installed **only** when
  `provider=ollama` (GO4) — no new dependency on the `bedrock` path, no new
  system-level (`apt`) dependency at all.
- **Required "do nothing / smaller change" alternative:**
  - *Do nothing:* don't add Ollama support at all — rejected; this is the
    explicit Gate-0-approved objective of the entire delta (GO1).
  - *Smaller change evaluated:* unconditionally swap `BedrockModel` for
    `OllamaModel` with no provider switch at all — rejected, because it
    would break every existing CI/agent caller relying on Bedrock (UC5)
    with no opt-back-in path. The provider switch (`ARDCONFIG_LLM_PROVIDER`)
    is the minimum mechanism that satisfies both "local-first default"
    (GO1) and "preserve the Bedrock path" (GO2) simultaneously — it is not
    extra machinery beyond what's required.
- **Bounded context count:** 1 (see
  [Bounded Contexts & Context Map](#bounded-contexts--context-map)) — this
  delta does not add a context. Well within the ≤5-context Conway's-Law
  guardrail for a project maintained by well under 3 teams.
- **Coordination mechanism count:** 0. No locks, transactions, sagas, or
  consensus protocols are introduced — the provider branch is a plain
  conditional, not a coordination mechanism, and there is no aggregate
  invariant spanning two provider paths to protect.
- **Modular-monolith re-evaluation trigger:** not applicable — this
  design has 1 bounded context and 0 coordination mechanisms, both well
  under the ">3 contexts or >2 coordination mechanisms" threshold that
  would trigger a mandatory monolith-alternative evaluation. This already
  *is* a single-process modular structure; stated explicitly rather than
  silently skipped.

---

## Rejected Abstractions

- **Provider-strategy class hierarchy** (`LLMProviderAdapter` base class +
  `BedrockAdapter`/`OllamaAdapter` subclasses + a registry/dict dispatch) —
  see A8. Rejected: a plain `if/elif` on a 2-valued string is the
  self-evident structure at this scale (Pike Rule 5).
- **Generic `LLMProviderConfig` dataclass/TypedDict** wrapping the 5 env
  vars — rejected: inline `os.environ.get(...) or default` reads at the
  point of use match the pre-existing code's own style (FR-11/FR-12's
  original implementation did the same); a wrapper type adds a layer
  between "env var" and "value used" with no behavioral benefit at 5
  variables / 2 branches.
- **A provider registry/plugin loader** auto-discovering arbitrary
  `strands.models.*` providers via their `__getattr__` lazy-loader —
  rejected: NGO1 explicitly caps scope to exactly `bedrock`/`ollama`;
  building a generic N-provider registry now is speculative generality with
  no requirement driving it (YAGNI).
- **A `check_llm_prereqs()` dispatcher function** wrapping the
  `check_aws_credentials`/`check_ollama_available` branch — rejected:
  `main()` already reads as a linear step sequence; wrapping a 4-line
  if/else in an extra function adds indirection for no readability gain at
  this call-site count (one).
- **`curl`/raw-`urllib`-based reachability probe** — see A10. Rejected in
  favor of the already-required `ollama` pip client.
- **Automatic cross-provider fallback** — see A9. Rejected per NGO4.
- **Automatic `ollama pull`** — see A11. Rejected per NGO5/OQ15.

---

## Verification Strategy

**Discovery Needed:** this repository currently has **no test framework or
test directory at all** (`tests/`, `pyproject.toml`, `requirements*.txt` were
all absent as of this design pass). The pre-delta onboarding feature's
acceptance criteria (AC-001–009) are, per `spec/requirements.md`, verified
manually ("Testable:" descriptions, not automated tests). Test-engineer will
need to decide whether to introduce a framework (e.g. `pytest` for
`agent/`, `bats`/`shellspec` or hand-rolled assertions for `bin/*`) as part
of closing out this delta — that decision is out of scope for this design
document but is a prerequisite for automating anything below.

### Requirement → verification mapping

| Requirement | Verification approach |
|---|---|
| FR-25 (provider selection & validation) | Unit: `create_agent()` with `ARDCONFIG_LLM_PROVIDER` unset defaults to the `ollama` branch (assert `OllamaModel` constructed, no AWS SDK calls); `=bedrock` constructs `BedrockModel`; invalid value raises `ValueError`. Integration: `ARDCONFIG_LLM_PROVIDER=nonsense bin/ardconfig-onboard` → exit 2, output names `"nonsense"`, and the `--json` step list contains only the failed `llm_provider` step (proving `ensure_ai_deps`/prereq checks never ran). |
| FR-26 (Ollama connection config) | Unit: default host/model used when unset; overridden via env var *and* via `conf/ardconfig.conf` (this must specifically regression-test the config-precedence fix — see below). |
| FR-27 (Ollama reachability/model check) | Integration against a local mock/stub Ollama HTTP endpoint: (a) nothing listening → exit 2, "unreachable" message; (b) listening but model absent from `/api/tags`-equivalent → exit 2, message contains `ollama pull <model>`, and assert no `ollama pull` subprocess was ever invoked; (c) listening with model present → proceeds past the check. |
| FR-28 (lazy import) | The literal AC-016 regression test: in a venv with `strands-agents` installed but **without** the `ollama` pip package, run (or directly call) `create_agent()` with `provider=bedrock` and assert no `ModuleNotFoundError`. Needs either a dedicated venv fixture without the `ollama` extra, or `sys.modules['ollama'] = None`-style mocking — flag this test-harness design to test-engineer explicitly. |
| FR-22 (amended, JIT deps) | Assert `ollama` package installed when provider=ollama and missing; assert **not** attempted when provider=bedrock (AC-014). `boto3`/`strands-agents` checks unaffected — regression only. |
| FR-23 (amended, provider-conditional) | AC-011 regression: provider=bedrock behavior identical to pre-delta. New: provider=ollama skips `check_aws_credentials` entirely — assert no `aws_creds` step appears in `--json` output and no AWS SDK call is made. |
| NFR-8 (scope boundary) | Snapshot/diff test: `agent/tools.py` and the `SYSTEM_PROMPT` constant in `agent/onboard_agent.py` must be byte-identical before/after this delta's implementation. This should be an automated check (e.g. a checksum or git-diff assertion in CI), not just manual review at code-review time. |
| Config precedence fix (unlabeled by any single FR, discovered during design) | New, explicit test: set `ARDCONFIG_OLLAMA_MODEL=custom-model` as an environment variable with `conf/ardconfig.conf`'s placeholder line present and unmodified; assert the agent receives `custom-model`, not the hardcoded default. Repeat for `ARDCONFIG_BEDROCK_MODEL` as a **regression** test (this variable was silently broken pre-delta — see Public Interfaces §2). |
| AC-001–AC-011 (regression) | Re-run the existing Nucleo-F411RE golden-path flow under `provider=bedrock` end-to-end to confirm zero behavior change. This regression surface is **elevated risk** in this delta specifically because the config-precedence fix touches `create_agent()`'s Bedrock branch too (even though its *external* behavior should be unchanged or strictly more-correct) — call this out to test-engineer as the single highest-priority regression check. |

---
