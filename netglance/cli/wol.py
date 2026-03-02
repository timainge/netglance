"""Wake-on-LAN CLI subcommands."""

from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from netglance.modules.wol import send_wol, wake_device
from netglance.store.models import WolResult

app = typer.Typer(help="Send Wake-on-LAN magic packets.", no_args_is_help=True)
console = Console()


def _print_result(result: WolResult, as_json: bool = False) -> None:
    """Print a WolResult to the console."""
    if as_json:
        data = {
            "mac": result.mac,
            "broadcast": result.broadcast,
            "port": result.port,
            "sent": result.sent,
            "device_name": result.device_name,
        }
        console.print(json.dumps(data, indent=2))
        return

    status = "[green]Sent[/green]" if result.sent else "[red]Failed[/red]"
    lines = [
        f"Status:    {status}",
        f"MAC:       {result.mac}",
        f"Broadcast: {result.broadcast}",
        f"Port:      {result.port}",
    ]
    if result.device_name:
        lines.insert(0, f"Device:    {result.device_name}")

    if result.sent:
        title = "[green]Wake-on-LAN — Magic Packet Sent[/green]"
    else:
        title = "[red]Wake-on-LAN — Send Failed[/red]"

    console.print(Panel("\n".join(lines), title=title, expand=False))


@app.command("send")
def wol_send_cmd(
    mac: str = typer.Argument(..., help="Target MAC address (AA:BB:CC:DD:EE:FF)."),
    broadcast: str = typer.Option(
        "255.255.255.255", "--broadcast", "-b", help="Broadcast address."
    ),
    port: int = typer.Option(9, "--port", "-p", help="UDP port (default 9)."),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Send a Wake-on-LAN magic packet to a MAC address."""
    try:
        result = send_wol(mac, broadcast=broadcast, port=port)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)
    _print_result(result, as_json=as_json)
    if not result.sent:
        raise typer.Exit(code=1)


@app.command("wake")
def wol_wake_cmd(
    name: str = typer.Argument(..., help="Device hostname from inventory."),
    broadcast: str = typer.Option(
        "255.255.255.255", "--broadcast", "-b", help="Broadcast address."
    ),
    port: int = typer.Option(9, "--port", "-p", help="UDP port (default 9)."),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Wake a device by hostname (looked up from inventory)."""
    try:
        result = wake_device(name, broadcast=broadcast, port=port)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)
    _print_result(result, as_json=as_json)
    if not result.sent:
        raise typer.Exit(code=1)
