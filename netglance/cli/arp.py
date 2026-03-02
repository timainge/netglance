"""ARP CLI subcommands."""

from __future__ import annotations

from dataclasses import asdict
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from netglance.modules.arp import (
    check_arp_anomalies,
    get_arp_table,
    watch_arp,
)
from netglance.store.db import Store
from netglance.store.models import ArpAlert, ArpEntry

app = typer.Typer(help="ARP table monitor & MITM detection.", no_args_is_help=True)
console = Console()


def _arp_table_rich(entries: list[ArpEntry], title: str = "ARP Table") -> Table:
    table = Table(title=title, show_lines=False)
    table.add_column("IP Address", style="bold")
    table.add_column("MAC Address")
    table.add_column("Vendor")
    table.add_column("Interface")

    for e in entries:
        vendor = _lookup_vendor(e.mac)
        table.add_row(e.ip, e.mac, vendor, e.interface)
    return table


def _lookup_vendor(mac: str) -> str:
    try:
        from mac_vendor_lookup import MacLookup

        return MacLookup().lookup(mac)
    except Exception:
        return ""


def _render_alerts(alerts: list[ArpAlert]) -> None:
    for alert in alerts:
        style = "red" if alert.severity == "critical" else "yellow"
        panel = Panel(
            Text(alert.description),
            title=f"[{style}]{alert.alert_type}[/{style}]",
            border_style=style,
            subtitle=f"severity: {alert.severity}",
        )
        console.print(panel)


def _entries_to_dicts(entries: list[ArpEntry]) -> list[dict]:
    result = []
    for e in entries:
        d = asdict(e)
        d["timestamp"] = e.timestamp.isoformat()
        result.append(d)
    return result


def _dicts_to_entries(dicts: list[dict]) -> list[ArpEntry]:
    entries = []
    for d in dicts:
        entries.append(
            ArpEntry(ip=d["ip"], mac=d["mac"], interface=d.get("interface", ""))
        )
    return entries


@app.command("table")
def arp_table_cmd(
    interface: Optional[str] = typer.Option(
        None, "--interface", "-i", help="Filter by interface."
    ),
    save: bool = typer.Option(False, "--save/--no-save", help="Save result to local DB."),
    db_path: Optional[str] = typer.Option(None, "--db", hidden=True, help="DB path override."),
) -> None:
    """Show the current ARP table."""
    entries = get_arp_table()
    if interface:
        entries = [e for e in entries if e.interface == interface]
    if not entries:
        console.print("[dim]No ARP entries found.[/dim]")
        raise typer.Exit()
    console.print(_arp_table_rich(entries))

    if save:
        try:
            store = Store(db_path) if db_path else Store()
            store.init_db()
            store.save_result("arp", {"entries": _entries_to_dicts(entries)})
            store.close()
            console.print("[dim]✓ Saved to local database.[/dim]")
        except Exception as exc:
            console.print(f"[dim yellow]Warning: could not save result: {exc}[/dim yellow]")


@app.command("check")
def arp_check_cmd(
    db_path: Optional[str] = typer.Option(None, "--db", help="Path to netglance database."),
    gateway: Optional[str] = typer.Option(
        None, "--gateway", "-g", help="Gateway IP to watch."
    ),
) -> None:
    """One-shot anomaly check against the saved baseline."""
    store = Store(db_path) if db_path else Store()
    store.init_db()

    baseline_data = store.get_latest_baseline()
    if not baseline_data or "arp" not in baseline_data:
        console.print(
            "[yellow]No ARP baseline found.[/yellow] "
            "Run [bold]netglance arp save[/bold] first."
        )
        store.close()
        raise typer.Exit(code=1)

    baseline_entries = _dicts_to_entries(baseline_data["arp"])
    current_entries = get_arp_table()

    alerts = check_arp_anomalies(current_entries, baseline_entries, gateway_ip=gateway)
    store.close()

    console.print(_arp_table_rich(current_entries, title="Current ARP Table"))

    if alerts:
        console.print()
        _render_alerts(alerts)
    else:
        console.print("\n[green]No anomalies detected.[/green]")


@app.command("watch")
def arp_watch_cmd(
    interval: float = typer.Option(
        5.0, "--interval", "-n", help="Poll interval in seconds."
    ),
    db_path: Optional[str] = typer.Option(None, "--db", help="Path to netglance database."),
    gateway: Optional[str] = typer.Option(
        None, "--gateway", "-g", help="Gateway IP to watch."
    ),
) -> None:
    """Continuous ARP monitoring (Ctrl+C to stop)."""
    store = Store(db_path) if db_path else Store()
    store.init_db()

    baseline_data = store.get_latest_baseline()
    baseline_entries: list[ArpEntry] = []
    if baseline_data and "arp" in baseline_data:
        baseline_entries = _dicts_to_entries(baseline_data["arp"])

    def _on_snapshot(entries: list[ArpEntry]) -> None:
        console.clear()
        console.print(_arp_table_rich(entries, title="ARP Table (live)"))
        if baseline_entries:
            alerts = check_arp_anomalies(entries, baseline_entries, gateway_ip=gateway)
            if alerts:
                console.print()
                _render_alerts(alerts)
            else:
                console.print("\n[green]No anomalies.[/green]")

    try:
        console.print("[dim]Watching ARP table... press Ctrl+C to stop.[/dim]\n")
        watch_arp(_on_snapshot, interval=interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")
    finally:
        store.close()


@app.command("save")
def arp_save_cmd(
    db_path: Optional[str] = typer.Option(None, "--db", help="Path to netglance database."),
    label: Optional[str] = typer.Option(
        None, "--label", "-l", help="Label for this baseline."
    ),
) -> None:
    """Save current ARP table as baseline."""
    entries = get_arp_table()
    if not entries:
        console.print("[red]Error:[/red] No ARP entries found. Cannot save empty baseline.")
        raise typer.Exit(code=1)

    store = Store(db_path) if db_path else Store()
    store.init_db()

    data = {"arp": _entries_to_dicts(entries)}
    bid = store.save_baseline(data, label=label or "arp")
    store.close()

    console.print(f"[green]Baseline saved[/green] (id={bid}, {len(entries)} entries)")
    console.print(_arp_table_rich(entries, title="Saved ARP Baseline"))
