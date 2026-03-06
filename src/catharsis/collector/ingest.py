"""Ingest parsed sessions into SQLite."""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from catharsis.collector.parser import ParsedSession, _extract_text, parse_jsonl
from catharsis.collector.session import compute_stats
from catharsis.paths import ARCHIVE_DIR

logger = logging.getLogger(__name__)


def _archive_jsonl(source: Path, project_encoded: str) -> Path:
    """Copy JSONL to archive directory. Returns archive path."""
    dest_dir = ARCHIVE_DIR / project_encoded
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source.name
    shutil.copy2(source, dest)
    return dest


def session_exists(conn: sqlite3.Connection, session_id: str) -> bool:
    """Check if a session is already in the database."""
    row = conn.execute(
        "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    return row is not None


def ingest_session(
    conn: sqlite3.Connection,
    jsonl_path: Path,
    project_path: str,
    project_encoded: str,
    force: bool = False,
) -> bool:
    """Parse and ingest a single session JSONL file.

    Returns True if the session was ingested, False if skipped.
    """
    parsed = parse_jsonl(jsonl_path)
    if not parsed:
        logger.warning("Could not parse %s", jsonl_path)
        return False

    if not force and session_exists(conn, parsed.session_id):
        logger.debug("Session %s already exists, skipping", parsed.session_id)
        return False

    stats = compute_stats(parsed)
    archive_path = _archive_jsonl(jsonl_path, project_encoded)
    now = datetime.now(timezone.utc).isoformat()

    # Use a transaction for atomicity
    with conn:
        # Upsert session
        conn.execute("""
            INSERT OR REPLACE INTO sessions (
                session_id, project_path, project_encoded,
                start_time, end_time, duration_seconds,
                total_input_tokens, total_output_tokens,
                total_cache_read_tokens, total_cache_creation_tokens,
                model, git_branch, turn_count, message_count,
                tool_call_count, has_commits, archive_path,
                collected_at, cc_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            parsed.session_id, project_path, project_encoded,
            parsed.start_time, parsed.end_time, stats.duration_seconds,
            stats.total_input_tokens, stats.total_output_tokens,
            stats.total_cache_read_tokens, stats.total_cache_creation_tokens,
            parsed.model, parsed.git_branch, stats.turn_count,
            stats.message_count, stats.tool_call_count,
            int(stats.has_commits), str(archive_path), now, parsed.cc_version,
        ))

        # Delete old messages/tool_calls if re-ingesting
        if force:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (parsed.session_id,))
            conn.execute("DELETE FROM tool_calls WHERE session_id = ?", (parsed.session_id,))

        # Insert messages
        for msg in parsed.messages:
            conn.execute("""
                INSERT OR IGNORE INTO messages (
                    session_id, message_index, uuid, parent_uuid,
                    role, content_text, thinking_text, timestamp,
                    input_tokens, output_tokens, cache_read_tokens,
                    cache_creation_tokens, model, is_tool_result
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                parsed.session_id, msg.index, msg.uuid, msg.parent_uuid,
                msg.role, msg.content_text, msg.thinking_text, msg.timestamp,
                msg.input_tokens, msg.output_tokens, msg.cache_read_tokens,
                msg.cache_creation_tokens, msg.model, int(msg.is_tool_result),
            ))

            # Insert tool calls
            for tu in msg.tool_uses:
                tool_use_id = tu.get("id", "")
                tool_name = tu.get("name", "unknown")
                tool_input = json.dumps(tu.get("input", {}))

                # Extract file_path from tool input if present
                inp = tu.get("input", {})
                file_path = None
                if isinstance(inp, dict):
                    file_path = inp.get("file_path") or inp.get("path")

                conn.execute("""
                    INSERT OR IGNORE INTO tool_calls (
                        session_id, message_index, tool_use_id,
                        tool_name, tool_input, is_error, file_path
                    ) VALUES (?, ?, ?, ?, ?, 0, ?)
                """, (
                    parsed.session_id, msg.index, tool_use_id,
                    tool_name, tool_input, file_path,
                ))

        # Match tool results to tool calls
        for msg in parsed.messages:
            for tr in msg.tool_results:
                tool_use_id = tr.get("tool_use_id")
                if not tool_use_id:
                    continue

                raw_content = tr.get("content", "")
                result_content = _extract_text(raw_content)
                if not result_content and raw_content:
                    result_content = json.dumps(raw_content) if not isinstance(raw_content, str) else raw_content

                # Truncate to 2000 chars
                result_content = result_content[:2000] if result_content else ""
                is_error = 1 if tr.get("is_error") else 0

                conn.execute("""
                    UPDATE tool_calls
                    SET tool_result = ?, is_error = ?
                    WHERE session_id = ? AND tool_use_id = ?
                """, (result_content, is_error, parsed.session_id, tool_use_id))

    logger.info("Ingested session %s (%d messages, %d tool calls)",
                parsed.session_id, stats.message_count, stats.tool_call_count)
    return True
