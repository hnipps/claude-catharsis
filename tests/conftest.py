"""Shared test fixtures."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from catharsis.db import ensure_schema


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    """In-memory-like SQLite connection with schema."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


@pytest.fixture
def sample_jsonl(tmp_path: Path) -> Path:
    """Create a sample JSONL session file."""
    session_id = "test-session-001"
    lines = [
        {
            "type": "user",
            "sessionId": session_id,
            "version": "2.1.0",
            "gitBranch": "main",
            "uuid": "uuid-1",
            "parentUuid": None,
            "timestamp": "2026-03-01T10:00:00Z",
            "message": {
                "role": "user",
                "content": "Fix the bug in parser.py",
            },
        },
        {
            "type": "assistant",
            "sessionId": session_id,
            "uuid": "uuid-2",
            "parentUuid": "uuid-1",
            "timestamp": "2026-03-01T10:00:05Z",
            "message": {
                "model": "claude-opus-4-6",
                "id": "msg_001",
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me read the file first."},
                ],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_read_input_tokens": 50,
                    "cache_creation_input_tokens": 10,
                },
            },
        },
        # Streaming update for same message (should be deduped)
        {
            "type": "assistant",
            "sessionId": session_id,
            "uuid": "uuid-3",
            "parentUuid": "uuid-2",
            "timestamp": "2026-03-01T10:00:06Z",
            "message": {
                "model": "claude-opus-4-6",
                "id": "msg_001",
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me read the file first."},
                    {
                        "type": "tool_use",
                        "id": "toolu_001",
                        "name": "Read",
                        "input": {"file_path": "/src/parser.py"},
                    },
                ],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 50,
                    "cache_creation_input_tokens": 10,
                },
            },
        },
        # Tool result
        {
            "type": "user",
            "sessionId": session_id,
            "uuid": "uuid-4",
            "parentUuid": "uuid-3",
            "timestamp": "2026-03-01T10:00:07Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_001",
                        "content": "def parse(): pass",
                    },
                ],
            },
        },
        # Assistant with Edit tool
        {
            "type": "assistant",
            "sessionId": session_id,
            "uuid": "uuid-5",
            "parentUuid": "uuid-4",
            "timestamp": "2026-03-01T10:00:10Z",
            "message": {
                "model": "claude-opus-4-6",
                "id": "msg_002",
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_002",
                        "name": "Edit",
                        "input": {
                            "file_path": "/src/parser.py",
                            "old_string": "def parse(): pass",
                            "new_string": "def parse():\n    return True",
                        },
                    },
                ],
                "usage": {
                    "input_tokens": 200,
                    "output_tokens": 80,
                    "cache_read_input_tokens": 100,
                    "cache_creation_input_tokens": 20,
                },
            },
        },
        # Tool result for Edit
        {
            "type": "user",
            "sessionId": session_id,
            "uuid": "uuid-6",
            "parentUuid": "uuid-5",
            "timestamp": "2026-03-01T10:00:11Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_002",
                        "content": "File edited successfully",
                    },
                ],
            },
        },
        # Assistant with Bash git commit
        {
            "type": "assistant",
            "sessionId": session_id,
            "uuid": "uuid-7",
            "parentUuid": "uuid-6",
            "timestamp": "2026-03-01T10:00:15Z",
            "message": {
                "model": "claude-opus-4-6",
                "id": "msg_003",
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_003",
                        "name": "Bash",
                        "input": {"command": "git commit -m 'fix parser'"},
                    },
                ],
                "usage": {
                    "input_tokens": 300,
                    "output_tokens": 30,
                    "cache_read_input_tokens": 150,
                    "cache_creation_input_tokens": 30,
                },
            },
        },
    ]

    jsonl_path = tmp_path / f"{session_id}.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    return jsonl_path


@pytest.fixture
def sample_jsonl_no_commit(tmp_path: Path) -> Path:
    """Session with edits but no git commit."""
    session_id = "test-session-nocommit"
    lines = [
        {
            "type": "user",
            "sessionId": session_id,
            "version": "2.1.0",
            "gitBranch": "feature",
            "uuid": "nc-1",
            "parentUuid": None,
            "timestamp": "2026-03-01T11:00:00Z",
            "message": {"role": "user", "content": "Add a helper function"},
        },
        {
            "type": "assistant",
            "sessionId": session_id,
            "uuid": "nc-2",
            "parentUuid": "nc-1",
            "timestamp": "2026-03-01T11:00:05Z",
            "message": {
                "model": "claude-opus-4-6",
                "id": "msg_nc_001",
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_nc_001",
                        "name": "Write",
                        "input": {"file_path": "/src/helpers.py", "content": "def helper(): pass"},
                    },
                ],
                "usage": {"input_tokens": 100, "output_tokens": 40,
                          "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            },
        },
    ]

    jsonl_path = tmp_path / f"{session_id}.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    return jsonl_path
