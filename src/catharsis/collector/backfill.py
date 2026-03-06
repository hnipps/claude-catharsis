"""Backfill historical sessions from ~/.claude/projects/."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from catharsis.collector.ingest import ingest_session
from catharsis.paths import CLAUDE_PROJECTS_DIR, decode_project_path

logger = logging.getLogger(__name__)


def discover_sessions(
    projects_dir: Path | None = None,
    excluded_projects: list[str] | None = None,
) -> list[tuple[Path, str, str]]:
    """Find all JSONL session files.

    Returns list of (jsonl_path, project_path, project_encoded).
    """
    base = projects_dir or CLAUDE_PROJECTS_DIR
    if not base.exists():
        logger.warning("Claude projects directory not found: %s", base)
        return []

    excluded = set(excluded_projects or [])
    results: list[tuple[Path, str, str]] = []

    for project_dir in sorted(base.iterdir()):
        if not project_dir.is_dir():
            continue

        project_encoded = project_dir.name
        project_path = decode_project_path(project_encoded)

        if project_path in excluded or project_encoded in excluded:
            logger.debug("Skipping excluded project: %s", project_path)
            continue

        for jsonl_file in sorted(project_dir.glob("*.jsonl")):
            results.append((jsonl_file, project_path, project_encoded))

    return results


def backfill(
    conn: sqlite3.Connection,
    projects_dir: Path | None = None,
    excluded_projects: list[str] | None = None,
    excluded_sessions: list[str] | None = None,
    force: bool = False,
) -> tuple[int, int]:
    """Backfill all historical sessions.

    Returns (ingested_count, skipped_count).
    """
    sessions = discover_sessions(projects_dir, excluded_projects)
    excluded_sess = set(excluded_sessions or [])

    ingested = 0
    skipped = 0

    for jsonl_path, project_path, project_encoded in sessions:
        session_id = jsonl_path.stem
        if session_id in excluded_sess:
            skipped += 1
            continue

        try:
            if ingest_session(conn, jsonl_path, project_path, project_encoded, force=force):
                ingested += 1
            else:
                skipped += 1
        except Exception:
            logger.exception("Failed to ingest %s", jsonl_path)
            skipped += 1

    return ingested, skipped
