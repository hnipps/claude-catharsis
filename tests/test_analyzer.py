"""Tests for the LLM analyzer (judge module)."""

import json
import sys

from catharsis.analyzer.judge import _get_unanalyzed_sessions, _run_claude_cli
from catharsis.paths import prompt_version
from catharsis.collector.ingest import ingest_session


class TestRunClaudeCli:
    def test_captures_stdout_and_stderr(self):
        result = _run_claude_cli(
            [sys.executable, "-c", "import sys; sys.stderr.write('err1\\nerr2\\n'); print('out')"],
            timeout=10,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "out"
        assert result.stderr_lines == ["err1", "err2"]
        assert result.elapsed > 0
        assert result.timed_out is False

    def test_calls_on_stderr_line(self):
        lines_seen = []
        result = _run_claude_cli(
            [sys.executable, "-c", "import sys; sys.stderr.write('line1\\nline2\\n')"],
            timeout=10,
            on_stderr_line=lines_seen.append,
        )
        assert lines_seen == ["line1", "line2"]

    def test_timeout_kills_process(self):
        result = _run_claude_cli(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            timeout=1,
        )
        assert result.timed_out is True
        assert result.elapsed >= 1.0

    def test_nonzero_exit_code(self):
        result = _run_claude_cli(
            [sys.executable, "-c", "import sys; sys.exit(2)"],
            timeout=10,
        )
        assert result.returncode == 2
        assert result.timed_out is False


def test_prompt_version_stable():
    v1 = prompt_version("test prompt")
    v2 = prompt_version("test prompt")
    assert v1 == v2
    assert len(v1) == 12


def test_prompt_version_changes():
    v1 = prompt_version("prompt A")
    v2 = prompt_version("prompt B")
    assert v1 != v2


def test_get_unanalyzed_sessions(db_conn, sample_jsonl, tmp_path):
    ingest_session(db_conn, sample_jsonl, "/test/project", "test-project")

    sessions = _get_unanalyzed_sessions(db_conn, lookback_days=365, max_sessions=10)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "test-session-001"


def test_get_unanalyzed_sessions_skips_analyzed(db_conn, sample_jsonl, tmp_path):
    ingest_session(db_conn, sample_jsonl, "/test/project", "test-project")

    # Mark as analyzed
    db_conn.execute("""
        INSERT INTO session_analyses (session_id, analysis_timestamp, judge_prompt_version, analysis_run_id)
        VALUES ('test-session-001', '2026-03-01T00:00:00Z', 'v1', 1)
    """)
    db_conn.commit()

    sessions = _get_unanalyzed_sessions(db_conn, lookback_days=365, max_sessions=10)
    assert len(sessions) == 0


def test_get_unanalyzed_sessions_force(db_conn, sample_jsonl, tmp_path):
    ingest_session(db_conn, sample_jsonl, "/test/project", "test-project")

    db_conn.execute("""
        INSERT INTO session_analyses (session_id, analysis_timestamp, judge_prompt_version, analysis_run_id)
        VALUES ('test-session-001', '2026-03-01T00:00:00Z', 'v1', 1)
    """)
    db_conn.commit()

    sessions = _get_unanalyzed_sessions(db_conn, lookback_days=365, max_sessions=10, force=True)
    assert len(sessions) == 1
