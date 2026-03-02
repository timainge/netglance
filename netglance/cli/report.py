"""Report CLI subcommands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from netglance.cli._shared import maybe_warn_db_size
from netglance.modules.report import (
    CheckStatus,
    _svg_sparkline,
    format_report_markdown,
    generate_html_report,
    generate_report,
    report_to_dict,
)

app = typer.Typer(help="Aggregate network health report.", invoke_without_command=True)
console = Console()


_STATUS_STYLE: dict[str, str] = {
    "pass": "[green]PASS[/green]",
    "warn": "[yellow]WARN[/yellow]",
    "fail": "[red]FAIL[/red]",
    "error": "[red bold]ERROR[/red bold]",
    "skip": "[dim]SKIP[/dim]",
}

_STATUS_ICON: dict[str, str] = {
    "pass": "[green]\u2714[/green]",
    "warn": "[yellow]\u26a0[/yellow]",
    "fail": "[red]\u2718[/red]",
    "error": "[red bold]\u2718[/red bold]",
    "skip": "[dim]\u2014[/dim]",
}


def _render_check(check: CheckStatus) -> Panel:
    """Render a single check result as a Rich Panel."""
    icon = _STATUS_ICON.get(check.status, "?")
    status_label = _STATUS_STYLE.get(check.status, check.status)
    title = f"{icon}  {check.module} - {status_label}"

    body_lines = [check.summary]
    if check.details:
        body_lines.append("")
        for detail in check.details:
            body_lines.append(f"  {detail}")

    body = "\n".join(body_lines)

    border_color = {
        "pass": "green",
        "warn": "yellow",
        "fail": "red",
        "error": "red",
        "skip": "dim",
    }.get(check.status, "white")

    return Panel(body, title=title, border_style=border_color)


@app.callback(invoke_without_command=True)
def report_cmd(
    ctx: typer.Context,
    modules: Optional[str] = typer.Option(
        None,
        "--modules",
        "-m",
        help="Comma-separated list of modules to check (e.g. discover,dns,tls).",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Save report as markdown to this file path.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output report as JSON.",
    ),
    subnet: str = typer.Option(
        "192.168.1.0/24",
        "--subnet",
        "-s",
        help="Network subnet for discovery.",
    ),
    html: bool = typer.Option(False, "--html", help="Generate HTML report."),
    html_output: Optional[Path] = typer.Option(
        None, "--html-output", help="Save HTML report to file."
    ),
    include_trending: bool = typer.Option(
        False, "--include-trending", help="Include metric sparklines."
    ),
    include_alerts: bool = typer.Option(
        False, "--include-alerts", help="Include recent alert history."
    ),
    db: Optional[str] = typer.Option(None, "--db", hidden=True),
) -> None:
    """Run all health checks and display an aggregate report."""
    if ctx.invoked_subcommand is not None:
        return

    # Parse modules filter
    module_list: list[str] | None = None
    if modules is not None:
        module_list = [m.strip() for m in modules.split(",") if m.strip()]

    # Allow test injection via context
    checks_override = None
    store_override = None
    if ctx.obj and isinstance(ctx.obj, dict):
        checks_override = ctx.obj.get("_checks")
        store_override = ctx.obj.get("_store")

    # Build store if needed (html with trending/alerts, or explicit --db)
    store = store_override
    if store is None and (html and (include_trending or include_alerts)):
        from netglance.store.db import Store

        store = Store(db) if db else Store()
        store.init_db()
    elif store is None and db:
        from netglance.store.db import Store

        store = Store(db)
        store.init_db()

    report = generate_report(
        modules=module_list,
        subnet=subnet,
        _checks=checks_override,
        _store=store,
    )

    if store is not None:
        maybe_warn_db_size(store, console)

    if json_output:
        console.print(json.dumps(report_to_dict(report), indent=2))
        return

    # HTML report path
    if html:
        metric_sparklines: dict[str, str] | None = None
        alert_log: list[dict] | None = None

        if include_trending and store is not None:
            from datetime import datetime, timedelta, timezone

            since = datetime.now(timezone.utc) - timedelta(hours=24)
            metric_names = store.list_metrics()
            metric_sparklines = {}
            for metric_name in metric_names:
                series = store.get_metric_series(metric_name, since=since, limit=200)
                if series:
                    values = [s["value"] for s in series]
                    metric_sparklines[metric_name] = _svg_sparkline(values)

        if include_alerts and store is not None:
            from netglance.modules.alerts import get_alert_log

            alert_log = get_alert_log(store, limit=20)

        html_content = generate_html_report(
            report,
            metric_sparklines=metric_sparklines,
            alert_log=alert_log,
        )

        if html_output is not None:
            html_output.write_text(html_content)
            console.print(f"[dim]HTML report saved to {html_output}[/dim]")
        else:
            print(html_content)
        return

    # Rich output: overall status banner
    overall_label = _STATUS_STYLE.get(report.overall_status, report.overall_status)
    overall_icon = _STATUS_ICON.get(report.overall_status, "?")
    console.print()
    console.print(
        Panel(
            f"{overall_icon}  Overall: {overall_label}",
            title="Network Health Report",
            border_style="bold",
        )
    )
    console.print()

    # Rich output: per-module panels
    for check in report.checks:
        console.print(_render_check(check))

    # Save markdown if requested
    if output is not None:
        md = format_report_markdown(report)
        output.write_text(md)
        console.print(f"\n[dim]Report saved to {output}[/dim]")
