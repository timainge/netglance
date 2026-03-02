"""Plugin discovery and loading for netglance."""

from __future__ import annotations

import importlib.util
import inspect
import logging
import sys
from pathlib import Path
from types import ModuleType

import typer

from netglance.plugins.base import NetglancePlugin
from netglance.store.models import CheckStatus, PluginInfo

logger = logging.getLogger(__name__)

_DEFAULT_PLUGIN_DIR = Path.home() / ".config" / "netglance" / "plugins"


def _default_plugin_dir() -> Path:
    """Return the default plugin directory path."""
    return _DEFAULT_PLUGIN_DIR


def _find_plugin_class(module: ModuleType) -> type | None:
    """Scan a module for a class that satisfies the NetglancePlugin Protocol.

    Returns the first matching class (excluding BasePlugin itself), or None.
    """
    from netglance.plugins.base import BasePlugin

    for _name, obj in inspect.getmembers(module, inspect.isclass):
        if obj is BasePlugin:
            continue
        # Must be defined in this module (not imported)
        if obj.__module__ != module.__name__:
            continue
        # Use isinstance() on an instance to check Protocol compliance.
        # issubclass() fails for Protocols with non-method members (properties)
        # in Python 3.12+.
        try:
            instance = obj()
            if isinstance(instance, NetglancePlugin):
                return obj
        except Exception:
            pass
    return None


def _import_module_from_path(path: Path) -> ModuleType | None:
    """Import a Python file as a module using importlib.

    Returns the module, or None on failure.
    """
    module_name = f"netglance_plugin_{path.stem}"
    # Avoid re-importing if already loaded
    if module_name in sys.modules:
        return sys.modules[module_name]

    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.warning("Could not create module spec for %s", path)
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module
    except Exception as exc:
        logger.warning("Failed to import plugin %s: %s", path, exc)
        # Remove from sys.modules on failure so re-attempts are clean
        sys.modules.pop(module_name, None)
        return None


def discover_plugins(
    plugin_dir: Path | None = None,
    *,
    _listdir_fn=None,
    _import_fn=None,
) -> list[PluginInfo]:
    """Discover plugins in *plugin_dir* without loading them.

    Scans for *.py files and inspects each for a NetglancePlugin-compatible
    class. Returns PluginInfo metadata for each valid plugin found.

    Args:
        plugin_dir: Directory to scan. Defaults to ~/.config/netglance/plugins/.
        _listdir_fn: Injectable callable(dir) -> list[Path] for testing.
        _import_fn: Injectable callable(path) -> module|None for testing.

    Returns:
        List of PluginInfo for each discovered plugin.
    """
    target_dir = plugin_dir or _default_plugin_dir()
    listdir_fn = _listdir_fn or (lambda d: sorted(d.glob("*.py")))
    import_fn = _import_fn or _import_module_from_path

    if not target_dir.exists():
        return []

    infos: list[PluginInfo] = []
    for py_file in listdir_fn(target_dir):
        if py_file.name.startswith("_"):
            continue
        module = import_fn(py_file)
        if module is None:
            continue
        cls = _find_plugin_class(module)
        if cls is None:
            continue
        try:
            instance = cls()
            commands: list[str] = []
            cli = instance.cli_app()
            if cli is not None:
                commands = [cmd.name for cmd in cli.registered_commands if cmd.name]
            infos.append(
                PluginInfo(
                    name=instance.name,
                    version=instance.version,
                    description=instance.description,
                    module_path=str(py_file),
                    commands=commands,
                )
            )
        except Exception as exc:
            logger.warning("Could not inspect plugin %s: %s", py_file, exc)

    return infos


def load_plugin(
    path: Path,
    *,
    _import_fn=None,
) -> NetglancePlugin | None:
    """Import and instantiate a single plugin from *path*.

    Args:
        path: Path to the plugin .py file.
        _import_fn: Injectable callable(path) -> module|None for testing.

    Returns:
        An instantiated plugin, or None if loading fails.
    """
    import_fn = _import_fn or _import_module_from_path
    module = import_fn(path)
    if module is None:
        return None
    cls = _find_plugin_class(module)
    if cls is None:
        logger.warning("No NetglancePlugin class found in %s", path)
        return None
    try:
        return cls()
    except Exception as exc:
        logger.warning("Could not instantiate plugin class in %s: %s", path, exc)
        return None


def load_all_plugins(
    plugin_dir: Path | None = None,
    *,
    _listdir_fn=None,
    _import_fn=None,
) -> list[NetglancePlugin]:
    """Discover and load all plugins from *plugin_dir*.

    Args:
        plugin_dir: Directory to scan. Defaults to ~/.config/netglance/plugins/.
        _listdir_fn: Injectable callable(dir) -> list[Path] for testing.
        _import_fn: Injectable callable(path) -> module|None for testing.

    Returns:
        List of successfully loaded plugin instances.
    """
    target_dir = plugin_dir or _default_plugin_dir()
    listdir_fn = _listdir_fn or (lambda d: sorted(d.glob("*.py")))
    import_fn = _import_fn or _import_module_from_path

    if not target_dir.exists():
        return []

    plugins: list[NetglancePlugin] = []
    for py_file in listdir_fn(target_dir):
        if py_file.name.startswith("_"):
            continue
        plugin = load_plugin(py_file, _import_fn=import_fn)
        if plugin is not None:
            plugins.append(plugin)
        else:
            logger.warning("Skipping plugin file %s (load failed)", py_file)

    return plugins


def register_plugin_commands(
    app: typer.Typer,
    plugins: list[NetglancePlugin],
) -> None:
    """Register CLI sub-apps from each plugin onto *app*.

    Each plugin with a cli_app() is registered as `plugin-{plugin.name}`.

    Args:
        app: The root Typer application.
        plugins: List of loaded plugin instances.
    """
    for plugin in plugins:
        try:
            cli = plugin.cli_app()
            if cli is not None:
                app.add_typer(cli, name=f"plugin-{plugin.name}")
        except Exception as exc:
            logger.warning("Could not register CLI for plugin %s: %s", plugin.name, exc)


def get_plugin_checks(plugins: list[NetglancePlugin]) -> list[CheckStatus]:
    """Run check() on each plugin and return results.

    Exceptions are caught and returned as CheckStatus with status='error'.

    Args:
        plugins: List of loaded plugin instances.

    Returns:
        List of CheckStatus results, one per plugin.
    """
    results: list[CheckStatus] = []
    for plugin in plugins:
        try:
            status = plugin.check()
            results.append(status)
        except Exception as exc:
            results.append(
                CheckStatus(
                    module=getattr(plugin, "name", "unknown"),
                    status="error",
                    summary=f"Plugin check raised an exception: {exc}",
                    details=[str(exc)],
                )
            )
    return results
