"""Firewall CLI subcommands."""

from __future__ import annotations

import json as json_mod
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from netglance.modules.firewall import (
    COMMON_EGRESS_PORTS,
    run_firewall_audit,
    test_egress_port,
    test_ingress_port,
)
from netglance.store.models import FirewallAuditReport, FirewallTestResult

app = typer.Typer(help="Firewall egress and ingress port checks.", no_args_is_help=True)
console = Console()


def _status_color(status: str) -> str:
    if status == "open":
        return "green"
    if status == "blocked":
        return "red"
    return "yellow"


def _format_latency(ms: float | None) -> str:
    if ms is None:
        return "--"
    return f"{ms:.1f} ms"


def _results_table(results: list[FirewallTestResult], title: str) -> Table:
    table = Table(title=title, show_lines=False)
    table.add_column("Port", justify="right", style="bold")
    table.add_column("Protocol")
    table.add_column("Status")
    table.add_column("Latency", justify="right")
    table.add_column("Target")

    for r in results:
        color = _status_color(r.status)
        table.add_row(
            str(r.port),
            r.protocol.upper(),
            f"[{color}]{r.status.upper()}[/{color}]",
            _format_latency(r.latency_ms),
            r.target or "--",
        )
    return table


def _print_audit_report(report: FirewallAuditReport) -> None:
    if report.egress_results:
        console.print(_results_table(report.egress_results, "Egress Port Results"))

    if report.ingress_results:
        console.print(_results_table(report.ingress_results, "Ingress Port Results"))

    open_count = sum(1 for r in report.egress_results if r.status == "open")
    blocked_count = len(report.blocked_egress_ports)

    summary_lines = [
        f"Egress open: [green]{open_count}[/green]  Blocked: [red]{blocked_count}[/red]",
    ]
    if report.open_ingress_ports:
        summary_lines.append(
            f"Open ingress ports: [yellow]{', '.join(str(p) for p in report.open_ingress_ports)}[/yellow]"
        )
    if report.recommendations:
        summary_lines.append("")
        summary_lines.append("[bold]Recommendations:[/bold]")
        for rec in report.recommendations:
            summary_lines.append(f"  • {rec}")

    console.print(Panel("\n".join(summary_lines), title="Firewall Audit Summary", expand=False))


@app.command("audit")
def audit_cmd(
    output_json: bool = typer.Option(False, "--json", help="Output results as JSON."),
) -> None:
    """Full egress and ingress firewall assessment."""
    report = run_firewall_audit()
    if output_json:
        import dataclasses
        console.print_json(json_mod.dumps(dataclasses.asdict(report), default=str))
    else:
        _print_audit_report(report)


@app.command("egress")
def egress_cmd(
    port: Optional[int] = typer.Option(None, "--port", "-p", help="Specific port to test."),
    output_json: bool = typer.Option(False, "--json", help="Output results as JSON."),
) -> None:
    """Test outbound (egress) port reachability."""
    if port is not None:
        results = [test_egress_port(port)]
    else:
        from netglance.modules.firewall import test_egress_common
        results = test_egress_common()

    if output_json:
        import dataclasses
        console.print_json(json_mod.dumps([dataclasses.asdict(r) for r in results], default=str))
    else:
        console.print(_results_table(results, "Egress Port Results"))
        open_count = sum(1 for r in results if r.status == "open")
        blocked_count = sum(1 for r in results if r.status == "blocked")
        console.print(
            Panel(
                f"Open: [green]{open_count}[/green]  Blocked: [red]{blocked_count}[/red]",
                title="Egress Summary",
                expand=False,
            )
        )


@app.command("ingress")
def ingress_cmd(
    port: int = typer.Option(..., "--port", "-p", help="Port to test for inbound reachability."),
    protocol: str = typer.Option("tcp", "--protocol", help="Protocol (tcp/udp)."),
    output_json: bool = typer.Option(False, "--json", help="Output results as JSON."),
) -> None:
    """Test inbound (ingress) port reachability from the internet."""
    result = test_ingress_port(port, protocol=protocol)

    if output_json:
        import dataclasses
        console.print_json(json_mod.dumps(dataclasses.asdict(result), default=str))
    else:
        console.print(_results_table([result], "Ingress Port Result"))
        if result.status == "unknown":
            console.print(
                Panel(
                    "No external probe service available. Cannot verify inbound reachability.",
                    title="Note",
                    expand=False,
                )
            )
