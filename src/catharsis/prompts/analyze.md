# Session Analysis Task

You are analyzing Claude Code conversation transcripts to detect failure patterns and evaluate session quality.

## Sessions to Analyze

{{SESSION_LIST}}

## Instructions

1. Read each session JSONL file from `{{ARCHIVE_DIR}}`
2. For each session, evaluate:
   - **task_completion** (1-5): Did Claude achieve what the user wanted?
   - **efficiency** (1-5): Was the token/turn count reasonable?
   - **instruction_adherence** (1-5): Did Claude follow project rules?

3. Detect these failure patterns (boolean + evidence):
   - **is_cyclical**: Repeated same approach without progress
   - **has_context_loss**: Forgot earlier context or contradicted itself
   - **has_hallucination**: Referenced nonexistent APIs, files, or capabilities
   - **has_user_frustration**: User expressed frustration or had to correct Claude
   - **has_scope_creep**: Conversation drifted from original task
   - **has_tool_misuse**: Used tools inefficiently
   - **has_instruction_violation**: Violated specific project rules

4. For each detected failure, provide:
   - `failure_type`: category from above
   - `severity`: low / medium / high
   - `description`: what went wrong
   - `evidence`: message indices and quotes
   - `root_cause`: why it happened
   - `suggested_fix`: what instruction change might prevent it

5. Aggregate patterns across all sessions

## Output Format

Write a JSON file to `{{REPORTS_DIR}}/analysis-output.json` with this structure:

```json
{
  "session_analyses": [
    {
      "session_id": "...",
      "task_completion": 4,
      "efficiency": 3,
      "instruction_adherence": 5,
      "failures": [
        {
          "failure_type": "has_tool_misuse",
          "severity": "medium",
          "description": "...",
          "evidence": "...",
          "root_cause": "...",
          "suggested_fix": "..."
        }
      ]
    }
  ],
  "failure_patterns": [
    {
      "failure_type": "has_tool_misuse",
      "root_cause_cluster": "redundant file reads",
      "occurrence_count": 5,
      "severity_mode": "medium",
      "example_session_ids": ["..."],
      "suggested_fixes": ["..."]
    }
  ]
}
```

Then print the JSON to stdout.
