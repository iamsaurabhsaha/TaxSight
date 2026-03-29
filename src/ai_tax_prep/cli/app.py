"""Typer CLI application — main entry point."""

from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ai_tax_prep import __version__
from ai_tax_prep.config.settings import get_settings
from ai_tax_prep.core.session import SessionManager
from ai_tax_prep.llm.client import LLMClient

app = typer.Typer(
    name="tax-prep",
    help="AI Tax Prep Assistant — Privacy-first tax preparation with BYOK LLM support.",
    no_args_is_help=True,
)
console = Console()

DISCLAIMER = (
    "[dim]Disclaimer: This tool provides tax estimates for informational purposes only. "
    "It is not professional tax advice and should not be used for official tax filing. "
    "Consult a qualified tax professional for your specific situation.[/dim]"
)


# --- Config commands ---
config_app = typer.Typer(help="Configure LLM provider and API keys.")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show():
    """Show current configuration."""
    settings = get_settings()
    console.print(f"[bold]Provider:[/bold]  {settings.llm_provider}")
    console.print(f"[bold]Model:[/bold]     {settings.resolved_model}")
    console.print(f"[bold]API Key:[/bold]   {'****' + settings.api_key[-4:] if settings.api_key else 'not set (using env var)'}")
    console.print(f"[bold]DB Path:[/bold]   {settings.db_path}")
    console.print(f"[bold]PE Mode:[/bold]   {settings.pe_mode}")


@config_app.command("test")
def config_test():
    """Test LLM connection."""
    settings = get_settings()
    console.print(f"Testing connection to [bold]{settings.llm_provider}[/bold]...")
    client = LLMClient(settings)
    result = client.test_connection()
    if result["status"] == "ok":
        console.print(f"[green]Connected![/green] Response: {result['response']}")
    else:
        console.print(f"[red]Failed:[/red] {result['error']}")


# --- Session commands ---
session_app = typer.Typer(help="Manage tax preparation sessions.")
app.add_typer(session_app, name="session")


@session_app.command("create")
def session_create(
    name: str = typer.Option(..., "--name", "-n", help="Session name"),
    tax_year: int = typer.Option(2025, "--year", "-y", help="Tax year"),
):
    """Create a new tax preparation session."""
    manager = SessionManager()
    try:
        session = manager.create_session(name=name, tax_year=tax_year)
        console.print(f"[green]Session created![/green]")
        console.print(f"  Name: {session.name}")
        console.print(f"  ID:   {session.id}")
        console.print(f"  Year: {session.tax_year}")
        console.print()
        console.print(DISCLAIMER)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@session_app.command("list")
def session_list(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
):
    """List all tax preparation sessions."""
    manager = SessionManager()
    sessions = manager.list_sessions(status=status)

    if not sessions:
        console.print("[dim]No sessions found.[/dim]")
        return

    table = Table(title="Tax Prep Sessions")
    table.add_column("Name", style="bold")
    table.add_column("Year")
    table.add_column("Status")
    table.add_column("Step")
    table.add_column("Updated")
    table.add_column("ID", style="dim")

    for s in sessions:
        updated = s.updated_at.strftime("%Y-%m-%d %H:%M") if s.updated_at else ""
        table.add_row(
            s.name,
            str(s.tax_year),
            s.status,
            s.current_step or "—",
            updated,
            s.id[:8],
        )

    console.print(table)


@session_app.command("delete")
def session_delete(
    name: str = typer.Option(..., "--name", "-n", help="Session name to delete"),
):
    """Delete a tax preparation session."""
    manager = SessionManager()
    session = manager.get_session_by_name(name)
    if not session:
        console.print(f"[red]Session '{name}' not found.[/red]")
        raise typer.Exit(1)

    confirm = typer.confirm(f"Delete session '{name}' and all its data?")
    if confirm:
        manager.delete_session(session.id)
        console.print(f"[green]Session '{name}' deleted.[/green]")


# --- Top-level commands ---
@app.command()
def version():
    """Show version."""
    console.print(f"AI Tax Prep Assistant v{__version__}")


@app.callback()
def main():
    """AI Tax Prep Assistant — Privacy-first tax preparation with BYOK LLM support."""
    pass


if __name__ == "__main__":
    app()
