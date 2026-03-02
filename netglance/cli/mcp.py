"""MCP server CLI subcommands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="MCP server for AI tool integration.", no_args_is_help=True)
console = Console()


@app.command("serve")
def serve(
    transport: str = typer.Option(
        "stdio",
        "--transport",
        "-t",
        help="Transport protocol: 'stdio' (default) or 'http'.",
    ),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Host to bind the SSE server to (ignored for stdio).",
    ),
    port: int = typer.Option(
        8080,
        "--port",
        "-p",
        help="Port to bind the SSE server to (ignored for stdio).",
    ),
    db: Optional[Path] = typer.Option(
        None,
        "--db",
        hidden=True,
        help="Override the SQLite database path (for testing).",
    ),
) -> None:
    """Start the netglance MCP server.

    By default, runs over stdio (for use with Claude Desktop / MCP clients).
    Use --transport sse to expose over HTTP for remote connections.
    """
    from netglance.mcp_server import create_mcp_server

    kwargs: dict = {}
    if db is not None:
        from netglance.store.db import Store

        store = Store(db_path=db)
        store.init_db()
        kwargs["_store"] = store

    mcp = create_mcp_server(**kwargs)

    if transport == "stdio":
        console.print(
            "[dim]Starting netglance MCP server (stdio transport)…[/dim]",
            err=True,
        )
        mcp.run(transport="stdio")
    elif transport == "http":
        # Warn when binding beyond localhost
        if host not in ("127.0.0.1", "localhost", "::1"):
            console.print(
                f"[yellow]Warning:[/yellow] Binding MCP HTTP to [bold]{host}[/bold] "
                "exposes tools on your network. MCP HTTP transport has no built-in auth.",
                err=True,
            )
        console.print(
            f"[dim]Starting netglance MCP server (Streamable HTTP on {host}:{port})…[/dim]",
            err=True,
        )
        mcp.run(transport="streamable-http", host=host, port=port)
    elif transport == "sse":
        console.print(
            "[yellow]Warning:[/yellow] SSE transport is deprecated. Use --transport http instead.",
            err=True,
        )
        mcp.run(transport="sse", host=host, port=port)
    else:
        console.print(f"[red]Unknown transport:[/red] {transport!r}. Use 'stdio' or 'http'.")
        raise typer.Exit(code=1)


@app.command("tools")
def list_tools(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show annotations and parameters."),
) -> None:
    """List all MCP tools exposed by the netglance server."""
    import asyncio
    from netglance.mcp_server import create_mcp_server

    mcp = create_mcp_server()

    async def _get_tools() -> list[dict]:
        tools = await mcp._tool_manager.get_tools()
        result = []
        for name, tool in tools.items():
            entry: dict = {
                "name": name,
                "description": (tool.description or "").splitlines()[0] if tool.description else "",
            }
            if verbose:
                annot = {}
                if hasattr(tool, "annotations") and tool.annotations is not None:
                    if hasattr(tool.annotations, "model_dump"):
                        annot = tool.annotations.model_dump(exclude_none=True)
                    elif isinstance(tool.annotations, dict):
                        annot = tool.annotations
                entry["annotations"] = annot
                params = {}
                if hasattr(tool, "parameters") and tool.parameters:
                    schema = tool.parameters
                    if isinstance(schema, dict) and "properties" in schema:
                        for pname, pinfo in schema["properties"].items():
                            params[pname] = pinfo.get("type", "any")
                entry["parameters"] = params
            result.append(entry)
        return result

    tools = asyncio.run(_get_tools())

    if json_output:
        console.print_json(json.dumps(tools))
        return

    table = Table(title="netglance MCP Tools", show_lines=False)
    table.add_column("Tool", style="bold cyan")
    table.add_column("Description")
    if verbose:
        table.add_column("Hints", style="dim")
        table.add_column("Parameters", style="dim")

    for tool in tools:
        if verbose:
            annot = tool.get("annotations", {})
            hints = []
            if annot.get("readOnlyHint"):
                hints.append("RO")
            if annot.get("openWorldHint"):
                hints.append("net")
            if annot.get("destructiveHint"):
                hints.append("DESTR")
            params = tool.get("parameters", {})
            param_str = ", ".join(f"{k}: {v}" for k, v in params.items()) if params else "-"
            table.add_row(tool["name"], tool["description"], " ".join(hints) or "-", param_str)
        else:
            table.add_row(tool["name"], tool["description"])

    console.print(table)
