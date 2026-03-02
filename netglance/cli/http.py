"""HTTP CLI subcommands."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from netglance.modules.http import (
    PROXY_HEADERS,
    HttpProbeResult,
    check_for_proxies,
    probe_url,
)

app = typer.Typer(help="HTTP header inspection & proxy detection.", no_args_is_help=True)
console = Console()


def _http_results_table(
    results: list[HttpProbeResult], title: str = "HTTP Probe Results"
) -> Table:
    table = Table(title=title, show_lines=True)
    table.add_column("URL", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Proxy?", justify="center")
    table.add_column("Suspicious Headers")
    table.add_column("Details")

    for r in results:
        proxy_label = "[red]YES[/red]" if r.proxy_detected else "[green]NO[/green]"
        status_color = "green" if 200 <= r.status_code < 400 else "red"

        header_parts: list[str] = []
        for name, value in r.suspicious_headers.items():
            header_parts.append(f"[red]{name}[/red]: {value}")
        headers_text = "\n".join(header_parts) if header_parts else "[dim]none[/dim]"
        details_text = "\n".join(r.details) if r.details else "[dim]clean[/dim]"

        table.add_row(
            r.url,
            f"[{status_color}]{r.status_code}[/{status_color}]",
            proxy_label,
            headers_text,
            details_text,
        )
    return table


def _headers_table(url: str, headers: dict[str, str]) -> Table:
    table = Table(title=f"Response Headers: {url}", show_lines=False)
    table.add_column("Header", style="bold")
    table.add_column("Value")

    proxy_set = {h.lower() for h in PROXY_HEADERS}
    for name, value in headers.items():
        if name.lower() in proxy_set:
            table.add_row(f"[red]{name}[/red]", value)
        else:
            table.add_row(name, value)
    return table


@app.command("check")
def http_check_cmd(
    url: Optional[str] = typer.Argument(None, help="URL to check (checks defaults if omitted)."),
    timeout: float = typer.Option(5.0, "--timeout", "-t", help="Request timeout in seconds."),
) -> None:
    """Check URLs for transparent proxies and header anomalies."""
    if url:
        results = [probe_url(url, timeout=timeout)]
    else:
        results = check_for_proxies(timeout=timeout)
    console.print(_http_results_table(results))


@app.command("headers")
def http_headers_cmd(
    url: str = typer.Argument(..., help="URL to inspect."),
    timeout: float = typer.Option(5.0, "--timeout", "-t", help="Request timeout in seconds."),
) -> None:
    """Display all response headers for a URL."""
    from netglance.modules.http import _httpx_get

    resp = _httpx_get(url, timeout)
    console.print(_headers_table(url, dict(resp.headers)))
