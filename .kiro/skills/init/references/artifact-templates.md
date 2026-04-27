# Artifact Templates

Templates for the four spec-driven workflow artifacts. Each template contains the required section headings. Content should be filled in by the corresponding specialist agent or by the user.

---

## spec/context.md Template

```markdown
# Context

**Status:** Draft
**Date:** <YYYY-MM-DD>

---

## Problem Statement

<!-- What problem are we solving? Why now? -->

## Goals

<!-- Numbered list of specific, measurable objectives -->

## Non-Goals / Out of Scope

<!-- Explicitly state what this work will NOT address -->

## Users & Use-Cases

<!-- Who are the users? What are the key use cases? -->

## Constraints & Invariants

<!-- Technical, business, and policy constraints -->

## Success Metrics & Acceptance Criteria

<!-- How will we know this is done? Falsifiable criteria. -->

## Risks & Edge Cases

<!-- What could go wrong? Likelihood and impact. -->

## Observability / Telemetry Expectations

<!-- What should be monitored? What alerts are needed? -->

## Rollout & Backward Compatibility

<!-- How will this be deployed? Any migration needed? -->

## Open Questions

<!-- Unresolved questions with suggested default answers -->

## Glossary

<!-- Terms and definitions specific to this work -->
```

---

## spec/requirements.md Template

```markdown
# Requirements

**Status:** Draft
**Date:** <YYYY-MM-DD>
**Traces to:** spec/context.md

---

## Functional Requirements

<!-- EARS-formatted requirements numbered REQ-001, REQ-002, ... -->
<!-- Use templates: Ubiquitous, Event-driven, State-driven, Unwanted behavior, Optional -->

## Data & Interface Contracts

<!-- API schemas, data formats, interface definitions -->

## Error Handling & Recovery

<!-- How should the system handle failures? -->

## Performance & Scalability

<!-- Response time budgets, throughput requirements, scaling expectations -->

## Security & Privacy

<!-- Authentication, authorization, data protection requirements -->

## Observability

<!-- Logging, metrics, tracing, alerting requirements -->

## Backward Compatibility & Migration

<!-- What must remain compatible? Migration path for breaking changes. -->

## Compliance / Policy Constraints

<!-- Regulatory, legal, or organizational policy requirements -->

## Validation Plan

<!-- How will each requirement be verified? -->

## Traceability Matrix

<!-- REQ IDs -> Design sections -> Task IDs -->

| REQ ID | Design Section | Task ID |
|--------|---------------|---------|
| REQ-001 | TBD | TBD |
```

---

## spec/design.md Template

```markdown
# Design

**Status:** Draft
**Date:** <YYYY-MM-DD>
**Traces to:** spec/context.md, spec/requirements.md

---

## Overview

<!-- One-paragraph summary of the design approach -->

## Architecture

<!-- System architecture diagram (ASCII or description) and component breakdown -->

## Data Flow

<!-- How data moves through the system -->

## Public Interfaces

<!-- API endpoints, function signatures, CLI commands -->

## Data Model & Storage

<!-- Database schema, data structures, storage decisions -->

## Concurrency / Consistency

<!-- Threading model, locking strategy, consistency guarantees -->

## Failure Modes & Recovery

<!-- What can fail and how the system recovers -->

## Security Model

<!-- Authentication, authorization, encryption, trust boundaries -->

## Observability

<!-- Logging, metrics, tracing design -->

## Rollout Plan

<!-- Deployment strategy, feature flags, phased rollout -->

## Alternatives Considered

<!-- At least 2 alternatives with reasons for rejection -->

## Open Design Questions

<!-- Unresolved technical decisions -->

## Verification Strategy

<!-- How will the design be validated? Maps to requirements. -->
```

---

## spec/tasks.md Template

```markdown
# Tasks

**Status:** Draft
**Date:** <YYYY-MM-DD>
**Traces to:** spec/context.md, spec/requirements.md, spec/design.md

---

## Task Graph Overview

<!-- ASCII dependency diagram showing task order -->

## Tasks

### TASK-001: <Title>

**Goal:** <One sentence>
**Files/areas:** <Expected files to change>
**Steps:**
1. <Step 1>
2. <Step 2>
**Verification:** <Commands or tests to verify>
**Rollback:** <How to undo>
**Risk:** Low / Med / High — <reason>
**Recommended agent:** executor

<!-- Repeat for each task -->

## Definition of Done Checklist

- [ ] All tasks completed
- [ ] All tests passing
- [ ] No security blockers
- [ ] Documentation updated
- [ ] Code review approved

## Execution Notes

<!-- Parallelism opportunities, ordering constraints, special instructions -->

## Traceability

| REQ ID | TASK ID |
|--------|---------|
| REQ-001 | TASK-001 |
```
