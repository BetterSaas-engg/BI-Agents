"""CLI entry point for the BI agent.

Usage:
    python -m bi_agent ask "How many orders were placed in 2017 by state?"
    python -m bi_agent ask "What is the average review score?" --verbose
"""

import argparse
import logging
import os
import sys

from rich.console import Console
from rich.table import Table

from bi_agent.pipeline import ask

# Force UTF-8 output on Windows to avoid cp1252 encoding errors with Rich
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
from bi_agent.types import Answer

console = Console()


def _print_answer(answer: Answer, verbose: bool = False) -> None:
    """Pretty-print an Answer to the terminal using rich."""
    console.print()

    # SQL
    console.print("[bold cyan]SQL Query:[/bold cyan]")
    console.print(f"```sql\n{answer.sql}\n```")
    console.print()

    # Result table
    if not answer.result.empty:
        console.print("[bold cyan]Result:[/bold cyan]")
        table = Table(show_lines=False)
        df = answer.result.head(30)
        for col in df.columns:
            table.add_column(str(col))
        for _, row in df.iterrows():
            table.add_row(*[str(v) for v in row])
        console.print(table)
        if len(answer.result) > 30:
            console.print(f"  ... ({len(answer.result)} total rows, showing first 30)")
        console.print()
    else:
        console.print("[yellow]No results returned.[/yellow]")
        console.print()

    # Chart
    if answer.chart_path:
        console.print(f"[bold cyan]Chart:[/bold cyan] {answer.chart_path}")
        console.print()

    # Explanation
    console.print("[bold cyan]Explanation:[/bold cyan]")
    console.print(answer.explanation)
    console.print()

    # Verbose: agent trace
    if verbose:
        _print_trace(answer)


def _print_trace(answer: Answer) -> None:
    """Print the agent trace for debugging."""
    trace = answer.trace
    console.print("[bold magenta]--- Agent Trace ---[/bold magenta]")
    console.print(f"  Retrieved tables: {answer.relevant_tables}")
    console.print(
        f"  Iterations: {trace.total_iterations}, "
        f"Tokens: {trace.total_input_tokens} in + {trace.total_output_tokens} out"
    )
    if trace.budget_exhausted:
        console.print("  [red]Budget exhausted![/red]")
    if trace.error:
        console.print(f"  [red]Error: {trace.error}[/red]")
    console.print()

    for step in trace.steps:
        status = "[red]ERROR[/red]" if step.was_error else "[green]OK[/green]"
        compliance = ""
        if step.dry_run_preceded is not None:
            if step.dry_run_preceded:
                compliance = " [green](dry_run: yes)[/green]"
            else:
                compliance = " [red](dry_run: NO)[/red]"

        console.print(f"  Step {step.step_number}: {step.tool_name} {status}{compliance}")
        # Show input compactly
        input_str = str(step.tool_input)
        if len(input_str) > 120:
            input_str = input_str[:120] + "..."
        console.print(f"    Input: {input_str}")

        # Show truncated output
        output_preview = step.tool_output[:200].replace("\n", " ")
        if len(step.tool_output) > 200:
            output_preview += "..."
        console.print(f"    Output: {output_preview}")
        console.print()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="bi_agent",
        description="LLM-driven BI agent for the Olist e-commerce dataset",
    )
    subparsers = parser.add_subparsers(dest="command")

    ask_parser = subparsers.add_parser("ask", help="Ask a business question")
    ask_parser.add_argument("question", help="The business question to answer")
    ask_parser.add_argument("--verbose", "-v", action="store_true", help="Show agent trace")

    args = parser.parse_args()

    if args.command == "ask":
        # Set our logger to DEBUG in verbose mode, but keep third-party loggers quiet
        log_level = logging.DEBUG if args.verbose else logging.INFO
        logging.basicConfig(
            level=logging.WARNING,
            format="%(levelname)s: %(name)s: %(message)s",
        )
        logging.getLogger("bi_agent").setLevel(log_level)

        try:
            answer = ask(args.question)
            _print_answer(answer, verbose=args.verbose)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)
