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
        console.print("[red]Session not found.[/red] Create one first with: taxsight session create --name <name>")
        raise typer.Exit(1)

    console.print()
    console.print(Panel(
        f"[bold]TaxSight Interview[/bold] — {session.name} (Tax Year {session.tax_year})\n"
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
            # Empty input = done uploading (if documents were uploaded)
            doc_summary = engine._get_document_summary()
            if "No documents uploaded" not in doc_summary:
                _finish_document_upload(engine)
                break  # Exit interview loop — calculation already shown
            continue

        # "done" / "Done" also triggers document review
        if user_input.lower().strip() == "done":
            doc_summary = engine._get_document_summary()
            if "No documents uploaded" not in doc_summary:
                _finish_document_upload(engine)
                break
            # No docs, treat as regular input

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
                console.print(f"  taxsight interview --name \"{session.name}\"")
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

        # Step-by-step breakdown
        breakdown = []
        breakdown.append("[bold underline]INCOME[/bold underline]")
        breakdown.append(f"  Wages (W-2):                {format_currency(engine.profile.income.total_wages())}")
        interest = engine.profile.income.total_interest()
        if interest > 0:
            breakdown.append(f"  Interest Income:            {format_currency(interest)}")
        dividends = engine.profile.income.total_dividends()
        if dividends > 0:
            qual = engine.profile.income.total_qualified_dividends()
            breakdown.append(f"  Dividends:                  {format_currency(dividends)} ({format_currency(qual)} qualified)")
        se = engine.profile.income.total_self_employment()
        if se > 0:
            breakdown.append(f"  Self-Employment:            {format_currency(se)}")
        cg = engine.profile.income.total_capital_gains()
        if cg != 0:
            breakdown.append(f"  Capital Gains/Losses:       {format_currency(cg)}")
        rental = engine.profile.income.total_rental()
        if rental != 0:
            breakdown.append(f"  Rental Income:              {format_currency(rental)}")
        retirement = engine.profile.income.total_retirement()
        if retirement > 0:
            breakdown.append(f"  Retirement (taxable):       {format_currency(retirement)}")
        breakdown.append(f"  [bold]Total Gross Income:        {format_currency(result.get('total_gross_income', 0))}[/bold]")

        breakdown.append("")
        breakdown.append("[bold underline]ADJUSTMENTS[/bold underline]")
        adj = engine.profile.adjustments
        if adj.student_loan_interest > 0:
            breakdown.append(f"  Student Loan Interest:      {format_currency(adj.student_loan_interest)} (see note below)")
        if adj.hsa_contributions > 0:
            breakdown.append(f"  HSA Contributions:          {format_currency(adj.hsa_contributions)}")
        if adj.ira_contributions > 0:
            breakdown.append(f"  IRA Contributions:          {format_currency(adj.ira_contributions)}")
        if adj.total() == 0:
            breakdown.append("  (none)")
        breakdown.append(f"  [bold]Adjusted Gross Income:     {format_currency(result.get('agi', 0))}[/bold]")

        breakdown.append("")
        breakdown.append("[bold underline]DEDUCTIONS[/bold underline]")
        if result.get('itemizes'):
            breakdown.append(f"  Method: Itemized")
            breakdown.append(f"  Itemized Total:             {format_currency(result.get('itemized_total', 0))}")
        else:
            breakdown.append(f"  Method: Standard Deduction")
            breakdown.append(f"  Standard Deduction:         {format_currency(result.get('standard_deduction', 0))}")
        breakdown.append(f"  [bold]Taxable Income:            {format_currency(result.get('taxable_income', 0))}[/bold]")

        breakdown.append("")
        breakdown.append("[bold underline]FEDERAL TAX[/bold underline]")
        breakdown.append(f"  Income Tax:                 {format_currency(result.get('federal_income_tax', 0))}")
        se_tax = result.get('se_tax_detail', {}).get('total_se_tax', 0)
        if se_tax > 0:
            breakdown.append(f"  Self-Employment Tax:        {format_currency(se_tax)}")
        breakdown.append(f"  [bold]Total Federal Tax:         {format_currency(result.get('total_federal_tax', 0))}[/bold]")

        if result.get('eitc', 0) > 0 or result.get('child_tax_credit', 0) > 0:
            breakdown.append("")
            breakdown.append("[bold underline]CREDITS[/bold underline]")
            if result.get('eitc', 0) > 0:
                breakdown.append(f"  Earned Income Credit:       {format_currency(result['eitc'])}")
            if result.get('child_tax_credit', 0) > 0:
                breakdown.append(f"  Child Tax Credit:           {format_currency(result['child_tax_credit'])}")

        breakdown.append("")
        breakdown.append("[bold underline]STATE TAX ({0})[/bold underline]".format(result.get('state', '')))
        breakdown.append(f"  State Income Tax:           {format_currency(result.get('state_income_tax', 0))}")

        breakdown.append("")
        breakdown.append("[bold underline]PAYMENTS & WITHHOLDING[/bold underline]")
        breakdown.append(f"  Federal Withheld (W-2):     {format_currency(result.get('federal_withholding', 0))}")
        if result.get('estimated_federal_payments', 0) > 0:
            breakdown.append(f"  Estimated Payments:         {format_currency(result['estimated_federal_payments'])}")
        breakdown.append(f"  State Withheld (W-2):       {format_currency(result.get('state_withholding', 0))}")

        breakdown.append("")
        breakdown.append("[bold underline]RESULT[/bold underline]")
        if federal_ro >= 0:
            breakdown.append(f"  [green]Federal Refund:            {format_currency(federal_ro)}[/green]")
        else:
            breakdown.append(f"  [red]Federal Amount Owed:       {format_currency(abs(federal_ro))}[/red]")
        if state_ro >= 0:
            breakdown.append(f"  [green]State Refund:              {format_currency(state_ro)}[/green]")
        else:
            breakdown.append(f"  [red]State Amount Owed:         {format_currency(abs(state_ro))}[/red]")

        breakdown.append("")
        if total_ro >= 0:
            breakdown.append(f"  [bold green]>>> TOTAL REFUND: {format_currency(total_ro)} <<<[/bold green]")
        else:
            breakdown.append(f"  [bold red]>>> TOTAL OWED: {format_currency(abs(total_ro))} <<<[/bold red]")
        breakdown.append("")
        breakdown.append(f"  Effective Tax Rate: {result.get('effective_total_rate', 0):.1f}%")

        console.print(Panel("\n".join(breakdown), title="Tax Estimate Breakdown", border_style="cyan"))

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
        console.print("[dim]For a detailed PDF report: taxsight report --name \"" + session.name + "\"[/dim]")
        console.print("[dim]For what-if scenarios: taxsight what-if --name \"" + session.name + "\" -s \"ira_contribution=7000\"[/dim]")
        console.print()
        console.print("[dim]Disclaimer: This is an estimate for informational purposes only. Not professional tax advice.[/dim]")

    except Exception as e:
        console.print(f"[red]Error calculating taxes:[/red] {e}")
        console.print("You can try manually: taxsight calculate --name \"" + session.name + "\"")


def _finish_document_upload(engine: InterviewEngine):
    """Show document summary, ask quick questions, then calculate."""
    docs = engine._get_document_summary()
    if "No documents uploaded" in docs:
        console.print()
        console.print("[dim]No documents uploaded. Moving to manual entry...[/dim]")
        # Fall back to manual interview flow
        engine.current_step_id = "income_sources"
        engine._update_session_step("income_sources")
        _display_step_message(engine)
        return

    # Show what we extracted
    console.print()
    console.print(Panel(docs, title="Documents Uploaded", border_style="blue"))
    console.print()

    # Quick confirmation
    confirm = console.input("[bold green]Does this look correct? (yes/no/upload more):[/bold green] ").strip()
    confirm_lower = confirm.lower()
    if confirm_lower in ("no", "n"):
        console.print("[dim]Paste corrected document paths or type /skip to enter manually.[/dim]")
        return
    if _looks_like_file_path(confirm.replace("\\ ", " ")):
        _handle_document_upload(engine, confirm.replace("\\ ", " "))
        return
    if confirm_lower not in ("yes", "y", ""):
        engine._save_message("user", confirm)
        console.print("[dim]Noted.[/dim]")

    # Quick questions that documents can't answer
    console.print()
    dependents = console.input("[bold green]Do you have any dependents? (yes/no):[/bold green] ").strip().lower()
    if dependents in ("yes", "y"):
        num = console.input("[bold green]How many, and their ages? (e.g., '2 kids, ages 5 and 8'):[/bold green] ").strip()
        engine._save_message("user", f"Dependents: {num}")
        # Parse basic dependent info
        import re
        ages = re.findall(r'\b(\d{1,2})\b', num)
        for i, age_str in enumerate(ages):
            from ai_tax_prep.core.tax_profile import Dependent
            engine.profile.personal_info.dependents.append(
                Dependent(relationship="child", age=int(age_str))
            )
        engine._save_profile()
        console.print(f"[dim]Added {len(ages)} dependent(s).[/dim]")

    console.print()
    deduction = console.input("[bold green]Standard deduction or itemized? (standard/itemized/auto):[/bold green] ").strip().lower()
    if deduction == "itemized":
        engine.profile.use_itemized = True
        console.print()
        console.print("[dim]For itemized, I'll need a few amounts:[/dim]")
        try:
            salt = console.input("  State/local taxes paid (SALT, max $10K): $").strip()
            mortgage = console.input("  Mortgage interest: $").strip()
            charity = console.input("  Charitable donations: $").strip()
            from ai_tax_prep.documents.parser import _safe_float
            engine.profile.itemized_deductions.state_local_taxes = min(_safe_float(salt), 10000)
            engine.profile.itemized_deductions.mortgage_interest = _safe_float(mortgage)
            engine.profile.itemized_deductions.charitable_cash = _safe_float(charity)
        except (KeyboardInterrupt, EOFError):
            pass
    elif deduction == "auto":
        engine.profile.use_itemized = None
    else:
        engine.profile.use_itemized = False

    engine._save_profile()

    # Go straight to calculation — no more LLM chat steps
    console.print()
    # Need session object for _run_auto_calculate
    from ai_tax_prep.core.session import SessionManager
    mgr = SessionManager()
    session = mgr.get_session(engine.session_id)
    _run_auto_calculate(engine, session)


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
