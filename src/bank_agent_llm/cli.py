"""CLI entry point — thin wrapper over the Pipeline library API.

All business logic lives in the library modules (pipeline.py, ingestion/,
parsers/, enrichment/, storage/, chat/). This file only handles CLI concerns:
argument parsing, output formatting, and exit codes.
"""

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.logging import RichHandler

app = typer.Typer(
    name="bank-agent",
    help="Local-first AI pipeline for personal financial intelligence.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
db_app = typer.Typer(help="Database management commands.")
app.add_typer(db_app, name="db")

console = Console()
err_console = Console(stderr=True)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False)],
    )


# ─── Top-level commands ───────────────────────────────────────────────────────

@app.command()
def run(
    fetch: bool = typer.Option(True, help="Fetch new emails before processing."),
    parse: bool = typer.Option(True, help="Parse downloaded files."),
    enrich: bool = typer.Option(True, help="Categorise transactions via Ollama."),
    log_level: str = typer.Option("INFO", envvar="LOG_LEVEL", help="Logging verbosity."),
) -> None:
    """Run the full pipeline: fetch → parse → enrich → store."""
    _setup_logging(log_level)
    from bank_agent_llm.pipeline import Pipeline

    try:
        Pipeline().run(fetch=fetch, parse=parse, enrich=enrich)
    except NotImplementedError:
        err_console.print("[yellow]Pipeline not yet implemented. See docs/roadmap.md.[/yellow]")
        raise typer.Exit(1)


@app.command()
def fetch(
    log_level: str = typer.Option("INFO", envvar="LOG_LEVEL"),
) -> None:
    """Download new bank statements from configured email accounts."""
    _setup_logging(log_level)
    from bank_agent_llm.pipeline import Pipeline

    try:
        Pipeline().fetch()
    except NotImplementedError:
        err_console.print("[yellow]Not yet implemented (M2).[/yellow]")
        raise typer.Exit(1)


@app.command()
def parse(
    log_level: str = typer.Option("INFO", envvar="LOG_LEVEL"),
) -> None:
    """Parse downloaded statement files into normalised transactions."""
    _setup_logging(log_level)
    from bank_agent_llm.pipeline import Pipeline

    try:
        Pipeline().parse()
    except NotImplementedError:
        err_console.print("[yellow]Not yet implemented (M3).[/yellow]")
        raise typer.Exit(1)


@app.command()
def enrich(
    log_level: str = typer.Option("INFO", envvar="LOG_LEVEL"),
) -> None:
    """Categorise transactions using the local Ollama model."""
    _setup_logging(log_level)
    from bank_agent_llm.pipeline import Pipeline

    try:
        Pipeline().enrich()
    except NotImplementedError:
        err_console.print("[yellow]Not yet implemented (M4).[/yellow]")
        raise typer.Exit(1)


@app.command()
def status(
    log_level: str = typer.Option("INFO", envvar="LOG_LEVEL"),
) -> None:
    """Show a summary of transactions currently in the database."""
    _setup_logging(log_level)
    err_console.print("[yellow]Not yet implemented (M5).[/yellow]")
    raise typer.Exit(1)


@app.command()
def chat(
    log_level: str = typer.Option("INFO", envvar="LOG_LEVEL"),
) -> None:
    """Start an interactive natural-language chat session with your data."""
    _setup_logging(log_level)
    err_console.print("[yellow]Not yet implemented (M7).[/yellow]")
    raise typer.Exit(1)


@app.command("import")
def import_files(
    path: str = typer.Argument(..., help="Path to a statement file or directory of files."),
    log_level: str = typer.Option("INFO", envvar="LOG_LEVEL"),
) -> None:
    """Import statement files from a local path, skipping email ingestion.

    Use this when you have already downloaded statements from your bank's
    web portal or have an existing folder of PDFs/spreadsheets.
    """
    _setup_logging(log_level)
    from pathlib import Path

    from bank_agent_llm.pipeline import Pipeline

    try:
        Pipeline().import_files(Path(path))
    except NotImplementedError:
        err_console.print("[yellow]Not yet implemented (M2).[/yellow]")
        raise typer.Exit(1)
    except FileNotFoundError:
        err_console.print(f"[red]Path not found: {path}[/red]")
        raise typer.Exit(1)


@app.command("config-check")
def config_check() -> None:
    """Validate the current configuration file and report any errors."""
    err_console.print("[yellow]Not yet implemented (M1).[/yellow]")
    raise typer.Exit(1)


# ─── DB sub-commands ─────────────────────────────────────────────────────────

@db_app.command("migrate")
def db_migrate() -> None:
    """Apply pending Alembic database migrations."""
    err_console.print("[yellow]Not yet implemented (M1).[/yellow]")
    raise typer.Exit(1)


@db_app.command("purge")
def db_purge(
    before: str = typer.Option(..., help="Delete transactions before this date (YYYY-MM-DD)."),
    confirm: bool = typer.Option(False, "--yes", help="Skip confirmation prompt."),
) -> None:
    """Delete all transactions before a given date. [red]Destructive.[/red]"""
    if not confirm:
        confirmed = typer.confirm(
            f"This will permanently delete all transactions before {before}. Continue?",
            default=False,
        )
        if not confirmed:
            raise typer.Abort()
    from bank_agent_llm.pipeline import Pipeline

    try:
        Pipeline().purge(before=before)
    except NotImplementedError:
        err_console.print("[yellow]Not yet implemented (M5).[/yellow]")
        raise typer.Exit(1)


@db_app.command("reset")
def db_reset(
    confirm: bool = typer.Option(False, "--yes", help="Skip confirmation prompt."),
) -> None:
    """Drop and recreate the database. [red]Destructive.[/red]"""
    if not confirm:
        confirmed = typer.confirm("This will delete all data. Continue?", default=False)
        if not confirmed:
            raise typer.Abort()
    err_console.print("[yellow]Not yet implemented (M1).[/yellow]")
    raise typer.Exit(1)


# ─── Version ─────────────────────────────────────────────────────────────────

def _version_callback(value: bool) -> None:
    if value:
        from bank_agent_llm import __version__
        console.print(f"bank-agent-llm {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(  # noqa: FBT001
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    pass


if __name__ == "__main__":
    app()
