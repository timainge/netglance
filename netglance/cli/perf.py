"""Perf CLI subcommands — network performance assessment."""

from __future__ import annotations

import json as _json_mod
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from netglance.modules.perf import (
    detect_bufferbloat,
    discover_path_mtu,
    measure_jitter,
    run_performance_test,
)

app = typer.Typer(help="Network performance assessment (jitter, MTU, bufferbloat).")
console = Console()


_BLOAT_COLOR = {"none": "green", "mild": "yellow", "severe": "red"}


def _bloat_label(rating: str) -> str:
    color = _BLOAT_COLOR.get(rating, "white")
    return f"[{color}]{rating.upper()}[/{color}]"


def _fmt_ms(v: float | None) -> str:
    if v is None:
        return "--"
    return f"{v:.1f} ms"


def _print_full_result(result) -> None:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Key", style="bold dim")
    table.add_column("Value")

    table.add_row("Target", result.target)
    table.add_row("Avg Latency", _fmt_ms(result.avg_latency_ms))
    table.add_row("Jitter", _fmt_ms(result.jitter_ms))
    table.add_row("P95 Latency", _fmt_ms(result.p95_latency_ms))
    table.add_row("P99 Latency", _fmt_ms(result.p99_latency_ms))
    table.add_row("Packet Loss", f"{result.packet_loss_pct:.1f}%")

    if result.path_mtu is not None:
        table.add_row("Path MTU", f"{result.path_mtu} bytes")

    if result.bufferbloat_rating is not None:
        table.add_row("Bufferbloat", _bloat_label(result.bufferbloat_rating))

    if result.idle_latency_ms is not None:
        table.add_row("  Idle Latency", _fmt_ms(result.idle_latency_ms))
    if result.loaded_latency_ms is not None:
        table.add_row("  Loaded Latency", _fmt_ms(result.loaded_latency_ms))

    console.print(Panel(table, title="[bold]Network Performance[/bold]", border_style="blue"))


@app.command()
def run(
    host: Optional[str] = typer.Argument(None, help="Target host (default: 1.1.1.1)."),
    jitter_only: bool = typer.Option(False, "--jitter-only", help="Jitter measurement only."),
    mtu: bool = typer.Option(False, "--mtu", help="Path MTU discovery only."),
    bufferbloat: bool = typer.Option(False, "--bufferbloat", help="Bufferbloat detection only."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
    count: int = typer.Option(50, "--count", "-c", help="Ping count for jitter measurement."),
) -> None:
    """Full network performance test, or specific sub-test."""
    target = host or "1.1.1.1"

    if jitter_only:
        if not json:
            console.print(f"[dim]Measuring jitter to {target} ({count} pings)…[/dim]")
        jitter, p95, p99 = measure_jitter(target, count=count)
        if json:
            console.print(_json_mod.dumps({"jitter_ms": jitter, "p95_ms": p95, "p99_ms": p99}))
        else:
            table = Table(show_header=False, box=None, padding=(0, 1))
            table.add_column("Key", style="bold dim")
            table.add_column("Value")
            table.add_row("Jitter", _fmt_ms(jitter))
            table.add_row("P95 Latency", _fmt_ms(p95))
            table.add_row("P99 Latency", _fmt_ms(p99))
            console.print(Panel(table, title="[bold]Jitter Results[/bold]", border_style="cyan"))
        return

    if mtu:
        if not json:
            console.print(f"[dim]Discovering path MTU to {target}…[/dim]")
        path_mtu = discover_path_mtu(target)
        if json:
            console.print(_json_mod.dumps({"path_mtu": path_mtu}))
        else:
            console.print(Panel(f"Path MTU: [bold]{path_mtu}[/bold] bytes", title="MTU Discovery", border_style="cyan"))
        return

    if bufferbloat:
        if not json:
            console.print(f"[dim]Detecting bufferbloat to {target}…[/dim]")
        rating, idle_ms, loaded_ms = detect_bufferbloat(target)
        if json:
            console.print(_json_mod.dumps({
                "bufferbloat_rating": rating,
                "idle_latency_ms": idle_ms,
                "loaded_latency_ms": loaded_ms,
            }))
        else:
            color = _BLOAT_COLOR.get(rating, "white")
            table = Table(show_header=False, box=None, padding=(0, 1))
            table.add_column("Key", style="bold dim")
            table.add_column("Value")
            table.add_row("Rating", _bloat_label(rating))
            table.add_row("Idle Latency", _fmt_ms(idle_ms))
            table.add_row("Loaded Latency", _fmt_ms(loaded_ms))
            console.print(Panel(table, title="[bold]Bufferbloat Detection[/bold]", border_style=color))
        return

    # Full test
    if not json:
        console.print(f"[dim]Running full performance test to {target}…[/dim]")
    result = run_performance_test(target)

    if json:
        import dataclasses

        def _serialise(v):
            if hasattr(v, "isoformat"):
                return v.isoformat()
            return v

        data = {k: _serialise(v) for k, v in dataclasses.asdict(result).items()}
        console.print(_json_mod.dumps(data))
    else:
        _print_full_result(result)
