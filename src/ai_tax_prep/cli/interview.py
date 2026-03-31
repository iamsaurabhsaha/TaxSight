"""CLI interview command — interactive terminal interview loop."""


import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from ai_tax_prep.core.interview_engine import InterviewEngine
from ai_tax_prep.core.interview_steps import get_step
from ai_tax_prep.core.session import SessionManager

console = Console()

HELP_TEXT = """
[bold]Available commands during the interview:[/bold]
  /skip    — Skip the current step (if optional)
  /back    — Go back to the previous step
  /status  — Show progress and collected data
  /help    — Show this help message
  /quit    — Save and exit (you can resume later)

[bold]Document upload:[/bold]
  During the document upload step, type a file path to upload:
    ~/Documents/w2.png
    /path/to/1099.pdf
  Type 'done' when finished uploading.
"""


def run_interview(
    session_name: str | None = None,
    session_id: str | None = None,
):
    """Run the interactive tax interview."""
    manager = SessionManager()

    # Find session
    session = None
    if session_id:
        session = manager.get_session(session_id)
    elif session_name:
        session = manager.get_session_by_name(session_name)

    if not session:
        console.print("[red]Session not found.[/red] Create one first with: tax-prep session create --name <name>")
        raise typer.Exit(1)

    console.print()
    console.print(Panel(
        f"[bold]Tax Prep Interview[/bold] — {session.name} (Tax Year {session.tax_year})\n"
        f"Type [bold]/help[/bold] for commands, [bold]/quit[/bold] to save and exit.",
        border_style="blue",
    ))
    console.print()

    # Initialize engine
    try:
        engine = InterviewEngine(session_id=session.id)
    except Exception as e:
        console.print(f"[red]Error initializing interview:[/red] {e}")
        raise typer.Exit(1)

    # Generate opening message for current step
    _display_step_message(engine)

    # Main interview loop
    while True:
        console.print()
        try:
            user_input = console.input("[bold green]You:[/bold green] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Saving progress and exiting...[/dim]")
            break

        if not user_input:
            # Empty input during document_upload = done uploading
            if engine.current_step_id in ("document_upload", "document_review", "income_gaps"):
                _finish_document_upload(engine)
            continue

        # Check for file paths on ANY income-related step (not just document_upload)
        # This handles cases where the step already advanced but user still has documents
        # Check for file paths on ANY step — users may paste documents at any point
        if True:
            cleaned = user_input.replace("\\ ", " ")
            first_word = cleaned.split()[0] if cleaned.split() else cleaned
            is_slash_cmd = first_word.lower() in ("/skip", "/back", "/status", "/help", "/quit", "/exit")
            if not is_slash_cmd and not cleaned.lower() == "done" and _looks_like_file_path(first_word):
                _handle_multi_upload(engine, user_input)
                continue

        # Handle slash commands
        if user_input.startswith("/") and user_input.split()[0].lower() in ("/skip", "/back", "/status", "/help", "/quit", "/exit"):
            command = user_input.lower().split()[0]

            if command == "/quit" or command == "/exit":
                console.print("[dim]Progress saved. You can resume with:[/dim]")
                console.print(f"  tax-prep interview --name \"{session.name}\"")
                break

            elif command == "/help":
                console.print(HELP_TEXT)
                continue

            elif command == "/status":
                status = engine.get_status_display()
                console.print(Panel(status, title="Interview Status", border_style="cyan"))
                continue

            elif command == "/back":
                prev = engine.go_back()
                if prev:
                    console.print(f"[dim]Going back to: {get_step(prev).title}[/dim]")
                    console.print()
                    _display_step_message(engine)
                else:
                    console.print("[dim]Already at the first step.[/dim]")
                continue

            elif command == "/skip":
                step = engine.get_current_step()
                if step and step.skippable:
                    from ai_tax_prep.core.interview_steps import get_next_step
                    next_id = get_next_step(step.id, engine.profile)
                    if next_id:
                        engine.current_step_id = next_id
                        engine._update_session_step(next_id)
                        console.print(f"[dim]Skipped. Moving to: {get_step(next_id).title}[/dim]")
                        console.print()
                        _display_step_message(engine)
                    else:
                        console.print("[dim]No next step to skip to.[/dim]")
                else:
                    console.print("[dim]This step cannot be skipped.[/dim]")
                continue

            else:
                console.print(f"[dim]Unknown command: {command}. Type /help for options.[/dim]")
                continue

        # Process user input through the engine
        with Progress(
            SpinnerColumn(),
            TextColumn("[dim]Thinking...[/dim]"),
            console=console,
            transient=True,
        ):
            result = engine.process_user_input(user_input)

        # Display response
        response = result["response"]
        if response:
            console.print()
            console.print(f"[bold blue]Assistant:[/bold blue] {response}")

        # Display any warnings
        for warning in result.get("warnings", []):
            console.print()
            console.print(Panel(warning, title="Note", border_style="yellow"))

        # Handle action
        action = result["action"]
        if action == "complete":
            console.print()
            # Auto-calculate and show results
            _run_auto_calculate(engine, session)
            break

        elif action == "next":
            # Auto-generate the next step's opening message
            console.print()
            _display_step_message(engine)


def _display_step_message(engine: InterviewEngine):
    """Display the step header and LLM's opening message."""
    step = engine.get_current_step()
    if not step:
        return

    progress = engine.get_progress()
    console.print(
        f"[dim]({progress['progress_pct']}%) {step.category.upper()} — {step.title}[/dim]"
    )

    # Stream the response
    console.print()
    console.print("[bold blue]Assistant:[/bold blue] ", end="")

    try:
        for chunk in engine.stream_step_message():
            console.print(chunk, end="", highlight=False)
        console.print()  # Newline after streaming
    except Exception:
        # Fallback to non-streaming
        console.print()
        try:
            msg = engine.generate_step_message()
            console.print(f"[bold blue]Assistant:[/bold blue] {msg}")
        except Exception as e2:
            console.print(f"[red]Error generating message:[/red] {e2}")
            console.print("[dim]You can still type your answer or /skip to continue.[/dim]")


def _handle_multi_upload(engine: InterviewEngine, raw_input: str):
    """Parse input that may contain one or multiple file paths and upload each."""
    import re
    from pathlib import Path

    raw = raw_input.strip()

    # Remove trailing "done" if user appended it
    if raw.lower().endswith(" done"):
        raw = raw[:-5].strip()

    # Replace backslash-escaped spaces with regular spaces
    raw = raw.replace("\\ ", " ")

    # Insert a newline between files at extension boundaries:
    # ".pdf /Users" becomes ".pdf\n/Users", ".png ~/Doc" becomes ".png\n~/Doc"
    raw = re.sub(r'\.(pdf|png|jpg|jpeg|tiff|bmp|gif|webp)\s+(?=[/~])', r'.\1\n', raw, flags=re.IGNORECASE)

    # Split by newlines to get individual paths
    paths = [p.strip() for p in raw.split("\n") if p.strip()]

    # Validate each path exists
    valid_paths = []
    not_found = []
    for p in paths:
        expanded = Path(p).expanduser()
        if expanded.exists():
            valid_paths.append(str(expanded))
        else:
            not_found.append(p)

    if not valid_paths and not_found:
        console.print(f"[red]File(s) not found:[/red]")
        for nf in not_found[:3]:
            console.print(f"  {nf}")
        console.print("[dim]Check the path and try again, or press Enter to skip.[/dim]")
        return

    # Upload each file
    success_count = 0
    for file_path in valid_paths:
        _handle_document_upload(engine, file_path)
        success_count += 1

    if not_found:
        console.print()
        console.print(f"[yellow]Could not find {len(not_found)} file(s):[/yellow]")
        for nf in not_found:
            console.print(f"  [dim]{nf}[/dim]")

    console.print()
    console.print(f"[dim]Processed {success_count} document(s). Paste more paths, or press Enter when done.[/dim]")


def _run_auto_calculate(engine: InterviewEngine, session):
    """Auto-calculate taxes at the end of the interview and show results."""
    from ai_tax_prep.tax.engine import TaxEngine
    from ai_tax_prep.export.templates import format_currency

    console.print(Panel("[bold]Calculating your tax estimate...[/bold]", border_style="green"))

    try:
        tax_engine = TaxEngine(session_id=session.id)
        result = tax_engine.calculate(engine.profile)

        federal_ro = result.get("federal_refund_or_owed", 0)
        state_ro = result.get("state_refund_or_owed", 0)
        total_ro = result.get("total_refund_or_owed", 0)

        # Build results display
        lines = []
        lines.append(f"[bold]Federal Income Tax:[/bold] {format_currency(result.get('federal_income_tax', 0))}")
        se_tax = result.get('se_tax_detail', {}).get('total_se_tax', 0)
        if se_tax > 0:
            lines.append(f"[bold]Self-Employment Tax:[/bold] {format_currency(se_tax)}")
        lines.append(f"[bold]State Income Tax ({result.get('state', '')}):[/bold] {format_currency(result.get('state_income_tax', 0))}")
        lines.append("")

        # Federal result
        if federal_ro >= 0:
            lines.append(f"[bold green]Federal Refund: {format_currency(federal_ro)}[/bold green]")
        else:
            lines.append(f"[bold red]Federal Amount Owed: {format_currency(abs(federal_ro))}[/bold red]")

        # State result
        if state_ro >= 0:
            lines.append(f"[bold green]State Refund: {format_currency(state_ro)}[/bold green]")
        else:
            lines.append(f"[bold red]State Amount Owed: {format_currency(abs(state_ro))}[/bold red]")

        lines.append("")
        if total_ro >= 0:
            lines.append(f"[bold green]>>> TOTAL REFUND: {format_currency(total_ro)} <<<[/bold green]")
        else:
            lines.append(f"[bold red]>>> TOTAL OWED: {format_currency(abs(total_ro))} <<<[/bold red]")

        lines.append("")
        lines.append(f"Effective Tax Rate: {result.get('effective_total_rate', 0):.1f}%")

        console.print(Panel("\n".join(lines), title="Tax Estimate Results", border_style="cyan"))

        # Show warnings
        for warning in result.get("warnings", []):
            console.print(Panel(warning, title="Note", border_style="yellow"))

        # Show suggestions summary
        suggestions = result.get("deduction_credit_suggestions", [])
        applicable = [s for s in suggestions if s.get("applies") is True]
        if applicable:
            console.print()
            console.print("[bold]Tax Savings Opportunities:[/bold]")
            for s in applicable[:3]:
                value = f" ({format_currency(s['estimated_value'])})" if s.get("estimated_value") else ""
                console.print(f"  [green]•[/green] {s['name']}{value}")

        console.print()
        console.print("[dim]For a detailed PDF report: tax-prep report --name \"" + session.name + "\"[/dim]")
        console.print("[dim]For what-if scenarios: tax-prep what-if --name \"" + session.name + "\" -s \"ira_contribution=7000\"[/dim]")
        console.print()
        console.print("[dim]Disclaimer: This is an estimate for informational purposes only. Not professional tax advice.[/dim]")

    except Exception as e:
        console.print(f"[red]Error calculating taxes:[/red] {e}")
        console.print("You can try manually: tax-prep calculate --name \"" + session.name + "\"")


def _finish_document_upload(engine: InterviewEngine):
    """Show document summary and advance past document steps."""
    docs = engine._get_document_summary()
    if "No documents uploaded" in docs:
        console.print()
        console.print("[dim]No documents uploaded. Moving to manual entry...[/dim]")
    else:
        console.print()
        console.print(Panel(docs, title="Documents Uploaded", border_style="blue"))
        console.print()
        confirm = console.input("[bold green]Does this look correct? (yes/no/upload more):[/bold green] ").strip()
        confirm_lower = confirm.lower()
        if confirm_lower in ("no", "n"):
            console.print("[dim]Paste corrected document paths or type /skip to enter manually.[/dim]")
            return
        if _looks_like_file_path(confirm.replace("\\ ", " ")):
            _handle_document_upload(engine, confirm.replace("\\ ", " "))
            return
        if confirm_lower not in ("yes", "y", ""):
            # User typed a correction or comment — save it so LLM sees it in context
            engine._save_message("user", confirm)
            console.print("[dim]Noted. I'll take that into account.[/dim]")

    # Advance to adjustments (skip document_review and income_gaps if we have docs)
    from ai_tax_prep.core.interview_steps import get_step
    target = "adjustments" if "No documents" not in docs else "income_sources"

    # If we have document data, skip manual income entry
    engine.current_step_id = target
    engine._update_session_step(target)
    _display_step_message(engine)


def _looks_like_file_path(text: str) -> bool:
    """Check if input looks like a file path."""
    from pathlib import Path

    text = text.strip().replace("\\ ", " ")
    if not text:
        return False
    # Common file path indicators
    if text.startswith(("~/", "/", "./", "../")):
        return True
    if any(text.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".pdf", ".tiff", ".bmp", ".gif", ".webp")):
        return True
    # Check if the expanded path actually exists
    try:
        return Path(text).expanduser().exists()
    except Exception:
        return False


def _handle_document_upload(engine: InterviewEngine, file_path: str):
    """Handle a document upload during the interview."""
    from ai_tax_prep.documents.schemas import DOC_TYPE_NAMES

    console.print(f"\n[dim]Uploading {file_path}...[/dim]")

    with console.status("Parsing document with AI vision..."):
        result = engine.upload_document(file_path)

    if not result["success"]:
        console.print(f"[red]Error:[/red] {result['error']}")
        console.print("[dim]Try another file or type 'done' to continue.[/dim]")
        return

    doc_type = result["doc_type"]
    confidence = result["confidence"]
    data = result["extracted_data"]
    label = DOC_TYPE_NAMES.get(doc_type, doc_type)
    conf_color = "green" if confidence >= 0.85 else "yellow" if confidence >= 0.6 else "red"

    console.print()
    console.print(Panel(
        f"[bold]Document:[/bold] {label}\n"
        f"[bold]Confidence:[/bold] [{conf_color}]{confidence:.0%}[/{conf_color}]",
        title="Extracted",
        border_style="blue",
    ))

    # Show key extracted fields
    if data:
        for key, value in data.items():
            if value and value != 0 and value != 0.0 and value != "":
                if isinstance(value, float):
                    console.print(f"  {key}: ${value:,.2f}")
                else:
                    console.print(f"  {key}: {value}")

    console.print()
    if result.get("skipped"):
        console.print("[dim]Skipped — supplemental document (data already captured from primary form).[/dim]")
    else:
        console.print("[green]Data applied to your profile.[/green]")

        if result["needs_review"]:
            console.print("[yellow]Low confidence — please verify the numbers above.[/yellow]")

    console.print("[dim]Paste another file path, or press Enter when done.[/dim]")
