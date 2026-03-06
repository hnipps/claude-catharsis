"""Report generation for metrics and analysis results."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from cc_improve.analyzer.metrics import MetricResult
from cc_improve.paths import REPORTS_DIR

METRIC_LABELS = {
    "turns_to_first_commit": "Turns to First Commit",
    "commitless_session_rate": "Commit-less Session Rate",
    "file_edit_churn": "File Edit Churn",
    "tokens_per_line_changed": "Tokens per Line Changed",
    "tool_error_rate": "Tool Error Rate",
}

METRIC_UNITS = {
    "turns_to_first_commit": "avg",
    "commitless_session_rate": "%",
    "file_edit_churn": "x",
    "tokens_per_line_changed": "",
    "tool_error_rate": "%",
}


def _fmt_value(value: float | None, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit == "%":
        return f"{value:.0f}%"
    if unit == "x":
        return f"{value:.1f}x"
    if unit == "avg":
        return f"{value:.1f} avg"
    return f"{value:.0f}"


def render_metrics_table(
    metrics: list[MetricResult],
    window_start: str,
    window_end: str,
    console: Console | None = None,
) -> None:
    """Render metrics as a Rich table to the terminal."""
    c = console or Console()

    table = Table(
        title=f"Weekly Health Metrics ({window_start[:10]} to {window_end[:10]})",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Current", justify="right")
    table.add_column("Previous", justify="right")
    table.add_column("Change", justify="right")
    table.add_column("Trend", justify="center")

    for m in metrics:
        unit = METRIC_UNITS.get(m.name, "")
        current_str = _fmt_value(m.value, unit)
        prev_str = _fmt_value(m.previous_value, unit)
        change_str = f"{m.pct_change:+.0f}%" if m.pct_change is not None else "n/a"
        label = METRIC_LABELS.get(m.name, m.name)
        table.add_row(label, current_str, prev_str, change_str, m.trend_arrow)

    c.print(table)


def generate_markdown_report(
    metrics: list[MetricResult],
    window_start: str,
    window_end: str,
) -> Path:
    """Generate a Markdown report file and return its path."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_path = REPORTS_DIR / f"{date_str}-metrics.md"

    lines = [
        f"# Weekly Health Metrics",
        f"",
        f"**Period**: {window_start[:10]} to {window_end[:10]}",
        f"**Generated**: {date_str}",
        f"",
        f"| Metric | Current | Previous | Change | Trend |",
        f"|--------|---------|----------|--------|-------|",
    ]

    for m in metrics:
        unit = METRIC_UNITS.get(m.name, "")
        label = METRIC_LABELS.get(m.name, m.name)
        current_str = _fmt_value(m.value, unit)
        prev_str = _fmt_value(m.previous_value, unit)
        change_str = f"{m.pct_change:+.0f}%" if m.pct_change is not None else "n/a"
        lines.append(f"| {label} | {current_str} | {prev_str} | {change_str} | {m.trend_arrow} |")

    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
