"""Discover CLI subcommands."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from netglance.cli._shared import maybe_warn_db_size
from netglance.modules.discover import (
    arp_scan,
    dicts_to_devices,
    devices_to_dicts,
    diff_devices,
    discover_all,
    mdns_scan,
)
from netglance.store.db import Store
from netglance.store.models import Device

app = typer.Typer(help="Network device discovery.")
console = Console()


class DiscoverMethod(str, Enum):
    arp = "arp"
    mdns = "mdns"
    all = "all"


@app.callback(invoke_without_command=True)
def discover_cmd(
    ctx: typer.Context,
    subnet: str = typer.Option("192.168.1.0/24", "--subnet", "-s", help="Subnet to scan."),
    interface: Optional[str] = typer.Option(None, "--interface", "-i", help="Network interface."),
    method: DiscoverMethod = typer.Option(
        DiscoverMethod.all, "--method", "-m", help="Discovery method."
    ),
    save: bool = typer.Option(False, "--save/--no-save", help="Save result to local DB."),
    diff: bool = typer.Option(False, "--diff", help="Compare against saved baseline."),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
    db_path: Optional[Path] = typer.Option(None, "--db", hidden=True, help="DB path override."),
) -> None:
    """Discover devices on the local network."""
    if ctx.invoked_subcommand is not None:
        return

    if method == DiscoverMethod.arp:
        devices = arp_scan(subnet, interface)
    elif method == DiscoverMethod.mdns:
        devices = mdns_scan()
    else:
        devices = discover_all(subnet, interface)

    # --save
    if save:
        store = Store(db_path=db_path) if db_path else Store()
        store.init_db()
        store.save_result("discover", {"devices": devices_to_dicts(devices)})
        store.save_baseline({"devices": devices_to_dicts(devices)}, label="discover")
        console.print("[dim]✓ Saved to local database.[/dim]")
        maybe_warn_db_size(store, console)
        store.close()

    # --diff
    diff_result: dict[str, list[Device]] | None = None
    if diff:
        store = Store(db_path=db_path) if db_path else Store()
        store.init_db()
        baseline_data = store.get_latest_baseline()
        store.close()
        if baseline_data and "devices" in baseline_data:
            baseline_devices = dicts_to_devices(baseline_data["devices"])
            diff_result = diff_devices(devices, baseline_devices)

    # --json
    if output_json:
        payload: dict = {"devices": devices_to_dicts(devices)}
        if diff_result is not None:
            payload["diff"] = {k: devices_to_dicts(v) for k, v in diff_result.items()}
        console.print_json(json.dumps(payload))
        return

    # Rich table output
    table = Table(title="Discovered Devices")
    table.add_column("IP", style="cyan")
    table.add_column("MAC", style="green")
    table.add_column("Hostname")
    table.add_column("Vendor")
    table.add_column("Method")
    table.add_column("Status", style="bold")

    for dev in devices:
        status = "online"
        if diff_result:
            if dev in diff_result["new"]:
                status = "new"
            elif dev in diff_result["changed"]:
                status = "changed"
        table.add_row(
            dev.ip, dev.mac, dev.hostname or "", dev.vendor or "", dev.discovery_method, status
        )

    console.print(table)

    if diff_result and diff_result["missing"]:
        missing_table = Table(title="Missing Devices (in baseline but not found)")
        missing_table.add_column("IP", style="red")
        missing_table.add_column("MAC", style="red")
        missing_table.add_column("Hostname")
        for dev in diff_result["missing"]:
            missing_table.add_row(dev.ip, dev.mac, dev.hostname or "")
        console.print(missing_table)
