"""VPN leak detection CLI subcommands."""

from __future__ import annotations

import json as _json
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from netglance.modules.vpn import (
    check_dns_leak,
    check_ipv6_leak,
    detect_vpn_interface,
    run_vpn_leak_check,
)
from netglance.store.models import VpnLeakReport

app = typer.Typer(help="VPN leak detection & tunnel analysis.", no_args_is_help=True)
console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _status_text(ok: bool, ok_label: str = "OK", bad_label: str = "LEAK") -> Text:
    if ok:
        return Text(ok_label, style="bold green")
    return Text(bad_label, style="bold red")


def _render_report(report: VpnLeakReport) -> None:
    """Print a rich panel summarising the VPN leak report."""
    # Build summary table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Check", style="dim")
    table.add_column("Result")

    # VPN interface
    if report.vpn_detected:
        iface_val = Text(f"Active  ({report.vpn_interface})", style="bold green")
    else:
        iface_val = Text("Not detected", style="yellow")
    table.add_row("VPN Interface", iface_val)

    # DNS leak
    dns_val = _status_text(not report.dns_leak, ok_label="No leak", bad_label="Leak detected")
    if report.dns_leak and report.dns_leak_resolvers:
        dns_val.append(f"  [{', '.join(report.dns_leak_resolvers)}]", style="dim red")
    table.add_row("DNS Leak", dns_val)

    # IPv6 leak
    ipv6_val = _status_text(not report.ipv6_leak, ok_label="No leak", bad_label="Leak detected")
    if report.ipv6_leak and report.ipv6_addresses:
        ipv6_val.append(f"  [{', '.join(report.ipv6_addresses)}]", style="dim red")
    table.add_row("IPv6 Leak", ipv6_val)

    # Split tunnel
    split_val = _status_text(
        not report.split_tunnel,
        ok_label="Not detected",
        bad_label="Detected",
    )
    table.add_row("Split Tunnel", split_val)

    # Overall colour
    has_issue = report.dns_leak or report.ipv6_leak or report.split_tunnel
    if not report.vpn_detected:
        panel_style = "yellow"
        title = "VPN Status — No VPN Active"
    elif has_issue:
        panel_style = "red"
        title = "VPN Status — [bold red]Leaks Detected[/bold red]"
    else:
        panel_style = "green"
        title = "VPN Status — [bold green]Secure[/bold green]"

    console.print(Panel(table, title=title, border_style=panel_style))

    # Details
    if report.details:
        console.print()
        for line in report.details:
            console.print(f"  [dim]•[/dim] {line}")


def _report_to_dict(report: VpnLeakReport) -> dict:
    return {
        "vpn_detected": report.vpn_detected,
        "vpn_interface": report.vpn_interface,
        "dns_leak": report.dns_leak,
        "dns_leak_resolvers": report.dns_leak_resolvers,
        "ipv6_leak": report.ipv6_leak,
        "ipv6_addresses": report.ipv6_addresses,
        "split_tunnel": report.split_tunnel,
        "local_ip_exposed": report.local_ip_exposed,
        "details": report.details,
        "timestamp": report.timestamp.isoformat(),
    }


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command("check")
def vpn_check(
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Full VPN leak assessment — interface, DNS, IPv6, split-tunnel."""
    with console.status("Running VPN leak checks…"):
        report = run_vpn_leak_check()

    if json:
        console.print_json(_json.dumps(_report_to_dict(report)))
        return

    _render_report(report)


@app.command("dns")
def vpn_dns(
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """DNS leak test only."""
    with console.status("Checking for DNS leaks…"):
        is_leaking, leak_ips = check_dns_leak()

    if json:
        console.print_json(_json.dumps({"dns_leak": is_leaking, "resolvers": leak_ips}))
        return

    if is_leaking:
        console.print(
            Panel(
                f"[bold red]DNS leak detected[/bold red]\n"
                f"Resolvers outside VPN: {', '.join(leak_ips)}",
                border_style="red",
                title="DNS Leak",
            )
        )
    else:
        console.print(
            Panel("[bold green]No DNS leak detected[/bold green]", border_style="green", title="DNS Leak")
        )


@app.command("ipv6")
def vpn_ipv6(
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """IPv6 leak test only."""
    with console.status("Checking for IPv6 leaks…"):
        is_leaking, addrs = check_ipv6_leak()

    if json:
        console.print_json(_json.dumps({"ipv6_leak": is_leaking, "addresses": addrs}))
        return

    if is_leaking:
        console.print(
            Panel(
                f"[bold red]IPv6 leak detected[/bold red]\n"
                f"Exposed addresses: {', '.join(addrs)}",
                border_style="red",
                title="IPv6 Leak",
            )
        )
    else:
        console.print(
            Panel(
                "[bold green]No IPv6 leak detected[/bold green]",
                border_style="green",
                title="IPv6 Leak",
            )
        )


@app.command("status")
def vpn_status(
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show active VPN interface information."""
    vpn_detected, vpn_iface = detect_vpn_interface()

    if json:
        console.print_json(
            _json.dumps({"vpn_detected": vpn_detected, "vpn_interface": vpn_iface})
        )
        return

    if vpn_detected:
        console.print(
            Panel(
                f"[bold green]VPN active[/bold green] — interface: [bold]{vpn_iface}[/bold]",
                border_style="green",
                title="VPN Interface",
            )
        )
    else:
        console.print(
            Panel(
                "[yellow]No active VPN tunnel interface detected.[/yellow]",
                border_style="yellow",
                title="VPN Interface",
            )
        )
