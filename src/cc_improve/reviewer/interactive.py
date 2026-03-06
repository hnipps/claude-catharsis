"""Interactive proposal review CLI."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text


def get_pending_proposals(conn: sqlite3.Connection) -> list[dict]:
    """Get all pending proposals."""
    rows = conn.execute("""
        SELECT p.id, p.title, p.target_file, p.change_type,
               p.current_content, p.proposed_content, p.rationale,
               p.failure_pattern_id,
               fp.failure_type, fp.occurrence_count, fp.severity_mode
        FROM proposals p
        LEFT JOIN failure_patterns fp ON fp.id = p.failure_pattern_id
        WHERE p.status = 'pending'
        ORDER BY p.created_at
    """).fetchall()
    return [dict(r) for r in rows]


def _display_proposal(console: Console, proposal: dict, index: int, total: int) -> None:
    """Display a single proposal for review."""
    console.print(f"\n[bold cyan]Proposal {index}/{total}: {proposal['title']}[/bold cyan]")
    console.print(f"  Target: [yellow]{proposal['target_file']}[/yellow]")
    console.print(f"  Type: {proposal['change_type']}")

    if proposal.get("failure_type"):
        console.print(
            f"  Pattern: {proposal['failure_type']} "
            f"({proposal.get('occurrence_count', '?')} occurrences, "
            f"{proposal.get('severity_mode', '?')} severity)"
        )

    if proposal.get("rationale"):
        console.print(Panel(proposal["rationale"], title="Rationale", border_style="dim"))

    if proposal.get("current_content"):
        console.print("\n[dim]Current:[/dim]")
        console.print(Syntax(proposal["current_content"], "markdown", theme="monokai"))

    console.print("\n[dim]Proposed:[/dim]")
    console.print(Syntax(proposal["proposed_content"], "markdown", theme="monokai"))


def _edit_in_editor(content: str) -> str | None:
    """Open content in $EDITOR for modification."""
    editor = os.environ.get("EDITOR", "vim")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        f.flush()
        tmp_path = f.name

    try:
        subprocess.run([editor, tmp_path], check=True)
        with open(tmp_path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None
    finally:
        os.unlink(tmp_path)


def review_proposals(conn: sqlite3.Connection) -> dict:
    """Run interactive review of pending proposals.

    Returns summary with counts of accepted/rejected/skipped.
    """
    console = Console()
    proposals = get_pending_proposals(conn)

    if not proposals:
        console.print("[yellow]No pending proposals to review.[/yellow]")
        return {"accepted": 0, "rejected": 0, "skipped": 0}

    console.print(f"\n[bold]Found {len(proposals)} pending proposal(s)[/bold]\n")

    accepted = 0
    rejected = 0
    skipped = 0

    for i, proposal in enumerate(proposals, 1):
        _display_proposal(console, proposal, i, len(proposals))

        while True:
            console.print("\n[bold][a]ccept [r]eject [e]dit [s]kip [q]uit[/bold]")
            choice = input("> ").strip().lower()

            if choice == "a":
                _accept_proposal(conn, proposal)
                accepted += 1
                console.print("[green]Accepted.[/green]")
                break
            elif choice == "r":
                reason = input("Rejection reason: ").strip()
                _reject_proposal(conn, proposal["id"], reason)
                rejected += 1
                console.print("[red]Rejected.[/red]")
                break
            elif choice == "e":
                edited = _edit_in_editor(proposal["proposed_content"])
                if edited and edited != proposal["proposed_content"]:
                    proposal["proposed_content"] = edited
                    console.print("[yellow]Content updated. Review again:[/yellow]")
                    _display_proposal(console, proposal, i, len(proposals))
                else:
                    console.print("[dim]No changes made.[/dim]")
            elif choice == "s":
                skipped += 1
                break
            elif choice == "q":
                skipped += len(proposals) - i + 1
                return {"accepted": accepted, "rejected": rejected, "skipped": skipped}

    return {"accepted": accepted, "rejected": rejected, "skipped": skipped}


def _accept_proposal(conn: sqlite3.Connection, proposal: dict) -> None:
    """Accept a proposal: apply changes and record decision."""
    from cc_improve.reviewer.apply import apply_proposal
    now = datetime.now(timezone.utc).isoformat()

    apply_proposal(proposal)

    with conn:
        conn.execute("""
            UPDATE proposals SET status = 'accepted', reviewed_at = ?,
                proposed_content = ?
            WHERE id = ?
        """, (now, proposal["proposed_content"], proposal["id"]))


def _reject_proposal(conn: sqlite3.Connection, proposal_id: int, reason: str) -> None:
    """Record proposal rejection."""
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute("""
            UPDATE proposals SET status = 'rejected', rejection_reason = ?, reviewed_at = ?
            WHERE id = ?
        """, (reason, now, proposal_id))
