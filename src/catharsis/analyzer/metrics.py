"""Deterministic health metrics computed from SQLite data."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class MetricResult:
    """A single metric computation result."""
    name: str
    value: float | None
    previous_value: float | None
    pct_change: float | None
    trend: str  # "up", "down", "stable", "n/a"
    lower_is_better: bool = True

    @property
    def trend_arrow(self) -> str:
        if self.trend == "n/a":
            return "-"
        # For "lower is better" metrics, a decrease is improvement
        if self.lower_is_better:
            return {"up": "\u2193", "down": "\u2191", "stable": "\u2192"}[self.trend]
        return {"up": "\u2191", "down": "\u2193", "stable": "\u2192"}[self.trend]


def _compute_change(current: float | None, previous: float | None) -> tuple[float | None, str]:
    """Compute % change and trend direction."""
    if current is None or previous is None:
        return None, "n/a"
    if previous == 0:
        return None, "n/a" if current == 0 else "up"
    pct = ((current - previous) / abs(previous)) * 100
    if abs(pct) < 2:
        return pct, "stable"
    return pct, "up" if pct > 0 else "down"


def turns_to_first_commit(
    conn: sqlite3.Connection, window_start: str, window_end: str
) -> float | None:
    """Average number of user messages before the first git commit in a session."""
    rows = conn.execute("""
        WITH first_commits AS (
            SELECT s.session_id, MIN(tc.message_index) as first_commit_idx
            FROM sessions s
            JOIN tool_calls tc ON tc.session_id = s.session_id
            WHERE s.start_time >= ? AND s.start_time < ?
              AND s.has_commits = 1
              AND tc.tool_name = 'Bash'
              AND tc.tool_input LIKE '%git commit%'
            GROUP BY s.session_id
        )
        SELECT fc.session_id,
               COUNT(m.id) as user_msgs_before_commit
        FROM first_commits fc
        LEFT JOIN messages m ON m.session_id = fc.session_id
            AND m.message_index < fc.first_commit_idx
            AND m.role = 'user'
            AND m.is_tool_result = 0
        GROUP BY fc.session_id
    """, (window_start, window_end)).fetchall()

    if not rows:
        return None

    values = [row["user_msgs_before_commit"] for row in rows]
    return sum(values) / len(values) if values else None


def commitless_session_rate(
    conn: sqlite3.Connection, window_start: str, window_end: str
) -> float | None:
    """Percentage of coding sessions without any git commit."""
    # A "coding session" has at least one Write or Edit tool call
    coding_sessions = conn.execute("""
        SELECT COUNT(DISTINCT s.session_id) as cnt
        FROM sessions s
        JOIN tool_calls tc ON tc.session_id = s.session_id
        WHERE s.start_time >= ? AND s.start_time < ?
          AND tc.tool_name IN ('Write', 'Edit')
    """, (window_start, window_end)).fetchone()["cnt"]

    if coding_sessions == 0:
        return None

    commitless = conn.execute("""
        SELECT COUNT(DISTINCT s.session_id) as cnt
        FROM sessions s
        JOIN tool_calls tc ON tc.session_id = s.session_id
        WHERE s.start_time >= ? AND s.start_time < ?
          AND tc.tool_name IN ('Write', 'Edit')
          AND s.has_commits = 0
    """, (window_start, window_end)).fetchone()["cnt"]

    return (commitless / coding_sessions) * 100


def file_edit_churn(
    conn: sqlite3.Connection, window_start: str, window_end: str
) -> float | None:
    """Average ratio of Write/Edit calls per distinct file, across sessions."""
    rows = conn.execute("""
        SELECT s.session_id,
               COUNT(*) as edit_count,
               COUNT(DISTINCT tc.file_path) as file_count
        FROM sessions s
        JOIN tool_calls tc ON tc.session_id = s.session_id
        WHERE s.start_time >= ? AND s.start_time < ?
          AND tc.tool_name IN ('Write', 'Edit')
          AND tc.file_path IS NOT NULL
        GROUP BY s.session_id
    """, (window_start, window_end)).fetchall()

    if not rows:
        return None

    ratios = [r["edit_count"] / r["file_count"] for r in rows if r["file_count"] > 0]
    return sum(ratios) / len(ratios) if ratios else None


def tokens_per_line_changed(
    conn: sqlite3.Connection, window_start: str, window_end: str
) -> float | None:
    """Average tokens per net line changed across coding sessions.

    Estimates lines changed from Edit tool inputs (old_string/new_string diffs)
    and Write tool inputs (full content length).
    """
    rows = conn.execute("""
        SELECT s.session_id,
               s.total_input_tokens + s.total_output_tokens as total_tokens
        FROM sessions s
        JOIN tool_calls tc ON tc.session_id = s.session_id
        WHERE s.start_time >= ? AND s.start_time < ?
          AND tc.tool_name IN ('Write', 'Edit')
        GROUP BY s.session_id
    """, (window_start, window_end)).fetchall()

    if not rows:
        return None

    values = []
    for row in rows:
        session_id = row["session_id"]
        total_tokens = row["total_tokens"]

        # Estimate lines changed from tool calls
        edits = conn.execute("""
            SELECT tool_name, tool_input FROM tool_calls
            WHERE session_id = ? AND tool_name IN ('Write', 'Edit')
        """, (session_id,)).fetchall()

        lines_changed = 0
        for edit in edits:
            try:
                inp = json.loads(edit["tool_input"]) if edit["tool_input"] else {}
                if edit["tool_name"] == "Edit":
                    old = inp.get("old_string", "")
                    new = inp.get("new_string", "")
                    lines_changed += abs(new.count("\n") - old.count("\n")) + 1
                elif edit["tool_name"] == "Write":
                    content = inp.get("content", "")
                    lines_changed += content.count("\n") + 1
            except Exception:
                lines_changed += 1

        if lines_changed > 0 and total_tokens > 0:
            values.append(total_tokens / lines_changed)

    return sum(values) / len(values) if values else None


def tool_error_rate(
    conn: sqlite3.Connection, window_start: str, window_end: str
) -> float | None:
    """Percentage of Bash/Write/Edit calls that errored."""
    total = conn.execute("""
        SELECT COUNT(*) as cnt FROM tool_calls tc
        JOIN sessions s ON s.session_id = tc.session_id
        WHERE s.start_time >= ? AND s.start_time < ?
          AND tc.tool_name IN ('Bash', 'Write', 'Edit')
    """, (window_start, window_end)).fetchone()["cnt"]

    if total == 0:
        return None

    errors = conn.execute("""
        SELECT COUNT(*) as cnt FROM tool_calls tc
        JOIN sessions s ON s.session_id = tc.session_id
        WHERE s.start_time >= ? AND s.start_time < ?
          AND tc.tool_name IN ('Bash', 'Write', 'Edit')
          AND tc.is_error = 1
    """, (window_start, window_end)).fetchone()["cnt"]

    return (errors / total) * 100


ALL_METRICS = [
    ("turns_to_first_commit", turns_to_first_commit),
    ("commitless_session_rate", commitless_session_rate),
    ("file_edit_churn", file_edit_churn),
    ("tokens_per_line_changed", tokens_per_line_changed),
    ("tool_error_rate", tool_error_rate),
]


def compute_all_metrics(
    conn: sqlite3.Connection,
    lookback_days: int = 7,
    reference_date: datetime | None = None,
) -> list[MetricResult]:
    """Compute all 5 metrics with comparison to prior window."""
    ref = reference_date or datetime.now(timezone.utc)
    window_end = ref.isoformat()
    window_start = (ref - timedelta(days=lookback_days)).isoformat()
    prev_end = window_start
    prev_start = (ref - timedelta(days=lookback_days * 2)).isoformat()

    results = []
    for name, func in ALL_METRICS:
        current = func(conn, window_start, window_end)
        previous = func(conn, prev_start, prev_end)
        pct_change, trend = _compute_change(current, previous)

        results.append(MetricResult(
            name=name,
            value=current,
            previous_value=previous,
            pct_change=pct_change,
            trend=trend,
        ))

    return results


def store_metrics(
    conn: sqlite3.Connection,
    metrics: list[MetricResult],
    window_start: str,
    window_end: str,
) -> None:
    """Store metric results in the weekly_metrics table."""
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        for m in metrics:
            conn.execute("""
                INSERT OR REPLACE INTO weekly_metrics
                (window_start, window_end, metric_name, value, previous_value, pct_change, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (window_start, window_end, m.name, m.value, m.previous_value, m.pct_change, now))
