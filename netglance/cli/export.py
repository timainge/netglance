"""Export CLI subcommands — device inventory and baseline export."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from netglance.modules.export import (
    export_baseline_json,
    export_devices_csv,
    export_devices_html,
    export_devices_json,
)
from netglance.store.db import DEFAULT_DB_PATH, Store
from netglance.store.models import Device, HostScanResult, PortResult

app = typer.Typer(help="Export network inventory to JSON, CSV, or HTML.", no_args_is_help=True)
console = Console()

# Hidden option name for test DB override
_DB_OPTION = typer.Option(
    None, "--db", hidden=True, help="Path to SQLite database (override for testing)."
)


def _load_store(db: Optional[Path]) -> Store:
    path = db or DEFAULT_DB_PATH
    store = Store(db_path=path)
    store.init_db()
    return store


def _devices_from_baseline(baseline: dict) -> list[Device]:
    """Reconstruct Device objects from a stored baseline dict."""
    from datetime import datetime

    devices: list[Device] = []
    for d in baseline.get("devices", []):
        devices.append(Device(
            ip=d["ip"],
            mac=d["mac"],
            hostname=d.get("hostname"),
            vendor=d.get("vendor"),
            discovery_method=d.get("discovery_method", "arp"),
            first_seen=datetime.fromisoformat(d["first_seen"]) if "first_seen" in d else datetime.now(),
            last_seen=datetime.fromisoformat(d["last_seen"]) if "last_seen" in d else datetime.now(),
        ))
    return devices


def _scans_from_baseline(baseline: dict) -> dict[str, HostScanResult]:
    """Reconstruct HostScanResult objects from open_ports in a baseline dict."""
    from datetime import datetime

    scans: dict[str, HostScanResult] = {}
    for host, ports in baseline.get("open_ports", {}).items():
        port_results = [
            PortResult(
                port=p["port"],
                state=p.get("state", "open"),
                service=p.get("service"),
                version=p.get("version"),
                banner=p.get("banner"),
            )
            for p in ports
        ]
        scans[host] = HostScanResult(
            host=host,
            ports=port_results,
            scan_time=datetime.now(),
        )
    return scans


@app.command("devices")
def export_devices_cmd(
    fmt: str = typer.Option("json", "--format", "-f", help="Output format: json, csv, html."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="File path to write output."),
    db: Optional[Path] = _DB_OPTION,
) -> None:
    """Export device inventory from the latest baseline."""
    store = _load_store(db)
    baseline = store.get_latest_baseline()

    if baseline is None:
        console.print("[yellow]No baseline found in store. Run `netglance baseline take` first.[/yellow]")
        raise typer.Exit(code=1)

    devices = _devices_from_baseline(baseline)
    scans = _scans_from_baseline(baseline)

    fmt = fmt.lower()
    if fmt == "json":
        content = export_devices_json(devices, scans=scans or None, output=output)
    elif fmt == "csv":
        content = export_devices_csv(devices, scans=scans or None, output=output)
    elif fmt == "html":
        content = export_devices_html(devices, scans=scans or None, output=output)
    else:
        console.print(f"[red]Unknown format:[/red] {fmt!r}. Choose from: json, csv, html.")
        raise typer.Exit(code=1)

    if output:
        console.print(f"[green]Exported {len(devices)} device(s) to {output}[/green]")
    else:
        sys.stdout.write(content)


@app.command("baseline")
def export_baseline_cmd(
    label: Optional[str] = typer.Option(None, "--label", "-l", help="Export baseline with this label."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="File path to write output."),
    db: Optional[Path] = _DB_OPTION,
) -> None:
    """Export the latest baseline (or by label) as JSON."""
    store = _load_store(db)

    baseline: dict | None = None

    if label:
        # Search baselines by label
        for meta in store.list_baselines(limit=100):
            if meta.get("label") == label:
                baseline = store.get_baseline(meta["id"])
                break
        if baseline is None:
            console.print(f"[red]No baseline found with label:[/red] {label!r}")
            raise typer.Exit(code=1)
    else:
        baseline = store.get_latest_baseline()
        if baseline is None:
            console.print("[yellow]No baseline found in store. Run `netglance baseline take` first.[/yellow]")
            raise typer.Exit(code=1)

    content = export_baseline_json(baseline, output=output)

    if output:
        console.print(f"[green]Baseline exported to {output}[/green]")
    else:
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")
