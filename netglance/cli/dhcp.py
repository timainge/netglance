"""DHCP CLI subcommands.

Note: DHCP packet capture requires root/sudo privileges.
"""

from __future__ import annotations

import json as _json_module
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from netglance.modules.dhcp import detect_rogue_servers, monitor_dhcp, sniff_dhcp
from netglance.store.models import DhcpAlert, DhcpEvent

app = typer.Typer(
    help="DHCP monitoring and rogue server detection. Requires root/sudo.",
    no_args_is_help=True,
)
console = Console()


def _events_table(events: list[DhcpEvent], title: str = "DHCP Events") -> Table:
    table = Table(title=title, show_lines=False)
    table.add_column("Time", style="dim", no_wrap=True)
    table.add_column("Type", style="bold")
    table.add_column("Client MAC")
    table.add_column("Client IP")
    table.add_column("Server IP")
    table.add_column("Offered IP")
    table.add_column("Gateway")
    table.add_column("DNS")

    for e in events:
        type_color = {
            "discover": "cyan",
            "offer": "green",
            "request": "yellow",
            "ack": "bold green",
            "nak": "red",
            "release": "dim",
        }.get(e.event_type, "white")

        table.add_row(
            e.timestamp.strftime("%H:%M:%S"),
            f"[{type_color}]{e.event_type.upper()}[/{type_color}]",
            e.client_mac or "--",
            e.client_ip or "--",
            e.server_ip or "--",
            e.offered_ip or "--",
            e.gateway or "--",
            ", ".join(e.dns_servers) if e.dns_servers else "--",
        )
    return table


def _leases_table(events: list[DhcpEvent]) -> Table:
    """Build a table of observed DHCP leases from ACK events."""
    table = Table(title="Observed DHCP Leases", show_lines=False)
    table.add_column("Client MAC", style="bold")
    table.add_column("Assigned IP")
    table.add_column("Server IP")
    table.add_column("Gateway")
    table.add_column("DNS Servers")
    table.add_column("Lease Time")
    table.add_column("Time")

    ack_events = [e for e in events if e.event_type == "ack"]
    for e in ack_events:
        lease_str = f"{e.lease_time}s" if e.lease_time else "--"
        table.add_row(
            e.client_mac or "--",
            e.offered_ip or e.client_ip or "--",
            e.server_ip or "--",
            e.gateway or "--",
            ", ".join(e.dns_servers) if e.dns_servers else "--",
            lease_str,
            e.timestamp.strftime("%H:%M:%S"),
        )
    return table


def _print_alerts(alerts: list[DhcpAlert]) -> None:
    for alert in alerts:
        severity_color = "red" if alert.severity == "critical" else "yellow"
        console.print(
            Panel(
                f"[bold]Type:[/bold] {alert.alert_type}\n"
                f"[bold]Server IP:[/bold] {alert.server_ip}\n"
                f"[bold]Server MAC:[/bold] {alert.server_mac or 'unknown'}\n"
                f"[bold]Description:[/bold] {alert.description}",
                title=f"[{severity_color}]ALERT: {alert.severity.upper()}[/{severity_color}]",
                border_style=severity_color,
            )
        )


@app.command("monitor")
def monitor_cmd(
    duration: float = typer.Option(30.0, "--duration", "-d", help="Listen duration in seconds."),
    interface: Optional[str] = typer.Option(None, "--interface", "-i", help="Network interface."),
    expected: Optional[str] = typer.Option(
        None,
        "--expected",
        "-e",
        help="Comma-separated list of expected DHCP server IPs.",
    ),
    output_json: bool = typer.Option(False, "--json", help="Output results as JSON."),
) -> None:
    """Listen for DHCP traffic and detect rogue servers.

    Requires root/sudo for packet capture.
    Example: sudo netglance dhcp monitor --duration 60
    """
    expected_servers: list[str] | None = None
    if expected:
        expected_servers = [s.strip() for s in expected.split(",") if s.strip()]

    if not output_json:
        console.print(
            f"[dim]Monitoring DHCP traffic for {duration:.0f}s "
            f"({'all interfaces' if not interface else interface})...[/dim]"
        )

    events, alerts = monitor_dhcp(
        duration=duration,
        interface=interface,
        expected_servers=expected_servers,
    )

    if output_json:
        data = {
            "events": [
                {
                    "event_type": e.event_type,
                    "client_mac": e.client_mac,
                    "client_ip": e.client_ip,
                    "server_mac": e.server_mac,
                    "server_ip": e.server_ip,
                    "offered_ip": e.offered_ip,
                    "gateway": e.gateway,
                    "dns_servers": e.dns_servers,
                    "lease_time": e.lease_time,
                    "timestamp": e.timestamp.isoformat(),
                }
                for e in events
            ],
            "alerts": [
                {
                    "alert_type": a.alert_type,
                    "severity": a.severity,
                    "description": a.description,
                    "server_ip": a.server_ip,
                    "server_mac": a.server_mac,
                    "timestamp": a.timestamp.isoformat(),
                }
                for a in alerts
            ],
        }
        console.print(_json_module.dumps(data, indent=2))
        return

    if events:
        console.print(_events_table(events, title=f"DHCP Events ({len(events)} captured)"))
    else:
        console.print("[dim]No DHCP events captured.[/dim]")

    if alerts:
        console.print()
        _print_alerts(alerts)
    elif events:
        console.print("[green]No rogue DHCP servers detected.[/green]")


@app.command("check")
def check_cmd(
    interface: Optional[str] = typer.Option(None, "--interface", "-i", help="Network interface."),
    expected: Optional[str] = typer.Option(
        None,
        "--expected",
        "-e",
        help="Comma-separated list of expected DHCP server IPs.",
    ),
    output_json: bool = typer.Option(False, "--json", help="Output results as JSON."),
) -> None:
    """Quick rogue DHCP server check (10-second sniff).

    Requires root/sudo for packet capture.
    Example: sudo netglance dhcp check
    """
    expected_servers: list[str] | None = None
    if expected:
        expected_servers = [s.strip() for s in expected.split(",") if s.strip()]

    if not output_json:
        console.print("[dim]Scanning for rogue DHCP servers (10s)...[/dim]")

    events, alerts = monitor_dhcp(
        duration=10.0,
        interface=interface,
        expected_servers=expected_servers,
    )

    if output_json:
        data = {
            "events_captured": len(events),
            "alerts": [
                {
                    "alert_type": a.alert_type,
                    "severity": a.severity,
                    "description": a.description,
                    "server_ip": a.server_ip,
                    "server_mac": a.server_mac,
                }
                for a in alerts
            ],
        }
        console.print(_json_module.dumps(data, indent=2))
        return

    console.print(f"[dim]Captured {len(events)} DHCP event(s).[/dim]")

    if alerts:
        console.print()
        _print_alerts(alerts)
        raise typer.Exit(code=1)
    else:
        console.print("[green]No rogue DHCP servers detected.[/green]")


@app.command("leases")
def leases_cmd(
    duration: float = typer.Option(30.0, "--duration", "-d", help="Listen duration in seconds."),
    interface: Optional[str] = typer.Option(None, "--interface", "-i", help="Network interface."),
    output_json: bool = typer.Option(False, "--json", help="Output results as JSON."),
) -> None:
    """Show observed DHCP leases from captured ACK packets.

    Requires root/sudo for packet capture.
    Example: sudo netglance dhcp leases --duration 60
    """
    if not output_json:
        console.print(
            f"[dim]Listening for DHCP leases for {duration:.0f}s...[/dim]"
        )

    events = sniff_dhcp(timeout=duration, interface=interface)
    ack_events = [e for e in events if e.event_type == "ack"]

    if output_json:
        data = [
            {
                "client_mac": e.client_mac,
                "assigned_ip": e.offered_ip or e.client_ip,
                "server_ip": e.server_ip,
                "gateway": e.gateway,
                "dns_servers": e.dns_servers,
                "lease_time": e.lease_time,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in ack_events
        ]
        console.print(_json_module.dumps(data, indent=2))
        return

    if ack_events:
        console.print(_leases_table(events))
    else:
        console.print("[dim]No DHCP leases observed.[/dim]")
