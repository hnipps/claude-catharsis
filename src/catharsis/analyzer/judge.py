"""LLM-as-judge analysis via Claude Code CLI."""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from catharsis.paths import ARCHIVE_DIR, REPORTS_DIR, load_prompt, prompt_version

logger = logging.getLogger(__name__)


@dataclass
class CliResult:
    returncode: int
    stdout: str
    stderr_lines: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    timed_out: bool = False


def _run_claude_cli(
    cmd: list[str],
    timeout: int,
    on_stderr_line: Callable[[str], None] | None = None,
) -> CliResult:
    """Run Claude CLI with real-time stderr streaming."""
    stderr_lines: list[str] = []
    start = time.monotonic()

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    def _read_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stripped = line.rstrip("\n")
            stderr_lines.append(stripped)
            if on_stderr_line:
                on_stderr_line(stripped)

    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stderr_thread.start()

    timed_out = False
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, _ = proc.communicate()
        timed_out = True

    stderr_thread.join(timeout=2)
    elapsed = time.monotonic() - start

    return CliResult(
        returncode=proc.returncode if not timed_out else -1,
        stdout=stdout or "",
        stderr_lines=stderr_lines,
        elapsed=elapsed,
        timed_out=timed_out,
    )


def _get_unanalyzed_sessions(
    conn: sqlite3.Connection,
    lookback_days: int,
    max_sessions: int,
    force: bool = False,
) -> list[dict]:
    """Get sessions that haven't been analyzed yet."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

    if force:
        rows = conn.execute("""
            SELECT session_id, archive_path, project_path,
                   total_input_tokens + total_output_tokens as total_tokens
            FROM sessions
            WHERE start_time >= ?
            ORDER BY start_time DESC
            LIMIT ?
        """, (cutoff, max_sessions)).fetchall()
    else:
        rows = conn.execute("""
            SELECT s.session_id, s.archive_path, s.project_path,
                   s.total_input_tokens + s.total_output_tokens as total_tokens
            FROM sessions s
            LEFT JOIN session_analyses sa ON sa.session_id = s.session_id
            WHERE s.start_time >= ? AND sa.id IS NULL
            ORDER BY s.start_time DESC
            LIMIT ?
        """, (cutoff, max_sessions)).fetchall()

    return [dict(r) for r in rows]


def _estimate_token_cost(sessions: list[dict]) -> int:
    """Estimate tokens needed for analysis based on session sizes."""
    # Rough estimate: reading a session takes ~2x its token count
    return sum(s.get("total_tokens", 0) for s in sessions) * 2


def _get_daily_average_tokens(conn: sqlite3.Connection, days: int = 30) -> float:
    """Get average daily token usage over recent history."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    row = conn.execute("""
        SELECT COALESCE(SUM(total_input_tokens + total_output_tokens), 0) as total,
               COUNT(DISTINCT DATE(start_time)) as day_count
        FROM sessions WHERE start_time >= ?
    """, (cutoff,)).fetchone()

    total = row["total"]
    day_count = row["day_count"] or 1
    return total / day_count


def run_llm_analysis(
    conn: sqlite3.Connection,
    lookback_days: int = 7,
    max_sessions: int = 20,
    token_ceiling_pct: float = 5.0,
    force: bool = False,
    auto_confirm: bool = False,
    timeout: int = 600,
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    """Run LLM-as-judge analysis on unanalyzed sessions.

    Returns a summary dict with counts and any errors.
    """
    template = load_prompt("analyze")
    version = prompt_version(template)

    sessions = _get_unanalyzed_sessions(conn, lookback_days, max_sessions, force)
    if not sessions:
        return {"status": "no_sessions", "analyzed": 0}

    # Token ceiling check
    estimated_tokens = _estimate_token_cost(sessions)
    daily_avg = _get_daily_average_tokens(conn)
    ceiling = daily_avg * (token_ceiling_pct / 100)

    if estimated_tokens > ceiling and not auto_confirm:
        return {
            "status": "token_ceiling_exceeded",
            "estimated_tokens": estimated_tokens,
            "ceiling": ceiling,
            "session_count": len(sessions),
        }

    # Build the prompt with session info
    session_list = "\n".join(
        f"- {s['session_id']}: {s['archive_path']}" for s in sessions
    )
    prompt = template.replace("{{SESSION_LIST}}", session_list)
    prompt = prompt.replace("{{ARCHIVE_DIR}}", str(ARCHIVE_DIR))
    prompt = prompt.replace("{{REPORTS_DIR}}", str(REPORTS_DIR))

    # Record analysis run
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        cursor = conn.execute("""
            INSERT INTO analysis_runs (run_timestamp, session_count, prompt_version, status)
            VALUES (?, ?, ?, 'running')
        """, (now, len(sessions), version))
        run_id = cursor.lastrowid

    # Launch Claude Code CLI
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--max-turns", "30"]
    try:
        result = _run_claude_cli(cmd, timeout=timeout, on_stderr_line=on_progress)

        if result.timed_out:
            with conn:
                conn.execute("UPDATE analysis_runs SET status = 'timeout' WHERE id = ?", (run_id,))
            return {
                "status": "timeout",
                "elapsed": result.elapsed,
                "session_count": len(sessions),
                "stderr_tail": result.stderr_lines[-10:],
            }

        if result.returncode != 0:
            stderr_text = "\n".join(result.stderr_lines)
            logger.error("Claude CLI failed: %s", stderr_text)
            with conn:
                conn.execute("UPDATE analysis_runs SET status = 'failed' WHERE id = ?", (run_id,))
            return {
                "status": "cli_error",
                "error": stderr_text,
                "stderr_tail": result.stderr_lines[-10:],
            }

        # Parse the structured output
        output = json.loads(result.stdout) if result.stdout.strip() else {}
        _store_analysis_results(conn, output, run_id, version)

        # Update run status
        tokens_used = output.get("usage", {})
        with conn:
            conn.execute("""
                UPDATE analysis_runs SET status = 'completed',
                    input_tokens = ?, output_tokens = ?
                WHERE id = ?
            """, (
                tokens_used.get("input_tokens", 0),
                tokens_used.get("output_tokens", 0),
                run_id,
            ))

        return {"status": "completed", "analyzed": len(sessions), "run_id": run_id}

    except FileNotFoundError:
        with conn:
            conn.execute("UPDATE analysis_runs SET status = 'failed' WHERE id = ?", (run_id,))
        return {"status": "cli_not_found", "error": "claude CLI not found in PATH"}
    except Exception as e:
        logger.exception("Analysis run failed")
        with conn:
            conn.execute("UPDATE analysis_runs SET status = 'failed' WHERE id = ?", (run_id,))
        return {"status": "error", "error": str(e)}


def _store_analysis_results(
    conn: sqlite3.Connection,
    output: dict,
    run_id: int,
    prompt_version: str,
) -> None:
    """Parse and store analysis output in the database."""
    now = datetime.now(timezone.utc).isoformat()

    # The CC agent writes results as JSON with session analyses
    analyses = output.get("session_analyses", [])
    patterns = output.get("failure_patterns", [])

    with conn:
        for analysis in analyses:
            session_id = analysis.get("session_id")
            if not session_id:
                continue

            conn.execute("""
                INSERT OR REPLACE INTO session_analyses (
                    session_id, analysis_timestamp,
                    task_completion, efficiency, instruction_adherence,
                    failures, judge_prompt_version, analysis_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id, now,
                analysis.get("task_completion"),
                analysis.get("efficiency"),
                analysis.get("instruction_adherence"),
                json.dumps(analysis.get("failures", [])),
                prompt_version, run_id,
            ))

        for pattern in patterns:
            conn.execute("""
                INSERT INTO failure_patterns (
                    failure_type, root_cause_cluster, occurrence_count,
                    severity_mode, example_session_ids, suggested_fixes,
                    first_seen, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pattern.get("failure_type"),
                pattern.get("root_cause_cluster"),
                pattern.get("occurrence_count", 0),
                pattern.get("severity_mode"),
                json.dumps(pattern.get("example_session_ids", [])),
                json.dumps(pattern.get("suggested_fixes", [])),
                now, now,
            ))
