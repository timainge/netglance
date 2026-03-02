"""Database management CLI subcommands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from netglance.store.db import DEFAULT_DB_PATH, Store

app = typer.Typer(help="Database management.", no_args_is_help=True)
console = Console()


def _get_store(db: str | None) -> Store:
    store = Store(db_path=db) if db else Store()
    store.init_db()
    return store


def _human_size(size_bytes: int) -> str:
    """Format byte count as human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024  # type: ignore[assignment]
    return f"{size_bytes:.1f} TB"


@app.command("status")
def status_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True, help="Database path override."),
) -> None:
    """Show database path, file size, and row counts per table."""
    store = _get_store(db)
    db_path = Path(store.db_path)

    file_size = db_path.stat().st_size if db_path.exists() else 0

    from netglance.store.db import VALID_TABLES

    counts = {}
    for t in sorted(VALID_TABLES):
        counts[t] = store.count_rows(t)
    store.close()

    if json_output:
        data = {
            "path": str(db_path),
            "size_bytes": file_size,
            "tables": counts,
        }
        console.print_json(json.dumps(data))
        return

    table = Table(title="Database Status", show_lines=False)
    table.add_column("Property", style="bold")
    table.add_column("Value")

    table.add_row("Path", str(db_path))
    table.add_row("Size", _human_size(file_size))

    for t in sorted(counts):
        table.add_row(f"  {t}", str(counts[t]))

    console.print(table)


@app.command("prune")
def prune_cmd(
    days: int = typer.Option(365, "--days", help="Prune metrics older than N days."),
    results_days: int = typer.Option(365, "--results-days", help="Prune results older than N days."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show counts but don't delete."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True, help="Database path override."),
) -> None:
    """Prune old metrics and results from the database."""
    store = _get_store(db)

    if dry_run:
        from datetime import datetime, timedelta, timezone

        metrics_cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        results_cutoff = (datetime.now(timezone.utc) - timedelta(days=results_days)).isoformat()
        metrics_count = store.conn.execute(
            "SELECT COUNT(*) as cnt FROM metrics WHERE ts < ?", (metrics_cutoff,)
        ).fetchone()["cnt"]
        results_count = store.conn.execute(
            "SELECT COUNT(*) as cnt FROM results WHERE timestamp < ?", (results_cutoff,)
        ).fetchone()["cnt"]
        store.close()
        console.print(f"Dry run: would prune {metrics_count} metrics, {results_count} results.")
        return

    metrics_deleted = store.prune_metrics(older_than_days=days)
    results_deleted = store.prune_results(older_than_days=results_days)
    store.close()
    console.print(f"Pruned {metrics_deleted} metrics rows, {results_deleted} results rows.")


@app.command("reset")
def reset_cmd(
    confirm: bool = typer.Option(False, "--confirm", help="Confirm you want to wipe all data."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True, help="Database path override."),
) -> None:
    """Wipe all data from the database. Requires --confirm."""
    if not confirm:
        console.print("[red]Error:[/red] Pass --confirm to wipe all data.")
        raise typer.Exit(code=1)

    store = _get_store(db)
    counts = store.reset_all()
    store.close()

    for t in sorted(counts):
        console.print(f"  {t}: {counts[t]} rows deleted")
    console.print("[green]Database reset complete.[/green]")


@app.command("export")
def export_cmd(
    output: Path = typer.Option(Path("netglance-export.json"), "--output", "-o", help="Output file path."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True, help="Database path override."),
) -> None:
    """Export all database tables to a JSON file."""
    store = _get_store(db)
    data = store.export_all()
    store.close()

    total = sum(len(rows) for rows in data.values())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2))
    console.print(f"Exported {total} total rows to {output}")


@app.command("import")
def import_cmd(
    input_file: Path = typer.Argument(..., help="JSON file to import."),
    mode: str = typer.Option("merge", "--mode", help="Import mode: 'merge' (append) or 'replace' (wipe first)."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True, help="Database path override."),
) -> None:
    """Import data from a JSON file into the database."""
    if not input_file.exists():
        console.print(f"[red]Error:[/red] File not found: {input_file}")
        raise typer.Exit(code=1)

    data = json.loads(input_file.read_text())

    store = _get_store(db)
    counts = store.import_all(data, mode=mode)
    store.close()

    for t in sorted(counts):
        if counts[t] > 0:
            console.print(f"  {t}: {counts[t]} rows imported")
    total = sum(counts.values())
    console.print(f"[green]Imported {total} total rows ({mode} mode).[/green]")
