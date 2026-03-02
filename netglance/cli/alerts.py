"""Alert rule management CLI subcommands."""

from __future__ import annotations

import json as _json_mod
from datetime import datetime, timedelta, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from netglance.modules.alerts import (
    acknowledge_alert,
    create_alert_rule,
    delete_alert_rule,
    get_alert_log,
    list_alert_rules,
    toggle_alert_rule,
)
from netglance.store.db import Store

app = typer.Typer(help="Alert rule management.", no_args_is_help=True)
console = Console()


def _get_store(db: Optional[str]) -> Store:
    store = Store(db) if db else Store()
    store.init_db()
    return store


def _parse_period(period: str) -> datetime:
    """Parse a period string like '1h', '24h', '7d' into a since datetime."""
    period = period.strip().lower()
    if period.endswith("d"):
        days = int(period[:-1])
        return datetime.now(timezone.utc) - timedelta(days=days)
    if period.endswith("h"):
        hours = int(period[:-1])
        return datetime.now(timezone.utc) - timedelta(hours=hours)
    if period.endswith("m"):
        minutes = int(period[:-1])
        return datetime.now(timezone.utc) - timedelta(minutes=minutes)
    raise typer.BadParameter(f"Unknown period format: {period!r}. Use e.g. '1h', '24h', '7d'.")


@app.command("add")
def add_cmd(
    metric: str = typer.Option(..., "--metric", "-m", help="Metric name to monitor."),
    above: Optional[float] = typer.Option(None, "--above", help="Trigger when metric exceeds this value."),
    below: Optional[float] = typer.Option(None, "--below", help="Trigger when metric falls below this value."),
    message: Optional[str] = typer.Option(None, "--message", help="Human-readable alert message."),
    window: int = typer.Option(300, "--window", "-w", help="Evaluation window in seconds."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True),
) -> None:
    """Add a new alert rule. Provide either --above or --below."""
    if above is None and below is None:
        console.print("[red]Error:[/red] Provide either --above or --below.")
        raise typer.Exit(code=1)
    if above is not None and below is not None:
        console.print("[red]Error:[/red] Provide only one of --above or --below, not both.")
        raise typer.Exit(code=1)

    condition = "above" if above is not None else "below"
    threshold = above if above is not None else below

    store = _get_store(db)
    try:
        rule_id = create_alert_rule(
            store,
            metric=metric,
            condition=condition,
            threshold=threshold,  # type: ignore[arg-type]
            message=message,
            window_s=window,
        )
        console.print(f"[green]Created alert rule #{rule_id}[/green]: {metric} {condition} {threshold}")
    finally:
        store.close()


@app.command("list")
def list_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True),
) -> None:
    """Show all alert rules."""
    store = _get_store(db)
    try:
        rules = list_alert_rules(store)
    finally:
        store.close()

    if json_output:
        console.print_json(_json_mod.dumps(rules))
        return

    if not rules:
        console.print("[dim]No alert rules configured.[/dim]")
        return

    table = Table(title="Alert Rules", show_lines=False)
    table.add_column("ID", justify="right", style="bold")
    table.add_column("Metric")
    table.add_column("Condition", justify="center")
    table.add_column("Threshold", justify="right")
    table.add_column("Window", justify="right")
    table.add_column("Enabled", justify="center")
    table.add_column("Message")

    for rule in rules:
        enabled_str = "[green]Yes[/green]" if rule["enabled"] else "[red]No[/red]"
        table.add_row(
            str(rule["id"]),
            rule["metric"],
            rule["condition"],
            str(rule["threshold"]),
            f"{rule['window_s']}s",
            enabled_str,
            rule["message"] or "",
        )

    console.print(table)


@app.command("delete")
def delete_cmd(
    rule_id: int = typer.Argument(..., help="Alert rule ID to delete."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True),
) -> None:
    """Delete an alert rule by ID."""
    store = _get_store(db)
    try:
        deleted = delete_alert_rule(store, rule_id)
    finally:
        store.close()

    if deleted:
        console.print(f"[green]Deleted alert rule #{rule_id}.[/green]")
    else:
        console.print(f"[red]Alert rule #{rule_id} not found.[/red]")
        raise typer.Exit(code=1)


@app.command("enable")
def enable_cmd(
    rule_id: int = typer.Argument(..., help="Alert rule ID to enable."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True),
) -> None:
    """Enable an alert rule."""
    store = _get_store(db)
    try:
        updated = toggle_alert_rule(store, rule_id, enabled=True)
    finally:
        store.close()

    if updated:
        console.print(f"[green]Enabled alert rule #{rule_id}.[/green]")
    else:
        console.print(f"[red]Alert rule #{rule_id} not found.[/red]")
        raise typer.Exit(code=1)


@app.command("disable")
def disable_cmd(
    rule_id: int = typer.Argument(..., help="Alert rule ID to disable."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True),
) -> None:
    """Disable an alert rule."""
    store = _get_store(db)
    try:
        updated = toggle_alert_rule(store, rule_id, enabled=False)
    finally:
        store.close()

    if updated:
        console.print(f"[yellow]Disabled alert rule #{rule_id}.[/yellow]")
    else:
        console.print(f"[red]Alert rule #{rule_id} not found.[/red]")
        raise typer.Exit(code=1)


@app.command("log")
def log_cmd(
    since: Optional[str] = typer.Option(None, "--since", help="Show alerts from period, e.g. '1h', '24h', '7d'."),
    unacked: bool = typer.Option(False, "--unacked", help="Show only unacknowledged alerts."),
    limit: int = typer.Option(50, "--limit", "-n", help="Maximum number of entries to show."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True),
) -> None:
    """Show fired alert history."""
    since_dt: datetime | None = None
    if since:
        try:
            since_dt = _parse_period(since)
        except typer.BadParameter as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(code=1)

    store = _get_store(db)
    try:
        entries = get_alert_log(store, since=since_dt, limit=limit, unacknowledged_only=unacked)
    finally:
        store.close()

    if json_output:
        console.print_json(_json_mod.dumps(entries))
        return

    if not entries:
        console.print("[dim]No alert log entries found.[/dim]")
        return

    table = Table(title="Alert Log", show_lines=False)
    table.add_column("ID", justify="right", style="bold")
    table.add_column("Time")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_column("Threshold", justify="right")
    table.add_column("Message")
    table.add_column("Acked", justify="center")

    for entry in entries:
        acked_str = "[green]Yes[/green]" if entry["acknowledged"] else "[dim]No[/dim]"
        # Truncate timestamp for display
        ts = entry["ts"][:19] if len(entry["ts"]) > 19 else entry["ts"]
        table.add_row(
            str(entry["id"]),
            ts,
            entry["metric"],
            str(entry["value"]),
            str(entry["threshold"]),
            entry["message"] or "",
            acked_str,
        )

    console.print(table)


@app.command("ack")
def ack_cmd(
    alert_id: int = typer.Argument(..., help="Alert log entry ID to acknowledge."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True),
) -> None:
    """Acknowledge a fired alert."""
    store = _get_store(db)
    try:
        updated = acknowledge_alert(store, alert_id)
    finally:
        store.close()

    if updated:
        console.print(f"[green]Acknowledged alert #{alert_id}.[/green]")
    else:
        console.print(f"[red]Alert #{alert_id} not found.[/red]")
        raise typer.Exit(code=1)
