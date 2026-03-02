"""IoT device detection and security audit CLI subcommands."""

from __future__ import annotations

import json as json_mod
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from netglance.modules.discover import arp_scan
from netglance.modules.scan import quick_scan
from netglance.modules.iot import (
    assess_device_risk,
    audit_network,
    classify_iot_device,
    format_risk_level,
    get_iot_signatures,
)
from netglance.store.models import Device, HostScanResult, IoTAuditReport, IoTDevice

app = typer.Typer(
    help="IoT device detection and security audit.",
    no_args_is_help=True,
)
console = Console()


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _risk_color(score: int) -> str:
    level = format_risk_level(score)
    return {
        "critical": "red",
        "high": "yellow",
        "medium": "dark_orange",
        "low": "green",
        "minimal": "bright_green",
    }.get(level, "white")


def _risk_cell(score: int) -> str:
    color = _risk_color(score)
    level = format_risk_level(score)
    return f"[{color}]{score} ({level})[/{color}]"


def _build_device_table(devices: list[IoTDevice], title: str = "IoT Devices") -> Table:
    table = Table(title=title, show_lines=False)
    table.add_column("IP", style="bold")
    table.add_column("MAC")
    table.add_column("Type")
    table.add_column("Manufacturer")
    table.add_column("Model")
    table.add_column("Risk Score", justify="right")
    table.add_column("Issues", justify="right")

    for dev in devices:
        table.add_row(
            dev.ip,
            dev.mac,
            dev.device_type,
            dev.manufacturer or "[dim]--[/dim]",
            dev.model or "[dim]--[/dim]",
            _risk_cell(dev.risk_score),
            str(len(dev.issues)),
        )

    return table


def _print_report_summary(report: IoTAuditReport) -> None:
    total = len(report.devices)
    if total == 0:
        console.print("[green]No IoT devices detected on this network.[/green]")
        return

    console.print(f"\n[bold]IoT Audit Summary[/bold]")
    console.print(f"  Total IoT devices: [bold]{total}[/bold]")
    console.print(f"  High-risk devices: [{'red' if report.high_risk_count else 'green'}]{report.high_risk_count}[/]")
    console.print(f"  Total issues found: [{'yellow' if report.total_issues else 'green'}]{report.total_issues}[/]")

    if report.recommendations:
        console.print("\n[bold]Recommendations:[/bold]")
        for rec in report.recommendations:
            console.print(f"  • {rec}")


def _iot_device_to_dict(dev: IoTDevice) -> dict:
    return {
        "ip": dev.ip,
        "mac": dev.mac,
        "device_type": dev.device_type,
        "manufacturer": dev.manufacturer,
        "model": dev.model,
        "risky_ports": dev.risky_ports,
        "risk_score": dev.risk_score,
        "risk_level": format_risk_level(dev.risk_score),
        "issues": dev.issues,
        "recommendations": dev.recommendations,
    }


def _report_to_dict(report: IoTAuditReport) -> dict:
    return {
        "devices": [_iot_device_to_dict(d) for d in report.devices],
        "high_risk_count": report.high_risk_count,
        "total_issues": report.total_issues,
        "recommendations": report.recommendations,
        "timestamp": report.timestamp.isoformat(),
    }


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command("audit")
def audit_cmd(
    subnet: str = typer.Option("192.168.1.0/24", "--subnet", "-s", help="Subnet to scan."),
    skip_scan: bool = typer.Option(False, "--skip-scan", help="Skip port scanning; classify from discovery data only."),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True, help="Database path override."),
) -> None:
    """Run a full IoT security audit: discover devices, scan ports, classify, and assess risk."""
    if not json_output:
        console.print(f"[dim]Discovering devices on {subnet}...[/dim]")

    try:
        devices = arp_scan(subnet)
    except Exception as exc:
        console.print(f"[red]Discovery failed:[/red] {exc}")
        raise typer.Exit(code=1)

    if not devices:
        console.print("[yellow]No devices found on network.[/yellow]")
        return

    if not json_output:
        console.print(f"[dim]Found {len(devices)} device(s). Classifying IoT devices...[/dim]")

    # Build scans dict if port scanning is requested
    scans: dict[str, HostScanResult] = {}
    if not skip_scan:
        if not json_output:
            console.print("[dim]Scanning ports (this may take a moment)...[/dim]")
        for device in devices:
            try:
                scans[device.ip] = quick_scan(device.ip)
            except Exception:
                pass

    report = audit_network(devices, scans=scans if scans else None)

    if json_output:
        console.print(json_mod.dumps(_report_to_dict(report), indent=2))
        return

    if not report.devices:
        console.print("[green]No IoT devices detected on this network.[/green]")
        return

    table = _build_device_table(report.devices, title=f"IoT Devices — {subnet}")
    console.print(table)
    _print_report_summary(report)

    # Show detailed issues for high-risk devices
    high_risk = [d for d in report.devices if d.risk_score >= 60]
    if high_risk:
        console.print("\n[bold red]High-Risk Device Details:[/bold red]")
        for dev in high_risk:
            console.print(f"\n  [bold]{dev.ip}[/bold] ({dev.device_type})")
            for issue in dev.issues:
                console.print(f"    [red]✗[/red] {issue}")


@app.command("list")
def list_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True, help="Database path override."),
) -> None:
    """List known IoT devices from the last audit (requires a prior audit run)."""
    # Without a persistent store, re-run a quick classification from discovery
    console.print("[dim]Scanning local network for IoT devices...[/dim]")

    try:
        devices = arp_scan("192.168.1.0/24")
    except Exception as exc:
        console.print(f"[red]Discovery failed:[/red] {exc}")
        raise typer.Exit(code=1)

    report = audit_network(devices)

    if json_output:
        console.print(json_mod.dumps([_iot_device_to_dict(d) for d in report.devices], indent=2))
        return

    if not report.devices:
        console.print("[green]No IoT devices found.[/green]")
        return

    table = _build_device_table(report.devices, title="Known IoT Devices")
    console.print(table)


@app.command("check")
def check_cmd(
    ip: str = typer.Argument(..., help="IP address of device to audit."),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON."),
    db: Optional[str] = typer.Option(None, "--db", hidden=True, help="Database path override."),
) -> None:
    """Audit a single device by IP address."""
    if not json_output:
        console.print(f"[dim]Auditing device {ip}...[/dim]")

    # Create a minimal Device for the given IP
    device = Device(ip=ip, mac="00:00:00:00:00:00")

    # Try to get MAC from ARP table
    try:
        # Parse subnet from IP
        parts = ip.split(".")
        subnet = ".".join(parts[:3]) + ".0/24"
        discovered = arp_scan(subnet)
        for d in discovered:
            if d.ip == ip:
                device = d
                break
    except Exception:
        pass

    # Port scan the target
    scan: HostScanResult | None = None
    try:
        scan = quick_scan(ip)
    except Exception as exc:
        if not json_output:
            console.print(f"[yellow]Port scan failed:[/yellow] {exc}")

    iot_device = classify_iot_device(device, scan=scan)
    if iot_device is None:
        if json_output:
            console.print(json_mod.dumps({"ip": ip, "is_iot": False}, indent=2))
        else:
            console.print(f"[green]{ip}[/green] does not appear to be an IoT device.")
        return

    iot_device = assess_device_risk(iot_device, scan=scan)

    if json_output:
        console.print(json_mod.dumps(_iot_device_to_dict(iot_device), indent=2))
        return

    # Rich display
    risk_color = _risk_color(iot_device.risk_score)
    level = format_risk_level(iot_device.risk_score)

    console.print(f"\n[bold]Device:[/bold] {iot_device.ip}")
    console.print(f"  MAC: {iot_device.mac}")
    console.print(f"  Type: [bold]{iot_device.device_type}[/bold]")
    if iot_device.manufacturer:
        console.print(f"  Manufacturer: {iot_device.manufacturer}")
    if iot_device.model:
        console.print(f"  Model: {iot_device.model}")
    console.print(
        f"  Risk Score: [{risk_color}]{iot_device.risk_score}/100 ({level})[/{risk_color}]"
    )

    if iot_device.issues:
        console.print("\n[bold]Issues:[/bold]")
        for issue in iot_device.issues:
            console.print(f"  [red]✗[/red] {issue}")

    if iot_device.recommendations:
        console.print("\n[bold]Recommendations:[/bold]")
        for rec in iot_device.recommendations:
            console.print(f"  • {rec}")

    if not iot_device.issues:
        console.print("\n[green]No security issues detected.[/green]")
