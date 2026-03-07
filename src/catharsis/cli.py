"""CLI entry point for Claude Catharsis."""

from __future__ import annotations

import click
from rich.console import Console

from catharsis.config import load_config
from catharsis.db import ensure_schema, get_connection
from catharsis.paths import ensure_dirs


@click.group()
@click.pass_context
def main(ctx: click.Context) -> None:
    """Claude Catharsis: Analyze Claude Code conversations and improve instructions."""
    ensure_dirs()
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config()
    ctx.obj["conn"] = get_connection()
    ensure_schema(ctx.obj["conn"])
    ctx.obj["console"] = Console()


@main.command()
@click.option("--session-id", help="Collect a specific session by ID")
@click.option("--force", is_flag=True, help="Re-ingest sessions that already exist")
@click.pass_context
def collect(ctx: click.Context, session_id: str | None, force: bool) -> None:
    """Collect and ingest Claude Code sessions."""
    conn = ctx.obj["conn"]
    config = ctx.obj["config"]
    console = ctx.obj["console"]

    if session_id:
        from catharsis.collector.hook import _find_jsonl
        from catharsis.collector.ingest import ingest_session

        result = _find_jsonl(session_id)
        if result:
            jsonl_path, project_path, project_encoded = result
            if ingest_session(conn, jsonl_path, project_path, project_encoded, force=force):
                console.print(f"[green]Ingested session {session_id}[/green]")
            else:
                console.print(f"[yellow]Session {session_id} already exists (use --force to re-ingest)[/yellow]")
        else:
            console.print(f"[red]Session {session_id} not found[/red]")
            raise SystemExit(1)
    else:
        from catharsis.collector.backfill import backfill

        ingested, skipped = backfill(
            conn,
            excluded_projects=config.get("excluded_projects", []),
            excluded_sessions=config.get("excluded_sessions", []),
            force=force,
        )
        console.print(f"[green]Collected {ingested} sessions[/green] ({skipped} skipped)")


@main.command()
@click.option("--skip-llm", is_flag=True, help="Only compute deterministic metrics, skip LLM analysis")
@click.option("--force-reanalyze", is_flag=True, help="Re-analyze sessions that were already analyzed")
@click.option("--no-limit", is_flag=True, help="Bypass the token ceiling safety check")
@click.option("--timeout", type=int, default=None, help="Analysis timeout in seconds (default: from config)")
@click.option("-v", "--verbose", is_flag=True, help="Print Claude CLI stderr output in real time")
@click.pass_context
def analyze(ctx: click.Context, skip_llm: bool, force_reanalyze: bool, no_limit: bool, timeout: int | None, verbose: bool) -> None:
    """Compute metrics and run LLM analysis on collected sessions."""
    conn = ctx.obj["conn"]
    config = ctx.obj["config"]
    console = ctx.obj["console"]

    from datetime import datetime, timedelta, timezone

    from catharsis.analyzer.metrics import compute_all_metrics, store_metrics
    from catharsis.analyzer.report import generate_markdown_report, render_metrics_table

    lookback = config.get("lookback_days", 7)
    ref = datetime.now(timezone.utc)
    window_end = ref.isoformat()
    window_start = (ref - timedelta(days=lookback)).isoformat()

    metrics = compute_all_metrics(conn, lookback_days=lookback)
    store_metrics(conn, metrics, window_start, window_end)
    render_metrics_table(metrics, window_start, window_end, console)

    report_path = generate_markdown_report(metrics, window_start, window_end)
    console.print(f"\n[dim]Report saved to {report_path}[/dim]")

    if not skip_llm:
        from catharsis.analyzer.judge import run_llm_analysis

        analysis_timeout = timeout or config.get("analysis_timeout", 600)

        def on_progress(line: str) -> None:
            if verbose:
                console.print(f"[dim]  {line}[/dim]")
            elif hasattr(on_progress, "_status"):
                truncated = line[:80] + ("..." if len(line) > 80 else "")
                on_progress._status.update(f"[bold]Running LLM analysis...[/bold] {truncated}")

        with console.status("[bold]Running LLM analysis...[/bold]") as status_ctx:
            on_progress._status = status_ctx
            result = run_llm_analysis(
                conn,
                lookback_days=lookback,
                max_sessions=config.get("max_analysis_sessions", 20),
                token_ceiling_pct=config.get("token_ceiling_pct", 5.0),
                force=force_reanalyze,
                auto_confirm=no_limit,
                timeout=analysis_timeout,
                on_progress=on_progress,
            )

        status = result.get("status")
        if status == "completed":
            console.print(f"[green]Analyzed {result.get('analyzed', 0)} sessions[/green]")
        elif status == "no_sessions":
            console.print("[yellow]No unanalyzed sessions found[/yellow]")
        elif status == "token_ceiling_exceeded":
            console.print(
                f"[yellow]Estimated token usage ({result['estimated_tokens']:,}) "
                f"exceeds ceiling ({result['ceiling']:,.0f}). "
                f"Run with --no-limit to override.[/yellow]"
            )
        elif status == "timeout":
            elapsed = result.get("elapsed", 0)
            session_count = result.get("session_count", 0)
            console.print(
                f"[red]Analysis timed out after {elapsed:.0f}s "
                f"({session_count} sessions). The subprocess was killed.[/red]"
            )
            stderr_tail = result.get("stderr_tail", [])
            if stderr_tail:
                console.print("[dim]Last stderr output:[/dim]")
                for line in stderr_tail:
                    console.print(f"[dim]  {line}[/dim]")
        elif status == "cli_not_found":
            console.print("[red]Claude CLI not found. Is it installed?[/red]")
        elif status == "cli_error":
            console.print(f"[red]Analysis failed: Claude CLI returned an error[/red]")
            stderr_tail = result.get("stderr_tail", [])
            if stderr_tail:
                console.print("[dim]Last stderr output:[/dim]")
                for line in stderr_tail:
                    console.print(f"[dim]  {line}[/dim]")
        else:
            console.print(f"[red]Analysis failed: {result.get('error', status)}[/red]")


@main.command()
@click.pass_context
def suggest(ctx: click.Context) -> None:
    """Generate improvement proposals from failure patterns."""
    conn = ctx.obj["conn"]
    config = ctx.obj["config"]
    console = ctx.obj["console"]

    from catharsis.improver.propose import generate_proposals

    console.print("[bold]Generating improvement proposals...[/bold]")
    result = generate_proposals(
        conn,
        top_n=config.get("top_n_patterns", 5),
        instruction_budget=config.get("instruction_budget_lines", 200),
    )

    status = result.get("status")
    if status == "completed":
        console.print(f"[green]Generated {result.get('proposals', 0)} proposals[/green]")
    elif status == "no_patterns":
        console.print("[yellow]No failure patterns with 3+ occurrences found. Run analyze first.[/yellow]")
    else:
        console.print(f"[red]Proposal generation failed: {result.get('error', status)}[/red]")


@main.command()
@click.pass_context
def review(ctx: click.Context) -> None:
    """Interactively review pending proposals."""
    conn = ctx.obj["conn"]

    from catharsis.reviewer.interactive import review_proposals

    result = review_proposals(conn)
    console = ctx.obj["console"]
    console.print(
        f"\n[bold]Review complete:[/bold] "
        f"{result['accepted']} accepted, "
        f"{result['rejected']} rejected, "
        f"{result['skipped']} skipped"
    )


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show system status dashboard."""
    from catharsis.status import show_status

    show_status(ctx.obj["conn"], ctx.obj["console"])
