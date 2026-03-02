"""CLI subcommands for daemon management."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from netglance.config.settings import DEFAULTS, Settings
from netglance.daemon.launchd import (
    get_plist_path,
    install_plist,
    is_installed,
    uninstall_plist,
)
from netglance.daemon.scheduler import Scheduler, ScheduledTask

app = typer.Typer(help="Background daemon management.", no_args_is_help=True)
console = Console()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task callbacks -- thin wrappers that the scheduler invokes
# ---------------------------------------------------------------------------


def _make_discover_callback(subnet: str, interface: str | None = None):
    """Return a callback that runs device discovery and saves results."""

    def _run() -> None:
        from netglance.modules.discover import devices_to_dicts, discover_all
        from netglance.store.db import Store

        devices = discover_all(subnet, interface)
        store = Store()
        store.init_db()
        store.save_result("discover", {"devices": devices_to_dicts(devices)})
        store.close()

    return _run


def _make_dns_callback():
    """Return a callback that runs DNS consistency checks."""

    def _run() -> None:
        from netglance.modules.dns import check_consistency
        from netglance.store.db import Store

        report = check_consistency("example.com")
        store = Store()
        store.init_db()
        store.save_result("dns_check", {"consistent": report.consistent})
        store.close()

    return _run


def _make_tls_callback():
    """Return a callback that runs TLS verification."""

    def _run() -> None:
        from netglance.modules.tls import check_multiple
        from netglance.store.db import Store

        results = check_multiple()
        store = Store()
        store.init_db()
        store.save_result(
            "tls_verify",
            {
                "hosts_checked": len(results),
                "all_trusted": all(r.is_trusted for r in results),
            },
        )
        store.close()

    return _run


def _make_baseline_callback(subnet: str, interface: str | None = None):
    """Return a callback that captures a network baseline."""

    def _run() -> None:
        from netglance.modules.baseline import baseline_to_dict, capture_baseline
        from netglance.store.db import Store

        baseline = capture_baseline(subnet, interface, label="daemon")
        store = Store()
        store.init_db()
        store.save_baseline(baseline_to_dict(baseline), label="daemon-auto")
        store.close()

    return _run


def _make_report_callback(subnet: str):
    """Return a callback that generates a health report."""

    def _run() -> None:
        from netglance.modules.report import generate_report, report_to_dict
        from netglance.store.db import Store

        report = generate_report(subnet=subnet)
        store = Store()
        store.init_db()
        store.save_result("report", report_to_dict(report))
        store.close()

    return _run


def _make_uptime_callback(hosts: list[str], timeout: float = 2.0):
    """Return a callback that checks uptime for configured hosts."""

    def _run() -> None:
        from netglance.modules.uptime import check_host, save_uptime_record
        from netglance.store.db import Store

        store = Store()
        store.init_db()
        for host in hosts:
            record = check_host(host, timeout=timeout)
            save_uptime_record(record, store)
        store.close()

    return _run


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


@app.command()
def start(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config YAML."
    ),
) -> None:
    """Start the scheduler in the foreground (for manual use or testing)."""
    settings = Settings.load(config)
    schedules: dict[str, str] = DEFAULTS["daemon"]["schedules"]

    # If the user has a config file, try to load daemon.schedules from it
    if config and config.exists():
        import yaml

        with open(config) as f:
            data = yaml.safe_load(f) or {}
        user_sched = data.get("daemon", {}).get("schedules", {})
        if user_sched:
            schedules = {**schedules, **user_sched}

    subnet = settings.network.subnet
    interface = settings.network.interface

    scheduler = Scheduler()

    # Map config keys to callbacks.  Wrap each in RuntimeError handling
    # so platform-specific modules (e.g. wifi on Linux) don't crash the daemon.
    # Get uptime hosts from config data
    if config and config.exists():
        uptime_hosts = data.get("daemon", {}).get("uptime_hosts", ["8.8.8.8", "1.1.1.1"])
    else:
        uptime_hosts = ["8.8.8.8", "1.1.1.1"]

    task_map: dict[str, callable] = {
        "discover": _make_discover_callback(subnet, interface),
        "dns_check": _make_dns_callback(),
        "tls_verify": _make_tls_callback(),
        "baseline_diff": _make_baseline_callback(subnet, interface),
        "report": _make_report_callback(subnet),
        "uptime_check": _make_uptime_callback(uptime_hosts),
    }

    for name, cron_expr in schedules.items():
        cb = task_map.get(name)
        if cb is None:
            logger.warning("Unknown schedule task: %s", name)
            continue
        scheduler.add_task(ScheduledTask(name=name, cron_expr=cron_expr, callback=cb))

    console.print("[bold green]netglance daemon starting[/bold green]")
    table = Table(title="Scheduled Tasks")
    table.add_column("Task", style="cyan")
    table.add_column("Schedule")
    for name, cron_expr in schedules.items():
        if name in task_map:
            table.add_row(name, cron_expr)
    console.print(table)
    console.print("[dim]Press Ctrl+C to stop.[/dim]")

    try:
        scheduler.start(blocking=True)
    except KeyboardInterrupt:
        scheduler.stop()
        console.print("\n[yellow]Daemon stopped.[/yellow]")


@app.command()
def install(
    netglance_path: Optional[str] = typer.Option(
        None, "--netglance-path", help="Override path to netglance executable."
    ),
    config: Optional[str] = typer.Option(
        None, "--config", "-c", help="Path to config YAML for the daemon."
    ),
) -> None:
    """Install the launchd plist for auto-start on macOS."""
    path = install_plist(netglance_path=netglance_path, config_path=config)
    console.print(f"[green]Plist installed:[/green] {path}")
    console.print("[dim]Load with: launchctl load {path}[/dim]")


@app.command()
def uninstall() -> None:
    """Remove the launchd plist."""
    removed = uninstall_plist()
    if removed:
        console.print("[green]Plist removed.[/green]")
        console.print("[dim]Unload with: launchctl unload <path>[/dim]")
    else:
        console.print("[yellow]Plist not found (not installed).[/yellow]")


@app.command()
def status() -> None:
    """Show daemon installation and schedule status."""
    installed = is_installed()
    plist_path = get_plist_path()

    if installed:
        console.print(f"[green]Plist installed:[/green] {plist_path}")
    else:
        console.print("[yellow]Plist not installed.[/yellow]")

    console.print()
    schedules = DEFAULTS["daemon"]["schedules"]
    table = Table(title="Configured Schedules")
    table.add_column("Task", style="cyan")
    table.add_column("Cron Expression")
    for name, cron_expr in schedules.items():
        table.add_row(name, cron_expr)
    console.print(table)
