# Evals — Ollama LLM Provider Delta (2026-07-20)

> Scope: this document covers evals added in response to `spec/design.md`'s
> Risk R14 ("Local Ollama models ... may be materially less reliable than
> Bedrock's Claude models at structured JSON output and multi-step
> tool-calling; no AC in this delta tests Ollama's actual board-
> identification accuracy"), explicitly deferred to eval-engineer for the
> verification phase. It does not re-evaluate the mechanical
> provider-branching/config-precedence code paths already covered by
> `tests/agent/test_create_agent.py`, `tests/agent/test_nfr8_scope_
> boundary.py`, and `tests/bin/test_ardconfig_onboard.bats` (see
> `spec/post-execution-log.md`'s test-engineer section) — those are
> deterministic unit/integration tests, not evals, and are out of scope
> here by design.

---

## Decision

**Build a small, two-tier eval addition — not a full statistically
rigorous benchmark, and not "no action."**

1. `evals/offline/` — fast (< 1s), deterministic, fixture-based, safe for
   CI. Not gated on a real model call.
2. `evals/run_golden_eval.py` + `evals/goldens/` — a small (3-case) live
   golden-case smoke check against the real agent and a real local Ollama
   server. **Manual/opt-in only** — not part of `./run-tests.sh`, not
   collected by `pytest`'s default `testpaths`, not wired into any CI
   trigger.

### Why not a full golden-eval suite (N boards, statistical scoring, CI-gated)

This is a proportionate-effort call, not a rubber stamp. Reasons a larger,
CI-gated suite would be disproportionate for this project:

- **Existing safety nets already sit between a bad AI profile and any
  real consequence**, and this delta does not touch any of them (NFR-8):
  - `bin/ardconfig-onboard`'s human confirmation step (FR-16) — the user
    sees the full generated profile and must approve it before it's
    written.
  - `run_setup`/`run_verify` (FR-19–21) actually install the core and
    compile a test sketch as part of the agent's own loop, with a 2-retry
    budget on failure — a wrong FQBN/core is not "blindly trusted," it is
    caught by a real compiler before the human even sees the result.
  - `validate_profile` (FR-15) schema-checks required fields via `jq`
    before the agent even proposes a result.
  - FR-24's explicit `"TODO"`-partial fallback path means "the model
    couldn't figure it out" is already a first-class, non-failure outcome
    the system is designed to produce and surface honestly.
- **This is a single-user, single-invocation local CLI tool**, not a
  service with an SLA or a fleet of unattended callers (see `spec/
  design.md`'s Communication Topology / Observability sections — ≤1
  request per invocation, no dashboards, no remote telemetry). The blast
  radius of one bad Ollama run is: the user sees a bad or partial profile,
  rejects/edits it, or re-runs with `ARDCONFIG_LLM_PROVIDER=bedrock`
  (zero-code-change backout, per the Rollout Plan).
- **A real live-Ollama, real-arduino-cli, real-compile eval is
  expensive**, not just "slow LLM inference": a live golden case in this
  environment took 30-90s for boards whose core is already installed
  locally, and would take several minutes on first run for a board
  needing a fresh third-party core install over the network (confirmed
  empirically — see "Live-run findings" below). Statistically
  meaningful N (dozens of boards, repeated runs to account for sampling
  variance) would turn a CLI project's test suite into a slow, flaky,
  infra-dependent one. That trade is not justified by this project's
  stakes.
- **Exact-match scoring against a "gold" profile is the wrong instrument
  for this delta anyway.** LLM output on an open-ended research task is
  not deterministic even at the schema level — a real gpt-oss:latest run
  during this eval's authoring produced a fully valid, complete Uno R3
  profile with `id: "arduino-uno"` instead of the existing `uno-r3.json`'s
  `id: "uno-r3"`. Both are correct per the schema (FR-13 only requires a
  lowercase-hyphenated slug); an exact-match harness would have recorded
  a false failure. This eval intentionally scores structurally (required
  fields present, USB IDs echoed correctly, no stray `"TODO"` on
  `status: success`) rather than diff-against-golden-JSON — see `evals/
  run_golden_eval.py`'s `_score()`.

Given those two facts together — a real downstream compile-check gate
that a rigorous eval would substantially duplicate, and a small-stakes,
single-user tool — a small, manually-run smoke check that (a) proves the
new default provider can still complete the full agentic loop and produce
a schema-complete profile, and (b) gives a maintainer a fast way to
sanity-check a future model/provider swap, is the proportionate answer.
Zero eval coverage was rejected because R14 is a real, named, deferred
risk and "the compile check will catch it eventually" is a weaker
guarantee than "a maintainer can run one command and get a direct answer
about whether the new default still works at all" before that default
ships to users.

---

## What is being evaluated

- **Agent:** `agent/onboard_agent.py`'s `create_agent()` → `Agent(...)`
  loop, exercised end-to-end via `main()`'s documented stdin/stdout JSON
  contract (`python -m agent.onboard_agent`) — the same entry point
  `bin/ardconfig-onboard`'s `invoke_agent()` uses in production.
- **Prompt:** `SYSTEM_PROMPT` (unmodified by this delta, NFR-8) —
  evaluated as a fixed input, not itself a variable under test.
- **Tools:** the real, unmocked 6-tool surface from `agent/tools.py`
  (unmodified by this delta, NFR-8) for the live golden-eval tier;
  `parse_agent_output()` in isolation (also unmodified) for the offline
  tier.
- **LLM backend swap (the actual delta under test):** `create_agent()`'s
  provider branch, specifically whether routing the exact same
  tools/prompt/schema through `OllamaModel(gpt-oss:latest)` — the new
  default — still reliably completes the task, compared to the previous
  default, `BedrockModel` (Claude). Bedrock is exercised opportunistically
  (auto-skips without live AWS credentials, per this environment) as a
  parity comparison, not a hard requirement of this eval.
- **Retrieval:** N/A — there is no retrieval step in this pipeline; board
  research is via `arduino-cli` subprocess calls and the model's own
  training knowledge (see "Live-run findings" below re: the absence of an
  actual web-search tool despite the system prompt's workflow step 3
  mentioning one).

---

## Failure modes covered

| Failure mode | Covered? | How |
|---|---|---|
| **Format drift** (model doesn't follow the "wrap in ```json fences" instruction) | Yes | `evals/offline/test_parse_agent_output_format_drift.py` — 6 fixtures covering all 4 of `parse_agent_output()`'s branches (clean fence, fence + trailing prose, missing language tag, TODO-without-fence, malformed JSON in fence, no fence/no TODO) |
| **Hallucination** (wrong FQBN/core/USB IDs) | Partially | Live golden-eval hard-fails on USB vendor/product ID mismatch (the model must echo input facts correctly, not invent them); FQBN/core mismatches against the reference are WARN-level, not hard-fail, because `run_verify`'s real compile step is the actual authority on FQBN/core correctness — duplicating that as a hard gate here would be redundant with an existing, better-positioned check |
| **Task incompletion** (missing required schema fields) | Yes | Live golden-eval hard-fails on any `required_fields` entry absent or literally `"TODO"` despite `status: success` |
| **Tool misuse** | Not separately covered | Out of scope for this delta — `agent/tools.py` is unmodified (NFR-8) and already covered by existing mock-based tests; the live golden-eval tier exercises real tool calls incidentally but does not add tool-call-shape assertions, since the delta doesn't change tool definitions |
| **Injection** | Not covered here | Out of scope — `spec/security.md` already covers the injection surface this delta actually introduces (env-var pass-through into `check_ollama_available()`'s heredoc); that surface is bash-side, not agent-loop-side, and unrelated to model-output evaluation |
| **Latency** | Yes (advisory) | Live golden-eval records wall-clock time per case and WARNs (does not hard-fail) if a case exceeds NFR-7's 5-minute onboarding budget |
| **Silent stdout-contract corruption** | Discovered, not "covered" as a pass/fail gate | See "Live-run findings" below — a real, pre-existing, provider-agnostic bug found while building this eval. The live-eval harness works around it (extracts the trailing JSON object) rather than gating on it, since fixing it is out of this delegation's scope |

---

## Metrics

Per live golden-eval case:

- **Task success** (binary): `status == "success"` and all hard-fail
  checks pass.
- **Schema completeness**: all `required_fields` present and non-`"TODO"`
  (only meaningful when `status == "success"`).
- **Groundedness** (input-echo correctness): `usb_vendor_id`/
  `usb_product_id` in the output profile match the input exactly.
- **Reference parity** (informational, not pass/fail): whether `fqbn`/
  `core` match the checked-in reference profile for that board.
- **Latency**: wall-clock seconds for the full agent subprocess run,
  compared against NFR-7's 300s budget (advisory).
- **Stdout-contract cleanliness** (informational): whether the recovered
  JSON required the trailing-JSON-extraction fallback (i.e., whether the
  known pre-existing pollution bug was observed on this run).

There is no "harmfulness" metric — this is a local dev-tool JSON
generation task with no user-facing content-safety surface; the existing
security review (`spec/security.md`) already covers the actual attack
surface this delta introduces.

No aggregate score/threshold across cases is computed (e.g. "80% pass
rate"). With a 3-case golden set, per-case pass/fail plus a written
summary is more informative than a synthetic aggregate — see Regression
Policy below for why this isn't a blocking gate in the first place.

---

## Golden Dataset strategy

**Case authoring:** 3 cases in `evals/goldens/*.json`, chosen for a
specific reason each (see each file's `description` field):

| Case | Why chosen |
|---|---|
| `uno-r3` | Official Arduino AVR core, already installed locally in a typical `ardconfig-setup`'d environment → cheap/fast to run repeatedly. Default smoke case. |
| `nano-r4` | Official Arduino Renesas core (non-AVR family) → board-family diversity without added install cost. |
| `nucleo-f411re` | Third-party core with a non-empty `core_url`. Explicitly named by `spec/design.md`'s Verification Strategy as the pre-delta golden-path regression board (AC-001–011). Marked `"weight": "heavy"` — not pre-installed, triggers a real network core install on first run — so it's excluded from the default (`--weight cheap`) run and must be requested explicitly. |

Each case's `expected` block is derived from the corresponding checked-in
`profiles/*.json` file (the project's own existing, presumably-correct
ground truth) — not hand-invented. `reference_profile` in each golden
case JSON points at the source of truth it was derived from, so a future
change to a real profile (e.g. correcting a FQBN) has an obvious place to
also update the golden case.

**Review:** golden case JSON is plain, readable, git-diffable data — any
future addition/edit goes through normal code review, same as any other
`spec/`-adjacent artifact. No separate approval workflow is introduced
(disproportionate for 3 cases).

**Versioning:** golden cases are versioned by git history, same as
everything else in this repo. No case ever needs to encode "expected
output" as an exact string (see Decision section's exact-match rationale
above), so profile-schema evolution (e.g. a new required field) only
requires updating the `required_fields` list in each case file, not
re-deriving expected outputs.

**Offline fixtures:** `evals/offline/fixtures/*.txt` — one real, verbatim
`str(result)` capture from a live gpt-oss:latest run performed while
authoring this eval (`real_clean_fence.txt`), plus 5 synthetic
edge-case variants documented as synthetic in the test module's docstring
(not misrepresented as observed failures). See `evals/offline/
test_parse_agent_output_format_drift.py`'s module docstring for full
provenance notes.

---

## Regression policy

- **`evals/offline/`**: safe to run on every change to `agent/
  onboard_agent.py` or `agent/tools.py` (fast, deterministic). Not
  currently wired into `./run-tests.sh` or CI — recommended CI
  integration point below. Recommended trigger: any PR touching
  `agent/onboard_agent.py`.
- **`evals/run_golden_eval.py`**: **not** run automatically, ever, by
  this delta's design. Recommended manual-trigger points for a
  maintainer:
  1. Before changing `ARDCONFIG_OLLAMA_MODEL`'s shipped default (e.g.
     upgrading from `gpt-oss:latest` to a newer tag).
  2. Before changing `SYSTEM_PROMPT` or `agent/tools.py` (even though
     NFR-8 keeps those out of *this* delta's scope, a future delta that
     does touch them should re-run this smoke check).
  3. If a user reports a bad/incomplete profile from the `ollama`
     provider path, as a first diagnostic step.
  4. Periodically/ad hoc, at a maintainer's discretion — there is no
     recurring schedule requirement for a project this size.
- **Thresholds:** none, by design (see Metrics section). A HARD FAIL on
  any case is a signal for a human to look at the `--out` JSON report
  and the raw agent transcript, not an automatic block on anything (there
  is no CI job for it to block).
- **Triage workflow when a live golden case hard-fails:**
  1. Re-run just that case with `--keep-tmp` to inspect the sandbox
     copy's `profiles/<id>.json` and the agent's tool-call sequence.
  2. Check whether `status` was `failure` (parsing/tool problem) vs.
     `success`-with-a-missing-field (schema-completeness problem) vs. a
     USB-ID mismatch (grounding problem) — each points to a different
     root cause (prompt-following vs. model capability vs. a genuine
     `parse_agent_output()` gap).
  3. If the root cause is in `agent/onboard_agent.py` or `agent/
     tools.py`, that's a production-code fix outside this delegation's
     scope — route through the normal spec-driven flow (a corrective
     requirements packet per `CLAUDE.md`'s regression/corrective-mode
     process, since it would touch NFR-8-protected files).
  4. If the root cause is "gpt-oss:latest just isn't reliable enough for
     this task," the remediation is a config change
     (`ARDCONFIG_LLM_PROVIDER=bedrock` or a different
     `ARDCONFIG_OLLAMA_MODEL`), not a code change — already a
     zero-code-change backout path per the Rollout Plan.

---

## Traceability

| REQ / Risk ID | Eval case(s) | Notes |
|---|---|---|
| R14 (context.md, carried into design.md Open Design Questions) | `evals/run_golden_eval.py` (all 3 golden cases) | The primary target of this eval addition — "no AC in this delta tests Ollama's actual board-identification accuracy" |
| FR-7 (agent LLM backend selection) | `evals/run_golden_eval.py` — real, unmocked `create_agent()` provider branch exercised end-to-end (as opposed to `tests/agent/test_create_agent.py`'s mocked-model-class unit coverage) | Confirms the *real* Ollama branch produces a working agent, not just that it constructs the right Python object |
| FR-13 (generate complete profile JSON, all schema fields) | `evals/run_golden_eval.py`'s `required_fields` check (all 3 cases) | |
| FR-24 (partial profile for unidentifiable boards) | `evals/offline/test_parse_agent_output_format_drift.py::test_todo_fields_without_fence_parses_to_partial` | Deterministic coverage of the partial-status path without needing a live run that happens to fail |
| NFR-7 (5-minute onboarding budget) | `evals/run_golden_eval.py`'s per-case latency WARN | Advisory only, per Regression Policy |
| NFR-8 (provider-selection scope boundary) | N/A — this eval suite is itself scoped to respect NFR-8: no file under `evals/` modifies `agent/tools.py`, `SYSTEM_PROMPT`, or the profile schema; `evals/run_golden_eval.py` exercises them read-only via the sandboxed subprocess | Self-referential: the eval harness's own additive-only design is a form of NFR-8 compliance |
| "Format drift" (this document's Failure Modes table) | `evals/offline/test_parse_agent_output_format_drift.py` (all 6 fixtures) | Not tied to a specific FR — a general agentic-reliability concern this document's system-prompt-level template asks eval-engineer to cover |

---

## Live-run findings (discovered while building this eval)

While validating `evals/run_golden_eval.py` against a real local Ollama
server (`gpt-oss:latest`) and real `arduino-cli`, the following were
observed. Neither is a defect in the Ollama-provider delta itself; both
are reported here as findings for the orchestrator to route (blocker /
follow-up), since fixing them would require touching files outside this
delegation's write scope (`agent/onboard_agent.py`, `agent/tools.py`).

1. **Stdout-contract pollution (pre-existing, provider-agnostic,
   moderate-to-high severity).** `agent/onboard_agent.py`'s
   `create_agent()` never passes `callback_handler=None` (or any
   explicit handler) to `strands.Agent(...)`. Strands' default callback
   handler prints `"Tool #N: <tool_name>"` trace lines (and occasionally
   inline model commentary, e.g. `"The path should be inside
   profiles/. Let's write to profiles/arduino-nano-r4.json."`) directly
   to **stdout** as a side effect during the `agent(prompt)` call in
   `main()`. `main()`'s own `json.dump(output, sys.stdout, indent=2)`
   then lands on the *same* stdout stream, after that trace text. Net
   effect: real subprocess stdout from `python -m agent.onboard_agent`
   is **not** pure JSON — it is `[trace text] + [the documented JSON
   object]`.
   - Confirmed this is **not** a `parse_agent_output()` defect:
     `str(result)` (what `parse_agent_output()` actually receives) was
     clean in every real run observed — the pollution happens entirely
     on the process-level stdout file descriptor, not inside the
     returned `AgentResult` object.
   - This directly threatens `bin/ardconfig-onboard`'s documented
     Bash↔Python JSON contract (`spec/design.md` Public Interfaces §5):
     `invoke_agent()` captures raw subprocess stdout into
     `agent_output`, and `handle_agent_output()` immediately runs
     `jq -r '.status // "failure"'` and `jq '.profile'` against that
     entire captured string. `jq` does not tolerate a non-JSON text
     prefix. This was previously unverified because no existing
     automated test exercises a real end-to-end subprocess call to
     `python -m agent.onboard_agent` against a real model — `tests/bin`'s
     bats suite mocks/delegates around `invoke_agent()`, and `tests/
     agent`'s pytest suite calls `create_agent()` directly, never
     `main()`.
   - Applies equally to `provider=bedrock` — this is a property of
     `strands.Agent`'s default callback handler, independent of which
     model backend is selected, so it predates this delta entirely.
   - **This eval harness works around it** (`evals/run_golden_eval.py`'s
     `_extract_trailing_json()`) rather than fixing it, since
     `agent/onboard_agent.py` is off-limits for this delegation.
     **Recommendation for the orchestrator:** route to executor as a
     corrective-mode fix (likely a one-line `callback_handler=None` add
     to `create_agent()`'s `Agent(...)` construction), since it plausibly
     affects real production `ardconfig-onboard` runs for both providers,
     not just this eval.

2. **`agent/tools.py` has no web-search tool despite the system prompt
   and `spec/design.md`'s architecture diagram referencing one**
   (informational, not a delegation blocker). `SYSTEM_PROMPT`'s workflow
   step 3 says "If the board requires a third-party core, determine the
   board manager URL" and `spec/design.md`'s Architecture diagram lists
   "web search (board docs)" as an external system, but the actual 6-tool
   surface (`arduino_cli_search`, `read_file`, `write_file`,
   `validate_profile`, `run_setup`, `run_verify`) contains no web-search
   or HTTP-fetch tool. In practice the model appears to rely on its own
   training-data knowledge for third-party board-manager URLs (observed:
   correct `core_url` reproduced for `nucleo-f411re` in prior manual
   testing referenced in `spec/design.md`). This is pre-existing
   (predates this delta) and out of scope for both this delegation and
   NFR-8; noted here only because it's directly relevant to *why* R14 is
   a real risk (a smaller/less-broadly-trained model has less to fall
   back on for niche third-party boards than Claude does) and because a
   future eval-set expansion into more third-party-core boards should
   expect this to be the dominant failure axis.

---

## Maintenance evals (out of scope for this pass)

The eval-engineer role's general mandate includes evaluating change
sequences (A → B → C within a subsystem) for regression-free completion,
diff-size growth, interface churn, corrective-cycle count, etc. This
delegation's actual scope, as given, is a single, already-completed delta
(the Ollama LLM Provider swap) and its LLM-behavior risk (R14) — not a
multi-step maintenance sequence to instrument. No maintenance-eval
artifact is produced in this pass. If a future delegation asks
eval-engineer to assess the *process* of making a sequence of related
changes to `agent/onboard_agent.py` or the onboarding subsystem more
broadly, that would be a separate, explicitly-scoped piece of work.

---

## How to run (summary)

See `evals/README.md` for full detail. Quick reference:

```bash
# Fast, deterministic, safe for CI:
.venv/bin/python -m pytest evals/offline -q

# Slow, live, manual/opt-in — requires a local Ollama server with
# gpt-oss:latest pulled, and arduino-cli on PATH:
.venv/bin/python evals/run_golden_eval.py
```

## Recommended CI integration point

- `evals/offline` is a reasonable candidate for a new, separate, fast CI
  step (e.g. `pytest evals/offline -q`) alongside the existing `./run-
  tests.sh` step — not merged into `run-tests.sh` itself, so the two
  remain independently skippable/reportable in CI output. No CI config
  exists in this repo yet (`spec/tasks.md` TASK-015 explicitly scoped CI
  setup out); this is a recommendation for whenever CI is introduced, not
  an action taken in this pass.
- `evals/run_golden_eval.py` should **not** be added to any CI trigger.
  It requires live infrastructure (a real Ollama server with a
  multi-gigabyte model pulled, `arduino-cli`, network access for the
  "heavy" case) that a typical CI runner won't have by default, and its
  runtime/flakiness profile is unsuited to blocking merges. If a
  self-hosted runner with those prerequisites exists in the future, it
  could run on a schedule (e.g. weekly) as an *informational* job, not a
  merge gate — consistent with this document's Regression Policy.
