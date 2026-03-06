"""SQLite database management for cc-improve."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cc_improve.paths import DB_PATH, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    project_encoded TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT,
    duration_seconds REAL,
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_cache_read_tokens INTEGER DEFAULT 0,
    total_cache_creation_tokens INTEGER DEFAULT 0,
    model TEXT,
    git_branch TEXT,
    turn_count INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    has_commits INTEGER DEFAULT 0,
    archive_path TEXT,
    collected_at TEXT NOT NULL,
    cc_version TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    message_index INTEGER NOT NULL,
    uuid TEXT,
    parent_uuid TEXT,
    role TEXT NOT NULL,
    content_text TEXT,
    thinking_text TEXT,
    timestamp TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    model TEXT,
    is_tool_result INTEGER DEFAULT 0,
    UNIQUE(session_id, message_index)
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    message_index INTEGER NOT NULL,
    tool_use_id TEXT,
    tool_name TEXT NOT NULL,
    tool_input TEXT,
    tool_result TEXT,
    is_error INTEGER DEFAULT 0,
    file_path TEXT,
    UNIQUE(session_id, tool_use_id)
);

CREATE TABLE IF NOT EXISTS weekly_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL,
    previous_value REAL,
    pct_change REAL,
    computed_at TEXT NOT NULL,
    UNIQUE(window_start, window_end, metric_name)
);

CREATE TABLE IF NOT EXISTS session_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    analysis_timestamp TEXT NOT NULL,
    task_completion REAL,
    efficiency REAL,
    instruction_adherence REAL,
    failures TEXT,
    judge_prompt_version TEXT,
    analysis_run_id INTEGER,
    UNIQUE(session_id, analysis_run_id)
);

CREATE TABLE IF NOT EXISTS failure_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    failure_type TEXT NOT NULL,
    root_cause_cluster TEXT,
    occurrence_count INTEGER DEFAULT 0,
    severity_mode TEXT,
    example_session_ids TEXT,
    suggested_fixes TEXT,
    first_seen TEXT,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    failure_pattern_id INTEGER REFERENCES failure_patterns(id),
    title TEXT NOT NULL,
    target_file TEXT NOT NULL,
    change_type TEXT NOT NULL,
    current_content TEXT,
    proposed_content TEXT NOT NULL,
    rationale TEXT,
    status TEXT DEFAULT 'pending',
    rejection_reason TEXT,
    created_at TEXT NOT NULL,
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_timestamp TEXT NOT NULL,
    session_count INTEGER DEFAULT 0,
    prompt_version TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running'
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_name ON tool_calls(tool_name);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_path);
CREATE INDEX IF NOT EXISTS idx_sessions_start_time ON sessions(start_time);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
"""


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Get a SQLite connection with schema ensured."""
    ensure_dirs()
    p = db_path or DB_PATH
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes if they don't exist."""
    conn.executescript(SCHEMA)
