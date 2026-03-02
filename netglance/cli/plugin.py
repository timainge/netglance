"""Plugin management CLI subcommands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from netglance.plugins.loader import (
    _default_plugin_dir,
    discover_plugins,
    load_all_plugins,
)
from netglance.store.models import PluginInfo

app = typer.Typer(help="Manage netglance plugins.", no_args_is_help=True)
console = Console()

_PLUGIN_TEMPLATE = '''\
"""Netglance plugin: {name}."""

import typer
from netglance.plugins.base import BasePlugin
from netglance.store.models import CheckStatus


class {class_name}(BasePlugin):
    name = "{name}"
    version = "0.1.0"
    description = "Description of what this plugin does"

    def check(self) -> CheckStatus:
        # Implement your health check here
        return CheckStatus(
            module=self.name,
            status="pass",
            summary="Everything looks good",
        )

    def cli_app(self) -> typer.Typer | None:
        app = typer.Typer(help="My plugin commands.")

        @app.command()
        def status():
            """Show plugin status."""
            print(f"{{self.name}} v{{self.version}} is running")

        return app
'''


def _plugin_dir_path(plugin_dir: Optional[Path] = None) -> Path:
    return plugin_dir or _default_plugin_dir()


def _status_color(status: str) -> str:
    return {
        "pass": "green",
        "warn": "yellow",
        "fail": "red",
        "error": "red",
        "skip": "dim",
    }.get(status, "white")


@app.command("list")
def list_plugins(
    plugin_dir: Optional[Path] = typer.Option(
        None, "--dir", "-d", help="Plugin directory to scan.", hidden=False
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
    db: Optional[Path] = typer.Option(None, "--db", hidden=True),
) -> None:
    """List all discovered plugins."""
    infos = discover_plugins(plugin_dir)

    if json_output:
        data = [
            {
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "author": p.author,
                "module_path": p.module_path,
                "enabled": p.enabled,
                "commands": p.commands,
            }
            for p in infos
        ]
        print(json.dumps(data, indent=2))
        return

    if not infos:
        console.print(
            f"[dim]No plugins found in {_plugin_dir_path(plugin_dir)}[/dim]"
        )
        return

    table = Table(title="Installed Plugins", show_lines=False)
    table.add_column("Name", style="bold cyan")
    table.add_column("Version")
    table.add_column("Description")
    table.add_column("Commands")

    for p in infos:
        cmds = ", ".join(p.commands) if p.commands else "[dim]none[/dim]"
        table.add_row(p.name, p.version, p.description or "[dim]—[/dim]", cmds)

    console.print(table)


@app.command("info")
def plugin_info(
    name: str = typer.Argument(..., help="Plugin name to inspect."),
    plugin_dir: Optional[Path] = typer.Option(None, "--dir", "-d", hidden=False),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
    db: Optional[Path] = typer.Option(None, "--db", hidden=True),
) -> None:
    """Show detailed information about a plugin."""
    infos = discover_plugins(plugin_dir)
    match = next((p for p in infos if p.name == name), None)

    if match is None:
        console.print(f"[red]Plugin '{name}' not found.[/red]")
        raise typer.Exit(code=1)

    if json_output:
        print(
            json.dumps(
                {
                    "name": match.name,
                    "version": match.version,
                    "description": match.description,
                    "author": match.author,
                    "module_path": match.module_path,
                    "enabled": match.enabled,
                    "commands": match.commands,
                },
                indent=2,
            )
        )
        return

    lines = [
        f"[bold]Name:[/bold]        {match.name}",
        f"[bold]Version:[/bold]     {match.version}",
        f"[bold]Description:[/bold] {match.description or '—'}",
        f"[bold]Author:[/bold]      {match.author or '—'}",
        f"[bold]Path:[/bold]        {match.module_path}",
        f"[bold]Enabled:[/bold]     {'yes' if match.enabled else 'no'}",
        f"[bold]Commands:[/bold]    {', '.join(match.commands) if match.commands else '—'}",
    ]
    console.print(Panel("\n".join(lines), title=f"Plugin: {match.name}"))


@app.command("dir")
def plugin_dir_cmd(
    db: Optional[Path] = typer.Option(None, "--db", hidden=True),
) -> None:
    """Show the plugin directory path."""
    path = _default_plugin_dir()
    exists = path.exists()
    status = "[green]exists[/green]" if exists else "[yellow]does not exist[/yellow]"
    console.print(f"{path}  ({status})")


@app.command("init")
def plugin_init(
    name: str = typer.Argument(..., help="Plugin name (used as filename and identifier)."),
    plugin_dir: Optional[Path] = typer.Option(
        None, "--dir", "-d", help="Directory to write the skeleton into."
    ),
    json_output: bool = typer.Option(False, "--json", help="Output result as JSON."),
    db: Optional[Path] = typer.Option(None, "--db", hidden=True),
) -> None:
    """Generate a skeleton plugin file in the plugin directory."""
    # Sanitise name → valid Python identifier for class name
    class_name = "".join(part.capitalize() for part in name.replace("-", "_").split("_"))
    if not class_name:
        console.print("[red]Invalid plugin name.[/red]")
        raise typer.Exit(code=1)

    target_dir = _plugin_dir_path(plugin_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    out_path = target_dir / f"{name.replace('-', '_')}.py"
    if out_path.exists():
        console.print(f"[yellow]File already exists:[/yellow] {out_path}")
        raise typer.Exit(code=1)

    content = _PLUGIN_TEMPLATE.format(name=name, class_name=class_name)
    out_path.write_text(content, encoding="utf-8")

    if json_output:
        print(json.dumps({"path": str(out_path), "name": name}, indent=2))
        return

    console.print(f"[green]Created plugin skeleton:[/green] {out_path}")
    console.print(
        f"\nEdit [bold]{out_path.name}[/bold] and implement your plugin.\n"
        f"Run [bold]netglance plugin list[/bold] to verify it is discovered."
    )
