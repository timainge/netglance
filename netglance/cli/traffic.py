"""Traffic CLI subcommands."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.live import Live
from rich.table import Table

from netglance.modules.traffic import (
    BandwidthSample,
    format_bytes,
    get_interface_stats,
    live_monitor,
)

app = typer.Typer(help="Traffic & bandwidth monitoring.", no_args_is_help=True)
console = Console()


@app.command("stats")
def traffic_stats_cmd(
    interface: Optional[str] = typer.Option(
        None, "--interface", "-i", help="Filter to a specific interface."
    ),
) -> None:
    """Show current interface traffic counters."""
    stats = get_interface_stats()

    if interface:
        stats = [s for s in stats if s.interface == interface]
        if not stats:
            console.print(f"[red]Error:[/red] Interface {interface!r} not found.")
            raise typer.Exit(code=1)

    table = Table(title="Interface Traffic Stats")
    table.add_column("Interface", style="cyan bold")
    table.add_column("Bytes Sent", justify="right")
    table.add_column("Bytes Recv", justify="right")
    table.add_column("Pkts Sent", justify="right")
    table.add_column("Pkts Recv", justify="right")

    for s in stats:
        table.add_row(
            s.interface,
            format_bytes(s.bytes_sent).replace("/s", ""),
            format_bytes(s.bytes_recv).replace("/s", ""),
            f"{s.packets_sent:,}",
            f"{s.packets_recv:,}",
        )

    console.print(table)


def _build_live_table(sample: BandwidthSample) -> Table:
    table = Table(title=f"Live Bandwidth: {sample.interface}")
    table.add_column("Direction", style="bold")
    table.add_column("Rate", justify="right", style="green")
    table.add_row("TX (upload)", format_bytes(sample.tx_bytes_per_sec))
    table.add_row("RX (download)", format_bytes(sample.rx_bytes_per_sec))
    return table


@app.command("live")
def traffic_live_cmd(
    interface: str = typer.Argument(..., help="Network interface to monitor (e.g. en0)."),
    interval: float = typer.Option(1.0, "--interval", "-n", help="Sampling interval in seconds."),
) -> None:
    """Live bandwidth dashboard for a network interface."""
    try:
        with Live(console=console, refresh_per_second=2) as live:

            def _update(sample: BandwidthSample) -> None:
                live.update(_build_live_table(sample))

            live_monitor(interface, callback=_update, interval=interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")
    except KeyError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)
