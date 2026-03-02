"""API server CLI subcommands."""

from __future__ import annotations

import os
from typing import List, Optional

import typer
from rich.console import Console

app = typer.Typer(help="REST API server.", no_args_is_help=True)
console = Console()

_LOCALHOST_ADDRS = ("127.0.0.1", "localhost", "::1")


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host address."),
    port: int = typer.Option(8080, "--port", "-p", help="Bind port."),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", help="API key for authentication (disables open access)."
    ),
    cors_origin: Optional[List[str]] = typer.Option(
        None, "--cors-origin", help="Allowed CORS origin (repeatable). Default: localhost only."
    ),
    db: Optional[str] = typer.Option(
        None, "--db", hidden=True, help="Override database path (for testing)."
    ),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload (development mode)."),
) -> None:
    """Start the netglance REST API server."""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]Error:[/red] uvicorn is not installed. Run: uv pip install uvicorn")
        raise typer.Exit(code=1)

    # Auto-generate API key when binding beyond localhost without explicit key
    has_env_key = bool(os.environ.get("NETGLANCE_API_KEY"))
    if host not in _LOCALHOST_ADDRS and not api_key and not has_env_key:
        import secrets

        api_key = secrets.token_urlsafe(32)
        console.print(
            f"[yellow]Warning:[/yellow] Binding to [bold]{host}[/bold] exposes the API on your network."
        )
        console.print(f"[yellow]Auto-generated API key:[/yellow] [bold]{api_key}[/bold]")
        console.print("[dim]Pass this key in the X-API-Key header. Use --api-key to set your own.[/dim]")
        console.print()

    from netglance.api.server import create_app

    server_app = create_app(
        api_key=api_key,
        db_path=db,
        cors_origins=cors_origin if cors_origin else None,
    )

    console.print(f"[bold green]netglance API[/bold green] starting on [bold]http://{host}:{port}[/bold]")
    if api_key or has_env_key:
        console.print("[dim]Authentication: API key required (X-API-Key header)[/dim]")
    else:
        console.print("[dim]Authentication: disabled (local mode)[/dim]")
    console.print(f"[dim]Docs: http://{host}:{port}/docs[/dim]")

    uvicorn.run(
        server_app,
        host=host,
        port=port,
        reload=reload,
    )
