"""Generate improvement proposals from failure patterns."""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from cc_improve.paths import ARCHIVE_DIR, PROPOSALS_DIR, load_prompt, prompt_version

logger = logging.getLogger(__name__)


def get_top_patterns(
    conn: sqlite3.Connection,
    min_occurrences: int = 3,
    top_n: int = 5,
) -> list[dict]:
    """Get the top N failure patterns ranked by frequency x severity."""
    severity_weights = {"high": 3, "medium": 2, "low": 1}

    rows = conn.execute("""
        SELECT id, failure_type, root_cause_cluster, occurrence_count,
               severity_mode, example_session_ids, suggested_fixes
        FROM failure_patterns
        WHERE occurrence_count >= ?
        ORDER BY occurrence_count DESC
    """, (min_occurrences,)).fetchall()

    patterns = []
    for r in rows:
        weight = severity_weights.get(r["severity_mode"], 1)
        score = r["occurrence_count"] * weight
        patterns.append({**dict(r), "score": score})

    patterns.sort(key=lambda p: p["score"], reverse=True)
    return patterns[:top_n]


def generate_proposals(
    conn: sqlite3.Connection,
    top_n: int = 5,
    instruction_budget: int = 200,
    auto_confirm: bool = False,
) -> dict:
    """Generate improvement proposals via Claude Code CLI.

    Returns a summary dict.
    """
    patterns = get_top_patterns(conn, top_n=top_n)
    if not patterns:
        return {"status": "no_patterns", "proposals": 0}

    template = load_prompt("improve")
    version = prompt_version(template)

    # Build pattern summary for the prompt
    pattern_text = json.dumps(patterns, indent=2)

    # Gather example session archive paths
    session_ids = set()
    for p in patterns:
        try:
            ids = json.loads(p.get("example_session_ids", "[]"))
            session_ids.update(ids[:3])
        except (json.JSONDecodeError, TypeError):
            pass

    session_paths = []
    if session_ids:
        placeholders = ",".join("?" for _ in session_ids)
        rows = conn.execute(
            f"SELECT archive_path FROM sessions WHERE session_id IN ({placeholders})",
            list(session_ids),
        ).fetchall()
        session_paths = [r["archive_path"] for r in rows if r["archive_path"]]

    prompt = template.replace("{{FAILURE_PATTERNS}}", pattern_text)
    prompt = prompt.replace("{{SESSION_ARCHIVE_PATHS}}", "\n".join(session_paths))
    prompt = prompt.replace("{{ARCHIVE_DIR}}", str(ARCHIVE_DIR))
    prompt = prompt.replace("{{PROPOSALS_DIR}}", str(PROPOSALS_DIR))
    prompt = prompt.replace("{{INSTRUCTION_BUDGET}}", str(instruction_budget))

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json", "--max-turns", "50"],
            capture_output=True,
            text=True,
            timeout=900,
        )

        if result.returncode != 0:
            logger.error("Claude CLI failed: %s", result.stderr)
            return {"status": "cli_error", "error": result.stderr}

        output = json.loads(result.stdout) if result.stdout.strip() else {}
        proposals = output.get("proposals", [])

        # Store proposals
        now = datetime.now(timezone.utc).isoformat()
        with conn:
            for prop in proposals:
                conn.execute("""
                    INSERT INTO proposals (
                        failure_pattern_id, title, target_file, change_type,
                        current_content, proposed_content, rationale,
                        status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """, (
                    prop.get("failure_pattern_id"),
                    prop.get("title", "Untitled"),
                    prop.get("target_file", "CLAUDE.md"),
                    prop.get("change_type", "addition"),
                    prop.get("current_content"),
                    prop.get("proposed_content", ""),
                    prop.get("rationale"),
                    now,
                ))

        # Write proposals markdown
        _write_proposals_markdown(proposals, now)

        return {"status": "completed", "proposals": len(proposals)}

    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    except FileNotFoundError:
        return {"status": "cli_not_found", "error": "claude CLI not found in PATH"}
    except Exception as e:
        logger.exception("Proposal generation failed")
        return {"status": "error", "error": str(e)}


def _write_proposals_markdown(proposals: list[dict], date_str: str) -> Path:
    """Write proposals to a Markdown file."""
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    date_short = date_str[:10]
    path = PROPOSALS_DIR / f"{date_short}-proposals.md"

    lines = [
        f"# Improvement Proposals",
        f"",
        f"**Generated**: {date_short}",
        f"**Count**: {len(proposals)}",
        f"",
    ]

    for i, prop in enumerate(proposals, 1):
        lines.extend([
            f"## {i}. {prop.get('title', 'Untitled')}",
            f"",
            f"**Target**: `{prop.get('target_file', 'CLAUDE.md')}`",
            f"**Type**: {prop.get('change_type', 'addition')}",
            f"",
            f"**Rationale**: {prop.get('rationale', 'N/A')}",
            f"",
        ])

        if prop.get("current_content"):
            lines.extend([
                "**Current**:",
                "```",
                prop["current_content"],
                "```",
                "",
            ])

        lines.extend([
            "**Proposed**:",
            "```",
            prop.get("proposed_content", ""),
            "```",
            "",
            "---",
            "",
        ])

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
