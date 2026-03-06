"""Status dashboard for Claude Catharsis."""

from __future__ import annotations

import sqlite3

from rich.console import Console
from rich.table import Table


def show_status(conn: sqlite3.Connection, console: Console | None = None) -> dict:
    """Show system status dashboard. Returns stats dict."""
    c = console or Console()

    stats = {}

    # Sessions collected
    row = conn.execute("SELECT COUNT(*) as cnt FROM sessions").fetchone()
    stats["sessions_collected"] = row["cnt"]

    # Sessions analyzed
    row = conn.execute("SELECT COUNT(DISTINCT session_id) as cnt FROM session_analyses").fetchone()
    stats["sessions_analyzed"] = row["cnt"]

    # Active failure patterns
    row = conn.execute("SELECT COUNT(*) as cnt FROM failure_patterns WHERE occurrence_count >= 3").fetchone()
    stats["active_patterns"] = row["cnt"]

    # Pending proposals
    row = conn.execute("SELECT COUNT(*) as cnt FROM proposals WHERE status = 'pending'").fetchone()
    stats["pending_proposals"] = row["cnt"]

    # Analysis token usage
    row = conn.execute("""
        SELECT COALESCE(SUM(input_tokens + output_tokens), 0) as analysis_tokens
        FROM analysis_runs WHERE status = 'completed'
    """).fetchone()
    stats["analysis_tokens"] = row["analysis_tokens"]

    # Total session tokens
    row = conn.execute("""
        SELECT COALESCE(SUM(total_input_tokens + total_output_tokens), 0) as total_tokens
        FROM sessions
    """).fetchone()
    stats["total_session_tokens"] = row["total_tokens"]

    # Percentage
    if stats["total_session_tokens"] > 0:
        stats["analysis_pct"] = (stats["analysis_tokens"] / stats["total_session_tokens"]) * 100
    else:
        stats["analysis_pct"] = 0.0

    # Render
    table = Table(title="Claude Catharsis Status", show_header=False)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Sessions collected", str(stats["sessions_collected"]))
    table.add_row("Sessions analyzed", str(stats["sessions_analyzed"]))
    table.add_row("Active failure patterns", str(stats["active_patterns"]))
    table.add_row("Pending proposals", str(stats["pending_proposals"]))
    table.add_row("Analysis tokens used", f"{stats['analysis_tokens']:,}")
    table.add_row("Analysis % of total usage", f"{stats['analysis_pct']:.1f}%")

    c.print(table)
    return stats
