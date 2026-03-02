"""IPv6 CLI subcommands."""

from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from netglance.modules.ipv6 import (
    classify_ipv6_address,
    check_privacy_extensions,
    discover_ipv6_neighbors,
    run_ipv6_audit,
)

app = typer.Typer(help="IPv6 network audit and neighbor discovery.", no_args_is_help=True)
console = Console()


def _neighbors_table(neighbors, title: str = "IPv6 Neighbors") -> Table:
    table = Table(title=title, show_lines=False)
    table.add_column("IPv6 Address", style="bold cyan")
    table.add_column("MAC Address")
    table.add_column("Type")
    table.add_column("Interface")

    type_colors = {
        "link-local": "yellow",
        "global": "green",
        "temporary": "blue",
        "eui64": "magenta",
        "unique-local": "cyan",
        "multicast": "dim",
        "loopback": "dim",
        "unknown": "red",
    }

    for n in neighbors:
        color = type_colors.get(n.address_type, "white")
        table.add_row(
            n.ipv6_address,
            n.mac,
            f"[{color}]{n.address_type}[/{color}]",
            n.interface or "--",
        )
    return table


def _addresses_table(local_addresses, title: str = "Local IPv6 Addresses") -> Table:
    table = Table(title=title, show_lines=False)
    table.add_column("Interface", style="bold")
    table.add_column("IPv6 Address", style="cyan")
    table.add_column("Classification")

    type_colors = {
        "link-local": "yellow",
        "global": "green",
        "temporary": "blue",
        "eui64": "magenta",
        "unique-local": "cyan",
        "multicast": "dim",
        "loopback": "dim",
        "unknown": "red",
    }

    for addr in local_addresses:
        addr_type = addr.get("type", "unknown")
        color = type_colors.get(addr_type, "white")
        table.add_row(
            addr.get("interface", ""),
            addr.get("address", ""),
            f"[{color}]{addr_type}[/{color}]",
        )
    return table


def _audit_summary_panel(result) -> Panel:
    lines: list[str] = []

    # Dual stack
    ds_icon = "[green]YES[/green]" if result.dual_stack else "[yellow]NO[/yellow]"
    lines.append(f"Dual-Stack Active:       {ds_icon}")

    # Privacy extensions
    pe_icon = "[green]YES[/green]" if result.privacy_extensions else "[red]NO[/red]"
    lines.append(f"Privacy Extensions:      {pe_icon}")

    # EUI-64 exposure
    eui_icon = "[red]YES[/red]" if result.eui64_exposed else "[green]NO[/green]"
    lines.append(f"EUI-64 MAC Exposure:     {eui_icon}")

    # DNS leak
    if result.ipv6_dns_leak is None:
        leak_str = "[dim]N/A (no VPN)[/dim]"
    elif result.ipv6_dns_leak:
        leak_str = "[red]LEAK DETECTED[/red]"
    else:
        leak_str = "[green]No leak[/green]"
    lines.append(f"IPv6 DNS Leak:           {leak_str}")

    lines.append(f"\nNeighbors found:         {len(result.neighbors)}")
    lines.append(f"Local IPv6 addresses:    {len(result.local_addresses)}")

    return Panel("\n".join(lines), title="IPv6 Audit Summary", border_style="blue")


@app.command("audit")
def audit_cmd(
    interface: Optional[str] = typer.Option(None, "--interface", "-i", help="Network interface."),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Full IPv6 assessment: neighbors, addresses, privacy, DNS leak."""
    result = run_ipv6_audit(interface=interface)

    if as_json:
        output = {
            "neighbors": [
                {
                    "ipv6_address": n.ipv6_address,
                    "mac": n.mac,
                    "address_type": n.address_type,
                    "interface": n.interface,
                }
                for n in result.neighbors
            ],
            "local_addresses": result.local_addresses,
            "privacy_extensions": result.privacy_extensions,
            "eui64_exposed": result.eui64_exposed,
            "dual_stack": result.dual_stack,
            "ipv6_dns_leak": result.ipv6_dns_leak,
            "timestamp": result.timestamp.isoformat(),
        }
        console.print_json(json.dumps(output))
        return

    if result.neighbors:
        console.print(_neighbors_table(result.neighbors))
        console.print()

    if result.local_addresses:
        console.print(_addresses_table(result.local_addresses))
        console.print()

    console.print(_audit_summary_panel(result))


@app.command("neighbors")
def neighbors_cmd(
    interface: Optional[str] = typer.Option(None, "--interface", "-i", help="Network interface."),
    timeout: float = typer.Option(5.0, "--timeout", "-t", help="Discovery timeout in seconds."),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Discover IPv6 neighbors via NDP (requires root/sudo)."""
    with console.status("Sending ICMPv6 Neighbor Solicitation..."):
        neighbors = discover_ipv6_neighbors(interface=interface, timeout=timeout)

    if not neighbors:
        console.print("[yellow]No IPv6 neighbors discovered.[/yellow]")
        console.print("[dim]Note: NDP discovery requires root privileges.[/dim]")
        return

    if as_json:
        output = [
            {
                "ipv6_address": n.ipv6_address,
                "mac": n.mac,
                "address_type": n.address_type,
                "interface": n.interface,
            }
            for n in neighbors
        ]
        console.print_json(json.dumps(output))
        return

    console.print(_neighbors_table(neighbors))


@app.command("addresses")
def addresses_cmd(
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show local IPv6 addresses with classification."""
    import socket
    import psutil

    local_addresses: list[dict] = []
    for iface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family != socket.AF_INET6:
                continue
            clean = addr.address.split("%")[0]
            addr_type = classify_ipv6_address(clean)
            local_addresses.append(
                {
                    "interface": iface,
                    "address": clean,
                    "type": addr_type,
                }
            )

    if not local_addresses:
        console.print("[yellow]No IPv6 addresses found on this system.[/yellow]")
        return

    if as_json:
        console.print_json(json.dumps(local_addresses))
        return

    console.print(_addresses_table(local_addresses))

    # Privacy extension status
    privacy_ext, eui64_exposed = check_privacy_extensions()
    lines = []
    pe_icon = "[green]enabled[/green]" if privacy_ext else "[red]not detected[/red]"
    eui_icon = "[red]exposed[/red]" if eui64_exposed else "[green]not exposed[/green]"
    lines.append(f"Privacy extensions: {pe_icon}")
    lines.append(f"EUI-64 addresses:   {eui_icon}")
    console.print(Panel("\n".join(lines), title="Privacy Status", border_style="dim"))
