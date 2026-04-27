---
inclusion: always
---
# Technical Context

## Agent Configuration
- Agents are JSON files in `.kiro/agents/`
- System prompts are markdown files in `.kiro/prompts/`, referenced via `file://` URIs
- Each agent declares its tools, allowed tools, and write path restrictions in `toolsSettings`

## Tool Inventory
Available tools: `read`, `write`, `glob`, `grep`, `shell`, `code`, `web_search`, `web_fetch`, `use_subagent`, `delegate`, `thinking`, `todo`

## Write Isolation
Each agent can only write to paths listed in its `toolsSettings.write.allowedPaths`. This is enforced by Kiro CLI at the tool level.

## Hook System
- PreToolUse hooks can block operations (exit code 2)
- PostToolUse hooks run after operations (informational, exit 0)
- Hook scripts are bash, located in `.kiro/hooks/`
- Hooks receive `TOOL_INPUT` as an environment variable (JSON)

## Delegation
- Only the orchestrator agent has `use_subagent`
- Subagents cannot spawn other subagents
- Trusted agents run without user confirmation; untrusted agents require confirmation per delegation

## Spec Artifacts
- The `spec/` directory contains workflow artifacts created per-project
- Artifacts are markdown files with structured sections
- Each spec agent can only write to its designated spec file
