"""CLI commands for document upload, listing, and review."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_tax_prep.core.session import SessionManager
from ai_tax_prep.documents.parser import DocumentParser
from ai_tax_prep.documents.schemas import DOC_TYPE_NAMES

console = Console()

docs_app = typer.Typer(help="Upload and manage tax documents.")

VALID_DOC_TYPES = list(DOC_TYPE_NAMES.keys())


@docs_app.command("upload")
def upload(
    file: Path = typer.Argument(..., help="Path to the document image or PDF"),
    session_name: str = typer.Option(..., "--session", "-s", help="Session name"),
    doc_type: Optional[str] = typer.Option(None, "--type", "-t", help=f"Document type: {', '.join(VALID_DOC_TYPES)}"),
):
    """Upload and parse a tax document (W-2, 1099, etc.)."""
    if not file.exists():
        console.print(f"[red]File not found:[/red] {file}")
        raise typer.Exit(1)

    if doc_type and doc_type not in VALID_DOC_TYPES:
        console.print(f"[red]Invalid document type:[/red] {doc_type}")
        console.print(f"Valid types: {', '.join(VALID_DOC_TYPES)}")
        raise typer.Exit(1)

    manager = SessionManager()
    session = manager.get_session_by_name(session_name)
    if not session:
        console.print(f"[red]Session '{session_name}' not found.[/red]")
        raise typer.Exit(1)

    console.print(f"Parsing [bold]{file.name}[/bold]...")

    parser = DocumentParser(session_id=session.id)

    with console.status("Extracting data with OCR + AI vision..."):
        result = parser.parse_document(file, doc_type=doc_type)

    doc_type_label = DOC_TYPE_NAMES.get(result["doc_type"], result["doc_type"])
    confidence = result["confidence"]
    confidence_color = "green" if confidence >= 0.85 else "yellow" if confidence >= 0.6 else "red"

    console.print()
    console.print(Panel(
        f"[bold]Document Type:[/bold] {doc_type_label}\n"
        f"[bold]Confidence:[/bold] [{confidence_color}]{confidence:.0%}[/{confidence_color}]\n"
        f"[bold]Needs Review:[/bold] {'Yes' if result['needs_review'] else 'No'}",
        title="Extraction Result",
        border_style="blue",
    ))

    # Show extracted data
    if result["extracted_data"]:
        console.print()
        console.print("[bold]Extracted Fields:[/bold]")
        for key, value in result["extracted_data"].items():
            if value and value != 0 and value != 0.0:
                if isinstance(value, float):
                    console.print(f"  {key}: ${value:,.2f}")
                else:
                    console.print(f"  {key}: {value}")

    if result["needs_review"]:
        console.print()
        console.print("[yellow]This document needs review due to low confidence.[/yellow]")
        console.print("Run [bold]tax-prep docs review[/bold] to verify extracted data.")

    # Ask if user wants to apply to profile
    console.print()
    apply = typer.confirm("Apply this data to your tax profile?")
    if apply:
        profile = manager.get_tax_profile(session.id)
        profile = parser.apply_to_profile(result["extracted_data"], result["doc_type"], profile)
        manager.save_tax_profile(session.id, profile)
        console.print("[green]Data applied to profile.[/green]")


@docs_app.command("list")
def list_docs(
    session_name: str = typer.Option(..., "--session", "-s", help="Session name"),
):
    """List all uploaded documents for a session."""
    manager = SessionManager()
    session = manager.get_session_by_name(session_name)
    if not session:
        console.print(f"[red]Session '{session_name}' not found.[/red]")
        raise typer.Exit(1)

    parser = DocumentParser(session_id=session.id)
    docs = parser.get_documents()

    if not docs:
        console.print("[dim]No documents uploaded yet.[/dim]")
        return

    table = Table(title="Uploaded Documents")
    table.add_column("Type", style="bold")
    table.add_column("File")
    table.add_column("Confidence")
    table.add_column("Review?")
    table.add_column("ID", style="dim")

    for doc in docs:
        conf = doc["confidence"]
        conf_color = "green" if conf >= 0.85 else "yellow" if conf >= 0.6 else "red"
        table.add_row(
            DOC_TYPE_NAMES.get(doc["doc_type"], doc["doc_type"]),
            Path(doc["file_path"]).name,
            f"[{conf_color}]{conf:.0%}[/{conf_color}]",
            "Yes" if doc["needs_review"] else "No",
            doc["id"][:8],
        )

    console.print(table)


@docs_app.command("check")
def check_docs(
    session_name: str = typer.Option(..., "--session", "-s", help="Session name"),
):
    """Cross-reference uploaded documents and flag issues."""
    manager = SessionManager()
    session = manager.get_session_by_name(session_name)
    if not session:
        console.print(f"[red]Session '{session_name}' not found.[/red]")
        raise typer.Exit(1)

    parser = DocumentParser(session_id=session.id)
    profile = manager.get_tax_profile(session.id)
    warnings = parser.cross_reference_documents(profile)

    if not warnings:
        console.print("[green]All documents look consistent. No issues found.[/green]")
    else:
        console.print(f"[yellow]Found {len(warnings)} issue(s):[/yellow]")
        for i, warning in enumerate(warnings, 1):
            console.print(f"  {i}. {warning}")
