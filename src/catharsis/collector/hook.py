"""SessionEnd hook handler — processes a single session on completion."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from catharsis.collector.ingest import ingest_session
from catharsis.db import ensure_schema, get_connection
from catharsis.paths import CLAUDE_PROJECTS_DIR, decode_project_path, ensure_dirs

logger = logging.getLogger(__name__)


def read_hook_payload() -> dict:
    """Read JSON payload from stdin (Claude Code hooks pass JSON on stdin)."""
    try:
        data = sys.stdin.read()
        if not data.strip():
            return {}
        return json.loads(data)
    except Exception:
        return {}


def _find_jsonl(session_id: str) -> tuple[Path, str, str] | None:
    """Find the JSONL file for a session ID by scanning project directories."""
    if not CLAUDE_PROJECTS_DIR.exists():
        return None

    for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        jsonl_path = project_dir / f"{session_id}.jsonl"
        if jsonl_path.exists():
            project_encoded = project_dir.name
            project_path = decode_project_path(project_encoded)
            return jsonl_path, project_path, project_encoded

    return None


def handle_session_end(payload: dict | None = None) -> bool:
    """Handle a SessionEnd hook event.

    Returns True if the session was processed successfully.
    Fails open — never raises exceptions.
    """
    try:
        if payload is None:
            payload = read_hook_payload()

        session_id = (
            payload.get("session_id")
            or payload.get("sessionId")
            or payload.get("session", {}).get("id")
        )

        transcript_path_str = (
            payload.get("transcript_path")
            or payload.get("transcriptPath")
            or payload.get("transcript", {}).get("path")
        )

        ensure_dirs()
        conn = get_connection()
        ensure_schema(conn)

        if transcript_path_str:
            transcript_path = Path(transcript_path_str).expanduser().resolve()
            if transcript_path.exists():
                # Derive project info from transcript path
                project_dir = transcript_path.parent
                project_encoded = project_dir.name
                project_path = decode_project_path(project_encoded)

                return ingest_session(conn, transcript_path, project_path, project_encoded)

        if session_id:
            result = _find_jsonl(session_id)
            if result:
                jsonl_path, project_path, project_encoded = result
                return ingest_session(conn, jsonl_path, project_path, project_encoded)

        logger.warning("Could not find session JSONL for payload: %s", payload)
        return False

    except Exception:
        logger.exception("Hook handler failed (fail-open)")
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass
