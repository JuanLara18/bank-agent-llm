"""CLI entry point — thin wrapper over the Pipeline library API.

All business logic lives in the library modules (pipeline.py, ingestion/,
parsers/, enrichment/, storage/, chat/). This file only handles CLI concerns:
argument parsing, output formatting, and exit codes.
"""

from __future__ import annotations

import logging

import typer
from dotenv import load_dotenv

load_dotenv()
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

console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)


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
    config_path: str = typer.Option("config/config.yaml", help="Path to config file."),
    discover: bool = typer.Option(
        False, "--discover",
        help="Scan emails and show patterns without downloading anything.",
    ),
    log_level: str = typer.Option("INFO", envvar="LOG_LEVEL"),
) -> None:
    """Download new bank statements from configured email accounts.

    On first run with a Gmail account, opens a browser window to authorize access.
    Use --discover to inspect what bank emails exist before downloading.
    """
    _setup_logging(log_level)
    from rich.table import Table
    from bank_agent_llm.pipeline import Pipeline

    result = Pipeline(config_path=config_path).fetch(discover=discover)

    if discover:
        if result.discovered_patterns:
            console.print(
                f"\n[bold]Patrones encontrados ({len(result.discovered_patterns)} unicos):[/bold]"
            )
            seen = Table(show_header=True, header_style="bold")
            seen.add_column("Remitente", max_width=45)
            seen.add_column("Asunto", max_width=55)
            seen.add_column("Fecha", max_width=30)
            for p in result.discovered_patterns:
                seen.add_row(p["sender"][:45], p["subject"][:55], p["date"][:25])
            console.print(seen)
            console.print(
                f"\n[dim]Correos con adjunto escaneados: {result.emails_scanned}[/dim]"
            )
        else:
            console.print("[yellow]No se encontraron patrones de correos bancarios.[/yellow]")
        return

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Cuentas revisadas", str(result.accounts_checked))
    table.add_row("Correos escaneados", str(result.emails_scanned))
    table.add_row("Correos nuevos", f"[green]{result.emails_new}[/green]")
    table.add_row("Archivos descargados", f"[green]{result.attachments_downloaded}[/green]")
    table.add_row("Errores", f"[red]{len(result.errors)}[/red]" if result.errors else "0")
    console.print(table)

    for err in result.errors:
        err_console.print(f"  [red]-[/red] {err}")

    if result.attachments_downloaded:
        console.print(
            f"[green]{result.attachments_downloaded} archivo(s) en data/raw/. "
            "Ejecuta 'bank-agent import data/raw' para procesarlos.[/green]"
        )
    elif result.accounts_checked == 0:
        console.print(
            "[yellow]Pon config/gmail_credentials.json o configura email_accounts "
            "en config/config.yaml.[/yellow]"
        )


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
    force: bool = typer.Option(False, "--force", help="Re-tag already-tagged transactions."),
    config_path: str = typer.Option("config/config.yaml", help="Path to config file."),
    log_level: str = typer.Option("INFO", envvar="LOG_LEVEL"),
) -> None:
    """Tag transactions with the rules engine and optional Ollama LLM."""
    _setup_logging(log_level)
    from rich.table import Table
    from bank_agent_llm.pipeline import Pipeline

    result = Pipeline(config_path=config_path).enrich(force=force)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Total processed", str(result.total))
    table.add_row("Tagged by rules", f"[green]{result.by_rules}[/green]")
    table.add_row("Tagged from cache", f"[green]{result.by_cache}[/green]")
    table.add_row("Tagged by LLM", f"[cyan]{result.by_llm}[/cyan]")
    table.add_row("Skipped (manual)", str(result.skipped_manual))
    table.add_row("Already tagged", str(result.already_tagged))
    table.add_row("Pending (no LLM)", f"[yellow]{result.pending}[/yellow]" if result.pending else "0")
    console.print(table)

    if result.llm_unavailable:
        console.print(
            "[yellow]Ollama was unavailable. Install and start it, then run "
            "'bank-agent enrich' again to tag remaining transactions.[/yellow]"
        )
        console.print("  [dim]ollama pull mistral:7b && ollama serve[/dim]")


@app.command()
def status(
    config_path: str = typer.Option("config/config.yaml", help="Path to config file."),
    top: int = typer.Option(10, help="Number of top items to show."),
    log_level: str = typer.Option("INFO", envvar="LOG_LEVEL"),
) -> None:
    """Show a financial summary dashboard of all transactions in the database."""
    _setup_logging(log_level)
    from decimal import Decimal

    from rich import box
    from rich.columns import Columns
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    from bank_agent_llm.pipeline import Pipeline
    from bank_agent_llm.storage.database import get_session
    from bank_agent_llm.storage.repository import StatsRepository
    from bank_agent_llm.enrichment.tags import get_taxonomy

    pipeline = Pipeline(config_path=config_path)
    try:
        pipeline._init_db()
    except Exception as exc:
        err_console.print(f"[red]Cannot open database: {exc}[/red]")
        raise typer.Exit(1)

    with get_session() as session:
        report = StatsRepository(session).build_report(top_n=top)

    if report.total_transactions == 0:
        console.print("[yellow]No transactions found. Run 'bank-agent import <path>' first.[/yellow]")
        raise typer.Exit(0)

    taxonomy = get_taxonomy()

    def _cop(amount: Decimal) -> str:
        return f"${amount:,.0f}"

    # ── Header ────────────────────────────────────────────────────────────────
    date_range = (
        f"{report.date_min} al {report.date_max}"
        if report.date_min and report.date_max
        else "-"
    )
    tagged = report.total_transactions - report.pending_enrichment
    tagged_pct = tagged / report.total_transactions * 100

    overview = Table(show_header=False, box=None, padding=(0, 2))
    overview.add_column(style="bold cyan")
    overview.add_column()
    overview.add_row("Transacciones", str(report.total_transactions))
    overview.add_row("Período", date_range)
    overview.add_row("Gasto total", f"[red]{_cop(report.total_debit)}[/red]")
    overview.add_row("Ingresos / pagos", f"[green]{_cop(report.total_credit)}[/green]")
    overview.add_row(
        "Categorizadas",
        f"[green]{tagged}[/green] / {report.total_transactions} "
        f"([green]{tagged_pct:.0f}%[/green])"
        + (f" — [yellow]{report.pending_enrichment} pendientes[/yellow]"
           if report.pending_enrichment else ""),
    )
    console.print(Panel(overview, title="[bold]Resumen General[/bold]", border_style="cyan"))

    # ── Accounts ──────────────────────────────────────────────────────────────
    acc_table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    acc_table.add_column("Banco")
    acc_table.add_column("Txns", justify="right")
    acc_table.add_column("Desde")
    acc_table.add_column("Hasta")
    acc_table.add_column("Gasto", justify="right", style="red")
    acc_table.add_column("Créditos", justify="right", style="green")
    for acc in sorted(report.accounts, key=lambda a: a.total_debit, reverse=True):
        acc_table.add_row(
            acc.bank_name,
            str(acc.total),
            str(acc.date_min) if acc.date_min else "—",
            str(acc.date_max) if acc.date_max else "—",
            _cop(acc.total_debit),
            _cop(acc.total_credit),
        )
    console.print(Panel(acc_table, title="[bold]Por Cuenta[/bold]", border_style="blue"))

    # ── Top Tags + Top Merchants (side by side) ───────────────────────────────
    tags_table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    tags_table.add_column("Categoría")
    tags_table.add_column("Txns", justify="right")
    tags_table.add_column("Total", justify="right", style="red")
    for ts in report.top_tags:
        name = taxonomy.display_name(ts.tag) or ts.tag
        tags_table.add_row(name, str(ts.count), _cop(ts.total))

    merchants_table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    merchants_table.add_column("Comercio")
    merchants_table.add_column("Txns", justify="right")
    merchants_table.add_column("Total", justify="right", style="red")
    for ms in report.top_merchants:
        merchants_table.add_row(ms.merchant[:28], str(ms.count), _cop(ms.total))

    console.print(Columns([
        Panel(tags_table, title="[bold]Top Categorías[/bold]", border_style="magenta"),
        Panel(merchants_table, title="[bold]Top Comercios[/bold]", border_style="yellow"),
    ]))

    # ── Monthly trend ─────────────────────────────────────────────────────────
    if report.monthly:
        max_debit = max(m.debit for m in report.monthly) or Decimal("1")
        monthly_table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
        monthly_table.add_column("Mes")
        monthly_table.add_column("Gasto", justify="right", style="red")
        monthly_table.add_column("Ingresos", justify="right", style="green")
        monthly_table.add_column("Barra", no_wrap=True)
        for m in report.monthly:
            bar_len = int(m.debit / max_debit * 30)
            bar = "|" * bar_len
            monthly_table.add_row(m.label, _cop(m.debit), _cop(m.credit), f"[red]{bar}[/red]")
        console.print(Panel(monthly_table, title="[bold]Tendencia Mensual[/bold]", border_style="green"))

    # ── Spending by day of week ───────────────────────────────────────────────
    if report.by_weekday:
        max_day = max(d.total for d in report.by_weekday) or Decimal("1")
        wd_table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
        wd_table.add_column("Día")
        wd_table.add_column("Txns", justify="right")
        wd_table.add_column("Total", justify="right", style="red")
        wd_table.add_column("Barra", no_wrap=True)
        for d in report.by_weekday:
            bar_len = int(d.total / max_day * 25)
            bar = "|" * bar_len
            wd_table.add_row(d.label, str(d.count), _cop(d.total), f"[magenta]{bar}[/magenta]")
        console.print(Panel(wd_table, title="[bold]Gasto por Día de Semana[/bold]", border_style="magenta"))

    # ── Pending warning ───────────────────────────────────────────────────────
    if report.pending_enrichment:
        console.print(
            f"[yellow]{report.pending_enrichment} transacción(es) sin categorizar. "
            "Ejecuta 'bank-agent enrich' para procesarlas.[/yellow]"
        )


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
    config_path: str = typer.Option("config/config.yaml", help="Path to config file."),
    log_level: str = typer.Option("INFO", envvar="LOG_LEVEL"),
) -> None:
    """Import statement files from a local path, skipping email ingestion.

    Use this when you have downloaded statements from your bank's web portal
    or have an existing folder of PDFs/spreadsheets.
    """
    _setup_logging(log_level)
    from pathlib import Path as P
    from rich.table import Table
    from bank_agent_llm.pipeline import Pipeline

    try:
        result = Pipeline(config_path=config_path).import_files(P(path))
    except FileNotFoundError:
        err_console.print(f"[red]Path not found: {path}[/red]")
        raise typer.Exit(1)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Files scanned", str(result.scanned))
    table.add_row("Transactions imported", f"[green]{result.imported}[/green]")
    table.add_row("Skipped (already imported)", str(result.skipped_dedup))
    table.add_row("Skipped (no parser)", str(result.skipped_no_parser))
    table.add_row("Errors", f"[red]{result.errors}[/red]" if result.errors else "0")
    console.print(table)

    for detail in result.error_details:
        err_console.print(f"  [red]•[/red] {detail}")

    if result.skipped_no_parser:
        console.print(
            f"[yellow]{result.skipped_no_parser} file(s) had no matching parser. "
            "See docs/adding-a-parser.md.[/yellow]"
        )

    if not result.success:
        raise typer.Exit(1)


@app.command("config-check")
def config_check(
    config_path: str = typer.Option("config/config.yaml", help="Path to config file."),
) -> None:
    """Validate the configuration file and report any errors."""
    from pydantic import ValidationError
    from rich.table import Table

    from bank_agent_llm.config import get_settings

    try:
        settings = get_settings(config_path)
    except FileNotFoundError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    except ValidationError as exc:
        err_console.print("[red]Configuration is invalid:[/red]")
        for error in exc.errors():
            loc = " > ".join(str(x) for x in error["loc"])
            err_console.print(f"  [red]•[/red] {loc}: {error['msg']}")
        raise typer.Exit(1)

    table = Table(title="Configuration", show_header=True, header_style="bold")
    table.add_column("Setting")
    table.add_column("Value")

    table.add_row("Database URL", settings.database.url)
    table.add_row("Ollama base URL", settings.ollama.base_url)
    table.add_row("Categorization model", settings.ollama.categorization_model)
    table.add_row("Chat model", settings.ollama.chat_model)
    table.add_row("Email accounts", str(len(settings.email_accounts)))
    table.add_row("Categories defined", str(len(settings.categories)))
    table.add_row("Log level", settings.pipeline.log_level)

    console.print(table)

    if not settings.email_accounts:
        console.print("[yellow]No email accounts configured — only manual import will work.[/yellow]")
    if not settings.categories:
        console.print("[yellow]No categories defined — enrichment will use defaults.[/yellow]")

    console.print("[green]Configuration is valid.[/green]")


# ─── DB sub-commands ─────────────────────────────────────────────────────────

@db_app.command("migrate")
def db_migrate(
    config_path: str = typer.Option("config/config.yaml", help="Path to config file."),
) -> None:
    """Apply pending Alembic database migrations."""
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    alembic_cfg = AlembicConfig("alembic.ini")
    try:
        alembic_command.upgrade(alembic_cfg, "head")
        console.print("[green]Database migrations applied.[/green]")
    except Exception as exc:
        err_console.print(f"[red]Migration failed: {exc}[/red]")
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
        console.print(f"[green]Transactions before {before} deleted.[/green]")
    except ValueError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


@db_app.command("reset")
def db_reset(
    confirm: bool = typer.Option(False, "--yes", help="Skip confirmation prompt."),
    config_path: str = typer.Option("config/config.yaml", help="Path to config file."),
) -> None:
    """Drop and recreate the database. [red]Destructive.[/red]"""
    if not confirm:
        if not typer.confirm("This will delete all data. Continue?", default=False):
            raise typer.Abort()

    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    from bank_agent_llm.storage.database import get_engine
    from bank_agent_llm.storage.models import Base

    try:
        engine = get_engine()
        Base.metadata.drop_all(engine)
        alembic_cfg = AlembicConfig("alembic.ini")
        alembic_command.upgrade(alembic_cfg, "head")
        console.print("[green]Database reset and recreated.[/green]")
    except Exception as exc:
        err_console.print(f"[red]Reset failed: {exc}[/red]")
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
