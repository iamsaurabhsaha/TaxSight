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
            continue

        # Handle slash commands
        if user_input.startswith("/"):
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
