"""Main CLI entry point for netglance."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from netglance import __version__

app = typer.Typer(
    name="netglance",
    help="Home network health checks — run by you or your AI.",
    no_args_is_help=True,
)
console = Console()


def version_callback(value: bool) -> None:
    if value:
        console.print(f"netglance {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-V", callback=version_callback, is_eager=True, help="Show version."
    ),
) -> None:
    """netglance - Home network health checks, run by you or your AI."""


# Register all subcommand groups
from netglance.cli.arp import app as arp_app
from netglance.cli.baseline import app as baseline_app
from netglance.cli.discover import app as discover_app
from netglance.cli.dns import app as dns_app
from netglance.cli.http import app as http_app
from netglance.cli.ping import app as ping_app
from netglance.cli.route import app as route_app
from netglance.cli.scan import app as scan_app
from netglance.cli.speed import app as speed_app
from netglance.cli.tls import app as tls_app
from netglance.cli.traffic import app as traffic_app
from netglance.cli.daemon import app as daemon_app
from netglance.cli.dhcp import app as dhcp_app
from netglance.cli.export import app as export_app
from netglance.cli.firewall import app as firewall_app
from netglance.cli.ipv6 import app as ipv6_app
from netglance.cli.report import app as report_app
from netglance.cli.perf import app as perf_app
from netglance.cli.uptime import app as uptime_app
from netglance.cli.wifi import app as wifi_app
from netglance.cli.vpn import app as vpn_app
from netglance.cli.alerts import app as alerts_app
from netglance.cli.wol import app as wol_app
from netglance.cli.fingerprint import app as fingerprint_app
from netglance.cli.metrics import app as metrics_app
from netglance.cli.mcp import app as mcp_app
from netglance.cli.api import app as api_app
from netglance.cli.topology import app as topo_app
from netglance.cli.iot import app as iot_app
from netglance.cli.db import app as db_app
from netglance.cli.plugin import app as plugin_app

app.add_typer(ping_app, name="ping")
app.add_typer(speed_app, name="speed")
app.add_typer(baseline_app, name="baseline")
app.add_typer(discover_app, name="discover")
app.add_typer(traffic_app, name="traffic")
app.add_typer(http_app, name="http")
app.add_typer(scan_app, name="scan")
app.add_typer(arp_app, name="arp")
app.add_typer(dns_app, name="dns")
app.add_typer(wifi_app, name="wifi")
app.add_typer(route_app, name="route")
app.add_typer(tls_app, name="tls")
app.add_typer(report_app, name="report")
app.add_typer(uptime_app, name="uptime")
app.add_typer(daemon_app, name="daemon")
app.add_typer(dhcp_app, name="dhcp")
app.add_typer(export_app, name="export")
app.add_typer(firewall_app, name="firewall")
app.add_typer(ipv6_app, name="ipv6")
app.add_typer(perf_app, name="perf")
app.add_typer(vpn_app, name="vpn")
app.add_typer(wol_app, name="wol")
app.add_typer(alerts_app, name="alert")
app.add_typer(fingerprint_app, name="identify")
app.add_typer(metrics_app, name="metrics")
app.add_typer(mcp_app, name="mcp")
app.add_typer(api_app, name="api")
app.add_typer(topo_app, name="topo")
app.add_typer(iot_app, name="iot")
app.add_typer(db_app, name="db")
app.add_typer(plugin_app, name="plugin")
