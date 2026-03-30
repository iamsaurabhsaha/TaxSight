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

        # Handle document upload step specially
        if engine.current_step_id == "document_upload":
            # Empty input (just Enter) = done uploading, show review
            if not user_input or user_input.lower().strip() == "done":
                docs = engine._get_document_summary()
                if "No documents uploaded" in docs:
                    console.print()
                    console.print("[dim]No documents uploaded. Moving to manual entry...[/dim]")
                else:
                    # Show summary and ask for approval
                    console.print()
                    console.print(Panel(docs, title="Documents Uploaded", border_style="blue"))
                    console.print()
                    confirm = console.input("[bold green]Does this look correct? (yes/no/upload more):[/bold green] ").strip().lower()
                    if confirm in ("no", "n"):
                        console.print("[dim]You can upload corrected documents or type /skip to enter manually.[/dim]")
                        continue
                    if _looks_like_file_path(confirm):
                        _handle_document_upload(engine, confirm)
                        continue
                    if confirm not in ("yes", "y", ""):
                        # They might be uploading another file
                        if _looks_like_file_path(confirm):
                            _handle_document_upload(engine, confirm)
                            continue

                # Move to next step
                from ai_tax_prep.core.interview_steps import get_next_step
                next_id = get_next_step("document_upload", engine.profile)
                if next_id:
                    engine.current_step_id = next_id
                    engine._update_session_step(next_id)
                    _display_step_message(engine)
                continue

            # Check if it's a slash command
            first_word = user_input.split()[0] if user_input.split() else user_input
            is_slash_cmd = first_word.lower() in ("/skip", "/back", "/status", "/help", "/quit", "/exit")
            if not is_slash_cmd and _looks_like_file_path(first_word):
                _handle_multi_upload(engine, user_input)
                continue
            # Fall through to slash command handling

        if not user_input:
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
            console.print(Panel(
                "[bold green]Interview complete![/bold green]\n\n"
                "You can now:\n"
                "  • Run [bold]tax-prep calculate[/bold] to get your tax estimate\n"
                "  • Run [bold]tax-prep report generate[/bold] to create a PDF summary",
                border_style="green",
            ))
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

    # Strategy: split by common PDF/image extensions to find file boundaries
    # This handles paths with spaces (common in macOS)
    file_extensions = r'\.(pdf|png|jpg|jpeg|tiff|bmp|gif|webp)'
    parts = re.split(f'({file_extensions})\\s+(?=/|~)', raw, flags=re.IGNORECASE)

    # Reconstruct file paths
    paths = []
    i = 0
    while i < len(parts):
        chunk = parts[i]
        # Check if next part is an extension
        if i + 1 < len(parts) and re.match(file_extensions, parts[i + 1], re.IGNORECASE):
            paths.append(chunk + parts[i + 1])
            i += 2
        else:
            if chunk.strip():
                paths.append(chunk)
            i += 1

    # If splitting didn't work well, try as a single path
    if not paths or (len(paths) == 1 and paths[0] == raw):
        # Try single path — remove backslash escapes
        single_path = raw.replace("\\ ", " ")
        _handle_document_upload(engine, single_path)
        return

    # Upload each file
    for file_path in paths:
        file_path = file_path.strip().replace("\\ ", " ")
        if file_path:
            _handle_document_upload(engine, file_path)

    console.print()
    console.print(f"[dim]Uploaded {len(paths)} document(s). Upload more or type 'done' to continue.[/dim]")


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
    console.print("[green]Data applied to your profile.[/green]")

    if result["needs_review"]:
        console.print("[yellow]Low confidence — please verify the numbers above.[/yellow]")

    console.print("[dim]Paste another file path, or press Enter when done.[/dim]")
