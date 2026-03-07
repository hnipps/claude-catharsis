"""Tests for CLI parameter wiring."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from catharsis.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_cli_setup(db_conn):
    """Patch load_config, get_connection, and ensure_schema for CLI tests."""
    with (
        patch("catharsis.cli.load_config", return_value={}),
        patch("catharsis.cli.get_connection", return_value=db_conn),
        patch("catharsis.cli.ensure_schema"),
        patch("catharsis.cli.ensure_dirs"),
    ):
        yield


class TestAnalyzeFlags:
    @pytest.mark.parametrize("flags,expected_force,expected_auto_confirm", [
        (["--force-reanalyze"], True, False),
        (["--no-limit"], False, True),
        (["--force-reanalyze", "--no-limit"], True, True),
    ])
    def test_analyze_flag_wiring(self, runner, mock_cli_setup, flags, expected_force, expected_auto_confirm):
        mock_run = MagicMock(return_value={"status": "completed", "analyzed": 0})
        with (
            patch("catharsis.analyzer.judge.run_llm_analysis", mock_run),
            patch("catharsis.analyzer.metrics.compute_all_metrics", return_value={}),
            patch("catharsis.analyzer.metrics.store_metrics"),
            patch("catharsis.analyzer.report.render_metrics_table"),
            patch("catharsis.analyzer.report.generate_markdown_report", return_value="/tmp/r.md"),
        ):
            result = runner.invoke(main, ["analyze", *flags])
            assert result.exit_code == 0, result.output
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            assert kwargs["force"] is expected_force
            assert kwargs["auto_confirm"] is expected_auto_confirm

    def test_analyze_skip_llm_skips_analysis(self, runner, mock_cli_setup):
        """--skip-llm should prevent run_llm_analysis from being called."""
        mock_run = MagicMock()
        with (
            patch("catharsis.analyzer.judge.run_llm_analysis", mock_run),
            patch("catharsis.analyzer.metrics.compute_all_metrics", return_value={}),
            patch("catharsis.analyzer.metrics.store_metrics"),
            patch("catharsis.analyzer.report.render_metrics_table"),
            patch("catharsis.analyzer.report.generate_markdown_report", return_value="/tmp/r.md"),
        ):
            result = runner.invoke(main, ["analyze", "--skip-llm"])
            assert result.exit_code == 0, result.output
            mock_run.assert_not_called()

    def test_analyze_shows_no_limit_in_ceiling_message(self, runner, mock_cli_setup):
        mock_run = MagicMock(return_value={
            "status": "token_ceiling_exceeded",
            "estimated_tokens": 100_000,
            "ceiling": 50_000,
        })
        with (
            patch("catharsis.analyzer.judge.run_llm_analysis", mock_run),
            patch("catharsis.analyzer.metrics.compute_all_metrics", return_value={}),
            patch("catharsis.analyzer.metrics.store_metrics"),
            patch("catharsis.analyzer.report.render_metrics_table"),
            patch("catharsis.analyzer.report.generate_markdown_report", return_value="/tmp/r.md"),
        ):
            result = runner.invoke(main, ["analyze"])
            assert result.exit_code == 0, result.output
            assert "--no-limit" in result.output


class TestCollectFlags:
    def test_collect_passes_force(self, runner, mock_cli_setup):
        mock_backfill = MagicMock(return_value=(5, 2))
        with patch("catharsis.collector.backfill.backfill", mock_backfill):
            result = runner.invoke(main, ["collect", "--force"])
            assert result.exit_code == 0, result.output
            mock_backfill.assert_called_once()
            _, kwargs = mock_backfill.call_args
            assert kwargs["force"] is True
