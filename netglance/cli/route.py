"""Route CLI subcommands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from netglance.cli._shared import maybe_warn_db_size
from netglance.modules.route import (
    TraceResult,
    dict_to_trace,
    diff_routes,
    trace_to_dict,
    traceroute,
)
from netglance.store.db import Store

app = typer.Typer(help="Traceroute & path analysis.", no_args_is_help=True)
console = Console()


def _format_rtt(ms: float | None) -> str:
    if ms is None:
        return "* * *"
    return f"{ms:.2f} ms"


def _trace_table(result: TraceResult, title: str | None = None) -> Table:
    table_title = title or f"Traceroute to {result.destination}"
    table = Table(title=table_title, show_lines=False)
    table.add_column("Hop", justify="right", style="dim")
    table.add_column("IP", style="cyan")
    table.add_column("Hostname")
    table.add_column("RTT", justify="right")
    table.add_column("ASN", style="bold")
    table.add_column("AS Name")

    for hop in result.hops:
        ip_str = hop.ip or "* * *"
        hostname_str = hop.hostname or ""
        rtt_str = _format_rtt(hop.rtt_ms)
        asn_str = hop.asn or ""
        as_name_str = hop.as_name or ""

        if hop.ip is None:
            ip_str = "[dim]* * *[/dim]"
            rtt_str = "[dim]* * *[/dim]"

        table.add_row(str(hop.ttl), ip_str, hostname_str, rtt_str, asn_str, as_name_str)

    status = "[green]Reached[/green]" if result.reached else "[red]Not reached[/red]"
    table.caption = f"Destination: {result.destination} | Status: {status}"
    return table


@app.command("trace")
def route_trace_cmd(
    host: str = typer.Argument(..., help="Target hostname or IP address."),
    max_hops: int = typer.Option(30, "--max-hops", "-m", help="Maximum number of hops."),
    timeout: float = typer.Option(2.0, "--timeout", "-t", help="Timeout per probe in seconds."),
    save: bool = typer.Option(False, "--save/--no-save", help="Save result to local DB."),
    diff: bool = typer.Option(False, "--diff", help="Compare against last saved route."),
    db_path: Optional[Path] = typer.Option(None, "--db", hidden=True, help="DB path override."),
) -> None:
    """Run a traceroute with ASN information."""
    result = traceroute(host, max_hops=max_hops, timeout=timeout)

    if save:
        store = Store(db_path=db_path) if db_path else Store()
        store.init_db()
        store.save_result("route", trace_to_dict(result))
        console.print("[dim]✓ Saved to local database.[/dim]")
        maybe_warn_db_size(store, console)
        store.close()

    diff_data: dict | None = None
    if diff:
        store = Store(db_path=db_path) if db_path else Store()
        store.init_db()
        previous_rows = store.get_results("route", limit=1)
        store.close()
        if previous_rows:
            previous = dict_to_trace(previous_rows[0])
            diff_data = diff_routes(result, previous)

    console.print(_trace_table(result))

    if diff_data is not None:
        console.print()
        if diff_data["changed_hops"]:
            diff_table = Table(title="Route Changes")
            diff_table.add_column("Hop", justify="right", style="dim")
            diff_table.add_column("Previous IP", style="red")
            diff_table.add_column("Current IP", style="green")
            for ch in diff_data["changed_hops"]:
                diff_table.add_row(
                    str(ch["ttl"]),
                    ch["old_ip"] or "* * *",
                    ch["new_ip"] or "* * *",
                )
            console.print(diff_table)
        else:
            console.print("[green]No route changes detected.[/green]")

        if diff_data["new_asns"]:
            console.print(
                f"[yellow]New ASNs observed:[/yellow] {', '.join(diff_data['new_asns'])}"
            )

        delta = diff_data["path_length_delta"]
        if delta != 0:
            direction = "longer" if delta > 0 else "shorter"
            console.print(f"Path is {abs(delta)} hop(s) {direction} than previous.")
