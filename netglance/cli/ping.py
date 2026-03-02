"""Ping CLI subcommands."""

from __future__ import annotations

import time
from typing import Optional

import typer
from rich.console import Console
from rich.live import Live
from rich.table import Table

from netglance.modules.ping import (
    check_gateway,
    check_internet,
    latency_color,
    ping_host,
    ping_sweep,
)
from netglance.modules.trending import emit_ping_metrics
from netglance.store.db import Store
from netglance.store.models import PingResult

app = typer.Typer(help="Connectivity & latency checks.", no_args_is_help=True)
console = Console()


def _format_latency(ms: float | None) -> str:
    if ms is None:
        return "--"
    return f"{ms:.1f} ms"


def _ping_result_table(results: list[PingResult], title: str = "Ping Results") -> Table:
    table = Table(title=title, show_lines=False)
    table.add_column("Host", style="bold")
    table.add_column("Status")
    table.add_column("Avg", justify="right")
    table.add_column("Min", justify="right")
    table.add_column("Max", justify="right")
    table.add_column("Loss", justify="right")

    for r in results:
        color = latency_color(r.avg_latency_ms)
        status = "[green]UP[/green]" if r.is_alive else "[red]DOWN[/red]"
        table.add_row(
            r.host,
            status,
            f"[{color}]{_format_latency(r.avg_latency_ms)}[/{color}]",
            f"[{color}]{_format_latency(r.min_latency_ms)}[/{color}]",
            f"[{color}]{_format_latency(r.max_latency_ms)}[/{color}]",
            f"{r.packet_loss * 100:.0f}%",
        )
    return table


@app.command("host")
def ping_host_cmd(
    host: str = typer.Argument(..., help="IP address or hostname to ping."),
    count: int = typer.Option(4, "--count", "-c", help="Number of echo requests."),
    timeout: float = typer.Option(2.0, "--timeout", "-t", help="Timeout per request in seconds."),
    watch: bool = typer.Option(False, "--watch", "-w", help="Continuous ping with live display."),
    save: bool = typer.Option(False, "--save/--no-save", help="Save result to local DB."),
) -> None:
    """Ping a single host."""
    if watch:
        try:
            with Live(console=console, refresh_per_second=1) as live:
                while True:
                    result = ping_host(host, count=count, timeout=timeout)
                    table = _ping_result_table([result], title=f"Ping {host} (live)")
                    live.update(table)
                    time.sleep(1)
        except KeyboardInterrupt:
            console.print("\n[dim]Stopped.[/dim]")
    else:
        result = ping_host(host, count=count, timeout=timeout)
        console.print(_ping_result_table([result], title=f"Ping {host}"))
        if save:
            try:
                store = Store()
                store.init_db()
                store.save_result("ping", {
                    "host": result.host,
                    "is_alive": result.is_alive,
                    "avg_latency_ms": result.avg_latency_ms,
                    "min_latency_ms": result.min_latency_ms,
                    "max_latency_ms": result.max_latency_ms,
                    "packet_loss": result.packet_loss,
                    "timestamp": result.timestamp.isoformat(),
                })
                emit_ping_metrics(result, store)
                console.print("[dim]✓ Saved to local database.[/dim]")
            except Exception as exc:
                console.print(f"[dim yellow]Warning: could not save result: {exc}[/dim yellow]")


@app.command("sweep")
def ping_sweep_cmd(
    subnet: str = typer.Argument(
        None, help="CIDR subnet to sweep (e.g. 192.168.1.0/24). Auto-detects if omitted."
    ),
    timeout: float = typer.Option(1.0, "--timeout", "-t", help="Timeout per host in seconds."),
) -> None:
    """Ping sweep all hosts in a subnet."""
    if subnet is None:
        console.print("[red]Error:[/red] Please provide a subnet (e.g. 192.168.1.0/24).")
        raise typer.Exit(code=1)
    results = ping_sweep(subnet, timeout=timeout)
    alive = [r for r in results if r.is_alive]
    console.print(_ping_result_table(alive, title=f"Sweep {subnet} ({len(alive)} alive)"))


@app.command("internet")
def ping_internet_cmd(
    count: int = typer.Option(4, "--count", "-c", help="Number of echo requests per host."),
    timeout: float = typer.Option(2.0, "--timeout", "-t", help="Timeout per request in seconds."),
    watch: bool = typer.Option(False, "--watch", "-w", help="Continuous check with live display."),
    save: bool = typer.Option(False, "--save/--no-save", help="Save result to local DB."),
) -> None:
    """Check internet connectivity via public DNS servers."""
    if watch:
        try:
            with Live(console=console, refresh_per_second=1) as live:
                while True:
                    results = check_internet(count=count, timeout=timeout)
                    table = _ping_result_table(results, title="Internet Connectivity (live)")
                    live.update(table)
                    time.sleep(1)
        except KeyboardInterrupt:
            console.print("\n[dim]Stopped.[/dim]")
    else:
        results = check_internet(count=count, timeout=timeout)
        console.print(_ping_result_table(results, title="Internet Connectivity"))
        if save:
            try:
                store = Store()
                store.init_db()
                for result in results:
                    store.save_result("ping", {
                        "host": result.host,
                        "is_alive": result.is_alive,
                        "avg_latency_ms": result.avg_latency_ms,
                        "min_latency_ms": result.min_latency_ms,
                        "max_latency_ms": result.max_latency_ms,
                        "packet_loss": result.packet_loss,
                        "timestamp": result.timestamp.isoformat(),
                    })
                    emit_ping_metrics(result, store)
                console.print("[dim]✓ Saved to local database.[/dim]")
            except Exception as exc:
                console.print(f"[dim yellow]Warning: could not save result: {exc}[/dim yellow]")


@app.command("gateway")
def ping_gateway_cmd(
    count: int = typer.Option(4, "--count", "-c", help="Number of echo requests."),
    timeout: float = typer.Option(2.0, "--timeout", "-t", help="Timeout per request in seconds."),
    watch: bool = typer.Option(False, "--watch", "-w", help="Continuous ping with live display."),
    save: bool = typer.Option(False, "--save/--no-save", help="Save result to local DB."),
) -> None:
    """Ping the default gateway."""
    try:
        if watch:
            try:
                with Live(console=console, refresh_per_second=1) as live:
                    while True:
                        result = check_gateway(count=count, timeout=timeout)
                        table = _ping_result_table(
                            [result], title=f"Gateway {result.host} (live)"
                        )
                        live.update(table)
                        time.sleep(1)
            except KeyboardInterrupt:
                console.print("\n[dim]Stopped.[/dim]")
        else:
            result = check_gateway(count=count, timeout=timeout)
            console.print(_ping_result_table([result], title=f"Gateway {result.host}"))
            if save:
                try:
                    store = Store()
                    store.init_db()
                    store.save_result("ping", {
                        "host": result.host,
                        "is_alive": result.is_alive,
                        "avg_latency_ms": result.avg_latency_ms,
                        "min_latency_ms": result.min_latency_ms,
                        "max_latency_ms": result.max_latency_ms,
                        "packet_loss": result.packet_loss,
                        "timestamp": result.timestamp.isoformat(),
                    })
                    emit_ping_metrics(result, store)
                    console.print("[dim]✓ Saved to local database.[/dim]")
                except Exception as exc:
                    console.print(f"[dim yellow]Warning: could not save result: {exc}[/dim yellow]")
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)
