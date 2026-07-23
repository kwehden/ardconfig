"""Offline, fast, deterministic format-drift coverage for
agent.onboard_agent.parse_agent_output().

WHY THIS LIVES OUTSIDE tests/agent (and is not collected by default):
parse_agent_output() itself is pre-existing code, byte-for-byte unmodified
by the Ollama-provider delta (NFR-8 -- see tests/agent/test_nfr8_scope_
boundary.py's golden-hash check, which covers agent/tools.py and
SYSTEM_PROMPT but not this function directly; parse_agent_output isn't
touched by that delta either way). So this isn't "delta regression
coverage" in the same sense as tests/agent/test_create_agent.py.

It earns a place in this repo's eval surface (not the fast pytest suite)
because the delta changes *what kind of text* this function has to parse
in practice: the new default provider (gpt-oss:latest, a materially
smaller open-weight model than the previous default, Bedrock Claude) may
follow the SYSTEM_PROMPT's "wrap your final answer in ```json fences"
instruction less reliably. That's a "format drift" failure mode
(spec/evals.md's failure-mode list) worth covering explicitly, cheaply,
and deterministically -- no live model call needed, because
parse_agent_output()'s behavior on a given input string is 100%
deterministic; only *which* input strings are realistic is influenced by
the LLM.

Fixture provenance (see evals/offline/fixtures/):
- real_clean_fence.txt: VERBATIM `str(result)` captured from a real
  gpt-oss:latest run via a live local Ollama server during this eval's
  authoring (2026-07-20), instrumented to capture str(result) separately
  from Strands' side-effect stdout trace printing (see
  evals/run_golden_eval.py's _extract_trailing_json docstring for why
  those are two different things). This is the common/expected case.
- The other four fixtures are synthetic, hand-authored edge cases
  representing plausible ways a smaller/less-instruction-following model
  could deviate from the expected fenced-JSON shape. They are not claims
  that gpt-oss:latest has been observed doing these things -- they exist
  to pin down parse_agent_output()'s documented behavior on each of its
  four branches (valid fenced JSON -> success; invalid JSON in a fence ->
  failure; TODO present, no fence -> partial; neither -> failure) using
  representative-looking text, so a future change to this function (or a
  future provider swap to a still-less-reliable model) has a regression
  net to run against.

This module is deliberately outside pyproject.toml's `testpaths`
(`["tests/agent"]`), so it is NOT collected by a bare `pytest` or by
./run-tests.sh. Run it explicitly:

    .venv/bin/python -m pytest evals/offline -q

It is fast (no I/O beyond reading local fixture files, no network, no
subprocess) and safe to add to CI as an independent, optional step if
desired -- see spec/evals.md's Regression Policy.
"""
from pathlib import Path

import pytest

from agent.onboard_agent import parse_agent_output

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class _FakeAgentResult:
    """Stand-in for the Strands AgentResult object parse_agent_output()
    receives in production. parse_agent_output()'s entire contract with
    its input is `str(result)`, so a plain str-wrapper is sufficient and
    keeps this test decoupled from Strands' actual AgentResult type."""

    def __init__(self, text: str):
        self._text = text

    def __str__(self) -> str:
        return self._text


def _fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def test_real_clean_fence_parses_to_success():
    result = _FakeAgentResult(_fixture("real_clean_fence.txt"))

    parsed = parse_agent_output(result)

    assert parsed["status"] == "success"
    assert parsed["profile"]["id"] == "arduino-uno-r3"
    assert parsed["profile"]["fqbn"] == "arduino:avr:uno"
    assert parsed["profile"]["usb_vendor_id"] == "2341"


def test_trailing_prose_after_fence_still_parses_to_success():
    """The regex only requires the fence to appear somewhere in the text
    (re.search, not re.fullmatch) -- trailing commentary after the
    closing fence should not break extraction."""
    result = _FakeAgentResult(_fixture("trailing_prose_after_fence.txt"))

    parsed = parse_agent_output(result)

    assert parsed["status"] == "success"
    assert parsed["profile"]["id"] == "arduino-nano-r4"


def test_missing_json_language_tag_fails_to_parse():
    """Documents existing, exact behavior: parse_agent_output()'s regex
    is anchored on the literal ```json fence tag, not a bare ``` fence.
    A model that drops the language tag produces a `status: failure`
    result today, not a successfully-parsed profile.

    This is intentionally captured as a *regression pin*, not a verdict
    that today's behavior is correct -- if this turns out to be a real
    gpt-oss failure pattern in the live golden-eval tier
    (evals/run_golden_eval.py), the fix (making the regex tolerant of a
    bare ``` fence) belongs in agent/onboard_agent.py, which is
    off-limits for this delegation (NFR-8 / additive-only constraints).
    Flagging this explicitly here means the fix, if ever made, will be
    visible as a deliberate, reviewed change to this test's expectation.
    """
    result = _FakeAgentResult(_fixture("missing_language_tag.txt"))

    parsed = parse_agent_output(result)

    assert parsed["status"] == "failure"
    assert parsed["error"] == "Could not parse profile from agent response"


def test_todo_fields_without_fence_parses_to_partial():
    result = _FakeAgentResult(_fixture("no_fence_but_todo.txt"))

    parsed = parse_agent_output(result)

    assert parsed["status"] == "partial"
    assert "raw" in parsed


def test_malformed_json_in_fence_reports_failure_not_a_silent_bad_profile():
    """The single most safety-relevant branch: if the model emits a
    fence but the JSON inside it is broken (here: a trailing comma), the
    caller must get an explicit `status: failure` + parseable error, not
    a truncated/partial silently-wrong profile object."""
    result = _FakeAgentResult(_fixture("malformed_json_in_fence.txt"))

    parsed = parse_agent_output(result)

    assert parsed["status"] == "failure"
    assert "Invalid JSON" in parsed["error"]


def test_no_fence_and_no_todo_reports_failure():
    result = _FakeAgentResult(_fixture("no_fence_no_todo.txt"))

    parsed = parse_agent_output(result)

    assert parsed["status"] == "failure"
    assert parsed["error"] == "Could not parse profile from agent response"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "real_clean_fence.txt",
        "trailing_prose_after_fence.txt",
        "missing_language_tag.txt",
        "no_fence_but_todo.txt",
        "malformed_json_in_fence.txt",
        "no_fence_no_todo.txt",
    ],
)
def test_parse_agent_output_never_raises(fixture_name):
    """Whatever the model outputs, parse_agent_output() must return a
    dict, never propagate an exception -- main() has no try/except
    around this call, so an uncaught exception here would crash the
    whole subprocess with a Python traceback instead of the documented
    {status, error, raw} failure shape."""
    result = _FakeAgentResult(_fixture(fixture_name))

    parsed = parse_agent_output(result)

    assert isinstance(parsed, dict)
    assert "status" in parsed
