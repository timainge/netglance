"""TLS CLI subcommands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from netglance.modules.tls import (
    TlsCheckResult,
    check_certificate,
    check_multiple,
    diff_fingerprints,
)
from netglance.store.db import Store

app = typer.Typer(
    help="TLS certificate verification & interception detection.", no_args_is_help=True
)
console = Console()


def _tls_status(result: TlsCheckResult) -> str:
    if result.is_intercepted:
        return "[red]INTERCEPTED[/red]"
    if result.is_trusted:
        return "[green]TRUSTED[/green]"
    return "[yellow]UNTRUSTED[/yellow]"


def _tls_result_table(
    results: list[TlsCheckResult], title: str = "TLS Certificate Check"
) -> Table:
    table = Table(title=title, show_lines=True)
    table.add_column("Host", style="bold")
    table.add_column("Issuer")
    table.add_column("Root CA")
    table.add_column("Fingerprint (SHA-256)")
    table.add_column("Status")

    for r in results:
        fp_display = (
            r.cert.fingerprint_sha256[:16] + "..." if r.cert.fingerprint_sha256 else ""
        )
        table.add_row(r.host, r.cert.issuer, r.cert.root_ca, fp_display, _tls_status(r))
    return table


@app.command("verify")
def tls_verify_cmd(
    host: Optional[str] = typer.Argument(
        None, help="Host to check (checks default sites if omitted)."
    ),
    port: int = typer.Option(443, "--port", "-p", help="TCP port."),
    save: bool = typer.Option(False, "--save/--no-save", help="Save result to local DB."),
) -> None:
    """Verify TLS certificates for one or more hosts."""
    if host:
        results = [check_certificate(host, port=port)]
    else:
        results = check_multiple()
    console.print(_tls_result_table(results))
    for r in results:
        if r.details:
            style = "green" if r.is_trusted else "red"
            console.print(f"  [{style}]{r.host}[/{style}]: {r.details}")

    if save:
        try:
            store = Store()
            store.init_db()
            store.save_result("tls", {
                "hosts_checked": len(results),
                "all_trusted": all(r.is_trusted for r in results),
                "any_intercepted": any(r.is_intercepted for r in results),
            })
            console.print("[dim]✓ Saved to local database.[/dim]")
        except Exception as exc:
            console.print(f"[dim yellow]Warning: could not save result: {exc}[/dim yellow]")


@app.command("save")
def tls_save_cmd(
    db_path: Optional[Path] = typer.Option(
        None, "--db", hidden=True, help="DB path override."
    ),
) -> None:
    """Save current TLS fingerprints as a baseline."""
    results = check_multiple()
    store = Store(db_path=db_path) if db_path else Store()
    store.init_db()
    baseline_data = [
        {
            "host": r.host,
            "fingerprint_sha256": r.cert.fingerprint_sha256,
            "issuer": r.cert.issuer,
            "root_ca": r.cert.root_ca,
        }
        for r in results
    ]
    store.save_baseline({"tls_fingerprints": baseline_data}, label="tls")
    store.close()
    console.print(f"[green]Saved TLS baseline for {len(results)} hosts.[/green]")


@app.command("diff")
def tls_diff_cmd(
    db_path: Optional[Path] = typer.Option(
        None, "--db", hidden=True, help="DB path override."
    ),
) -> None:
    """Compare current TLS fingerprints against saved baseline."""
    results = check_multiple()
    store = Store(db_path=db_path) if db_path else Store()
    store.init_db()
    baseline = store.get_latest_baseline()
    store.close()

    if not baseline or "tls_fingerprints" not in baseline:
        console.print("[red]No TLS baseline found. Run 'netglance tls save' first.[/red]")
        raise typer.Exit(code=1)

    diffs = diff_fingerprints(results, baseline["tls_fingerprints"])
    table = Table(title="TLS Fingerprint Diff", show_lines=True)
    table.add_column("Host", style="bold")
    table.add_column("Status")
    table.add_column("Old Fingerprint")
    table.add_column("New Fingerprint")

    for d in diffs:
        if d["status"] == "match":
            status_str = "[green]match[/green]"
        elif d["status"] == "changed":
            status_str = "[red]CHANGED[/red]"
        else:
            status_str = "[yellow]new[/yellow]"
        old_fp = (d["old_fingerprint"] or "")[:16] + "..." if d["old_fingerprint"] else "--"
        new_fp = (d["new_fingerprint"] or "")[:16] + "..." if d["new_fingerprint"] else "--"
        table.add_row(d["host"], status_str, old_fp, new_fp)

    console.print(table)


@app.command("chain")
def tls_chain_cmd(
    host: str = typer.Argument(..., help="Host to inspect."),
    port: int = typer.Option(443, "--port", "-p", help="TCP port."),
) -> None:
    """Show TLS certificate chain for a host."""
    result = check_certificate(host, port=port)
    table = Table(title=f"Certificate Chain: {host}:{port}", show_lines=True)
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("Subject", result.cert.subject)
    table.add_row("Issuer", result.cert.issuer)
    table.add_row("Root CA", result.cert.root_ca)
    table.add_row("Fingerprint (SHA-256)", result.cert.fingerprint_sha256)
    table.add_row("Not Before", str(result.cert.not_before))
    table.add_row("Not After", str(result.cert.not_after))
    table.add_row("SAN", ", ".join(result.cert.san) if result.cert.san else "--")
    table.add_row("Chain Length", str(result.cert.chain_length))
    table.add_row("Trusted", _tls_status(result))

    console.print(table)
