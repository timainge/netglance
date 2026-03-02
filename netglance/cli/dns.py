"""DNS CLI subcommands."""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from netglance.modules.dns import (
    DEFAULT_RESOLVERS,
    DnsHealthReport,
    benchmark_resolvers,
    check_consistency,
    detect_dns_hijack,
    query_resolver,
)
from netglance.store.db import Store
from netglance.store.models import DnsResolverResult

app = typer.Typer(help="DNS health & leak detection.")
console = Console()


def _build_resolvers(extra: list[str] | None = None) -> dict[str, str]:
    resolvers = dict(DEFAULT_RESOLVERS)
    for ip in extra or []:
        resolvers.setdefault(ip, ip)
    return resolvers


def _render_resolve_table(results: list[DnsResolverResult]) -> Table:
    table = Table(title="DNS Resolution Results")
    table.add_column("Resolver", style="cyan")
    table.add_column("Name", style="blue")
    table.add_column("Answers")
    table.add_column("Time (ms)", justify="right")
    table.add_column("Error", style="red")
    for r in results:
        table.add_row(
            r.resolver,
            r.resolver_name,
            ", ".join(r.answers) if r.answers else "-",
            f"{r.response_time_ms:.1f}" if r.error is None else "-",
            r.error or "",
        )
    return table


@app.command("check")
def dns_check(
    domain: str = typer.Argument("example.com", help="Domain to check."),
    resolver: Optional[list[str]] = typer.Option(
        None, "--resolver", "-r", help="Extra resolver IP."
    ),
    save: bool = typer.Option(False, "--save/--no-save", help="Save result to local DB."),
) -> None:
    """Run all DNS health checks for a domain."""
    resolvers = _build_resolvers(resolver)
    report: DnsHealthReport = check_consistency(domain, resolvers=resolvers)

    status = "[green]CONSISTENT[/green]" if report.consistent else "[red]INCONSISTENT[/red]"
    hijack = "[red]YES[/red]" if report.potential_hijack else "[green]No[/green]"
    dnssec = "[green]Yes[/green]" if report.dnssec_supported else "[yellow]No[/yellow]"

    console.print()
    console.print(f"[bold]DNS Health Check:[/bold] {domain}")
    console.print(f"  Resolvers checked : {report.resolvers_checked}")
    console.print(f"  Consistency       : {status}")
    console.print(f"  Fastest resolver  : {report.fastest_resolver or 'N/A'}")
    console.print(f"  DNSSEC supported  : {dnssec}")
    console.print(f"  Potential hijack  : {hijack}")
    console.print()

    console.print(_render_resolve_table(report.details))

    if save:
        try:
            store = Store()
            store.init_db()
            store.save_result("dns", {
                "consistent": report.consistent,
                "resolvers_checked": report.resolvers_checked,
                "fastest_resolver": report.fastest_resolver,
                "dnssec_supported": report.dnssec_supported,
                "potential_hijack": report.potential_hijack,
            })
            console.print("[dim]✓ Saved to local database.[/dim]")
        except Exception as exc:
            console.print(f"[dim yellow]Warning: could not save result: {exc}[/dim yellow]")


@app.command("resolve")
def dns_resolve(
    domain: str = typer.Argument(..., help="Domain to resolve."),
    resolver: Optional[list[str]] = typer.Option(
        None, "--resolver", "-r", help="Extra resolver IP."
    ),
) -> None:
    """Resolve a domain across multiple resolvers."""
    resolvers = _build_resolvers(resolver)
    results = [
        query_resolver(ip, domain, resolver_name=name) for ip, name in resolvers.items()
    ]
    console.print(_render_resolve_table(results))


@app.command("benchmark")
def dns_benchmark(
    resolver: Optional[list[str]] = typer.Option(
        None, "--resolver", "-r", help="Extra resolver IP."
    ),
) -> None:
    """Benchmark resolver response times."""
    resolvers = _build_resolvers(resolver)
    results = benchmark_resolvers(resolvers=resolvers)

    table = Table(title="DNS Resolver Benchmark")
    table.add_column("Resolver", style="cyan")
    table.add_column("Name", style="blue")
    table.add_column("Domain")
    table.add_column("Time (ms)", justify="right")
    table.add_column("Error", style="red")
    for r in results:
        style = "green" if r.error is None else "red"
        table.add_row(
            r.resolver,
            r.resolver_name,
            r.query,
            f"{r.response_time_ms:.1f}" if r.error is None else "-",
            r.error or "",
            style=style,
        )
    console.print(table)

    # Per-resolver averages
    totals: dict[str, list[float]] = defaultdict(list)
    for r in results:
        if r.error is None:
            totals[f"{r.resolver_name} ({r.resolver})"].append(r.response_time_ms)

    if totals:
        console.print()
        console.print("[bold]Average response times:[/bold]")
        for label, times in sorted(totals.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
            avg = sum(times) / len(times)
            console.print(f"  {label}: {avg:.1f} ms")


@app.command("hijack")
def dns_hijack(
    resolver: Optional[list[str]] = typer.Option(
        None, "--resolver", "-r", help="Extra resolver IP."
    ),
) -> None:
    """Check for DNS hijacking."""
    resolvers = _build_resolvers(resolver)
    result = detect_dns_hijack(resolvers=resolvers)

    if result["hijack_detected"]:
        console.print("[bold red]WARNING: Potential DNS hijacking detected![/bold red]")
    else:
        console.print("[bold green]No DNS hijacking detected.[/bold green]")

    table = Table(title="DNS Hijack Detection")
    table.add_column("Resolver", style="cyan")
    table.add_column("Name", style="blue")
    table.add_column("Answers")
    table.add_column("Status")
    for r in result["details"]:
        if r.answers:
            status_str = "[red]HIJACKED[/red]"
        elif r.error == "NXDOMAIN":
            status_str = "[green]OK[/green]"
        else:
            status_str = f"[yellow]{r.error}[/yellow]"
        table.add_row(
            r.resolver,
            r.resolver_name,
            ", ".join(r.answers) if r.answers else "-",
            status_str,
        )
    console.print(table)
