"""Uptime CLI subcommands."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from netglance.modules.uptime import check_host, get_uptime_summary, save_uptime_record
from netglance.store.db import Store
from netglance.store.models import UptimeSummary

app = typer.Typer(help="Host uptime monitoring.", no_args_is_help=True)
console = Console()


def _format_latency(ms: float | None) -> str:
    if ms is None:
        return "--"
    return f"{ms:.1f} ms"


def _format_datetime(dt: datetime | None) -> str:
    if dt is None:
        return "--"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _status_markup(status: str) -> str:
    if status == "up":
        return "[bold green]UP[/bold green]"
    if status == "down":
        return "[bold red]DOWN[/bold red]"
    return "[dim]unknown[/dim]"


def _uptime_color(pct: float) -> str:
    if pct >= 99.0:
        return "green"
    if pct >= 95.0:
        return "yellow"
    return "red"


def _print_summary(summary: UptimeSummary) -> None:
    """Render an uptime summary as a rich panel with outage table."""
    color = _uptime_color(summary.uptime_pct)
    status_str = _status_markup(summary.current_status)

    lines = [
        f"Host:            [bold]{summary.host}[/bold]",
        f"Period:          {summary.period}",
        f"Current Status:  {status_str}",
        f"Uptime:          [{color}]{summary.uptime_pct:.2f}%[/{color}]",
        f"Checks:          {summary.successful_checks} / {summary.total_checks}",
        f"Avg Latency:     {_format_latency(summary.avg_latency_ms)}",
        f"Last Seen:       {_format_datetime(summary.last_seen)}",
    ]
    body = "\n".join(lines)

    if summary.outages:
        outage_table = Table(title="Outages", show_lines=False, expand=False)
        outage_table.add_column("Start", style="red")
        outage_table.add_column("End", style="red")
        outage_table.add_column("Duration", justify="right")
        for o in summary.outages:
            start = _format_datetime(o.get("start"))
            end = _format_datetime(o.get("end"))
            duration_s = o.get("duration_s", 0.0)
            if duration_s >= 3600:
                dur_str = f"{duration_s / 3600:.1f}h"
            elif duration_s >= 60:
                dur_str = f"{duration_s / 60:.1f}m"
            else:
                dur_str = f"{duration_s:.0f}s"
            outage_table.add_row(start, end, dur_str)
        console.print(Panel(body, title="Uptime Summary", border_style=color))
        console.print(outage_table)
    else:
        no_outage_note = "\nOutages:         [green]none[/green]"
        console.print(Panel(body + no_outage_note, title="Uptime Summary", border_style=color))


def _summary_to_dict(summary: UptimeSummary) -> dict:
    """Serialize UptimeSummary to a JSON-compatible dict."""
    outages_serialized = []
    for o in summary.outages:
        outages_serialized.append(
            {
                "start": _format_datetime(o.get("start")),
                "end": _format_datetime(o.get("end")),
                "duration_s": o.get("duration_s", 0.0),
            }
        )
    return {
        "host": summary.host,
        "period": summary.period,
        "uptime_pct": summary.uptime_pct,
        "total_checks": summary.total_checks,
        "successful_checks": summary.successful_checks,
        "avg_latency_ms": summary.avg_latency_ms,
        "current_status": summary.current_status,
        "last_seen": _format_datetime(summary.last_seen),
        "outages": outages_serialized,
    }


@app.command("check")
def uptime_check_cmd(
    host: str = typer.Argument(..., help="IP address or hostname to check."),
    period: str = typer.Option("24h", "--period", "-p", help="Summary period (e.g. 24h, 7d)."),
    timeout: float = typer.Option(2.0, "--timeout", "-t", help="Ping timeout in seconds."),
    save: bool = typer.Option(False, "--save/--no-save", help="Save result to local DB."),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Check current status and show uptime summary for a host."""
    record = check_host(host, timeout=timeout)

    if save:
        try:
            store = Store()
            store.init_db()
            save_uptime_record(record, store)
            store.close()
            console.print("[dim]\u2713 Saved to local database.[/dim]")
        except Exception as exc:
            console.print(f"[dim yellow]Warning: could not save result: {exc}[/dim yellow]")

    summary = get_uptime_summary(host, period=period)
    # Override current status with live check
    summary.current_status = "up" if record.is_alive else "down"
    if record.is_alive:
        summary.last_seen = record.check_time

    if output_json:
        data = _summary_to_dict(summary)
        data["live_check"] = {
            "is_alive": record.is_alive,
            "latency_ms": record.latency_ms,
            "check_time": _format_datetime(record.check_time),
        }
        console.print(json.dumps(data, indent=2))
    else:
        # Show live check result first
        status_str = _status_markup(summary.current_status)
        latency_str = _format_latency(record.latency_ms)
        console.print(f"\n[bold]{host}[/bold] is currently {status_str}  (latency: {latency_str})\n")
        _print_summary(summary)


@app.command("summary")
def uptime_summary_cmd(
    host: str = typer.Argument(..., help="IP address or hostname."),
    period: str = typer.Option("24h", "--period", "-p", help="Summary period (e.g. 24h, 7d)."),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show stored uptime summary for a host without a live check."""
    summary = get_uptime_summary(host, period=period)
    if output_json:
        console.print(json.dumps(_summary_to_dict(summary), indent=2))
    else:
        _print_summary(summary)


@app.command("list")
def uptime_list_cmd(
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List all hosts with stored uptime records."""
    try:
        store = Store()
        store.init_db()
        rows = store.get_results("uptime", limit=10000)
        store.close()
    except Exception:
        rows = []

    # Extract unique hosts with latest status
    hosts: dict[str, dict] = {}
    for row in rows:
        h = row.get("host", "")
        if h and (h not in hosts or row.get("check_time", "") > hosts[h].get("check_time", "")):
            hosts[h] = row

    if output_json:
        console.print(json.dumps({"hosts": list(hosts.values())}, indent=2))
        return

    if not hosts:
        console.print(Panel(
            "[dim]No uptime records found.\n"
            "Run [bold]netglance uptime check <host> --save[/bold] to start tracking.[/dim]",
            title="Monitored Hosts",
            border_style="dim",
        ))
        return

    table = Table(title="Monitored Hosts")
    table.add_column("Host", style="bold")
    table.add_column("Last Check")
    table.add_column("Status")
    table.add_column("Latency")
    for h, data in sorted(hosts.items()):
        status = _status_markup("up" if data.get("is_alive") else "down")
        table.add_row(
            h,
            data.get("check_time", "")[:19],
            status,
            _format_latency(data.get("latency_ms")),
        )
    console.print(table)
