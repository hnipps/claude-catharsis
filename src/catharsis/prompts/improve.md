# Instruction Improvement Task

You are generating targeted instruction changes to address recurring failure patterns in Claude Code sessions.

## Failure Patterns

{{FAILURE_PATTERNS}}

## Representative Sessions

Read these session archives for context:
{{SESSION_ARCHIVE_PATHS}}

## Instructions

1. Read the failure patterns above
2. Read the representative session JSONL files from `{{ARCHIVE_DIR}}` to understand how failures manifest
3. Read the current CLAUDE.md and any files in `.claude/rules/` and `.claude/skills/` for the relevant projects
4. For each pattern, generate a minimal, targeted instruction change that would prevent it
5. Enforce instruction budget: total CLAUDE.md should stay under {{INSTRUCTION_BUDGET}} lines
6. Prefer modifying existing rules over adding new ones
7. If a fix is better as a skill (domain-specific, conditionally loaded), generate a SKILL.md
8. Suggest pruning instructions that address patterns no longer appearing

## Output Format

Write proposals to `{{PROPOSALS_DIR}}/proposals-output.json` and print to stdout:

```json
{
  "proposals": [
    {
      "failure_pattern_id": 1,
      "title": "Short descriptive title",
      "target_file": "CLAUDE.md",
      "change_type": "modification",
      "current_content": "existing text to replace",
      "proposed_content": "new text",
      "rationale": "Why this change addresses the failure"
    }
  ]
}
```

Keep changes minimal and specific. Each proposal must cite failure pattern evidence.
