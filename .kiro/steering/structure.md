---
inclusion: always
---
# Directory Structure

```
.kiro/
  agents/          — Agent JSON configurations (14 files)
  prompts/         — Agent system prompts in markdown (14 files)
  steering/        — Cross-cutting context files (always loaded)
  skills/          — Portable instruction packages
    init/          — /init skill for bootstrapping spec workflow
      references/  — Detailed reference material for skills
  hooks/           — Safety and quality hook scripts (bash)

spec/              — Workflow artifacts (created per-project, not shipped)
  context.md       — Problem scope, goals, constraints
  requirements.md  — EARS-formatted requirements
  design.md        — Architecture and interfaces
  tasks.md         — Atomic implementation tasks
  security.md      — Security review and threat model
  evals.md         — Evaluation plan for agentic features
  mcp.md           — MCP tool surface design
  post-execution-log.md — Post-execution agent results

postmortems/       — Incident postmortem documents (created as needed)
docs/              — Additional documentation (created as needed)
```

## Naming Conventions
- Agent files: lowercase with hyphens (e.g., `spec-coordinator.json`)
- Prompt files: match agent name (e.g., `spec-coordinator.md`)
- Hook scripts: descriptive with hyphens (e.g., `dangerous-command-blocker.sh`)
- Spec artifacts: lowercase (e.g., `context.md`, `requirements.md`)
