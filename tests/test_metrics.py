"""Tests for deterministic health metrics."""

from datetime import datetime, timezone

from cc_improve.analyzer.metrics import (
    commitless_session_rate,
    compute_all_metrics,
    file_edit_churn,
    tool_error_rate,
    turns_to_first_commit,
)
from cc_improve.collector.ingest import ingest_session


def _ingest_both(db_conn, sample_jsonl, sample_jsonl_no_commit, tmp_path):
    ingest_session(db_conn, sample_jsonl, "/test/project", "test-project")
    ingest_session(db_conn, sample_jsonl_no_commit, "/test/project", "test-project")


def test_turns_to_first_commit(db_conn, sample_jsonl, tmp_path):
    ingest_session(db_conn, sample_jsonl, "/test/project", "test-project")

    result = turns_to_first_commit(
        db_conn, "2026-01-01T00:00:00Z", "2026-12-31T00:00:00Z"
    )
    assert result == 1.0  # 1 user message before the git commit tool call


def test_commitless_session_rate(db_conn, sample_jsonl, sample_jsonl_no_commit, tmp_path):
    _ingest_both(db_conn, sample_jsonl, sample_jsonl_no_commit, tmp_path)

    rate = commitless_session_rate(
        db_conn, "2026-01-01T00:00:00Z", "2026-12-31T00:00:00Z"
    )
    assert rate is not None
    assert rate == 50.0  # 1 of 2 coding sessions has no commit


def test_file_edit_churn(db_conn, sample_jsonl, tmp_path):
    ingest_session(db_conn, sample_jsonl, "/test/project", "test-project")

    churn = file_edit_churn(
        db_conn, "2026-01-01T00:00:00Z", "2026-12-31T00:00:00Z"
    )
    # Edit targets parser.py: 1 Edit / 1 file = 1.0
    assert churn == 1.0


def test_tool_error_rate(db_conn, sample_jsonl, tmp_path):
    ingest_session(db_conn, sample_jsonl, "/test/project", "test-project")

    rate = tool_error_rate(
        db_conn, "2026-01-01T00:00:00Z", "2026-12-31T00:00:00Z"
    )
    # No errors in sample data
    assert rate is not None
    assert rate == 0.0


def test_compute_all_metrics(db_conn, sample_jsonl, sample_jsonl_no_commit, tmp_path):
    _ingest_both(db_conn, sample_jsonl, sample_jsonl_no_commit, tmp_path)

    metrics = compute_all_metrics(
        db_conn,
        lookback_days=365,
        reference_date=datetime(2026, 12, 1, tzinfo=timezone.utc),
    )
    assert len(metrics) == 5

    for m in metrics:
        assert m.name in [
            "turns_to_first_commit",
            "commitless_session_rate",
            "file_edit_churn",
            "tokens_per_line_changed",
            "tool_error_rate",
        ]


def test_metrics_with_no_data(db_conn):
    metrics = compute_all_metrics(db_conn, lookback_days=7)
    assert len(metrics) == 5
    for m in metrics:
        assert m.value is None
