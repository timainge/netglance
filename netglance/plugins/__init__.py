"""netglance plugin system — discovery, loading, and base classes."""

from netglance.plugins.base import BasePlugin, NetglancePlugin
from netglance.plugins.loader import (
    discover_plugins,
    get_plugin_checks,
    load_all_plugins,
    load_plugin,
    register_plugin_commands,
)

__all__ = [
    "NetglancePlugin",
    "BasePlugin",
    "discover_plugins",
    "load_plugin",
    "load_all_plugins",
    "register_plugin_commands",
    "get_plugin_checks",
]
