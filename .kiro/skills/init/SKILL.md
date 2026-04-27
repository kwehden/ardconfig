# /init — Bootstrap Spec-Driven Workflow

## Description

Initializes the spec-driven development workflow in the current project by creating the `spec/` directory and populating it with template files for all four workflow artifacts.

## When to Use

- At the start of a new project
- When adding KiroAgentPack to an existing project
- When the `spec/` directory does not yet exist

## Steps

1. Create the `spec/` directory if it does not exist.
2. Create `spec/context.md` from the template below (section headings with empty content placeholders).
3. Create `spec/requirements.md` from the template below.
4. Create `spec/design.md` from the template below.
5. Create `spec/tasks.md` from the template below.
6. If no project documentation exists (no `README.md`), recommend running the `repo-governor` agent to survey the codebase.
7. Print a summary of created files and the recommended next step.

## Templates

Use the templates defined in `references/artifact-templates.md`. Each template contains the required section headings with placeholder text prompting the user (or agent) to fill in content.

## After Running

The recommended workflow after `/init`:
1. Start the orchestrator agent
2. Describe your goal — the orchestrator will delegate to spec-coordinator to fill in `spec/context.md`
3. Review and approve each spec artifact through the quality gates
4. The orchestrator will manage the full lifecycle through implementation and verification

## References

See `references/artifact-templates.md` for the complete section templates.
