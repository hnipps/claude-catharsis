# Claude Catharsis


_Where Claude confronts itself._

A self-improvement feedback loop for Claude Code. Analyzes your past conversations to detect failure patterns, then generates targeted instruction changes to prevent them.

```
Session ends → Collector → Analyzer → Improver → Human Review → Better instructions
```

## How it works

1. **Collector** — A Claude Code `SessionEnd` hook parses completed sessions into a local SQLite database. Extracts messages, tool calls, token usage, thinking traces, and git context.

2. **Analyzer** — Computes deterministic health metrics (turns to first commit, edit churn, tool error rate, etc.) and runs an LLM-as-judge pass via `claude -p` to detect failure patterns: loops, hallucinations, context loss, scope creep, instruction violations.

3. **Improver** — Takes the most frequent failure patterns and generates minimal, targeted changes to CLAUDE.md, project rules, or skills. Proposes modifications over additions, respects an instruction budget.

4. **Reviewer** — Interactive CLI to accept, reject, or edit each proposal with diff previews. Accepted changes are applied to the target files.

## Install

```bash
pip install -e .
```

## Usage

```bash
# Backfill all existing sessions into the database
catharsis collect

# Collect a specific session
catharsis collect --session-id <uuid>

# Run analysis (deterministic metrics + LLM judge)
catharsis analyze

# Metrics only, no LLM calls
catharsis analyze --skip-llm

# Generate improvement proposals from failure patterns
catharsis suggest

# Interactively review and apply proposals
catharsis review

# Show system status dashboard
catharsis status
```

## Configuration

Config lives at `~/.claude-analysis/config.yaml`. Key options:

| Key | Default | Description |
|-----|---------|-------------|
| `lookback_days` | 7 | Analysis window |
| `max_analysis_sessions` | 20 | Max sessions per LLM analysis run |
| `token_ceiling_pct` | 5.0 | Max analysis tokens as % of recent daily usage |
| `top_n_patterns` | 5 | Failure patterns to target for improvement |
| `instruction_budget_lines` | 200 | Max CLAUDE.md line count |
| `excluded_projects` | [] | Projects to skip during collection |
| `excluded_sessions` | [] | Session IDs to skip |

## Data

Everything stays local:

- **Database**: `~/.claude-analysis/conversations.db`
- **Archives**: `~/.claude-analysis/archive/{project}/{session}.jsonl`
- **Reports**: `~/.claude-analysis/reports/`
- **Proposals**: `~/.claude-analysis/proposals/`
- **Logs**: `~/.claude-analysis/logs/`

## Dependencies

Python 3.10+. No ML libraries, no Docker, no API keys.

- `click` — CLI
- `pyyaml` — config
- `rich` — terminal output

All LLM work runs through the `claude` CLI using your existing subscription.
