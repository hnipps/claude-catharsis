# V1 Requirements: Claude Code Conversation Analysis & Self-Improvement

## Design Philosophy

**Close the loop, then optimize it.** V1 prioritizes a working end-to-end feedback cycle over analytical sophistication. Every design decision follows from one question: *does this help me ship a system that actually improves my Claude Code workflow within two weeks?*

Four principles guide scoping:

1. **LLM-as-judge over ML infrastructure.** No embeddings, no Sentence-BERT, no separate ML models. Claude itself is the analyzer. It can detect loops, frustration, context loss, and hallucinations through direct conversation review — and it produces richer natural-language failure explanations than any algorithmic approach. This eliminates the entire ML dependency chain from V1.

2. **Claude Code as the analysis engine.** The Analyzer and Improver run as Claude Code CLI sessions (`claude -p "prompt"`), not as raw API calls. This means the agent can read JSONL files, CLAUDE.md, rules, and skills directly from disk — no transcript concatenation, no context window juggling, no API key management. Analysis cost is covered by the existing Claude subscription.

3. **Local-first, no new servers.** No Langfuse, no Docker Compose, no ClickHouse. V1 runs as local scripts triggered by Claude Code hooks, storing everything in SQLite and the filesystem. Observability infrastructure is a V2 concern — the bottleneck right now is not visualization, it's having any feedback loop at all.

4. **Broad improvement targets.** The system doesn't just improve CLAUDE.md. It proposes changes to CLAUDE.md, project rules, skills (SKILL.md), and can suggest new skills or workflow patterns. The output is whatever instruction artifact best addresses the detected failure.

---

## System Overview

```
┌──────────────┐     ┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│ Claude Code  │────▶│  Collector   │────▶│   Analyzer    │────▶│  Improver    │
│ SessionEnd   │     │  (hook script)│    │  (CC CLI      │     │ (CC CLI      │
│              │     │              │     │   session)    │     │  session)    │
│ ~/.claude/   │     │  SQLite DB   │     │               │     │              │
│ projects/    │     │  + raw JSONL │     │ Deterministic │     │ Proposed     │
│ *.jsonl      │     │  archive     │     │ metrics +     │     │ changes      │
└──────────────┘     └──────────────┘     │ LLM-as-judge  │     │ to rules     │
                                          └───────────────┘     └──────┬───────┘
                                                                       │
                                                                ┌──────▼───────┐
                                                                │ Human Review │
                                                                │ (accept/     │
                                                                │  reject/edit)│
                                                                └──────────────┘
```

The system has four components. Each must work independently and be testable in isolation.

---

## Component 1: Collector

**Purpose:** Parse completed Claude Code sessions into structured, queryable data.

### Trigger

A Claude Code `SessionEnd` hook that fires after every conversation. The hook script reads the just-completed session's JSONL file and processes it.

### Input

Raw JSONL files from `~/.claude/projects/{encoded-path}/{session-uuid}.jsonl`, plus index files:
- `~/.claude/projects/{encoded-path}/sessions-index.json` (session metadata)
- `~/.claude/history.jsonl` (global input log)

### Processing

Parse each JSONL line and extract:

| Field | Source | Purpose |
|-------|--------|---------|
| `session_id` | Message metadata | Primary key, links all data for one conversation |
| `project_path` | Encoded in directory path | Group sessions by project |
| `timestamp` | Each message | Ordering, duration calculation |
| `role` | Message type | Distinguish user/assistant/system |
| `content_text` | Content blocks (type=text) | The actual conversation for analysis |
| `thinking_text` | Content blocks (type=thinking) | Reasoning traces — rich signal for failure analysis |
| `tool_calls` | Content blocks (type=tool_use) | What tools were invoked, with what params |
| `tool_results` | Content blocks (type=tool_result) | What tools returned, including errors |
| `model` | Assistant message metadata | Track model version |
| `input_tokens` | Usage stats | Cost and efficiency tracking |
| `output_tokens` | Usage stats | Cost and efficiency tracking |
| `cache_read_tokens` | Usage stats | Cache hit rate |
| `git_branch` | Message metadata | Correlate with code changes |
| `summary` | Summary messages | Auto-generated session summaries |

### Storage

**SQLite database** at `~/.claude-analysis/conversations.db` with these tables:

- `sessions` — one row per conversation: session_id, project, start/end time, total tokens, total cost, model, git_branch, turn_count, summary
- `messages` — one row per message: session_id, message_index, role, content_text, thinking_text, timestamp, input_tokens, output_tokens
- `tool_calls` — one row per tool invocation: session_id, message_index, tool_name, tool_input (JSON), tool_result (truncated to 2000 chars), is_error, duration_ms

Also archive raw JSONL files to `~/.claude-analysis/archive/{project}/{session-uuid}.jsonl` for reprocessing.

### Configuration

In `~/.claude/settings.json`:
```json
{
  "cleanupPeriodDays": 100000
}
```

### Requirements

- **C1.1** The collector must be idempotent — running it twice on the same session produces identical database state
- **C1.2** The collector must handle malformed JSONL lines gracefully (log and skip)
- **C1.3** The collector must complete within 5 seconds for a typical session (< 200 messages)
- **C1.4** The collector must back-fill: on first run, process all existing JSONL files in `~/.claude/projects/`
- **C1.5** The collector must be installable as a Claude Code hook with a single command

---

## Component 2: Analyzer

**Purpose:** Compute deterministic health metrics from collected data, then use Claude Code CLI to review conversations, detect failure patterns, and build an error taxonomy.

### Trigger

Manual invocation or scheduled (cron/launchd). Not triggered per-session — it operates in batch over recent conversations. Suggested cadence: weekly, or on-demand after a frustrating session.

### Input

All sessions from the SQLite database within a configurable lookback window (default: 7 days). The Claude Code CLI agent also reads the current CLAUDE.md, project rules, and any SKILL.md files directly from disk.

### Part A: Deterministic Metrics

Five objective metrics computed directly from the SQLite data with zero LLM involvement. Each metric is tracked per-session and aggregated over the lookback window, with **% change vs. the prior equivalent window** (e.g., this week vs. last week) and a simple trend arrow (↑ improving, ↓ degrading, → stable).

**Metric 1: Turns to First Commit**
Count of user messages in a session before the first tool call containing `git commit`. Measures how efficiently Claude reaches working, committed code. Sessions with no commit are excluded from this metric (captured separately below). Lower is better.

**Metric 2: Commit-less Session Rate**
Percentage of sessions that end without any `git commit` tool call. Captures abandoned work, failed attempts, and sessions where Claude never produced committable output. Excludes sessions that are clearly non-coding (e.g., pure Q&A — identified by absence of Write/Edit tool calls). Lower is better.

**Metric 3: File Edit Churn**
Total Write/Edit tool calls targeting the same file path within a session, divided by the number of distinct files edited. A ratio of 1.0 means every file was touched once; 3.0+ suggests significant rework and thrashing. Averaged across sessions. Lower is better.

**Metric 4: Tokens per Line Changed**
Total session tokens (input + output) divided by net lines of code changed (sum of insertions and deletions across all Write/Edit tool calls). Measures raw efficiency — how much "thinking" goes into each line of actual output. Averaged across coding sessions. Lower is better.

**Metric 5: Tool Error Rate**
Percentage of Bash tool calls that return a non-zero exit code, plus Write/Edit calls that fail. Proxy for hallucinated commands, wrong file paths, incorrect assumptions about the environment. Averaged across sessions. Lower is better.

**Reporting format:**

```
╔══════════════════════════════════════════════════════════════╗
║  WEEKLY HEALTH METRICS  (Feb 24 – Mar 2 vs Feb 17 – Feb 23)║
╠══════════════════════════════════════════════════════════════╣
║  Turns to First Commit    4.2 avg   (was 5.8)    ↑ -28%    ║
║  Commit-less Session Rate 18%       (was 22%)    ↑ -4pp     ║
║  File Edit Churn          1.8x      (was 2.1x)   ↑ -14%    ║
║  Tokens per Line Changed  342       (was 410)    ↑ -17%    ║
║  Tool Error Rate          12%       (was 9%)     ↓ +3pp     ║
╚══════════════════════════════════════════════════════════════╝
```

### Part B: LLM-as-Judge via Claude Code CLI

The analyzer launches a Claude Code CLI session to perform qualitative analysis:

```bash
claude -p "$(cat ~/.claude-analysis/prompts/analyze.md)" \
  --output-format json \
  --max-turns 30
```

The analyze prompt instructs the Claude Code agent to:
1. Read the SQLite database to identify sessions in the lookback window
2. Read the raw JSONL files for those sessions directly from `~/.claude-analysis/archive/`
3. Read the current CLAUDE.md, project rules, and skills from the project directories
4. For each session, produce structured evaluation output

**The agent has full filesystem access**, so it can read conversation files of any length without transcript concatenation or context window management on our part. It handles its own context by reading files selectively, summarizing long tool outputs, and focusing on the most relevant conversation segments.

For each session, the judge produces:

**Session-level scores** (1–5 scale):
- `task_completion` — Did Claude achieve what the user wanted?
- `efficiency` — Was the token/turn count reasonable for the task complexity?
- `instruction_adherence` — Did Claude follow the project's CLAUDE.md and rules?

**Failure pattern detection** (boolean + evidence):
- `is_cyclical` — Did Claude repeat itself or get stuck in a loop? Quote the repeated segments.
- `has_context_loss` — Did Claude forget earlier context or contradict itself?
- `has_hallucination` — Did Claude reference nonexistent APIs, files, or capabilities?
- `has_user_frustration` — Did the user express frustration, rephrase requests, or correct Claude?
- `has_scope_creep` — Did the conversation drift from the original task?
- `has_tool_misuse` — Did Claude use tools inefficiently (unnecessary reads, redundant searches, etc.)?
- `has_instruction_violation` — Did Claude violate a specific rule from CLAUDE.md or project rules?

**For each detected failure:**
- `failure_type` — Category from the list above
- `severity` — low / medium / high
- `description` — Natural language explanation of what went wrong
- `evidence` — Specific message indices and quoted content
- `root_cause` — Why this happened (missing instruction? ambiguous rule? inherent limitation?)
- `suggested_fix` — What instruction change might prevent this

The agent writes its structured output (JSON) to `~/.claude-analysis/reports/` and updates the SQLite database directly.

### Output

**Deterministic metrics** stored in a `weekly_metrics` table:
- window_start, window_end, metric_name, value, previous_value, pct_change

**Per-session analysis** stored in a `session_analyses` table:
- session_id, analysis_timestamp, scores (JSON), failures (JSON array), judge_prompt_version

**Error taxonomy** — an aggregated view across all analyzed sessions:
- Group failures by `failure_type` and `root_cause`
- Count occurrences of each pattern
- Rank by frequency × severity
- Store in a `failure_patterns` table: pattern_id, failure_type, root_cause_cluster, occurrence_count, severity_mode, example_session_ids (JSON array), suggested_fixes (JSON array)

**Combined Markdown report** at `~/.claude-analysis/reports/{date}-analysis.md` containing both the metrics dashboard and the qualitative findings.

### Requirements

- **A1.1** Deterministic metrics must be computable without any LLM calls — pure SQL/Python over the SQLite database
- **A1.2** The judge prompt must be versioned — changes to the evaluation criteria are tracked so results are comparable over time
- **A1.3** The analyzer must produce a combined human-readable report (Markdown) with both metrics and qualitative findings
- **A1.4** The analyzer must respect a configurable token ceiling per batch run (default: 5% of the user's recent daily average token usage, estimated from collected session data). Before running, it estimates token cost based on session count × average session size and requires confirmation if above the ceiling.
- **A1.5** The analyzer must skip sessions already analyzed (unless `--force` flag)
- **A1.6** The error taxonomy must merge similar root causes across sessions — the CC CLI agent handles this clustering as part of its analysis
- **A1.7** Analysis results must include the judge prompt version used, for reproducibility
- **A1.8** The CC CLI session must write structured JSON output that the collector script can parse and insert into SQLite — the agent is given a schema to follow

---

## Component 3: Improver

**Purpose:** Generate specific, actionable instruction changes that address the most frequent failure patterns.

### Trigger

Manual invocation after reviewing an analysis report. Not automated in V1 — human judgment is required to decide when the error taxonomy has enough signal to act on.

### Input

- The current error taxonomy (failure_patterns table, filtered to patterns with 3+ occurrences)
- The current CLAUDE.md file for the target project
- The current project rules (`.claude/rules/` directory)
- The current SKILL.md files (`.claude/skills/` directory)
- 2–3 representative conversation transcripts for each targeted failure pattern

### Processing: Meta-Prompt Optimization via Claude Code CLI

The improver launches a Claude Code CLI session, similar to the analyzer:

```bash
claude -p "$(cat ~/.claude-analysis/prompts/improve.md)" \
  --output-format json \
  --max-turns 50
```

The improve prompt instructs the Claude Code agent to implement the Arize "Prompt Learning" approach adapted for broader instruction targets:

1. Read the error taxonomy from the SQLite database, filtered to the top N patterns by frequency × severity (default N=5)
2. For each pattern, read the full conversation JSONL files of representative sessions directly from `~/.claude-analysis/archive/`
3. Read the current CLAUDE.md, project rules, and skills from the project directories on disk
4. Generate specific, minimal changes that address each failure pattern without adding unnecessary bloat
5. Enforce the instruction budget constraint: total CLAUDE.md should stay under 200 lines, preferring modification of existing rules over addition of new ones
6. If the fix is better expressed as a skill (domain-specific, conditionally loaded), generate a SKILL.md instead of adding to CLAUDE.md
7. Write the proposals as structured JSON and a human-readable Markdown report to `~/.claude-analysis/proposals/`

### Output

For each proposed change, produce:

```
## Proposed Change: [short title]

**Addresses pattern:** [failure_type] — [root_cause_cluster]
**Occurrences:** [count] across [N] sessions
**Severity:** [low/medium/high]

**Target file:** CLAUDE.md | .claude/rules/[name].md | .claude/skills/[name]/SKILL.md

**Change type:** addition | modification | deletion

**Current content** (if modifying):
> [existing instruction text]

**Proposed content:**
> [new instruction text]

**Rationale:** [why this change addresses the failure pattern]

**Example session:** [session_id] — [brief description of how this would have helped]
```

### Requirements

- **I1.1** Each proposed change must cite specific failure pattern evidence — no generic "best practices"
- **I1.2** The improver must check for conflicts with existing instructions before proposing additions
- **I1.3** The improver must output a total instruction count (current + proposed additions - proposed deletions) and warn if approaching the 200-line ceiling
- **I1.4** Proposed changes must be formatted as copy-pasteable content that can be directly inserted into the target file
- **I1.5** The improver must distinguish between CLAUDE.md-level rules (always loaded) and skill-level rules (loaded on trigger) and recommend the appropriate level
- **I1.6** The improver should suggest pruning instructions that address patterns no longer appearing in recent conversations

---

## Component 4: Human Review Interface

**Purpose:** Present proposed changes for human decision-making.

### V1 Scope

V1 does not build a UI. The review interface is:

1. A Markdown report file generated by the improver, containing all proposed changes with evidence
2. A CLI command (`catharsis review`) that walks through each proposal interactively: shows the proposal, accepts/rejects/edits, and applies accepted changes to the target files
3. A simple log of decisions (accepted, rejected with reason, edited) stored in the SQLite database for the system to learn which types of proposals get accepted

### Requirements

- **R1.1** The review CLI must show a diff preview before applying any change
- **R1.2** Rejected proposals must record a reason (free text) — this feedback improves future meta-prompt quality
- **R1.3** Accepted changes must be applied atomically — either all file modifications for a proposal succeed, or none do
- **R1.4** The review process must create a git commit (if in a git repo) with a descriptive message referencing the failure pattern addressed

---

## Cross-Cutting Requirements

### Installation & Configuration

- **X1.1** The entire system installs via a single script that sets up the Claude Code hook, creates the SQLite database, and adds CLI commands (`catharsis collect`, `catharsis analyze`, `catharsis suggest`, `catharsis review`)
- **X1.2** All configuration lives in a single YAML file at `~/.claude-analysis/config.yaml` with sensible defaults
- **X1.3** The system must work on macOS and Linux

### Data & Privacy

- **X2.1** All data stays local — no external services, no telemetry. Analysis runs use Claude Code CLI which uses the existing subscription.
- **X2.2** Users can exclude specific projects or sessions from analysis via config
- **X2.3** The CC CLI sessions used for analysis are themselves collected and excluded from future analysis (to avoid self-referential loops)

### Cost Control

- **X3.1** Analysis runs use the existing Claude subscription via Claude Code CLI — no separate API costs. The system estimates token usage before each run based on session count × average session size, and requires confirmation if the estimated usage exceeds 5% of the user's recent daily average (configurable 5–10%).
- **X3.2** The system tracks cumulative analysis token usage in the database (parsed from `--output-format json` which includes token counts)
- **X3.3** The `catharsis status` command shows analysis token usage as a percentage of recent total session usage, so the user can judge whether the system is consuming a reasonable share of their subscription

### Observability

- **X4.1** Every component logs to `~/.claude-analysis/logs/` with rotation
- **X4.2** The `catharsis status` command shows: sessions collected, sessions analyzed, active failure patterns, pending proposals, analysis token usage (absolute and as % of total CC usage)

---

## Implementation Language & Dependencies

**Python 3.10+** for all components. Dependencies limited to:

- `sqlite3` (stdlib) — storage
- `subprocess` (stdlib) — launching Claude Code CLI sessions
- `click` — CLI framework
- `pyyaml` — configuration
- `rich` — terminal output and diff display

No ML libraries, no embedding models, no Docker, no Node.js, no Anthropic SDK. The system shells out to `claude` CLI for all LLM work.

---

## What V1 Explicitly Defers

| Deferred to V2+ | Why |
|------------------|-----|
| Langfuse / observability platform | Adds infra complexity without proportional V1 value |
| Sentence-BERT embeddings | LLM-as-judge handles the same detection tasks |
| GitHub Agentic Workflows | Research preview; local cron is more reliable |
| Automated PR creation | Human review is critical for trust-building |
| Promptfoo eval suites | Requires a golden dataset that doesn't exist yet |
| Real-time session monitoring | Batch analysis is sufficient for the feedback loop |
| Multi-user support | Personal tool first |
| Web dashboard | CLI + Markdown reports are adequate |
| AST-level code analysis | LLM judge can assess code quality directly |

---

## Success Criteria

V1 is successful if, after two weeks of use:

1. The system has identified at least 3 recurring failure patterns in my Claude Code sessions
2. At least 2 instruction changes have been accepted and applied
3. Subsequent sessions show measurable reduction in the targeted failure patterns (re-analysis confirms lower occurrence count)
4. The total system token usage (analysis + improvement sessions) stays under 10% of regular Claude Code session usage
5. The end-to-end cycle (session → collection → analysis → proposal → review → applied change) completes in under 30 minutes of human time
6. The deterministic metrics show measurable trend improvement (at least 2 of 5 metrics improving week-over-week)
