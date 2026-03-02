"""WiFi CLI subcommands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from netglance.modules.trending import emit_wifi_metrics
from netglance.modules.wifi import (
    channel_utilization,
    current_connection,
    detect_rogue_aps,
    scan_wifi,
    signal_bar,
)
from netglance.store.db import Store

app = typer.Typer(help="Wireless network analysis.", no_args_is_help=True)
console = Console()


@app.command("scan")
def wifi_scan_cmd(
    sort_by: str = typer.Option(
        "signal", "--sort", "-s", help="Sort by: signal, channel, ssid."
    ),
    save: bool = typer.Option(False, "--save/--no-save", help="Save result to local DB."),
) -> None:
    """Scan and list nearby WiFi networks."""
    try:
        networks = scan_wifi()
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    if sort_by == "signal":
        networks.sort(key=lambda n: n.signal_dbm, reverse=True)
    elif sort_by == "channel":
        networks.sort(key=lambda n: n.channel)
    elif sort_by == "ssid":
        networks.sort(key=lambda n: n.ssid.lower())

    table = Table(title="WiFi Networks")
    table.add_column("SSID", style="cyan bold")
    table.add_column("BSSID", style="dim")
    table.add_column("Signal", justify="right")
    table.add_column("Bar")
    table.add_column("Ch", justify="right")
    table.add_column("Band")
    table.add_column("Security")

    for net in networks:
        table.add_row(
            net.ssid or "(hidden)",
            net.bssid,
            f"{net.signal_dbm} dBm",
            signal_bar(net.signal_dbm),
            str(net.channel),
            net.band,
            net.security,
        )

    console.print(table)
    console.print(f"[dim]{len(networks)} networks found.[/dim]")

    if save:
        try:
            store = Store()
            store.init_db()
            store.save_result("wifi", {
                "networks_found": len(networks),
                "networks": [{"ssid": n.ssid, "bssid": n.bssid, "signal_dbm": n.signal_dbm, "channel": n.channel, "security": n.security} for n in networks],
            })
            # Emit signal metric for current connection if available
            try:
                conn = current_connection()
                if conn:
                    emit_wifi_metrics(conn.signal_dbm, conn.ssid, store)
            except Exception:
                pass
            console.print("[dim]✓ Saved to local database.[/dim]")
        except Exception as exc:
            console.print(f"[dim yellow]Warning: could not save result: {exc}[/dim yellow]")


@app.command("info")
def wifi_info_cmd() -> None:
    """Show current WiFi connection details."""
    try:
        conn = current_connection()
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    if conn is None:
        console.print("[yellow]Not connected to any WiFi network.[/yellow]")
        raise typer.Exit()

    info_lines = [
        f"[bold]SSID:[/bold]     {conn.ssid}",
        f"[bold]BSSID:[/bold]    {conn.bssid}",
        f"[bold]Signal:[/bold]   {conn.signal_dbm} dBm  {signal_bar(conn.signal_dbm)}",
        f"[bold]Channel:[/bold]  {conn.channel} ({conn.band})",
        f"[bold]Security:[/bold] {conn.security}",
    ]
    if conn.noise_dbm is not None:
        snr = conn.signal_dbm - conn.noise_dbm
        info_lines.append(f"[bold]Noise:[/bold]    {conn.noise_dbm} dBm")
        info_lines.append(f"[bold]SNR:[/bold]      {snr} dB")

    console.print(Panel("\n".join(info_lines), title="Current WiFi Connection"))


@app.command("channels")
def wifi_channels_cmd() -> None:
    """Show WiFi channel utilization."""
    try:
        networks = scan_wifi()
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    utilization = channel_utilization(networks)

    if not utilization:
        console.print("[yellow]No networks found.[/yellow]")
        raise typer.Exit()

    max_count = max(utilization.values()) if utilization else 1

    table = Table(title="Channel Utilization")
    table.add_column("Channel", justify="right", style="cyan bold")
    table.add_column("Networks", justify="right")
    table.add_column("Usage")

    bar_char = "\u2588"
    for ch, count in utilization.items():
        bar_width = int((count / max_count) * 20) if max_count > 0 else 0
        color = "green" if count <= 2 else ("yellow" if count <= 5 else "red")
        bar = f"[{color}]{bar_char * bar_width}[/{color}]"
        table.add_row(str(ch), str(count), bar)

    console.print(table)


@app.command("rogues")
def wifi_rogues_cmd(
    ssid: list[str] = typer.Option(
        ..., "--ssid", "-s", help="Known SSID to check (repeatable)."
    ),
    bssid: list[str] = typer.Option(
        ..., "--bssid", "-b", help="Known BSSID for the SSID (repeatable, same order as --ssid)."
    ),
) -> None:
    """Detect rogue access points (evil twins).

    Provide known SSID/BSSID pairs. Any network broadcasting a known SSID
    from an unknown BSSID will be flagged.
    """
    known_ssids: dict[str, list[str]] = {}
    for s, b in zip(ssid, bssid):
        known_ssids.setdefault(s, []).append(b)

    try:
        rogues = detect_rogue_aps(known_ssids)
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    if not rogues:
        console.print("[green]No rogue access points detected.[/green]")
        return

    table = Table(title="[red]Rogue Access Points Detected[/red]")
    table.add_column("SSID", style="red bold")
    table.add_column("BSSID", style="red")
    table.add_column("Signal", justify="right")
    table.add_column("Channel", justify="right")
    table.add_column("Security")

    for net in rogues:
        table.add_row(
            net.ssid,
            net.bssid,
            f"{net.signal_dbm} dBm",
            str(net.channel),
            net.security,
        )

    console.print(table)
    console.print(
        f"[red bold]WARNING:[/red bold] {len(rogues)} potential rogue AP(s) found!"
    )
