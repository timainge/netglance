"""Fingerprint / identify CLI subcommands."""

from __future__ import annotations

import json as json_mod
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from netglance.modules.discover import arp_scan
from netglance.modules.fingerprint import (
    classify_device,
    fingerprint_all,
    fingerprint_device,
    label_device,
)
from netglance.store.models import DeviceFingerprint, DeviceProfile

app = typer.Typer(
    help="Device fingerprinting and identification.",
    no_args_is_help=False,
)
console = Console()


def _confidence_color(conf: float) -> str:
    if conf >= 0.8:
        return "green"
    if conf >= 0.5:
        return "yellow"
    return "red"


def _profile_to_row(profile: DeviceProfile) -> tuple[str, ...]:
    conf_color = _confidence_color(profile.confidence)
    device_type = profile.device_type or "[dim]unknown[/dim]"
    manufacturer = profile.manufacturer or "[dim]--[/dim]"
    name = profile.friendly_name or profile.user_label or "[dim]--[/dim]"
    conf_str = f"[{conf_color}]{profile.confidence:.0%}[/{conf_color}]" if profile.confidence > 0 else "[dim]--[/dim]"
    method = profile.classification_method or "[dim]--[/dim]"
    return (profile.ip, profile.mac, device_type, manufacturer, name, conf_str, method)


def _build_table(profiles: list[DeviceProfile], title: str = "Device Identification") -> Table:
    table = Table(title=title, show_lines=False)
    table.add_column("IP", style="bold")
    table.add_column("MAC")
    table.add_column("Type")
    table.add_column("Manufacturer")
    table.add_column("Name")
    table.add_column("Confidence", justify="right")
    table.add_column("Method", style="dim")

    for profile in profiles:
        table.add_row(*_profile_to_row(profile))

    return table


def _profiles_to_json(profiles: list[DeviceProfile]) -> list[dict]:
    out = []
    for p in profiles:
        fp = p.fingerprint
        row = {
            "ip": p.ip,
            "mac": p.mac,
            "device_type": p.device_type,
            "device_category": p.device_category,
            "os": p.os,
            "manufacturer": p.manufacturer,
            "model": p.model,
            "friendly_name": p.friendly_name,
            "confidence": p.confidence,
            "classification_method": p.classification_method,
            "user_label": p.user_label,
            "fingerprint": {
                "mac_is_randomized": fp.mac_is_randomized if fp else False,
                "oui_vendor": fp.oui_vendor if fp else None,
                "hostname": fp.hostname if fp else None,
                "mdns_services": fp.mdns_services if fp else [],
                "upnp_friendly_name": fp.upnp_friendly_name if fp else None,
                "upnp_manufacturer": fp.upnp_manufacturer if fp else None,
                "open_ports": fp.open_ports if fp else [],
            } if fp else None,
        }
        out.append(row)
    return out


@app.callback(invoke_without_command=True)
def identify_cmd(
    ctx: typer.Context,
    ip: Optional[str] = typer.Argument(None, help="IP address of device to fingerprint."),
    unknown_only: bool = typer.Option(False, "--unknown", help="Show only unclassified devices."),
    label: Optional[str] = typer.Option(None, "--label", help="Assign a user label to the device at <ip>."),
    device_type: Optional[str] = typer.Option(None, "--type", help="Assign device type to device at <ip>."),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON."),
    subnet: str = typer.Option("192.168.1.0/24", "--subnet", "-s", help="Subnet to scan for all-devices mode."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True, help="Database path override."),
) -> None:
    """Fingerprint and identify network devices.

    With no arguments, fingerprints all discovered devices on the local subnet.
    Provide an IP to deep-fingerprint a single device.
    Use --label to assign a friendly name, --unknown to filter unidentified devices.
    """
    if ctx.invoked_subcommand is not None:
        return

    # --label with ip: label the device
    if label is not None and ip is not None:
        record = label_device(mac=ip, label=label, device_type=device_type)
        if json_output:
            console.print(json_mod.dumps(record, indent=2))
        else:
            console.print(f"[green]Labeled[/green] device [bold]{ip}[/bold] as [bold]{label!r}[/bold]")
            if device_type:
                console.print(f"  Device type set to: [bold]{device_type}[/bold]")
        return

    # Single IP: deep fingerprint
    if ip is not None:
        _fingerprint_single(ip, json_output=json_output)
        return

    # All devices: discover then fingerprint
    _fingerprint_all_cmd(subnet=subnet, unknown_only=unknown_only, json_output=json_output)


def _fingerprint_single(ip: str, json_output: bool = False) -> None:
    """Deep fingerprint a single device by IP."""
    console.print(f"[dim]Fingerprinting {ip}...[/dim]")

    # For single-device mode we can't do ARP, so we use the IP as mac placeholder
    # In real usage the caller should have the MAC from ARP; we do best-effort here
    fp = fingerprint_device(ip=ip, mac=ip)
    profile = classify_device(fp)
    profile.ip = ip

    if json_output:
        data = _profiles_to_json([profile])
        console.print(json_mod.dumps(data[0], indent=2))
    else:
        table = _build_table([profile], title=f"Fingerprint: {ip}")
        console.print(table)

        # Show fingerprint details
        if fp.mdns_services:
            console.print(f"\n[bold]mDNS services:[/bold] {', '.join(fp.mdns_services)}")
        if fp.upnp_friendly_name:
            console.print(f"[bold]UPnP device:[/bold] {fp.upnp_friendly_name}")
            if fp.upnp_manufacturer:
                console.print(f"  Manufacturer: {fp.upnp_manufacturer}")
            if fp.upnp_model_name:
                console.print(f"  Model: {fp.upnp_model_name}")
        if fp.mac_is_randomized:
            console.print("[yellow]Warning:[/yellow] MAC appears to be randomized (locally administered)")


def _fingerprint_all_cmd(subnet: str, unknown_only: bool, json_output: bool) -> None:
    """Discover and fingerprint all devices on the subnet."""
    if not json_output:
        console.print(f"[dim]Scanning {subnet}...[/dim]")

    try:
        devices = arp_scan(subnet)
    except Exception as exc:
        console.print(f"[red]Error during discovery:[/red] {exc}")
        raise typer.Exit(code=1)

    if not devices:
        console.print("[yellow]No devices found.[/yellow]")
        return

    if not json_output:
        console.print(f"[dim]Fingerprinting {len(devices)} device(s)...[/dim]")
    profiles = fingerprint_all(devices)

    if unknown_only:
        profiles = [p for p in profiles if not p.device_type]

    if not profiles:
        console.print("[dim]No matching devices.[/dim]")
        return

    if json_output:
        data = _profiles_to_json(profiles)
        console.print(json_mod.dumps(data, indent=2))
    else:
        table = _build_table(profiles, title=f"Network Devices — {subnet}")
        console.print(table)
        unknown = sum(1 for p in profiles if not p.device_type)
        if unknown:
            console.print(f"\n[dim]{unknown} device(s) could not be classified.[/dim]")
