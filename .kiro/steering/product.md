---
inclusion: always
---
# KiroAgentPack — Product Context

This project uses a spec-driven, multi-agent development workflow inspired by System2.

All non-trivial work follows the artifact chain:
1. **Context** (spec/context.md) — scope, goals, constraints, open questions
2. **Requirements** (spec/requirements.md) — EARS-formatted functional and non-functional requirements
3. **Design** (spec/design.md) — architecture, interfaces, failure modes, rollout plan
4. **Tasks** (spec/tasks.md) — atomic implementation tasks with verification steps
5. **Implementation** — TDD-driven code changes by the executor agent
6. **Verification** — test-engineer, security-sentinel, code-reviewer

The orchestrator agent coordinates all work. Each quality gate requires explicit user approval before proceeding. Do not bypass gates without user consent.

Agents are specialists with isolated write access. The orchestrator delegates; it never implements directly.
