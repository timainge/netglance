"""Plugin base classes and Protocol definition for netglance plugins."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import typer

from netglance.store.models import CheckStatus


@runtime_checkable
class NetglancePlugin(Protocol):
    """Protocol that all netglance plugins must satisfy.

    Plugins can be implemented as plain classes — no inheritance required.
    Simply satisfy this interface and place the file in the plugin directory.
    """

    @property
    def name(self) -> str:
        """Unique identifier for the plugin (e.g. 'my-plugin')."""
        ...

    @property
    def version(self) -> str:
        """Semantic version string (e.g. '1.0.0')."""
        ...

    @property
    def description(self) -> str:
        """One-line description shown in plugin list."""
        ...

    def check(self) -> CheckStatus:
        """Run the plugin's health check. Called by the report module."""
        ...

    def cli_app(self) -> typer.Typer | None:
        """Return a Typer app for CLI subcommands, or None if not needed."""
        ...


class BasePlugin:
    """Convenience base class for plugins.

    Inherit from this class to get sensible defaults. You are not required
    to inherit — satisfying the NetglancePlugin Protocol is sufficient.
    """

    name: str = "unnamed"
    version: str = "0.0.0"
    description: str = ""

    def check(self) -> CheckStatus:
        """Default check returns 'skip' — override to implement a real check."""
        return CheckStatus(
            module=self.name,
            status="skip",
            summary="No check implemented",
        )

    def cli_app(self) -> typer.Typer | None:
        """Default: no CLI commands. Override to add a Typer sub-app."""
        return None
