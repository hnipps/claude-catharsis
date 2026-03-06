"""CLI entry point for cc-improve."""

from __future__ import annotations

import click
from rich.console import Console

from cc_improve.config import load_config
from cc_improve.db import ensure_schema, get_connection
from cc_improve.paths import ensure_dirs


@click.group()
@click.pass_context
def main(ctx: click.Context) -> None:
    """cc-improve: Analyze Claude Code conversations and improve instructions."""
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
        from cc_improve.collector.hook import _find_jsonl
        from cc_improve.collector.ingest import ingest_session

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
        from cc_improve.collector.backfill import backfill

        ingested, skipped = backfill(
            conn,
            excluded_projects=config.get("excluded_projects", []),
            excluded_sessions=config.get("excluded_sessions", []),
            force=force,
        )
        console.print(f"[green]Collected {ingested} sessions[/green] ({skipped} skipped)")


@main.command()
@click.option("--skip-llm", is_flag=True, help="Only compute deterministic metrics, skip LLM analysis")
@click.option("--force", is_flag=True, help="Re-analyze sessions that were already analyzed")
@click.pass_context
def analyze(ctx: click.Context, skip_llm: bool, force: bool) -> None:
    """Compute metrics and run LLM analysis on collected sessions."""
    conn = ctx.obj["conn"]
    config = ctx.obj["config"]
    console = ctx.obj["console"]

    from datetime import datetime, timedelta, timezone

    from cc_improve.analyzer.metrics import compute_all_metrics, store_metrics
    from cc_improve.analyzer.report import generate_markdown_report, render_metrics_table

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
        from cc_improve.analyzer.judge import run_llm_analysis

        console.print("\n[bold]Running LLM analysis...[/bold]")
        result = run_llm_analysis(
            conn,
            lookback_days=lookback,
            max_sessions=config.get("max_analysis_sessions", 20),
            token_ceiling_pct=config.get("token_ceiling_pct", 5.0),
            force=force,
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
                f"Run with --force to override.[/yellow]"
            )
        elif status == "cli_not_found":
            console.print("[red]Claude CLI not found. Is it installed?[/red]")
        else:
            console.print(f"[red]Analysis failed: {result.get('error', status)}[/red]")


@main.command()
@click.pass_context
def suggest(ctx: click.Context) -> None:
    """Generate improvement proposals from failure patterns."""
    conn = ctx.obj["conn"]
    config = ctx.obj["config"]
    console = ctx.obj["console"]

    from cc_improve.improver.propose import generate_proposals

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

    from cc_improve.reviewer.interactive import review_proposals

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
    from cc_improve.status import show_status

    show_status(ctx.obj["conn"], ctx.obj["console"])
