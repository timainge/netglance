"""Shared CLI helpers."""

from __future__ import annotations

from rich.console import Console

from netglance.store.db import Store


def maybe_warn_db_size(
    store: Store, console: Console | None = None, threshold_mb: int = 100
) -> None:
    """Print a warning if the DB exceeds the size threshold. Non-fatal on any error."""
    try:
        warning = store.check_db_size(warn_threshold_mb=threshold_mb)
        if warning:
            c = console or Console()
            c.print(
                f"[yellow]\u26a0 Database is {warning['size_mb']:.0f} MB "
                f"(threshold: {warning['threshold_mb']} MB). "
                f"Largest table: {warning['largest_table']} "
                f"({warning['largest_count']:,} rows).[/yellow]"
            )
            c.print("[dim]  Run 'netglance db prune' to clean up old data.[/dim]")
    except Exception:
        pass
