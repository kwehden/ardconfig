"""NFR-8 automated scope-boundary check.

NFR-8: The introduction of LLM provider selection (FR-25-FR-28) SHALL NOT
alter agent tool definitions (agent/tools.py) or the system prompt in
agent/onboard_agent.py (among other things out of this delta's scope).

Mechanism (test-engineer decision, per spec/tasks.md TASK-016 item 7):
golden SHA-256 checksums, not a git-diff-against-a-base-ref comparison.

Rationale for choosing checksums over a git-diff-based check:
- A git-diff-based check needs a stable base ref (e.g. a specific commit
  SHA or tag). This repo's delta was developed as uncommitted working-tree
  changes on top of HEAD, so "the base ref" is really just "whatever HEAD
  happened to be when this test was written" — accurate today, but this
  relationship inverts the moment the delta is committed (HEAD moves to
  include the delta, and a "diff against HEAD" check would then trivially
  pass forever after, silently losing its guard value for *future*
  changes). The task's own risk note flags exactly this: "a git-history-
  based check is fragile across rebases/squashes."
- A checksum golden file instead pins the specific known-good content
  directly, independent of git history. It stays meaningful indefinitely:
  any future change to agent/tools.py or SYSTEM_PROMPT (in this delta or
  any later one) will fail this test until the golden file is deliberately
  (and reviewably) regenerated — which is exactly the friction NFR-8 wants
  for those two artifacts.

The golden hashes in tests/agent/golden/ were generated from the on-disk
state of agent/tools.py and agent/onboard_agent.py's SYSTEM_PROMPT
constant *before* this delta's test suite was added, confirmed identical
to the pre-delta git history (git diff agent/tools.py was empty at the
time these goldens were generated).
"""
import hashlib
from pathlib import Path

from agent.onboard_agent import SYSTEM_PROMPT

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


def _read_golden(name):
    return (GOLDEN_DIR / name).read_text().strip()


def test_agent_tools_py_byte_identical_to_golden():
    tools_py_path = REPO_ROOT / "agent" / "tools.py"
    actual = hashlib.sha256(tools_py_path.read_bytes()).hexdigest()
    expected = _read_golden("agent_tools_py.sha256")

    assert actual == expected, (
        "agent/tools.py has changed since the golden checksum was recorded. "
        "NFR-8 forbids the Ollama-provider delta (and any change asserting "
        "compliance with this test) from altering agent tool definitions. "
        "If this is an intentionally *approved* change (cite the approving "
        "REQ ID / design section), regenerate the golden file:\n"
        "  python3 -c \"import hashlib; open('tests/agent/golden/"
        "agent_tools_py.sha256','w').write(hashlib.sha256(open('agent/"
        "tools.py','rb').read()).hexdigest()+chr(10))\""
    )


def test_system_prompt_byte_identical_to_golden():
    actual = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    expected = _read_golden("system_prompt.sha256")

    assert actual == expected, (
        "SYSTEM_PROMPT in agent/onboard_agent.py has changed since the "
        "golden checksum was recorded. NFR-8 forbids the Ollama-provider "
        "delta from altering the system prompt. If this is an intentionally "
        "*approved* change (cite the approving REQ ID / design section), "
        "regenerate the golden file (see tests/agent/golden/ for the "
        "sibling agent_tools_py.sha256 regeneration pattern)."
    )
