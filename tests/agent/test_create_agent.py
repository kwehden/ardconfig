"""Unit tests for agent.onboard_agent.create_agent()'s provider branch.

Covers TASK-016's 6 provider-branching/precedence items:
  1. provider unset -> ollama branch, no Bedrock/boto3 touched
  2. provider=bedrock -> bedrock branch, no Ollama touched
  3. provider=nonsense -> ValueError naming the bad value
  4. AC-016/FR-28: provider=bedrock never needs the `ollama` package
  5. config-precedence fix: non-empty env vars are honored (both branches)
  6. config-precedence fix: empty-string env vars fall back to defaults,
     they do NOT get treated as "set to empty" (both branches)

Requirements: FR-25, FR-26, FR-28/AC-016, FR-11/FR-12 (regression).
NFR-8's byte-identical scope-boundary check lives in a separate file,
test_nfr8_scope_boundary.py, so it isn't tangled up with provider-branch
assertions.

None of these tests make a real network call, AWS SDK call, or Ollama
HTTP call: create_agent()'s lazily-imported BedrockModel/OllamaModel
classes are monkeypatched with lightweight recording stand-ins before
create_agent() runs (per design.md's Verification Strategy: "mock the
lazy import; no real Ollama/AWS call"), except in the AC-016 test, whose
entire purpose is to prove the *unmocked* import chain doesn't require
the `ollama` package on the provider=bedrock path.
"""
import sys

import pytest


ENV_VARS_UNDER_TEST = (
    "ARDCONFIG_LLM_PROVIDER",
    "ARDCONFIG_BEDROCK_MODEL",
    "ARDCONFIG_AWS_REGION",
    "ARDCONFIG_OLLAMA_HOST",
    "ARDCONFIG_OLLAMA_MODEL",
)


@pytest.fixture(autouse=True)
def clean_provider_env(monkeypatch):
    """Ensure no ambient ARDCONFIG_LLM_PROVIDER/* leaks between tests or
    from the invoking shell."""
    for var in ENV_VARS_UNDER_TEST:
        monkeypatch.delenv(var, raising=False)


class _RecordingModel:
    """Stand-in for BedrockModel/OllamaModel: records constructor kwargs
    instead of building a real AWS/Ollama client."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _ForbiddenModel:
    """Stand-in that fails the test immediately if constructed — used to
    assert the *other* provider's model class is never touched."""

    def __init__(self, **kwargs):
        raise AssertionError(
            f"This model class must not be constructed on this branch (kwargs={kwargs!r})"
        )


class _RecordingAgent:
    """Stand-in for strands.Agent: records what create_agent() passed to
    it instead of constructing a real Agent (which validates/introspects
    `model` attributes like `.stateful` that our lightweight
    `_RecordingModel` stand-in intentionally doesn't implement).

    This decouples these tests from strands.Agent's internal constructor
    requirements entirely — we only care what create_agent() *passes to*
    Agent(...), not what a real Agent does with it.
    """

    def __init__(self, *, model, system_prompt, tools, callback_handler):
        self.model = model
        self.system_prompt = system_prompt
        self.tools = tools
        self.callback_handler = callback_handler


def _import_agent_module():
    # Imported lazily (inside test bodies / fixtures) rather than at
    # module top-level so that test collection itself never forces
    # strands.models.ollama to be imported ahead of the AC-016 test.
    from agent import onboard_agent

    return onboard_agent


@pytest.fixture
def stub_agent_class(monkeypatch):
    """Autoused implicitly by every fixture below that stubs a model
    class — see stub_bedrock/stub_ollama. Not @pytest.fixture(autouse=True)
    at module scope because test_ac016_... deliberately wants the *real*
    Agent + real BedrockModel (see that test's docstring)."""
    onboard_agent = _import_agent_module()
    monkeypatch.setattr(onboard_agent, "Agent", _RecordingAgent)


@pytest.fixture
def stub_bedrock(monkeypatch, stub_agent_class):
    import strands.models.bedrock as bedrock_mod

    monkeypatch.setattr(bedrock_mod, "BedrockModel", _RecordingModel)
    return bedrock_mod


@pytest.fixture
def stub_ollama(monkeypatch, stub_agent_class):
    import strands.models.ollama as ollama_mod

    monkeypatch.setattr(ollama_mod, "OllamaModel", _RecordingModel)
    return ollama_mod


@pytest.fixture
def forbid_bedrock(monkeypatch):
    import strands.models.bedrock as bedrock_mod

    monkeypatch.setattr(bedrock_mod, "BedrockModel", _ForbiddenModel)


@pytest.fixture
def forbid_ollama(monkeypatch):
    import strands.models.ollama as ollama_mod

    monkeypatch.setattr(ollama_mod, "OllamaModel", _ForbiddenModel)


# --- Item 1: unset provider defaults to ollama, never touches Bedrock ----


def test_unset_provider_defaults_to_ollama(stub_ollama, forbid_bedrock):
    onboard_agent = _import_agent_module()

    agent = onboard_agent.create_agent()

    assert isinstance(agent.model, _RecordingModel)
    assert agent.model.kwargs == {
        "host": "http://localhost:11434",
        "model_id": "gpt-oss:latest",
    }
    assert agent.callback_handler is None, (
        "create_agent() must pass callback_handler=None so Strands' default "
        "callback handler never writes tool-trace lines to stdout, which "
        "would corrupt main()'s json.dump(..., sys.stdout) output contract "
        "(regression guard for the stdout-pollution bug found in spec/evals.md)"
    )


# --- Item 2: provider=bedrock constructs BedrockModel, never touches Ollama


def test_bedrock_provider_constructs_bedrock_model(monkeypatch, stub_bedrock, forbid_ollama):
    monkeypatch.setenv("ARDCONFIG_LLM_PROVIDER", "bedrock")
    onboard_agent = _import_agent_module()

    agent = onboard_agent.create_agent()

    assert isinstance(agent.model, _RecordingModel)
    assert agent.model.kwargs == {
        "model_id": "us.anthropic.claude-sonnet-4-6",
        "region_name": "us-west-2",
    }
    assert agent.callback_handler is None, (
        "provider=bedrock must also suppress Strands' default stdout "
        "callback handler (the bug is provider-agnostic, see spec/evals.md)"
    )


def test_ollama_provider_explicit_matches_default(monkeypatch, stub_ollama, forbid_bedrock):
    monkeypatch.setenv("ARDCONFIG_LLM_PROVIDER", "ollama")
    onboard_agent = _import_agent_module()

    agent = onboard_agent.create_agent()

    assert isinstance(agent.model, _RecordingModel)
    assert agent.model.kwargs == {
        "host": "http://localhost:11434",
        "model_id": "gpt-oss:latest",
    }


# --- Item 3: invalid provider raises ValueError naming the bad value -----


def test_invalid_provider_raises_value_error(monkeypatch):
    monkeypatch.setenv("ARDCONFIG_LLM_PROVIDER", "nonsense")
    onboard_agent = _import_agent_module()

    with pytest.raises(ValueError, match="nonsense"):
        onboard_agent.create_agent()


# --- Item 4: AC-016/FR-28 — provider=bedrock must not require `ollama` ---


def test_ac016_bedrock_path_does_not_require_ollama_package(monkeypatch):
    """Regression test for FR-28/AC-016.

    Simulates the `ollama` pip package being absent via a sys.modules
    trick (`sys.modules['ollama'] = None` makes any subsequent
    `import ollama` raise ImportError) rather than relying on the ambient
    venv's actual package set, per design.md's explicit fallback guidance
    — this keeps the regression guard valid even if a future unrelated
    change installs `ollama` into the dev/test venv for some other reason.

    Deliberately does NOT mock BedrockModel/OllamaModel here: the whole
    point is to exercise the *real* lazy-import chain and prove it never
    touches `ollama` on the bedrock path.
    """
    # Clean slate: drop any cached ollama/strands.models.ollama modules so
    # this guard can't accidentally pass just because an earlier test in
    # the same process already imported (and cached) them.
    for mod_name in list(sys.modules):
        if mod_name == "ollama" or mod_name.startswith("strands.models.ollama"):
            monkeypatch.delitem(sys.modules, mod_name, raising=False)

    monkeypatch.setitem(sys.modules, "ollama", None)
    monkeypatch.setenv("ARDCONFIG_LLM_PROVIDER", "bedrock")

    onboard_agent = _import_agent_module()

    try:
        agent = onboard_agent.create_agent()
    except ModuleNotFoundError as exc:
        pytest.fail(
            "create_agent() with provider=bedrock raised ModuleNotFoundError "
            f"(AC-016 regression — bedrock path must not require `ollama`): {exc}"
        )

    import strands.models.bedrock as bedrock_mod

    assert isinstance(agent.model, bedrock_mod.BedrockModel)


# --- Item 5: config-precedence fix — non-empty env vars are honored ------


def test_precedence_fix_bedrock_model_env_var_honored(monkeypatch, stub_bedrock, forbid_ollama):
    monkeypatch.setenv("ARDCONFIG_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("ARDCONFIG_BEDROCK_MODEL", "custom-bedrock-model")
    onboard_agent = _import_agent_module()

    agent = onboard_agent.create_agent()

    assert agent.model.kwargs["model_id"] == "custom-bedrock-model"


def test_precedence_fix_ollama_model_env_var_honored(monkeypatch, stub_ollama, forbid_bedrock):
    monkeypatch.setenv("ARDCONFIG_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("ARDCONFIG_OLLAMA_MODEL", "custom-ollama-model")
    onboard_agent = _import_agent_module()

    agent = onboard_agent.create_agent()

    assert agent.model.kwargs["model_id"] == "custom-ollama-model"


# --- Item 6: config-precedence fix — empty-string env vars fall back -----
#
# This is the specific defect the delta fixes: invoke_agent() passes
# ARDCONFIG_BEDROCK_MODEL="${ARDCONFIG_BEDROCK_MODEL:-}" etc. through to
# the Python subprocess, so an *unset* conf-file placeholder arrives as
# a present-but-empty-string env var, not an absent one. The old
# `os.environ.get(KEY, default)` read treats "" as "present" and returns
# "" (never falls back to `default`); the fixed `os.environ.get(KEY) or
# default` correctly falls back on "" (falsy) as well as on None.


def test_precedence_fix_empty_string_bedrock_vars_fall_back_to_defaults(
    monkeypatch, stub_bedrock, forbid_ollama
):
    monkeypatch.setenv("ARDCONFIG_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("ARDCONFIG_BEDROCK_MODEL", "")
    monkeypatch.setenv("ARDCONFIG_AWS_REGION", "")
    onboard_agent = _import_agent_module()

    agent = onboard_agent.create_agent()

    assert agent.model.kwargs == {
        "model_id": "us.anthropic.claude-sonnet-4-6",
        "region_name": "us-west-2",
    }


def test_precedence_fix_empty_string_ollama_vars_fall_back_to_defaults(
    monkeypatch, stub_ollama, forbid_bedrock
):
    monkeypatch.setenv("ARDCONFIG_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("ARDCONFIG_OLLAMA_HOST", "")
    monkeypatch.setenv("ARDCONFIG_OLLAMA_MODEL", "")
    onboard_agent = _import_agent_module()

    agent = onboard_agent.create_agent()

    assert agent.model.kwargs == {
        "host": "http://localhost:11434",
        "model_id": "gpt-oss:latest",
    }


def test_precedence_fix_empty_string_provider_falls_back_to_ollama_default(
    monkeypatch, stub_ollama, forbid_bedrock
):
    # ARDCONFIG_LLM_PROVIDER itself follows the same present-but-empty
    # pattern in create_agent() ("os.environ.get(...) or 'ollama'") —
    # bash-level resolve_llm_provider() normally prevents an empty value
    # from ever reaching this point (TASK-009), but create_agent() is
    # independently robust to it per design.md's listing.
    monkeypatch.setenv("ARDCONFIG_LLM_PROVIDER", "")
    onboard_agent = _import_agent_module()

    agent = onboard_agent.create_agent()

    assert agent.model.kwargs == {
        "host": "http://localhost:11434",
        "model_id": "gpt-oss:latest",
    }


def test_bedrock_region_falls_back_to_aws_default_region_env_var(
    monkeypatch, stub_bedrock, forbid_ollama
):
    """AWS_DEFAULT_REGION fallback (pre-existing FR-12 behavior) — regression."""
    monkeypatch.setenv("ARDCONFIG_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    onboard_agent = _import_agent_module()

    agent = onboard_agent.create_agent()

    assert agent.model.kwargs["region_name"] == "eu-central-1"
