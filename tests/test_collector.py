"""Tests for session ingestion and backfill."""

import sqlite3

from cc_improve.collector.ingest import ingest_session, session_exists
from cc_improve.collector.session import compute_stats
from cc_improve.collector.parser import parse_jsonl


def test_compute_stats(sample_jsonl):
    parsed = parse_jsonl(sample_jsonl)
    stats = compute_stats(parsed)

    assert stats.message_count == 6  # 1 user + 3 assistant (msg_001 deduped, msg_002, msg_003) + 2 tool results
    assert stats.tool_call_count == 3  # Read, Edit, Bash
    assert stats.has_commits is True
    assert stats.turn_count == 1  # 1 non-tool-result user message


def test_compute_stats_no_commit(sample_jsonl_no_commit):
    parsed = parse_jsonl(sample_jsonl_no_commit)
    stats = compute_stats(parsed)

    assert stats.has_commits is False
    assert stats.tool_call_count == 1  # Write


def test_ingest_session(db_conn, sample_jsonl, tmp_path):
    result = ingest_session(
        db_conn, sample_jsonl, "/test/project", "test-project"
    )
    assert result is True

    # Verify session in DB
    row = db_conn.execute("SELECT * FROM sessions WHERE session_id = 'test-session-001'").fetchone()
    assert row is not None
    assert row["project_path"] == "/test/project"
    assert row["has_commits"] == 1

    # Verify messages
    msgs = db_conn.execute("SELECT COUNT(*) as cnt FROM messages WHERE session_id = 'test-session-001'").fetchone()
    assert msgs["cnt"] > 0

    # Verify tool calls
    tools = db_conn.execute("SELECT * FROM tool_calls WHERE session_id = 'test-session-001'").fetchall()
    assert len(tools) >= 2  # At least Read and Edit


def test_idempotent_ingest(db_conn, sample_jsonl, tmp_path):
    ingest_session(db_conn, sample_jsonl, "/test/project", "test-project")
    # Second ingest should be skipped
    result = ingest_session(db_conn, sample_jsonl, "/test/project", "test-project")
    assert result is False


def test_force_reingest(db_conn, sample_jsonl, tmp_path):
    ingest_session(db_conn, sample_jsonl, "/test/project", "test-project")
    result = ingest_session(
        db_conn, sample_jsonl, "/test/project", "test-project", force=True
    )
    assert result is True


def test_session_exists(db_conn, sample_jsonl, tmp_path):
    assert session_exists(db_conn, "test-session-001") is False
    ingest_session(db_conn, sample_jsonl, "/test/project", "test-project")
    assert session_exists(db_conn, "test-session-001") is True


def test_tool_results_matched(db_conn, sample_jsonl, tmp_path):
    ingest_session(db_conn, sample_jsonl, "/test/project", "test-project")

    # Check that tool results were matched
    read_call = db_conn.execute(
        "SELECT tool_result FROM tool_calls WHERE tool_use_id = 'toolu_001'"
    ).fetchone()
    assert read_call is not None
    assert read_call["tool_result"] is not None
    assert "parse" in read_call["tool_result"]
