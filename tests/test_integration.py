"""Integration test — runs the full pipeline on real data (skips LLM)."""

from pathlib import Path

import pytest

from cc_improve.collector.backfill import discover_sessions
from cc_improve.paths import CLAUDE_PROJECTS_DIR


@pytest.mark.skipif(
    not CLAUDE_PROJECTS_DIR.exists(),
    reason="No Claude projects directory found",
)
def test_discover_real_sessions():
    """Verify we can find real session files."""
    sessions = discover_sessions()
    assert len(sessions) > 0

    for jsonl_path, project_path, project_encoded in sessions[:3]:
        assert jsonl_path.exists()
        assert jsonl_path.suffix == ".jsonl"
        assert project_path.startswith("/")


@pytest.mark.skipif(
    not CLAUDE_PROJECTS_DIR.exists(),
    reason="No Claude projects directory found",
)
def test_parse_real_session():
    """Verify we can parse a real session."""
    from cc_improve.collector.parser import parse_jsonl

    sessions = discover_sessions()
    if not sessions:
        pytest.skip("No sessions found")

    jsonl_path = sessions[0][0]
    result = parse_jsonl(jsonl_path)
    assert result is not None
    assert result.session_id
    assert len(result.messages) > 0


@pytest.mark.skipif(
    not CLAUDE_PROJECTS_DIR.exists(),
    reason="No Claude projects directory found",
)
def test_full_collect_and_analyze(tmp_path):
    """Full e2e: collect real sessions, compute metrics."""
    from cc_improve.collector.backfill import backfill
    from cc_improve.analyzer.metrics import compute_all_metrics
    from cc_improve.db import ensure_schema, get_connection

    db_path = tmp_path / "integration_test.db"
    conn = get_connection(db_path)
    ensure_schema(conn)

    ingested, skipped = backfill(conn)
    assert ingested + skipped > 0

    if ingested > 0:
        metrics = compute_all_metrics(conn, lookback_days=365)
        assert len(metrics) == 5

        # At least some metric should have data
        has_data = any(m.value is not None for m in metrics)
        assert has_data, "Expected at least one metric to have data"

    conn.close()
