"""CLI commands for tax calculation and PDF report generation."""

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_tax_prep.core.session import SessionManager
from ai_tax_prep.export.pdf_report import generate_report
from ai_tax_prep.export.templates import format_currency, format_percentage
from ai_tax_prep.tax.engine import TaxEngine

console = Console()


def run_calculate(session_name: str):
    """Run tax calculation for a session and display results."""
    manager = SessionManager()
    session = manager.get_session_by_name(session_name)
    if not session:
        console.print(f"[red]Session '{session_name}' not found.[/red]")
        raise typer.Exit(1)

    profile = manager.get_tax_profile(session.id)
    if not profile.personal_info.filing_status:
        console.print("[red]No tax profile data. Run the interview first:[/red]")
        console.print(f"  tax-prep interview --name \"{session_name}\"")
        raise typer.Exit(1)

    engine = TaxEngine(session_id=session.id)

    with console.status("Calculating taxes..."):
        result = engine.calculate(profile)

    _display_results(result)

    # Display warnings
    for warning in result.get("warnings", []):
        console.print(Panel(warning, title="Warning", border_style="yellow"))

    # Generate explanation
    console.print()
    with console.status("Generating plain-English explanation..."):
        explanation = engine.explain_results(result)
    console.print(Panel(explanation, title="Summary", border_style="blue"))

    # Show deduction/credit suggestions
    suggestions = result.get("deduction_credit_suggestions", [])
    applicable = [s for s in suggestions if s.get("applies") is True]
    possible = [s for s in suggestions if s.get("applies") is None]

    if applicable or possible:
        console.print()
        console.print("[bold]Deduction & Credit Opportunities:[/bold]")
        if applicable:
            for s in applicable:
                value = f" (est. {format_currency(s['estimated_value'])})" if s.get("estimated_value") else ""
                console.print(f"  [green]✓[/green] {s['name']}{value}")
        if possible:
            for s in possible:
                console.print(f"  [yellow]?[/yellow] {s['name']} — {s['explanation'][:80]}...")

    console.print()
    console.print(f"[dim]Run 'tax-prep report --name \"{session_name}\"' to generate a PDF report.[/dim]")


def run_report(session_name: str, output: str | None = None):
    """Generate a PDF report for a session."""
    manager = SessionManager()
    session = manager.get_session_by_name(session_name)
    if not session:
        console.print(f"[red]Session '{session_name}' not found.[/red]")
        raise typer.Exit(1)

    profile = manager.get_tax_profile(session.id)
    if not profile.personal_info.filing_status:
        console.print("[red]No tax profile data. Run the interview first.[/red]")
        raise typer.Exit(1)

    engine = TaxEngine(session_id=session.id)

    # Calculate
    with console.status("Calculating taxes..."):
        result = engine.calculate(profile)

    # Generate explanation
    with console.status("Generating summary..."):
        explanation = engine.explain_results(result)

    # Generate PDF
    if not output:
        output = f"tax_report_{session.name}_{session.tax_year}.pdf"

    output_path = Path(output)

    with console.status("Generating PDF report..."):
        path = generate_report(result, output_path, explanation)

    console.print(f"[green]Report saved to:[/green] {path.absolute()}")
    console.print()
    console.print("[dim]Disclaimer: This report is for informational purposes only.[/dim]")


def run_whatif(session_name: str, scenario: str):
    """Run a what-if tax scenario."""
    manager = SessionManager()
    session = manager.get_session_by_name(session_name)
    if not session:
        console.print(f"[red]Session '{session_name}' not found.[/red]")
        raise typer.Exit(1)

    profile = manager.get_tax_profile(session.id)
    engine = TaxEngine(session_id=session.id)

    # Parse scenario string (e.g., "ira_contribution=5000")
    changes = {}
    for part in scenario.split(","):
        if "=" in part:
            key, value = part.strip().split("=", 1)
            try:
                changes[key.strip()] = float(value.strip())
            except ValueError:
                changes[key.strip()] = value.strip()

    if not changes:
        console.print("[red]Invalid scenario format.[/red] Use: key=value,key2=value2")
        console.print("Examples:")
        console.print("  ira_contribution=5000")
        console.print("  charitable_donation=3000")
        console.print("  use_itemized=true")
        raise typer.Exit(1)

    with console.status("Running what-if scenario..."):
        result = engine.what_if(profile, changes)

    diff = result["difference"]

    console.print()
    console.print(Panel(
        f"[bold]Changes applied:[/bold] {result['changes_applied']}\n\n"
        f"Federal tax change: {format_currency(diff['federal_tax_change'])}\n"
        f"State tax change: {format_currency(diff['state_tax_change'])}\n"
        f"Total tax change: {format_currency(diff['total_tax_change'])}\n"
        f"Refund change: {format_currency(diff['refund_change'])}",
        title="What-If Results",
        border_style="cyan",
    ))

    if diff["total_tax_change"] < 0:
        console.print(f"\n[green]This scenario would save you {format_currency(abs(diff['total_tax_change']))} in taxes.[/green]")
    elif diff["total_tax_change"] > 0:
        console.print(f"\n[yellow]This scenario would increase your taxes by {format_currency(diff['total_tax_change'])}.[/yellow]")
    else:
        console.print("\n[dim]No change in total taxes.[/dim]")


def _display_results(result: dict):
    """Display tax calculation results in a formatted table."""
    console.print()

    # Income table
    table = Table(title=f"Tax Estimate — {result.get('tax_year', '')} ({result.get('filing_status', '').replace('_', ' ').title()})")
    table.add_column("", style="bold", width=35)
    table.add_column("Amount", justify="right", width=15)

    table.add_row("[bold underline]INCOME[/bold underline]", "")
    table.add_row("Total Gross Income", format_currency(result.get("total_gross_income", 0)))
    table.add_row("Adjusted Gross Income", format_currency(result.get("agi", 0)))
    table.add_row("Taxable Income", format_currency(result.get("taxable_income", 0)))

    table.add_row("", "")
    table.add_row("[bold underline]DEDUCTIONS[/bold underline]", "")
    method = "Itemized" if result.get("itemizes") else "Standard"
    table.add_row(f"Deduction ({method})", format_currency(
        result.get("itemized_total", 0) if result.get("itemizes") else result.get("standard_deduction", 0)
    ))

    table.add_row("", "")
    table.add_row("[bold underline]TAXES[/bold underline]", "")
    table.add_row("Federal Income Tax", format_currency(result.get("federal_income_tax", 0)))
    se_tax = result.get("se_tax_detail", {}).get("total_se_tax", 0)
    if se_tax > 0:
        table.add_row("Self-Employment Tax", format_currency(se_tax))
    table.add_row("Total Federal Tax", format_currency(result.get("total_federal_tax", 0)))
    table.add_row("State Income Tax", format_currency(result.get("state_income_tax", 0)))

    table.add_row("", "")
    table.add_row("[bold underline]CREDITS[/bold underline]", "")
    if result.get("eitc", 0) > 0:
        table.add_row("Earned Income Credit", format_currency(result["eitc"]))
    if result.get("child_tax_credit", 0) > 0:
        table.add_row("Child Tax Credit", format_currency(result["child_tax_credit"]))

    table.add_row("", "")
    table.add_row("[bold underline]PAYMENTS & REFUND[/bold underline]", "")
    table.add_row("Federal Withholding", format_currency(result.get("federal_withholding", 0)))
    table.add_row("Estimated Payments", format_currency(result.get("estimated_federal_payments", 0)))

    federal_ro = result.get("federal_refund_or_owed", 0)
    state_ro = result.get("state_refund_or_owed", 0)
    total_ro = result.get("total_refund_or_owed", 0)

    style = "green" if federal_ro >= 0 else "red"
    table.add_row(f"[{style}]Federal Refund / (Owed)[/{style}]", f"[{style}]{format_currency(federal_ro)}[/{style}]")
    style = "green" if state_ro >= 0 else "red"
    table.add_row(f"[{style}]State Refund / (Owed)[/{style}]", f"[{style}]{format_currency(state_ro)}[/{style}]")

    table.add_row("", "")
    style = "green bold" if total_ro >= 0 else "red bold"
    table.add_row(f"[{style}]TOTAL REFUND / (OWED)[/{style}]", f"[{style}]{format_currency(total_ro)}[/{style}]")

    table.add_row("", "")
    table.add_row("Effective Total Rate", format_percentage(result.get("effective_total_rate", 0)))

    console.print(table)
