"""Speed test CLI subcommands."""

from __future__ import annotations

import json as json_lib
from datetime import datetime, timedelta
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from netglance.cli._shared import maybe_warn_db_size
from netglance.modules.speed import run_speedtest, run_speedtest_iperf3, run_speedtest_ookla
from netglance.store.db import Store
from netglance.store.models import SpeedTestResult

app = typer.Typer(help="Internet and LAN speed testing.", no_args_is_help=False)
console = Console()


def _speed_color(mbps: float) -> str:
    """Return a rich color name based on speed thresholds."""
    if mbps >= 100:
        return "green"
    if mbps >= 25:
        return "yellow"
    return "red"


def _latency_color(ms: float) -> str:
    """Return a rich color name based on latency thresholds."""
    if ms < 20:
        return "green"
    if ms < 100:
        return "yellow"
    return "red"


def _fmt_mbps(mbps: float) -> str:
    return f"{mbps:.1f} Mbps"


def _fmt_ms(ms: float | None) -> str:
    if ms is None:
        return "--"
    return f"{ms:.1f} ms"


def _fmt_bytes(b: int) -> str:
    if b >= 1_000_000_000:
        return f"{b / 1_000_000_000:.2f} GB"
    if b >= 1_000_000:
        return f"{b / 1_000_000:.1f} MB"
    if b >= 1_000:
        return f"{b / 1_000:.1f} KB"
    return f"{b} B"


def _result_to_dict(r: SpeedTestResult) -> dict:
    return {
        "download_mbps": r.download_mbps,
        "upload_mbps": r.upload_mbps,
        "latency_ms": r.latency_ms,
        "jitter_ms": r.jitter_ms,
        "server": r.server,
        "server_location": r.server_location,
        "provider": r.provider,
        "download_bytes": r.download_bytes,
        "upload_bytes": r.upload_bytes,
        "timestamp": r.timestamp.isoformat(),
    }


def _print_result(result: SpeedTestResult, as_json: bool = False) -> None:
    """Print a SpeedTestResult either as JSON or a rich table."""
    if as_json:
        console.print_json(json_lib.dumps(_result_to_dict(result)))
        return

    dl_color = _speed_color(result.download_mbps)
    ul_color = _speed_color(result.upload_mbps)
    lat_color = _latency_color(result.latency_ms)

    table = Table(title="Speed Test Results", show_lines=False, expand=False)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_column("Detail", style="dim", justify="right")

    table.add_row(
        "Download",
        f"[{dl_color}]{_fmt_mbps(result.download_mbps)}[/{dl_color}]",
        _fmt_bytes(result.download_bytes),
    )
    table.add_row(
        "Upload",
        f"[{ul_color}]{_fmt_mbps(result.upload_mbps)}[/{ul_color}]",
        _fmt_bytes(result.upload_bytes),
    )
    table.add_row(
        "Latency",
        f"[{lat_color}]{_fmt_ms(result.latency_ms)}[/{lat_color}]",
        "",
    )
    if result.jitter_ms is not None:
        table.add_row("Jitter", _fmt_ms(result.jitter_ms), "")

    server_label = result.server
    if result.server_location:
        server_label = f"{result.server} ({result.server_location})"

    table.add_row("Server", server_label, "")
    table.add_row("Provider", result.provider, "")
    table.add_row("Tested at", result.timestamp.strftime("%Y-%m-%d %H:%M:%S"), "")

    console.print(table)


@app.callback(invoke_without_command=True)
def speed_cmd(
    ctx: typer.Context,
    download_only: bool = typer.Option(False, "--download-only", help="Run download test only."),
    upload_only: bool = typer.Option(False, "--upload-only", help="Run upload test only."),
    provider: str = typer.Option("cloudflare", "--provider", "-p", help="Provider: cloudflare | ookla | iperf3."),
    server: Optional[str] = typer.Option(None, "--server", "-s", help="Override server (required for iperf3)."),
    duration: float = typer.Option(10.0, "--duration", "-d", help="Test duration in seconds (Cloudflare/iperf3)."),
    output_json: bool = typer.Option(False, "--json", help="Output results as JSON."),
    save: bool = typer.Option(True, "--save/--no-save", help="Save result to local DB."),
) -> None:
    """Run an internet speed test.

    Defaults to Cloudflare's speed test infrastructure. Use --provider ookla
    for Ookla (requires speedtest CLI) or --provider iperf3 for LAN testing.
    """
    if ctx.invoked_subcommand is not None:
        return

    try:
        if provider == "ookla":
            if not output_json:
                console.print("[dim]Running Ookla speed test…[/dim]")
            result = run_speedtest_ookla()

        elif provider == "iperf3":
            if server is None:
                console.print("[red]Error:[/red] --server is required for iperf3 provider.")
                raise typer.Exit(code=1)
            if not output_json:
                console.print(f"[dim]Running iperf3 speed test against {server}…[/dim]")
            result = run_speedtest_iperf3(server, duration_s=duration)

        else:
            # Cloudflare (default)
            host = server or "speed.cloudflare.com"
            if download_only:
                if not output_json:
                    console.print(f"[dim]Testing download from {host}…[/dim]")
                from netglance.modules.speed import test_download
                dl_mbps, dl_bytes = test_download(host, duration_s=duration)
                result = SpeedTestResult(
                    download_mbps=dl_mbps,
                    upload_mbps=0.0,
                    latency_ms=0.0,
                    download_bytes=dl_bytes,
                    server=host,
                    provider="cloudflare",
                )
            elif upload_only:
                if not output_json:
                    console.print(f"[dim]Testing upload to {host}…[/dim]")
                from netglance.modules.speed import test_upload
                ul_mbps, ul_bytes = test_upload(host, duration_s=duration)
                result = SpeedTestResult(
                    download_mbps=0.0,
                    upload_mbps=ul_mbps,
                    latency_ms=0.0,
                    upload_bytes=ul_bytes,
                    server=host,
                    provider="cloudflare",
                )
            else:
                if not output_json:
                    console.print(f"[dim]Running full speed test via {host}…[/dim]")
                result = run_speedtest(server=server, provider="cloudflare", duration_s=duration)

    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    _print_result(result, as_json=output_json)

    if save:
        try:
            store = Store()
            store.init_db()
            store.save_result("speed", _result_to_dict(result))
            console.print("[dim]✓ Saved to local database.[/dim]")
            maybe_warn_db_size(store, console)
        except Exception as exc:
            console.print(f"[dim yellow]Warning: could not save result: {exc}[/dim yellow]")


@app.command("history")
def history_cmd(
    days: int = typer.Option(7, "--days", "-d", help="Number of days of history to show."),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum number of results to show."),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show recent speed test results from the local database."""
    since = datetime.now() - timedelta(days=days)

    try:
        store = Store()
        store.init_db()
        rows = store.get_results("speed", limit=limit, since=since)
    except Exception as exc:
        console.print(f"[red]Error:[/red] Could not read history: {exc}")
        raise typer.Exit(code=1)

    if not rows:
        console.print(f"[dim]No speed test results in the last {days} day(s).[/dim]")
        return

    if output_json:
        console.print_json(json_lib.dumps(rows))
        return

    table = Table(title=f"Speed Test History (last {days} days)", show_lines=False)
    table.add_column("Timestamp")
    table.add_column("Download", justify="right")
    table.add_column("Upload", justify="right")
    table.add_column("Latency", justify="right")
    table.add_column("Jitter", justify="right")
    table.add_column("Provider")
    table.add_column("Server")

    for row in rows:
        dl = row.get("download_mbps", 0.0)
        ul = row.get("upload_mbps", 0.0)
        lat = row.get("latency_ms", 0.0)
        jitter = row.get("jitter_ms")
        ts = row.get("timestamp", "")
        # Trim microseconds from timestamp display
        if "T" in ts:
            ts = ts.replace("T", " ").split(".")[0]

        dl_color = _speed_color(dl)
        ul_color = _speed_color(ul)
        lat_color = _latency_color(lat)

        table.add_row(
            ts,
            f"[{dl_color}]{_fmt_mbps(dl)}[/{dl_color}]",
            f"[{ul_color}]{_fmt_mbps(ul)}[/{ul_color}]",
            f"[{lat_color}]{_fmt_ms(lat)}[/{lat_color}]",
            _fmt_ms(jitter),
            row.get("provider", ""),
            row.get("server", ""),
        )

    console.print(table)
