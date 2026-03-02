"""Baseline CLI subcommands."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from netglance.cli._shared import maybe_warn_db_size
from netglance.modules.baseline import (
    NetworkBaseline,
    capture_baseline,
    diff_baselines,
    load_baseline,
    save_baseline,
)
from netglance.store.db import DEFAULT_DB_PATH, Store

app = typer.Typer(help="Network baseline snapshot & diff.", no_args_is_help=True)
console = Console()


def _get_store(db: str | None) -> Store:
    """Create a Store, optionally from a custom path, and initialise the DB."""
    store = Store(db_path=db) if db else Store()
    store.init_db()
    return store


def _devices_table(baseline: NetworkBaseline, title: str = "Devices") -> Table:
    table = Table(title=title, show_lines=False)
    table.add_column("IP", style="bold")
    table.add_column("MAC")
    table.add_column("Hostname")
    table.add_column("Vendor")
    table.add_column("Method", style="dim")
    for d in sorted(baseline.devices, key=lambda d: d.ip):
        table.add_row(d.ip, d.mac, d.hostname or "", d.vendor or "", d.discovery_method)
    return table


def _ports_table(open_ports: dict, title: str = "Open Ports") -> Table:
    table = Table(title=title, show_lines=False)
    table.add_column("Host", style="bold")
    table.add_column("Port", justify="right")
    table.add_column("State")
    table.add_column("Service")
    for host in sorted(open_ports.keys()):
        for p in sorted(open_ports[host], key=lambda x: x.port):
            table.add_row(host, str(p.port), p.state, p.service or "")
    return table


def _arp_table(baseline: NetworkBaseline, title: str = "ARP Table") -> Table:
    table = Table(title=title, show_lines=False)
    table.add_column("IP", style="bold")
    table.add_column("MAC")
    table.add_column("Interface", style="dim")
    for e in sorted(baseline.arp_table, key=lambda e: e.ip):
        table.add_row(e.ip, e.mac, e.interface)
    return table


@app.command("capture")
def baseline_capture(
    subnet: str = typer.Option("192.168.1.0/24", "--subnet", "-s", help="CIDR subnet."),
    label: Optional[str] = typer.Option(None, "--label", "-l", help="Label for this baseline."),
    interface: Optional[str] = typer.Option(None, "--interface", "-i", help="Network interface."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True, help="Database path override."),
) -> None:
    """Capture a full network baseline (devices, ARP, DNS, ports)."""
    console.print("[bold]Capturing network baseline...[/bold]")

    baseline = capture_baseline(subnet, interface=interface, label=label)

    store = _get_store(db)
    baseline_id = save_baseline(baseline, store)

    console.print(f"[green]Baseline #{baseline_id} saved.[/green]")
    maybe_warn_db_size(store, console)
    store.close()
    console.print(f"  Devices:     {len(baseline.devices)}")
    console.print(f"  ARP entries: {len(baseline.arp_table)}")
    console.print(f"  DNS results: {len(baseline.dns_results)}")
    port_count = sum(len(ports) for ports in baseline.open_ports.values())
    console.print(f"  Open ports:  {port_count}")
    console.print(f"  Gateway MAC: {baseline.gateway_mac or 'N/A'}")
    console.print()
    console.print(_devices_table(baseline))


@app.command("diff")
def baseline_diff(
    subnet: str = typer.Option("192.168.1.0/24", "--subnet", "-s", help="CIDR subnet."),
    interface: Optional[str] = typer.Option(None, "--interface", "-i", help="Network interface."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True, help="Database path override."),
) -> None:
    """Diff current network state against the last saved baseline."""
    store = _get_store(db)
    previous = load_baseline(store)
    if previous is None:
        console.print("[red]No saved baseline found. Run 'baseline capture' first.[/red]")
        store.close()
        raise typer.Exit(code=1)

    console.print("[bold]Capturing current state...[/bold]")
    current = capture_baseline(subnet, interface=interface)

    changes = diff_baselines(current, previous)
    store.close()

    has_changes = False

    # Devices
    if changes["new_devices"]:
        has_changes = True
        console.print(f"\n[red]New devices ({len(changes['new_devices'])}):[/red]")
        for d in changes["new_devices"]:
            console.print(f"  [red]+[/red] {d.ip}  {d.mac}  {d.hostname or ''}")

    if changes["missing_devices"]:
        has_changes = True
        console.print(f"\n[yellow]Missing devices ({len(changes['missing_devices'])}):[/yellow]")
        for d in changes["missing_devices"]:
            console.print(f"  [yellow]-[/yellow] {d.ip}  {d.mac}  {d.hostname or ''}")

    if changes["changed_devices"]:
        has_changes = True
        console.print(f"\n[yellow]Changed devices ({len(changes['changed_devices'])}):[/yellow]")
        for d in changes["changed_devices"]:
            console.print(f"  [yellow]~[/yellow] {d.ip}  {d.mac}  {d.hostname or ''}")

    # ARP alerts
    if changes["arp_alerts"]:
        has_changes = True
        console.print(f"\n[red]ARP alerts ({len(changes['arp_alerts'])}):[/red]")
        for alert in changes["arp_alerts"]:
            color = "red" if alert.severity == "critical" else "yellow"
            console.print(f"  [{color}]{alert.alert_type}[/{color}]: {alert.description}")

    # DNS changes
    if changes["dns_changes"]:
        has_changes = True
        console.print(f"\n[yellow]DNS changes ({len(changes['dns_changes'])}):[/yellow]")
        for ch in changes["dns_changes"]:
            console.print(
                f"  [yellow]{ch['resolver_name']} ({ch['resolver']})[/yellow]: {ch['change']}"
            )

    # Port changes
    if changes["port_changes"]:
        has_changes = True
        console.print(f"\n[yellow]Port changes:[/yellow]")
        for host, host_changes in changes["port_changes"].items():
            if host_changes["new_ports"]:
                for p in host_changes["new_ports"]:
                    console.print(f"  [red]+[/red] {host}:{p['port']} ({p.get('service', '')})")
            if host_changes["closed_ports"]:
                for p in host_changes["closed_ports"]:
                    console.print(f"  [dim]-[/dim] {host}:{p['port']} ({p.get('service', '')})")

    if not has_changes:
        console.print("[green]No changes since last baseline.[/green]")


@app.command("list")
def baseline_list(
    db: Optional[str] = typer.Option(None, "--db", hidden=True, help="Database path override."),
) -> None:
    """List saved baselines."""
    store = _get_store(db)
    entries = store.list_baselines()
    store.close()

    if not entries:
        console.print("[dim]No baselines saved yet.[/dim]")
        return

    table = Table(title="Saved Baselines", show_lines=False)
    table.add_column("ID", justify="right", style="bold")
    table.add_column("Label")
    table.add_column("Timestamp")
    for entry in entries:
        table.add_row(
            str(entry["id"]),
            entry["label"] or "",
            entry["timestamp"],
        )
    console.print(table)


@app.command("show")
def baseline_show(
    baseline_id: int = typer.Argument(..., help="Baseline ID to show."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True, help="Database path override."),
) -> None:
    """Show details of a specific baseline."""
    store = _get_store(db)
    baseline = load_baseline(store, baseline_id=baseline_id)
    store.close()

    if baseline is None:
        console.print(f"[red]Baseline #{baseline_id} not found.[/red]")
        raise typer.Exit(code=1)

    console.print(f"[bold]Baseline #{baseline_id}[/bold]")
    console.print(f"  Label:       {baseline.label or 'N/A'}")
    console.print(f"  Timestamp:   {baseline.timestamp.isoformat()}")
    console.print(f"  Devices:     {len(baseline.devices)}")
    console.print(f"  ARP entries: {len(baseline.arp_table)}")
    console.print(f"  DNS results: {len(baseline.dns_results)}")
    port_count = sum(len(ports) for ports in baseline.open_ports.values())
    console.print(f"  Open ports:  {port_count}")
    console.print(f"  Gateway MAC: {baseline.gateway_mac or 'N/A'}")
    console.print()

    console.print(_devices_table(baseline))
    console.print()

    if baseline.open_ports:
        console.print(_ports_table(baseline.open_ports))
        console.print()

    console.print(_arp_table(baseline))


@app.command("delete")
def baseline_delete(
    baseline_id: int = typer.Argument(..., help="Baseline ID to delete."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True, help="Database path override."),
) -> None:
    """Delete a saved baseline by ID."""
    store = _get_store(db)
    deleted = store.delete_baseline(baseline_id)
    store.close()
    if deleted:
        console.print(f"[green]Deleted baseline #{baseline_id}.[/green]")
    else:
        console.print(f"[red]Baseline #{baseline_id} not found.[/red]")
        raise typer.Exit(code=1)
