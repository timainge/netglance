"""Scan CLI subcommands."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from netglance.cli._shared import maybe_warn_db_size
from netglance.modules.scan import (
    SUSPICIOUS_PORTS,
    diff_scans,
    quick_scan,
    scan_host,
)
from netglance.store.db import Store
from netglance.store.models import HostScanResult, PortResult

app = typer.Typer(help="Port scanning & service enumeration.", no_args_is_help=True)
console = Console()


def _scan_result_table(
    result: HostScanResult,
    title: str = "Scan Results",
    new_ports: set[int] | None = None,
) -> Table:
    table = Table(title=title, show_lines=False)
    table.add_column("Port", justify="right", style="bold")
    table.add_column("State")
    table.add_column("Service")
    table.add_column("Version")

    if new_ports is None:
        new_ports = set()

    for p in sorted(result.ports, key=lambda x: x.port):
        if p.port in new_ports:
            color = "yellow"
        elif p.port in SUSPICIOUS_PORTS:
            color = "red"
        else:
            color = "green"

        table.add_row(
            f"[{color}]{p.port}[/{color}]",
            f"[{color}]{p.state}[/{color}]",
            f"[{color}]{p.service or ''}[/{color}]",
            f"[{color}]{p.version or ''}[/{color}]",
        )

    return table


@app.command("host")
def scan_host_cmd(
    host: str = typer.Argument(..., help="IP address or hostname to scan."),
    ports: Optional[str] = typer.Option(
        None, "--ports", "-p", help="Port range (e.g. '22,80,443' or '1-1024')."
    ),
    save: bool = typer.Option(False, "--save/--no-save", help="Save result to local DB."),
    diff: bool = typer.Option(
        False, "--diff", "-d", help="Compare with last saved scan for this host."
    ),
) -> None:
    """Scan a host for open ports. Defaults to top-100 common ports."""
    if ports:
        result = scan_host(host, ports=ports)
    else:
        result = quick_scan(host)

    new_port_nums: set[int] = set()

    if diff or save:
        store = Store()
        store.init_db()

        if diff:
            previous_data = store.get_results("scan", limit=1)
            if previous_data:
                prev_ports = [PortResult(**p) for p in previous_data[0].get("ports", [])]
                previous = HostScanResult(
                    host=previous_data[0]["host"],
                    ports=prev_ports,
                )
                changes = diff_scans(result, previous)
                new_port_nums = {p["port"] for p in changes["new_ports"]}  # type: ignore[arg-type]

                if changes["new_ports"] or changes["closed_ports"] or changes["changed_services"]:
                    console.print()
                    if changes["new_ports"]:
                        console.print(
                            f"[yellow]New ports:[/yellow] "
                            f"{', '.join(str(p['port']) for p in changes['new_ports'])}"
                        )
                    if changes["closed_ports"]:
                        console.print(
                            f"[dim]Closed ports:[/dim] "
                            f"{', '.join(str(p['port']) for p in changes['closed_ports'])}"
                        )
                    if changes["changed_services"]:
                        for ch in changes["changed_services"]:
                            console.print(
                                f"[yellow]Port {ch['port']}:[/yellow] "
                                f"{ch['old_service']} -> {ch['new_service']}"
                            )
                else:
                    console.print("[dim]No changes since last scan.[/dim]")
            else:
                console.print("[dim]No previous scan to compare against.[/dim]")

        if save:
            scan_data = {
                "host": result.host,
                "ports": [
                    {
                        "port": p.port,
                        "state": p.state,
                        "service": p.service,
                        "version": p.version,
                        "banner": p.banner,
                    }
                    for p in result.ports
                ],
                "scan_duration_s": result.scan_duration_s,
            }
            store.save_result("scan", scan_data)
            console.print("[dim]✓ Saved to local database.[/dim]")
            maybe_warn_db_size(store, console)

    console.print(
        _scan_result_table(
            result,
            title=f"Scan {host} ({len(result.ports)} open)",
            new_ports=new_port_nums,
        )
    )
    console.print(f"\n[dim]Scan completed in {result.scan_duration_s:.1f}s[/dim]")
