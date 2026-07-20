"""Typer CLI entry point for HALU Checker."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import Session

from halu_core import __version__
from halu_core.config import settings
from halu_core.db import create_db_and_tables, engine
from halu_core.models.enums import AgentType
from halu_core.services.cleanup_service import run_cleanup
from halu_core.services.prompt_service import generate_prompt
from halu_core.services.run_service import create_run
from halu_core.timeutils import utc_now

app = typer.Typer(
    name="halu-checker",
    help="Verify what your AI agent actually did.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def version() -> None:
    """Print the HALU Checker version."""
    console.print(f"halu-checker {__version__}")


@app.command("create-run")
def create_run_command(
    challenge_id: str = typer.Option(..., "--challenge-id", help="Challenge to run."),
    agent_type: AgentType = typer.Option(
        AgentType.GENERIC, "--agent-type", help="openclaw, hermes, or generic."
    ),
) -> None:
    """Create a run, print its prompt and temporary token (Phase 1)."""
    create_db_and_tables()
    with Session(engine) as session:
        run, raw_token = create_run(session, challenge_id=challenge_id, agent_type=agent_type)
        prompt = generate_prompt(run, raw_token, settings.base_url)

    console.print(f"[bold]run_id:[/bold] {run.id}")
    console.print(f"[bold]expires_at:[/bold] {run.expires_at.isoformat()}")
    console.print("")
    console.print(prompt)


@app.command("cleanup")
def cleanup_command(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would be deleted without deleting anything."
    ),
) -> None:
    """Delete runs/tokens past their configured retention window (Phase 8 §5).

    Never deletes a completed run that's currently publicly shared, or
    within its post-disable retention window. Always logs one
    structured operational summary line, dry-run or not.
    """
    create_db_and_tables()
    with Session(engine) as session:
        report = run_cleanup(session, now=utc_now(), dry_run=dry_run)

    table = Table(title=f"Cleanup {'(dry run)' if dry_run else 'result'}")
    table.add_column("Bucket")
    table.add_column("Count", justify="right")
    table.add_row("Incomplete runs deleted", str(len(report.incomplete_runs_deleted)))
    table.add_row("Completed runs deleted", str(len(report.completed_runs_deleted)))
    table.add_row(
        "Completed runs skipped (public share)",
        str(len(report.completed_runs_skipped_public_share)),
    )
    table.add_row("Expired agent tokens deleted", str(report.expired_agent_tokens_deleted))
    table.add_row("Expired view tokens deleted", str(report.expired_view_tokens_deleted))
    console.print(table)
    if dry_run:
        console.print("[yellow]Dry run: nothing was actually deleted.[/yellow]")


if __name__ == "__main__":
    app()
