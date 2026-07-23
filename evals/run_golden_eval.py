#!/usr/bin/env python3
"""Live golden-case eval for agent/onboard_agent.py's board-onboarding output.

MANUAL / OPT-IN ONLY. This script is NOT part of ./run-tests.sh, is not
collected by pytest (it lives outside tests/agent's pyproject testpaths),
and is not wired into any CI trigger. It exercises the *real* Strands agent
against a *real* local Ollama server (or, optionally, real Bedrock) and,
depending on the case, a real arduino-cli core install/compile. That makes
it slow (tens of seconds to several minutes per case) and environment-
dependent (local Ollama server + model pulled, and/or AWS credentials,
network access, arduino-cli installed) — the opposite of what belongs in
the fast, mock-based tests/agent and tests/bin suites.

Why this exists (see spec/evals.md for the full decision writeup): the
Ollama-provider delta changes which LLM backend answers the onboarding
question by default, but does not touch agent/tools.py, SYSTEM_PROMPT, or
the profile schema (NFR-8). spec/design.md's Risk R14 flagged that no
acceptance criterion in that delta tests whether the new default provider
(gpt-oss:latest via Ollama) is still reliably able to identify a board and
produce a complete, valid profile JSON, the way the previous default
(Bedrock Claude) was assumed to. This script is a deliberately small,
proportionate smoke check for that question — not a statistically
rigorous benchmark, and not a CI gate. It exists because the real
downstream safety net (human confirmation in bin/ardconfig-onboard, and
the run_setup/run_verify compile check) already catches a bad profile
before it's trusted; this eval exists to catch the *pattern* of degraded
output before a human has to.

SAFETY: each golden case runs the agent inside an isolated temporary copy
of the repository (write_file/run_setup/run_verify's target paths are
hardcoded relative to agent/tools.py's own location, so the *real*
profiles/ directory would otherwise be at risk of being overwritten by
AI-generated content). Nothing in the real working tree is touched. See
_make_sandbox().

Usage:
    python evals/run_golden_eval.py                       # all "cheap" cases, provider=ollama
    python evals/run_golden_eval.py --boards uno-r3        # just one case
    python evals/run_golden_eval.py --weight all           # include the "heavy" (real core install) cases
    python evals/run_golden_eval.py --provider bedrock     # opt-in Bedrock comparison (needs AWS creds)
    python evals/run_golden_eval.py --list                 # list available cases, run nothing
    python evals/run_golden_eval.py --out /tmp/report.json --keep-tmp

Exit code: 0 if no HARD FAIL among cases that actually ran (skipped cases
don't count against this); 1 otherwise. WARN-level findings (e.g. a
non-exact FQBN match, or exceeding the NFR-7 5-minute budget) are reported
but do not affect the exit code — see spec/evals.md's Regression Policy
for why this is intentionally advisory, not a hard gate.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDENS_DIR = Path(__file__).resolve().parent / "goldens"

# Directories excluded when building the isolated sandbox copy of the repo.
# .venv is symlinked in (not copied — it's large and shared/read-only for
# our purposes). tests/ and evals/ are irrelevant to the agent run itself.
_SANDBOX_EXCLUDE = {".git", ".venv", "tests", "evals", "__pycache__", ".pytest_cache"}

ID_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Matches production defaults documented in spec/design.md Public
# Interfaces §2 / agent/onboard_agent.py's create_agent(). Duplicated here
# deliberately (not imported from onboard_agent) so this eval script never
# needs to modify or depend on the internals of the file under test beyond
# its documented CLI/env-var contract.
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "gpt-oss:latest"
DEFAULT_BEDROCK_MODEL = "us.anthropic.claude-sonnet-4-6"
DEFAULT_AWS_REGION = "us-west-2"

# NFR-7's onboarding budget. A WARN (not a hard fail) if exceeded — see
# module docstring / spec/evals.md for why this eval doesn't hard-gate.
NFR7_BUDGET_SECONDS = 300


def _ignore(_dir, names):
    return [n for n in names if n in _SANDBOX_EXCLUDE]


def _make_sandbox() -> Path:
    tmp_root = Path(tempfile.mkdtemp(prefix="ardconfig-eval-"))
    dest = tmp_root / "repo"
    shutil.copytree(REPO_ROOT, dest, ignore=_ignore)
    venv_src = REPO_ROOT / ".venv"
    if venv_src.exists():
        (dest / ".venv").symlink_to(venv_src, target_is_directory=True)
    return dest


def _load_goldens(weight: str, boards: list[str] | None) -> list[dict]:
    cases = []
    for path in sorted(GOLDENS_DIR.glob("*.json")):
        case = json.loads(path.read_text())
        if boards and case["case_id"] not in boards:
            continue
        if not boards and weight != "all" and case.get("weight") != weight:
            continue
        cases.append(case)
    return cases


def _preflight_ollama(host: str, model: str) -> str | None:
    """Return None if OK, else a human-readable reason to skip."""
    try:
        import ollama
    except ImportError:
        return f"'ollama' pip package not importable from this interpreter ({sys.executable})"
    try:
        client = ollama.Client(host=host)
        resp = client.list()
    except Exception as exc:  # noqa: BLE001 - reachability probe, any failure means "unreachable"
        return f"Ollama server unreachable at {host}: {exc}"
    names = {(m.model or "") for m in resp.models}
    if model not in names and f"{model}:latest" not in names:
        return f"Ollama server at {host} does not have model '{model}' pulled"
    return None


def _preflight_bedrock() -> str | None:
    try:
        import boto3
    except ImportError:
        return "'boto3' not importable from this interpreter"
    try:
        boto3.client("sts").get_caller_identity()
    except Exception as exc:  # noqa: BLE001
        return f"AWS credentials/Bedrock access unavailable: {exc}"
    return None


def _score(case: dict, agent_stdout_obj: dict, elapsed: float) -> dict:
    """Structural/schema scoring against the golden case. Deliberately does
    NOT require exact string equality on free-text or LLM-chosen fields
    (e.g. `id`, `notes`) — see spec/evals.md's rationale for avoiding
    brittle exact-match on non-deterministic LLM output. usb_vendor_id/
    usb_product_id are hard-checked because they are input facts the model
    must echo back correctly, not facts it needs to research."""
    hard_failures: list[str] = []
    warnings: list[str] = []

    status = agent_stdout_obj.get("status")
    profile = agent_stdout_obj.get("profile")

    if status == "failure":
        hard_failures.append(f"status=failure: {agent_stdout_obj.get('error')}")
    elif status not in ("success", "partial"):
        hard_failures.append(f"unrecognized status value: {status!r}")

    if status == "partial":
        warnings.append(
            "status=partial (agent could not determine all fields) — a legitimate "
            "FR-24 outcome, not a hard failure, but worth a human look"
        )

    if status in ("success", "partial") and not isinstance(profile, dict):
        hard_failures.append("status implies a profile object but none was returned")
        profile = {}
    profile = profile or {}

    expected = case["expected"]

    if status == "success":
        # NOTE: "empty" is not itself a defect for every field -- core_url
        # is legitimately "" for boards using an official Arduino core
        # (see e.g. the checked-in profiles/uno-r3.json). The real
        # correctness bar is: the key must be *present* (the model didn't
        # forget the field), and it must not be the literal "TODO"
        # placeholder (FR-24's placeholder is only valid on
        # status=partial, never on status=success).
        _empty_ok_fields = {"core_url"}
        for field in expected["required_fields"]:
            if field not in profile:
                hard_failures.append(f"required field '{field}' missing from profile")
                continue
            value = profile[field]
            if value == "TODO":
                hard_failures.append(
                    f"required field '{field}' is 'TODO' despite status=success"
                )
            elif value in ("", None) and field not in _empty_ok_fields:
                warnings.append(f"field '{field}' is present but empty")

    got_vid = str(profile.get("usb_vendor_id", "")).lower()
    got_pid = str(profile.get("usb_product_id", "")).lower()
    exp_vid = expected["usb_vendor_id"].lower()
    exp_pid = expected["usb_product_id"].lower()
    if status in ("success", "partial"):
        if got_vid and got_vid != exp_vid:
            hard_failures.append(f"usb_vendor_id mismatch: got {got_vid!r}, input was {exp_vid!r}")
        if got_pid and got_pid != exp_pid:
            hard_failures.append(f"usb_product_id mismatch: got {got_pid!r}, input was {exp_pid!r}")

        pid = profile.get("id", "")
        if pid and not ID_SLUG_RE.match(pid):
            warnings.append(f"id '{pid}' does not match the lowercase-hyphenated slug convention")

        got_fqbn = profile.get("fqbn", "")
        if got_fqbn and got_fqbn != expected.get("fqbn"):
            warnings.append(
                f"fqbn differs from the known-good reference: got {got_fqbn!r}, "
                f"reference is {expected.get('fqbn')!r} (not necessarily wrong — "
                f"run_setup/run_verify's compile result is the authoritative signal)"
            )
        got_core = profile.get("core", "")
        if got_core and got_core != expected.get("core"):
            warnings.append(
                f"core differs from the known-good reference: got {got_core!r}, "
                f"reference is {expected.get('core')!r}"
            )

    if elapsed > NFR7_BUDGET_SECONDS:
        warnings.append(
            f"took {elapsed:.1f}s, exceeding NFR-7's {NFR7_BUDGET_SECONDS}s onboarding budget"
        )

    return {
        "hard_failures": hard_failures,
        "warnings": warnings,
        "pass": not hard_failures,
    }


def _extract_trailing_json(stdout: str) -> tuple[dict | None, bool]:
    """Parse the agent's stdout as the JSON object documented in
    spec/design.md's Bash <-> Python JSON Contract (Public Interfaces §5).

    KNOWN PRE-EXISTING ISSUE (discovered while building this eval, not
    introduced by the Ollama-provider delta, and confirmed NOT to be a
    parse_agent_output() defect -- see spec/evals.md for the full writeup):
    agent/onboard_agent.py's create_agent() never passes
    callback_handler=... to strands.Agent(), so Strands' own default
    callback handler prints "Tool #N: <name>" trace lines (and sometimes
    inline model commentary) directly to stdout as a *side effect* during
    the `agent(prompt)` call in main(). str(result) itself (what
    parse_agent_output() actually receives) is clean in every real run
    observed while building this eval -- the pollution happens entirely
    on the process stdout *stream*, because main()'s later
    `json.dump(output, sys.stdout, indent=2)` lands on the same stdout
    fd, after Strands' already-printed trace. This is a property of
    strands.Agent's default callback handler (independent of
    BedrockModel vs OllamaModel), so it predates and is unrelated to this
    delta; it was previously unverified because no prior automated test
    exercised a real end-to-end subprocess call to
    `python -m agent.onboard_agent` against a real model (tests/bin's
    bats suite mocks/delegates around invoke_agent(); tests/agent's
    pytest suite calls create_agent() directly, never main()). It very
    likely also affects bin/ardconfig-onboard's handle_agent_output()'s
    `jq -r '.status // "failure"'` on the captured `agent_output` for
    BOTH providers in real usage. See spec/evals.md and this eval run's
    completion summary for the corresponding blocker report to executor
    -- this eval harness works around it (see below) rather than fixing
    production code, which is out of scope/off-limits for this
    delegation.

    Returns (parsed_dict_or_None, was_stdout_polluted).
    """
    stripped = stdout.strip()
    try:
        return json.loads(stripped), False
    except json.JSONDecodeError:
        pass

    # Fall back: try each '{' from rightmost to leftmost. json.loads
    # rejects trailing data after a valid value, so an inner/nested brace
    # (e.g. from a nested object inside the profile) will fail with
    # "Extra data" and we'll keep walking left until we find the *outer*
    # brace that parses cleanly to the end of the string.
    candidates = [i for i, ch in enumerate(stripped) if ch == "{"]
    for idx in reversed(candidates):
        try:
            return json.loads(stripped[idx:]), True
        except json.JSONDecodeError:
            continue
    return None, True


def _run_case(case: dict, provider: str, env_overrides: dict, timeout: int, keep_tmp: bool) -> dict:
    case_id = case["case_id"]
    print(f"\n=== {case_id} (provider={provider}) ===")
    sandbox = _make_sandbox()
    try:
        venv_python = sandbox / ".venv" / "bin" / "python"
        if not venv_python.exists():
            venv_python = Path(sys.executable)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(sandbox)
        env.update(env_overrides)

        stdin_payload = json.dumps(case["input"])
        start = time.monotonic()
        try:
            proc = subprocess.run(
                [str(venv_python), "-m", "agent.onboard_agent"],
                cwd=str(sandbox),
                input=stdin_payload,
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            print(f"  TIMEOUT after {elapsed:.1f}s (limit {timeout}s)")
            return {
                "case_id": case_id,
                "provider": provider,
                "skipped": False,
                "elapsed_s": elapsed,
                "hard_failures": [f"timed out after {timeout}s"],
                "warnings": [],
                "pass": False,
                "stdout": None,
                "stderr": None,
            }
        elapsed = time.monotonic() - start

        stdout_obj, polluted = _extract_trailing_json(proc.stdout)
        if stdout_obj is None:
            print(f"  HARD FAIL: agent stdout contained no recoverable JSON object (exit={proc.returncode})")
            return {
                "case_id": case_id,
                "provider": provider,
                "skipped": False,
                "elapsed_s": elapsed,
                "hard_failures": [
                    f"agent process exit={proc.returncode}; stdout had no parseable "
                    f"trailing JSON object (see _extract_trailing_json docstring)"
                ],
                "warnings": [],
                "pass": False,
                "stdout": proc.stdout[-2000:],
                "stderr": proc.stderr[-2000:],
            }

        result = _score(case, stdout_obj, elapsed)
        if polluted:
            result["warnings"].append(
                "stdout was not pure JSON (contained tool-trace preamble before the "
                "documented JSON contract) -- recovered by extracting the trailing "
                "JSON object; see _extract_trailing_json's docstring, this is a "
                "pre-existing, provider-agnostic issue, not scored as a hard failure"
            )
        result.update(
            {
                "case_id": case_id,
                "provider": provider,
                "skipped": False,
                "elapsed_s": elapsed,
                "stdout": stdout_obj,
                "stdout_polluted": polluted,
                "stderr": proc.stderr[-2000:] if proc.stderr else "",
            }
        )

        verdict = "PASS" if result["pass"] else "HARD FAIL"
        print(f"  {verdict} in {elapsed:.1f}s (status={stdout_obj.get('status')})")
        for msg in result["hard_failures"]:
            print(f"    [FAIL] {msg}")
        for msg in result["warnings"]:
            print(f"    [warn] {msg}")
        return result
    finally:
        if keep_tmp:
            print(f"  (sandbox retained at {sandbox.parent})")
        else:
            shutil.rmtree(sandbox.parent, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=["ollama", "bedrock"], default="ollama")
    parser.add_argument("--boards", help="comma-separated golden case_ids to run (default: all matching --weight)")
    parser.add_argument("--weight", choices=["cheap", "heavy", "all"], default="cheap",
                         help="cheap = boards whose core is already installed (fast); "
                              "heavy = boards needing a real core install (slow); "
                              "all = both (ignored if --boards given)")
    parser.add_argument("--timeout", type=int, default=300, help="per-case subprocess timeout, seconds")
    parser.add_argument("--keep-tmp", action="store_true", help="don't delete the sandbox copy after each case")
    parser.add_argument("--out", help="write a JSON report to this path")
    parser.add_argument("--list", action="store_true", help="list available golden cases and exit")
    parser.add_argument("--ollama-host", default=os.environ.get("ARDCONFIG_OLLAMA_HOST") or DEFAULT_OLLAMA_HOST)
    parser.add_argument("--ollama-model", default=os.environ.get("ARDCONFIG_OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL)
    args = parser.parse_args()

    boards = [b.strip() for b in args.boards.split(",")] if args.boards else None

    if args.list:
        for path in sorted(GOLDENS_DIR.glob("*.json")):
            case = json.loads(path.read_text())
            print(f"{case['case_id']:20s} weight={case.get('weight','?'):6s} {case.get('description','')}")
        return 0

    cases = _load_goldens(args.weight, boards)
    if not cases:
        print("No golden cases matched the given filters.", file=sys.stderr)
        return 1

    if args.provider == "ollama":
        skip_reason = _preflight_ollama(args.ollama_host, args.ollama_model)
        env_overrides = {
            "ARDCONFIG_LLM_PROVIDER": "ollama",
            "ARDCONFIG_OLLAMA_HOST": args.ollama_host,
            "ARDCONFIG_OLLAMA_MODEL": args.ollama_model,
        }
    else:
        skip_reason = _preflight_bedrock()
        env_overrides = {
            "ARDCONFIG_LLM_PROVIDER": "bedrock",
            "ARDCONFIG_BEDROCK_MODEL": os.environ.get("ARDCONFIG_BEDROCK_MODEL") or DEFAULT_BEDROCK_MODEL,
            "ARDCONFIG_AWS_REGION": os.environ.get("ARDCONFIG_AWS_REGION") or DEFAULT_AWS_REGION,
        }

    if skip_reason:
        print(f"SKIPPING all cases for provider={args.provider}: {skip_reason}")
        print("(this is not a failure — it means the prerequisite live service/credentials "
              "for this provider aren't available in this environment; see evals/README.md)")
        if args.out:
            Path(args.out).write_text(json.dumps({"provider": args.provider, "skipped": True,
                                                    "reason": skip_reason, "cases": []}, indent=2))
        return 0

    results = [
        _run_case(case, args.provider, env_overrides, args.timeout, args.keep_tmp)
        for case in cases
    ]

    print("\n=== Summary ===")
    failed = [r for r in results if not r["pass"]]
    for r in results:
        print(f"  {r['case_id']:20s} {'PASS' if r['pass'] else 'FAIL':5s} {r['elapsed_s']:.1f}s")
    print(f"\n{len(results) - len(failed)}/{len(results)} cases passed (provider={args.provider}).")

    if args.out:
        Path(args.out).write_text(json.dumps({"provider": args.provider, "skipped": False,
                                                "cases": results}, indent=2, default=str))

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
