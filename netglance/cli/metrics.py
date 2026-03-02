"""Metrics CLI subcommands for querying and visualising stored time-series data."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from netglance.modules.trending import parse_period, render_chart, sparkline
from netglance.store.db import DEFAULT_DB_PATH, Store

app = typer.Typer(help="Query and chart stored metrics.", no_args_is_help=True)
console = Console()

# Hidden DB path option shared across commands
_DB_HELP = "Path to the SQLite database."


def _get_store(db: Path) -> Store:
    store = Store(db_path=db)
    store.init_db()
    return store


@app.command("list")
def list_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
    db: Path = typer.Option(DEFAULT_DB_PATH, "--db", hidden=True, help=_DB_HELP),
) -> None:
    """List all metric names stored in the database."""
    store = _get_store(db)
    metrics = store.list_metrics()

    if json_output:
        console.print_json(json.dumps(metrics))
        return

    if not metrics:
        console.print("[dim]No metrics found in database.[/dim]")
        return

    table = Table(title="Stored Metrics", show_lines=False)
    table.add_column("Metric Name", style="bold cyan")
    for name in metrics:
        table.add_row(name)
    console.print(table)


@app.command("show")
def show_cmd(
    name: str = typer.Argument(..., help="Metric name to chart."),
    period: str = typer.Option("24h", "--period", "-p", help="Time period (e.g. 1h, 24h, 7d)."),
    width: int = typer.Option(80, "--width", help="Chart width in characters."),
    height: int = typer.Option(20, "--height", help="Chart height in characters."),
    json_output: bool = typer.Option(False, "--json", help="Output raw series as JSON."),
    db: Path = typer.Option(DEFAULT_DB_PATH, "--db", hidden=True, help=_DB_HELP),
) -> None:
    """Show a time-series chart for a metric."""
    try:
        since = parse_period(period)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    store = _get_store(db)
    series = store.get_metric_series(name, since=since)

    if json_output:
        console.print_json(json.dumps(series))
        return

    if not series:
        console.print(f"[dim]No data for metric '{name}' in the last {period}.[/dim]")
        return

    # Show sparkline summary
    values = [p["value"] for p in series]
    spark = sparkline(values, width=min(width, 60))
    console.print(f"[bold]{name}[/bold]  ({len(series)} samples, last {period})")
    console.print(f"[cyan]{spark}[/cyan]")

    # Render full chart
    try:
        chart = render_chart(series, title=name, ylabel=name, width=width, height=height)
        console.print(chart)
    except Exception as exc:
        console.print(f"[yellow]Warning:[/yellow] Could not render chart: {exc}")
        # Fallback: show table summary
        table = Table(title=f"{name} — last {period}", show_lines=False)
        table.add_column("Timestamp")
        table.add_column("Value", justify="right")
        for row in series[-20:]:
            table.add_row(row["ts"], f"{row['value']:.4f}")
        console.print(table)


@app.command("stats")
def stats_cmd(
    name: str = typer.Argument(..., help="Metric name to analyse."),
    period: str = typer.Option("7d", "--period", "-p", help="Time period (e.g. 1h, 24h, 7d)."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
    db: Path = typer.Option(DEFAULT_DB_PATH, "--db", hidden=True, help=_DB_HELP),
) -> None:
    """Show aggregate statistics for a metric."""
    try:
        since = parse_period(period)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    store = _get_store(db)
    stats = store.get_metric_stats(name, since=since)

    if json_output:
        console.print_json(json.dumps(stats))
        return

    if stats["count"] == 0:
        console.print(f"[dim]No data for metric '{name}' in the last {period}.[/dim]")
        return

    table = Table(title=f"Stats: {name} (last {period})", show_lines=False)
    table.add_column("Stat", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Count", str(stats["count"]))
    table.add_row("Min", f"{stats['min']:.4f}")
    table.add_row("Max", f"{stats['max']:.4f}")
    avg = stats["avg"]
    table.add_row("Avg", f"{avg:.4f}" if avg is not None else "--")
    console.print(table)


@app.command("export")
def export_cmd(
    since: str = typer.Option("7d", "--since", "-s", help="Time period to export (e.g. 7d, 24h)."),
    output: Path = typer.Option(Path("metrics_export.csv"), "--output", "-o", help="Output CSV file path."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON instead of CSV."),
    db: Path = typer.Option(DEFAULT_DB_PATH, "--db", hidden=True, help=_DB_HELP),
) -> None:
    """Export metrics to a CSV file."""
    try:
        since_dt = parse_period(since)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    store = _get_store(db)
    metric_names = store.list_metrics()

    all_rows: list[dict] = []
    for metric_name in metric_names:
        series = store.get_metric_series(metric_name, since=since_dt)
        for point in series:
            all_rows.append(
                {
                    "ts": point["ts"],
                    "metric": metric_name,
                    "value": point["value"],
                    "tags": json.dumps(point["tags"]) if point["tags"] else "",
                }
            )

    # Sort by timestamp
    all_rows.sort(key=lambda r: r["ts"])

    if json_output:
        console.print_json(json.dumps(all_rows))
        return

    if not all_rows:
        console.print(f"[dim]No metrics data found for the last {since}.[/dim]")
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ts", "metric", "value", "tags"])
        writer.writeheader()
        writer.writerows(all_rows)

    console.print(
        f"[green]Exported[/green] {len(all_rows)} rows to [bold]{output}[/bold]"
    )
